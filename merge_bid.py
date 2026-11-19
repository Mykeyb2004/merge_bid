#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generic bid-document merger driven by a Markdown outline.

Parses an outline Markdown file, preserves its heading hierarchy, matches target
headings (default: level 4 `####` or auto-detected leaf headings) to chapter
Markdown files under an input directory—even when filenames diverge due to OS
filename restrictions, punctuation changes, numbering formatting, or truncation—
and writes a single merged Markdown document.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote

INVISIBLE_CHARS_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u200e\u200f\u2060]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_IMG_SRC_RE = re.compile(
    r"""(\bsrc\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""",
    re.IGNORECASE,
)

# Multi-level numeric code like 1.1.1, 1-1-1, 1_1_1, 1.1.01, optionally followed by '.'
MULTI_CODE_RE = re.compile(r"^\s*(\d+(?:[._-]\d+)+)\.?\s*[-_.\s:：、]*\s*(.*)$")
# Single-level numeric code like "1. 标题" or "1、标题" (requires explicit separator)
SINGLE_CODE_RE = re.compile(r"^\s*(\d+)\s*[.、]\s+(.*)$")


@dataclass(frozen=True)
class OutlineNode:
    """A heading line parsed from the outline file."""

    index: int
    level: int
    raw_line: str
    title: str
    code_raw: str | None
    code_tuple: tuple[int, ...] | None
    title_body: str
    full_skeleton: str
    body_skeleton: str
    is_target: bool = False


@dataclass(frozen=True)
class ChapterFile:
    """A candidate chapter Markdown file discovered in the input directory."""

    path: Path
    rel_path: str
    stem: str
    code_raw: str | None
    code_tuple: tuple[int, ...] | None
    title_body: str
    full_skeleton: str
    body_skeleton: str


@dataclass(frozen=True)
class MatchResult:
    """Pairing between an outline target heading and a chapter file."""

    heading_index: int
    heading_title: str
    file_path: str
    match_type: str
    score: float
    warning: str | None = None


@dataclass(frozen=True)
class AssetWarning:
    """Warning recorded when rebasing relative asset paths in a chapter."""

    chapter_path: str
    asset_url: str
    kind: str  # "pre_rebased_for_output" | "missing_asset"
    message: str


def clean_invisible(text: str) -> str:
    """Remove BOM and zero-width invisible characters."""
    return INVISIBLE_CHARS_RE.sub("", text)


def normalize_text(text: str) -> str:
    """Normalize Unicode compatibility forms and strip invisible characters."""
    return unicodedata.normalize("NFKC", clean_invisible(text)).strip()


def to_skeleton(text: str) -> str:
    """Keep only normalized alphanumeric/CJK characters for punctuation-agnostic comparison."""
    normalized = normalize_text(text).lower()
    return "".join(ch for ch in normalized if ch.isalnum())


def extract_code_and_title(text: str) -> tuple[str | None, tuple[int, ...] | None, str]:
    """Extract leading hierarchical numbering and remaining title text."""
    norm = normalize_text(text)
    for pattern in (MULTI_CODE_RE, SINGLE_CODE_RE):
        m = pattern.match(norm)
        if m:
            code_str = m.group(1)
            rest = m.group(2).strip()
            parts = tuple(int(p) for p in re.split(r"[._-]", code_str) if p.isdigit())
            if parts:
                return code_str, parts, rest
    return None, None, norm


def bigrams(text: str) -> set[str]:
    """Build character bigrams for overlap scoring."""
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def text_similarity(a: str, b: str) -> float:
    """Blend SequenceMatcher ratio and character bigram Jaccard similarity."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq_ratio = SequenceMatcher(None, a, b).ratio()
    bg_a, bg_b = bigrams(a), bigrams(b)
    union = bg_a | bg_b
    jaccard = (len(bg_a & bg_b) / len(union)) if union else 0.0
    return 0.65 * seq_ratio + 0.35 * jaccard


def parse_outline(outline_path: Path, target_mode: str) -> list[OutlineNode]:
    """Parse Markdown outline headings and mark which headings receive chapter bodies."""
    raw_lines = outline_path.read_text(encoding="utf-8-sig").splitlines()
    parsed: list[OutlineNode] = []
    in_fence = False
    fence_char = ""

    for line in raw_lines:
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
            continue
        if in_fence:
            continue

        heading_match = HEADING_RE.match(line)
        if not heading_match:
            continue

        hashes, raw_title = heading_match.groups()
        level = len(hashes)
        preserved_title = clean_invisible(raw_title).strip()
        title = normalize_text(preserved_title)
        code_raw, code_tuple, title_body = extract_code_and_title(title)
        parsed.append(
            OutlineNode(
                index=len(parsed),
                level=level,
                raw_line=f"{hashes} {preserved_title}",
                title=title,
                code_raw=code_raw,
                code_tuple=code_tuple,
                title_body=title_body,
                full_skeleton=to_skeleton(title),
                body_skeleton=to_skeleton(title_body),
            )
        )

    if not parsed:
        raise ValueError(f"未在大纲文件中解析到任何 Markdown 标题: {outline_path}")

    target_level: int | None = None
    if target_mode != "leaf":
        target_level = int(target_mode)

    result: list[OutlineNode] = []
    for i, node in enumerate(parsed):
        if target_level is not None:
            is_target = node.level == target_level
        else:
            next_level = parsed[i + 1].level if i + 1 < len(parsed) else 0
            is_target = next_level <= node.level
        result.append(
            OutlineNode(
                index=node.index,
                level=node.level,
                raw_line=node.raw_line,
                title=node.title,
                code_raw=node.code_raw,
                code_tuple=node.code_tuple,
                title_body=node.title_body,
                full_skeleton=node.full_skeleton,
                body_skeleton=node.body_skeleton,
                is_target=is_target,
            )
        )
    return result


def scan_chapter_files(input_dir: Path, exclude_paths: set[Path]) -> list[ChapterFile]:
    """Recursively collect candidate Markdown files under input_dir."""
    files: list[ChapterFile] = []
    resolved_excludes = {p.resolve() for p in exclude_paths}

    for path in sorted(input_dir.rglob("*.md")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in resolved_excludes:
            continue
        rel_parts = path.relative_to(input_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue

        stem = normalize_text(path.stem)
        code_raw, code_tuple, title_body = extract_code_and_title(stem)
        files.append(
            ChapterFile(
                path=path,
                rel_path=str(path.relative_to(input_dir)),
                stem=stem,
                code_raw=code_raw,
                code_tuple=code_tuple,
                title_body=title_body,
                full_skeleton=to_skeleton(stem),
                body_skeleton=to_skeleton(title_body),
            )
        )
    return files


def score_pair(
    node: OutlineNode,
    chap: ChapterFile,
    min_similarity: float,
    min_code_only_similarity: float,
) -> tuple[int, float, str, str | None] | None:
    """Evaluate match tier, score, type, and optional warning for a (heading, file) pair.

    Lower tier number means higher priority.
    """
    # Tier 1: Exact normalized stem match
    if node.title == chap.stem:
        return (1, 1.0, "exact", None)

    # Tier 2: Full skeleton match (ignores punctuation, OS-illegal chars, spacing, dash style)
    if node.full_skeleton and node.full_skeleton == chap.full_skeleton:
        return (
            2,
            0.98,
            "normalized_skeleton",
            f"文件名与标题标点/空格/分隔符不完全一致: 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    same_code = (
        node.code_tuple is not None
        and chap.code_tuple is not None
        and node.code_tuple == chap.code_tuple
    )
    body_sim = text_similarity(node.body_skeleton, chap.body_skeleton)

    # Tier 3: Exact section code + exact body skeleton (e.g. code formatted as 1-1-1 or 1.1.01)
    if same_code and node.body_skeleton and node.body_skeleton == chap.body_skeleton:
        return (
            3,
            0.96,
            "code_and_body_skeleton",
            f"章节编号格式或分隔符有差异: 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    # Tier 4: Exact section code + truncated prefix match
    if same_code and node.body_skeleton and chap.body_skeleton:
        shorter, longer = (
            (chap.body_skeleton, node.body_skeleton)
            if len(chap.body_skeleton) <= len(node.body_skeleton)
            else (node.body_skeleton, chap.body_skeleton)
        )
        if len(shorter) >= 6 and longer.startswith(shorter):
            ratio = len(shorter) / len(longer)
            if ratio >= 0.35:
                return (
                    4,
                    0.90 + 0.05 * ratio,
                    "code_and_truncated_prefix",
                    f"疑似文件名被截断: 标题「{node.title}」<- 文件「{chap.rel_path}」",
                )

    # Tier 5: Exact section code + high fuzzy title similarity
    if same_code and body_sim >= 0.45:
        return (
            5,
            0.80 + 0.10 * body_sim,
            "code_and_fuzzy_title",
            f"同编号下标题存在微调 (相似度 {body_sim:.2f}): 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    # Tier 6: Title body skeleton matches exactly even though section code changed or was omitted
    if node.body_skeleton and len(node.body_skeleton) >= 6 and node.body_skeleton == chap.body_skeleton:
        return (
            6,
            0.84,
            "title_exact_code_mismatch",
            f"章节编号不一致但正文标题完全一致: 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    # Tier 7: Exact section code fallback when title changed substantially or was omitted
    if same_code and body_sim >= min_code_only_similarity:
        detail = (
            "文件名仅包含编号"
            if not chap.body_skeleton
            else f"标题差异较大 (相似度 {body_sim:.2f})"
        )
        return (
            7,
            0.68 + 0.10 * body_sim,
            "code_fallback",
            f"仅编号一致且{detail}，请人工复核: 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    # Tier 8: Pure fuzzy title match (e.g. renumbered + slightly edited title, or missing code)
    if len(node.body_skeleton) >= 6 and len(chap.body_skeleton) >= 6 and body_sim >= min_similarity:
        return (
            8,
            0.60 * body_sim,
            "fuzzy_title",
            f"跨编号模糊匹配 (相似度 {body_sim:.2f})，请人工复核: 标题「{node.title}」<- 文件「{chap.rel_path}」",
        )

    return None


def match_chapters(
    nodes: list[OutlineNode],
    files: list[ChapterFile],
    min_similarity: float,
    min_code_only_similarity: float,
) -> tuple[dict[int, MatchResult], list[OutlineNode], list[ChapterFile]]:
    """Assign chapter files 1-to-1 to target outline headings by priority tier and score."""
    target_nodes = [n for n in nodes if n.is_target]
    candidates: list[tuple[int, float, int, int, str, str | None]] = []

    for node in target_nodes:
        for file_idx, chap in enumerate(files):
            scored = score_pair(node, chap, min_similarity, min_code_only_similarity)
            if scored is None:
                continue
            tier, score, match_type, warning = scored
            candidates.append((tier, -score, node.index, file_idx, match_type, warning))

    # Best tier first, then highest score; deterministic tie-break by node/file order
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

    used_nodes: set[int] = set()
    used_files: set[int] = set()
    matches: dict[int, MatchResult] = {}

    node_by_idx = {n.index: n for n in target_nodes}
    for tier, neg_score, node_idx, file_idx, match_type, warning in candidates:
        if node_idx in used_nodes or file_idx in used_files:
            continue
        used_nodes.add(node_idx)
        used_files.add(file_idx)
        node = node_by_idx[node_idx]
        chap = files[file_idx]
        matches[node_idx] = MatchResult(
            heading_index=node_idx,
            heading_title=node.title,
            file_path=chap.rel_path,
            match_type=match_type,
            score=round(-neg_score, 4),
            warning=warning,
        )

    missing_nodes = [n for n in target_nodes if n.index not in matches]
    orphan_files = [chap for idx, chap in enumerate(files) if idx not in used_files]
    return matches, missing_nodes, orphan_files


def clean_chapter_body(
    raw_text: str,
    node: OutlineNode,
    strip_duplicate_title: bool,
) -> str:
    """Normalize line endings, strip invisible chars, and optionally drop a repeated leading heading."""
    text = clean_invisible(raw_text).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()

    # Trim leading/trailing blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if strip_duplicate_title and lines:
        first_line = normalize_text(lines[0])
        heading_match = HEADING_RE.match(first_line)
        candidate = heading_match.group(2) if heading_match else first_line
        if to_skeleton(candidate) == node.full_skeleton or (
            node.body_skeleton and to_skeleton(candidate) == node.body_skeleton
        ):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)

    return "\n".join(lines)


def _is_escaped(text: str, index: int) -> bool:
    """Return True if text[index] is preceded by an odd number of backslashes."""
    backslashes = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "\\":
        backslashes += 1
        pos -= 1
    return backslashes % 2 == 1


def _find_inline_code_end(text: str, start: int) -> int | None:
    """Return index immediately after the closing backtick run, or None if unclosed."""
    i = start
    while i < len(text) and text[i] == "`":
        i += 1
    tick_len = i - start
    j = i
    while j < len(text):
        if text[j] == "`":
            k = j
            while k < len(text) and text[k] == "`":
                k += 1
            if k - j == tick_len:
                return k
            j = k
        else:
            j += 1
    return None


def _should_passthrough_url(url: str) -> bool:
    """Return True for empty URLs, anchors, URL schemes, drive letters, and absolute paths."""
    stripped = url.strip()
    if not stripped:
        return True
    if stripped.startswith(("#", "//", "/")):
        return True
    if URL_SCHEME_RE.match(stripped):
        return True
    decoded = unquote(stripped)
    return decoded.startswith("/") or Path(decoded).is_absolute()


def _split_url_suffix(raw_url: str) -> tuple[str, str]:
    """Split trailing #fragment or ?query suffix from a relative URL."""
    indices = [idx for idx in (raw_url.find("#"), raw_url.find("?")) if idx != -1]
    if not indices:
        return raw_url, ""
    cut = min(indices)
    return raw_url[:cut], raw_url[cut:]


def _resolve_candidate(base_dir: Path, decoded_rel: str) -> Path:
    """Resolve a decoded relative path against base_dir without dereferencing asset symlinks."""
    rel_part = Path(decoded_rel.replace("\\", "/"))
    return Path(os.path.normpath(base_dir / rel_part))


def _format_rebased_url(rel_posix: str, has_angle_brackets: bool, for_html: bool) -> str:
    """Format a rebased POSIX path, preserving readability while keeping Markdown syntax valid."""
    if has_angle_brackets or for_html:
        return rel_posix
    return rel_posix.replace(" ", "%20").replace("\t", "%09")


def _looks_like_file_path(url_path: str) -> bool:
    """Return True if a non-image link target looks like a local file reference."""
    decoded = unquote(url_path.strip())
    return "/" in decoded or "\\" in decoded or Path(decoded).suffix != ""


def _rebase_single_url(
    raw_url: str,
    *,
    chapter_dir: Path,
    output_dir: Path,
    chapter_rel_path: str,
    is_image: bool,
    has_angle_brackets: bool,
    for_html: bool,
    warnings: list[AssetWarning],
) -> tuple[str, bool]:
    """Rebase one relative asset/link URL from chapter_dir to output_dir."""
    if _should_passthrough_url(raw_url):
        return raw_url, False

    path_part, suffix = _split_url_suffix(raw_url)
    candidates: list[tuple[str, str]] = [(raw_url, "")]
    if suffix:
        candidates.append((path_part, suffix))

    for candidate_path, candidate_suffix in candidates:
        decoded_rel = unquote(candidate_path)
        from_chapter = _resolve_candidate(chapter_dir, decoded_rel)
        if from_chapter.exists():
            rel_posix = Path(os.path.relpath(from_chapter, start=output_dir)).as_posix()
            formatted = _format_rebased_url(
                rel_posix + candidate_suffix,
                has_angle_brackets=has_angle_brackets,
                for_html=for_html,
            )
            return formatted, formatted != raw_url

    for candidate_path, _ in candidates:
        decoded_rel = unquote(candidate_path)
        from_output = _resolve_candidate(output_dir, decoded_rel)
        if from_output.exists():
            warnings.append(
                AssetWarning(
                    chapter_path=chapter_rel_path,
                    asset_url=raw_url,
                    kind="pre_rebased_for_output",
                    message=(
                        f"章节目录基准下未找到资源，但在输出目录下存在（保留原路径）: "
                        f"章节「{chapter_rel_path}」-> 「{raw_url}」"
                    ),
                )
            )
            return raw_url, False

    if is_image or _looks_like_file_path(path_part):
        kind_label = "图片" if is_image else "文件链接"
        warnings.append(
            AssetWarning(
                chapter_path=chapter_rel_path,
                asset_url=raw_url,
                kind="missing_asset",
                message=f"{kind_label}资源不存在（断链）: 章节「{chapter_rel_path}」-> 「{raw_url}」",
            )
        )
    return raw_url, False


def _skip_optional_title(text: str, pos: int) -> int | None:
    """Advance past optional whitespace and quoted/parenthesized link title to closing ')'."""
    n = len(text)
    t = pos
    while t < n and text[t] in " \t":
        t += 1
    if t < n and text[t] == ")":
        return t
    if t >= n or text[t] not in ('"', "'", "("):
        return None

    quote_open = text[t]
    quote_close = ")" if quote_open == "(" else quote_open
    t += 1
    while t < n:
        ch = text[t]
        if ch == "\\" and t + 1 < n:
            t += 2
            continue
        if ch == "\n":
            return None
        if ch == quote_close:
            t += 1
            break
        t += 1
    else:
        return None

    while t < n and text[t] in " \t":
        t += 1
    if t < n and text[t] == ")":
        return t
    return None


def _parse_markdown_link_at(
    text: str, pos: int
) -> tuple[bool, str, str, bool, str, str, int] | None:
    """Parse ![alt](url ...) or [text](url ...) starting at pos."""
    n = len(text)
    is_image = text.startswith("![", pos)
    label_start = pos + 2 if is_image else pos + 1

    idx = label_start
    bracket_depth = 1
    while idx < n and bracket_depth > 0:
        ch = text[idx]
        if ch == "\\" and idx + 1 < n:
            idx += 2
            continue
        if ch == "`":
            code_end = _find_inline_code_end(text, idx)
            if code_end is not None:
                idx = code_end
                continue
        if ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
        idx += 1

    if bracket_depth != 0 or idx >= n or text[idx] != "(":
        return None

    label_raw = text[label_start : idx - 1]
    p = idx + 1
    ws_start = p
    while p < n and text[p] in " \t":
        p += 1
    ws_before = text[ws_start:p]
    if p >= n:
        return None

    if text[p] == "<":
        has_angle = True
        u_start = p + 1
        u_end = u_start
        while u_end < n and text[u_end] != ">":
            if text[u_end] == "\\" and u_end + 1 < n:
                u_end += 2
                continue
            if text[u_end] == "\n":
                return None
            u_end += 1
        if u_end >= n or text[u_end] != ">":
            return None
        raw_url = text[u_start:u_end]
        after_url = u_end + 1
    else:
        has_angle = False
        u_start = p
        u_end = p
        paren_depth = 0
        while u_end < n:
            ch = text[u_end]
            if ch == "\\" and u_end + 1 < n and text[u_end + 1] in "()\\ ":
                u_end += 2
                continue
            if ch in " \t\r\n":
                break
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                if paren_depth == 0:
                    break
                paren_depth -= 1
            u_end += 1
        if paren_depth != 0:
            return None
        raw_url = text[u_start:u_end]
        after_url = u_end

    close_idx = _skip_optional_title(text, after_url)
    if close_idx is None:
        return None

    tail = text[after_url:close_idx]
    return is_image, label_raw, ws_before, has_angle, raw_url, tail, close_idx


def _rewrite_paragraph(
    paragraph: str,
    *,
    chapter_dir: Path,
    output_dir: Path,
    chapter_rel_path: str,
    warnings: list[AssetWarning],
) -> tuple[str, int]:
    """Rewrite Markdown image/link URLs and HTML <img> src inside a non-fenced paragraph."""
    out: list[str] = []
    rebased_count = 0
    pos = 0
    n = len(paragraph)

    def handle_html_img(tag_text: str) -> str:
        nonlocal rebased_count

        def replace_src(m: re.Match[str]) -> str:
            nonlocal rebased_count
            prefix = m.group(1)
            if m.group(2) is not None:
                quote, url_val = '"', m.group(2)
            elif m.group(3) is not None:
                quote, url_val = "'", m.group(3)
            else:
                quote, url_val = "", m.group(4)

            new_url, changed = _rebase_single_url(
                url_val,
                chapter_dir=chapter_dir,
                output_dir=output_dir,
                chapter_rel_path=chapter_rel_path,
                is_image=True,
                has_angle_brackets=False,
                for_html=True,
                warnings=warnings,
            )
            if changed:
                rebased_count += 1
            return f"{prefix}{quote}{new_url}{quote}"

        return HTML_IMG_SRC_RE.sub(replace_src, tag_text)

    while pos < n:
        ch = paragraph[pos]

        if ch == "`":
            code_end = _find_inline_code_end(paragraph, pos)
            if code_end is not None:
                out.append(paragraph[pos:code_end])
                pos = code_end
                continue
            out.append(ch)
            pos += 1
            continue

        if ch == "<" and not _is_escaped(paragraph, pos):
            img_match = HTML_IMG_TAG_RE.match(paragraph, pos)
            if img_match:
                out.append(handle_html_img(img_match.group(0)))
                pos = img_match.end()
                continue

        if (paragraph.startswith("![", pos) or ch == "[") and not _is_escaped(paragraph, pos):
            parsed = _parse_markdown_link_at(paragraph, pos)
            if parsed is not None:
                is_image, label_raw, ws_before, has_angle, raw_url, tail, close_idx = parsed
                rewritten_label, label_rebased = _rewrite_paragraph(
                    label_raw,
                    chapter_dir=chapter_dir,
                    output_dir=output_dir,
                    chapter_rel_path=chapter_rel_path,
                    warnings=warnings,
                )
                rebased_count += label_rebased
                new_url, url_changed = _rebase_single_url(
                    raw_url,
                    chapter_dir=chapter_dir,
                    output_dir=output_dir,
                    chapter_rel_path=chapter_rel_path,
                    is_image=is_image,
                    has_angle_brackets=has_angle,
                    for_html=False,
                    warnings=warnings,
                )
                if url_changed:
                    rebased_count += 1
                prefix = "!" if is_image else ""
                formatted_url = f"<{new_url}>" if has_angle else new_url
                out.append(f"{prefix}[{rewritten_label}]({ws_before}{formatted_url}{tail})")
                pos = close_idx + 1
                continue

        out.append(ch)
        pos += 1

    return "".join(out), rebased_count


def rebase_chapter_links(
    text: str,
    chapter_dir: Path,
    output_dir: Path,
    chapter_rel_path: str,
) -> tuple[str, list[AssetWarning], int]:
    """Rebase relative image/asset paths from chapter_dir to output_dir, skipping code blocks."""
    resolved_chapter_dir = chapter_dir.resolve()
    resolved_output_dir = output_dir.resolve()
    warnings: list[AssetWarning] = []
    rebased_count = 0

    lines = text.split("\n")
    out_lines: list[str] = []
    para_lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    def flush_paragraph() -> None:
        nonlocal rebased_count
        if not para_lines:
            return
        rewritten, count = _rewrite_paragraph(
            "\n".join(para_lines),
            chapter_dir=resolved_chapter_dir,
            output_dir=resolved_output_dir,
            chapter_rel_path=chapter_rel_path,
            warnings=warnings,
        )
        rebased_count += count
        out_lines.extend(rewritten.split("\n"))
        para_lines.clear()

    for line in lines:
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                flush_paragraph()
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                out_lines.append(line)
                continue
            if (
                marker[0] == fence_char
                and len(marker) >= fence_len
                and not line[fence_match.end() :].strip()
            ):
                in_fence = False
                out_lines.append(line)
                continue

        if in_fence:
            out_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            out_lines.append(line)
            continue

        para_lines.append(line)

    flush_paragraph()
    return "\n".join(out_lines), warnings, rebased_count


def merge_document(
    nodes: list[OutlineNode],
    matches: dict[int, MatchResult],
    input_dir: Path,
    output_dir: Path,
    missing_policy: str,
    strip_duplicate_title: bool,
) -> tuple[str, list[AssetWarning], int]:
    """Assemble the final Markdown document, rebasing chapter asset paths to output_dir."""
    chunks: list[str] = []
    all_warnings: list[AssetWarning] = []
    total_rebased = 0

    for node in nodes:
        chunks.append(node.raw_line)
        if not node.is_target:
            continue

        match = matches.get(node.index)
        if match is not None:
            chapter_path = input_dir / match.file_path
            raw_body = chapter_path.read_text(encoding="utf-8-sig")
            body = clean_chapter_body(raw_body, node, strip_duplicate_title)
            if body:
                rebased_body, warnings, rebased_count = rebase_chapter_links(
                    body,
                    chapter_dir=chapter_path.resolve().parent,
                    output_dir=output_dir,
                    chapter_rel_path=match.file_path,
                )
                all_warnings.extend(warnings)
                total_rebased += rebased_count
                chunks.append(rebased_body)
        elif missing_policy == "placeholder":
            chunks.append(f"<!-- [MISSING] 未找到匹配章节文件: {node.title} -->")

    return "\n\n".join(chunks) + "\n", all_warnings, total_rebased


def resolve_output_path(
    outline_path: Path,
    input_dir: Path,
    output_dir_arg: Path | None,
    output_arg: Path | None,
) -> Path:
    """Resolve final output file path, defaulting output directory to sibling of input_dir."""
    default_filename = f"{outline_path.stem}-合并版.md"
    default_output_dir = input_dir.resolve().parent

    if output_dir_arg is not None and output_dir_arg.exists() and not output_dir_arg.is_dir():
        raise ValueError(f"输出文件夹路径不是目录: {output_dir_arg}")

    if output_arg is None:
        target_dir = output_dir_arg if output_dir_arg is not None else default_output_dir
        return target_dir / default_filename

    looks_like_dir = str(output_arg).endswith(("/", "\\"))
    if output_dir_arg is not None:
        if output_arg.is_absolute():
            return output_arg / default_filename if (output_arg.is_dir() or looks_like_dir) else output_arg
        candidate = output_dir_arg / output_arg
        return candidate / default_filename if (candidate.is_dir() or looks_like_dir) else candidate

    if output_arg.is_dir() or looks_like_dir:
        return output_arg / default_filename
    return output_arg


@dataclass(frozen=True)
class MergeConfig:
    """Validated parameters for a merge execution (shared by CLI and GUI)."""

    outline: Path
    input_dir: Path = Path("output")
    output_dir: Path | None = None
    output: Path | None = None
    level: str = "4"
    min_similarity: float = 0.72
    min_code_only_similarity: float = 0.0
    missing_policy: str = "placeholder"
    strip_duplicate_title: bool = False
    report: Path | None = None
    dry_run: bool = False

    def to_preset_dict(self) -> dict[str, object]:
        """Serialize parameters into a portable JSON preset for repeating the run."""
        outline_res = self.outline.resolve()
        input_res = self.input_dir.resolve()
        output_dir_val = str(self.output_dir.resolve()) if self.output_dir is not None else None
        if self.output is None:
            output_val = None
        elif self.output_dir is not None and not self.output.is_absolute():
            output_val = str(self.output)
        else:
            output_val = str(self.output.resolve())

        report_val = str(self.report.resolve()) if self.report is not None else None
        return {
            "outline": str(outline_res),
            "input_dir": str(input_res),
            "output_dir": output_dir_val,
            "output": output_val,
            "level": self.level,
            "min_similarity": self.min_similarity,
            "min_code_only_similarity": self.min_code_only_similarity,
            "missing_policy": self.missing_policy,
            "strip_duplicate_title": self.strip_duplicate_title,
            "report": report_val,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    @classmethod
    def from_preset_dict(cls, data: dict[str, object]) -> MergeConfig:
        """Reconstruct a MergeConfig from a saved preset dictionary."""
        outline_str = str(data.get("outline") or "").strip()
        if not outline_str:
            raise ValueError("上次运行记录中缺少大纲文件路径 (outline)")
        input_str = str(data.get("input_dir") or "output").strip()
        out_dir_raw = data.get("output_dir")
        out_raw = data.get("output")
        report_raw = data.get("report")
        return cls(
            outline=Path(outline_str),
            input_dir=Path(input_str),
            output_dir=Path(str(out_dir_raw)) if out_dir_raw else None,
            output=Path(str(out_raw)) if out_raw else None,
            level=str(data.get("level") or "4"),
            min_similarity=float(data.get("min_similarity", 0.72)),
            min_code_only_similarity=float(data.get("min_code_only_similarity", 0.0)),
            missing_policy=str(data.get("missing_policy") or "placeholder"),
            strip_duplicate_title=bool(data.get("strip_duplicate_title", False)),
            report=Path(str(report_raw)) if report_raw else None,
            dry_run=False,
        )


@dataclass
class MergeRunResult:
    """Structured result returned by run_merge_pipeline for CLI formatting and GUI inspection."""

    exit_code: int
    output_path: Path
    output_dir: Path
    nodes: list[OutlineNode]
    target_nodes: list[OutlineNode]
    files: list[ChapterFile]
    matches: dict[int, MatchResult]
    missing_nodes: list[OutlineNode]
    orphan_files: list[ChapterFile]
    asset_warnings: list[AssetWarning]
    rebased_count: int
    merged_text: str
    written_output: bool
    report_path: Path | None = None
    error_message: str | None = None


def get_default_last_run_path() -> Path:
    """Return path to the persisted last-run preset JSON file."""
    env_override = os.environ.get("MERGE_BID_CONFIG_FILE")
    if env_override:
        return Path(env_override)
    return Path.home() / ".config" / "merge_bid" / "last_run.json"


def load_last_run_state(
    config_path: Path | None = None,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Load the most recent preset and recent history list from JSON."""
    path = config_path or get_default_last_run_path()
    if not path.is_file():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    if not isinstance(payload, dict):
        return None, []

    last = payload.get("last")
    history_raw = payload.get("history")
    history: list[dict[str, object]] = []
    if isinstance(history_raw, list):
        history = [item for item in history_raw if isinstance(item, dict) and item.get("outline")]
    if isinstance(last, dict) and last.get("outline"):
        if not history:
            history = [last]
        return last, history
    if history:
        return history[0], history
    return None, []


def save_last_run_state(
    preset: dict[str, object],
    config_path: Path | None = None,
    max_history: int = 8,
) -> None:
    """Persist the latest run preset and deduplicated recent history."""
    path = config_path or get_default_last_run_path()
    _, existing_history = load_last_run_state(path)

    def identity(item: dict[str, object]) -> tuple[object, ...]:
        return (
            item.get("outline"),
            item.get("input_dir"),
            item.get("output_dir"),
            item.get("output"),
        )

    preset_key = identity(preset)
    deduped = [preset] + [item for item in existing_history if identity(item) != preset_key]
    payload = {
        "last": preset,
        "history": deduped[:max_history],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # Config persistence should never abort a merge run in read-only environments.
        pass


def format_cli_command(config: MergeConfig) -> str:
    """Format an equivalent CLI invocation string for a MergeConfig."""
    parts = ["python3", "merge_bid.py", "-O", str(config.outline), "-i", str(config.input_dir)]
    if config.output_dir is not None:
        parts.extend(["-d", str(config.output_dir)])
    if config.output is not None:
        parts.extend(["-o", str(config.output)])
    if config.level != "4":
        parts.extend(["--level", config.level])
    if config.missing_policy != "placeholder":
        parts.extend(["--missing-policy", config.missing_policy])
    if config.strip_duplicate_title:
        parts.append("--strip-duplicate-title")
    if abs(config.min_similarity - 0.72) > 1e-9:
        parts.extend(["--min-similarity", f"{config.min_similarity:.2f}"])
    if abs(config.min_code_only_similarity - 0.0) > 1e-9:
        parts.extend(["--min-code-only-similarity", f"{config.min_code_only_similarity:.2f}"])
    if config.report is not None:
        parts.extend(["--report", str(config.report)])
    if config.dry_run:
        parts.append("--dry-run")
    return shlex.join(parts)


def run_merge_pipeline(config: MergeConfig) -> MergeRunResult:
    """Execute outline parsing, matching, asset rebasing, reporting, and optional file write."""
    outline_path = config.outline
    input_dir = config.input_dir

    if not outline_path.is_file():
        raise FileNotFoundError(f"大纲文件不存在: {outline_path}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"章节目录不存在: {input_dir}")

    output_path = resolve_output_path(
        outline_path=outline_path,
        input_dir=input_dir,
        output_dir_arg=config.output_dir,
        output_arg=config.output,
    )
    if output_path.exists() and output_path.is_dir():
        raise ValueError(f"输出文件路径指向已存在的目录: {output_path}")

    output_dir = output_path.resolve().parent

    nodes = parse_outline(outline_path, config.level)
    target_nodes = [n for n in nodes if n.is_target]
    if not target_nodes:
        raise ValueError(f"大纲中未找到目标层级 ({config.level}) 的标题")

    exclude = {outline_path, output_path}
    if config.report:
        exclude.add(config.report)
    files = scan_chapter_files(input_dir, exclude)

    matches, missing_nodes, orphan_files = match_chapters(
        nodes,
        files,
        min_similarity=config.min_similarity,
        min_code_only_similarity=config.min_code_only_similarity,
    )

    merged, asset_warnings, rebased_count = merge_document(
        nodes,
        matches,
        input_dir=input_dir,
        output_dir=output_dir,
        missing_policy=config.missing_policy,
        strip_duplicate_title=config.strip_duplicate_title,
    )

    exact_count = sum(1 for m in matches.values() if m.match_type == "exact")
    fuzzy_matches = [m for m in matches.values() if m.match_type != "exact"]

    written_report: Path | None = None
    if config.report:
        report_payload = {
            "outline": str(outline_path),
            "input_dir": str(input_dir),
            "output": str(output_path),
            "output_dir": str(output_dir),
            "summary": {
                "total_headings": len(nodes),
                "target_headings": len(target_nodes),
                "scanned_files": len(files),
                "matched": len(matches),
                "exact_matches": exact_count,
                "tolerant_matches": len(fuzzy_matches),
                "missing": len(missing_nodes),
                "orphan_files": len(orphan_files),
                "rebased_image_count": rebased_count,
                "asset_warnings": len(asset_warnings),
            },
            "matches": [asdict(matches[n.index]) for n in target_nodes if n.index in matches],
            "missing_headings": [n.title for n in missing_nodes],
            "orphan_files": [c.rel_path for c in orphan_files],
            "asset_warnings": [asdict(w) for w in asset_warnings],
        }
        config.report.parent.mkdir(parents=True, exist_ok=True)
        config.report.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written_report = config.report

    if missing_nodes and config.missing_policy == "error":
        return MergeRunResult(
            exit_code=1,
            output_path=output_path,
            output_dir=output_dir,
            nodes=nodes,
            target_nodes=target_nodes,
            files=files,
            matches=matches,
            missing_nodes=missing_nodes,
            orphan_files=orphan_files,
            asset_warnings=asset_warnings,
            rebased_count=rebased_count,
            merged_text=merged,
            written_output=False,
            report_path=written_report,
            error_message="存在缺失章节且设置了 --missing-policy error，终止合并。",
        )

    if config.dry_run:
        return MergeRunResult(
            exit_code=0,
            output_path=output_path,
            output_dir=output_dir,
            nodes=nodes,
            target_nodes=target_nodes,
            files=files,
            matches=matches,
            missing_nodes=missing_nodes,
            orphan_files=orphan_files,
            asset_warnings=asset_warnings,
            rebased_count=rebased_count,
            merged_text=merged,
            written_output=False,
            report_path=written_report,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(merged, encoding="utf-8")
    return MergeRunResult(
        exit_code=0,
        output_path=output_path,
        output_dir=output_dir,
        nodes=nodes,
        target_nodes=target_nodes,
        files=files,
        matches=matches,
        missing_nodes=missing_nodes,
        orphan_files=orphan_files,
        asset_warnings=asset_warnings,
        rebased_count=rebased_count,
        merged_text=merged,
        written_output=True,
        report_path=written_report,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="根据 Markdown 投标大纲合并各章节文件（支持 CLI / PySide6 图形界面、快速代入上次参数与图片路径自动重算）"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="启动 PySide6 图形界面模式",
    )
    parser.add_argument(
        "--use-last",
        action="store_true",
        help="快速代入上次运行保存的参数（可搭配其他参数局部覆盖）",
    )
    parser.add_argument(
        "--last-config-file",
        type=Path,
        default=None,
        help="可选：指定读取/保存上次运行参数的 JSON 配置文件路径",
    )
    parser.add_argument(
        "-O",
        "--outline",
        type=Path,
        default=None,
        help="投标大纲 Markdown 文件路径",
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        default=None,
        help="待合并章节 Markdown 所在目录，会递归遍历（默认: output）",
    )
    parser.add_argument(
        "-d",
        "--output-dir",
        type=Path,
        default=None,
        help="合并后输出文件夹路径（默认: 待合并文件夹的同级目录，即 input-dir 的父目录）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="可选：指定输出 Markdown 文件路径或文件名（默认: <输出文件夹>/<大纲文件名>-合并版.md）",
    )
    parser.add_argument(
        "--level",
        default=None,
        choices=["1", "2", "3", "4", "5", "6", "leaf"],
        help="需要填充正文的大纲标题层级，或使用 leaf 自动识别末级标题（默认: 4）",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        help="跨编号模糊匹配的最低相似度阈值 0~1（默认: 0.72）",
    )
    parser.add_argument(
        "--min-code-only-similarity",
        type=float,
        default=None,
        help="仅编号相同时允许兜底匹配的最低标题相似度 0~1（默认: 0.0，即只要多级编号一致即可兜底匹配）",
    )
    parser.add_argument(
        "--missing-policy",
        choices=["placeholder", "empty", "error"],
        default=None,
        help="缺失章节的处理方式: placeholder(插入注释占位)/empty(仅保留标题)/error(报错退出)（默认: placeholder）",
    )
    parser.add_argument(
        "--strip-duplicate-title",
        action="store_true",
        default=None,
        help="若章节正文首行重复写了当前四级标题，则自动剔除",
    )
    parser.add_argument(
        "--no-strip-duplicate-title",
        action="store_false",
        dest="strip_duplicate_title",
        help="取消自动剔除章节首行重复标题（常用于覆盖 --use-last）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：输出 JSON 格式的匹配与资源路径审计报告路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅执行解析、匹配与路径重算检查并打印统计/告警，不写入合并文件",
    )
    return parser


def _build_config_from_args(args: argparse.Namespace, last_config_path: Path | None) -> MergeConfig:
    """Resolve CLI arguments into a MergeConfig, optionally seeding from last run preset."""
    base: MergeConfig | None = None
    if args.use_last:
        last_preset, _ = load_last_run_state(last_config_path)
        if last_preset is None:
            raise ValueError("未找到上次运行记录，请先指定 -O/--outline 运行一次")
        base = MergeConfig.from_preset_dict(last_preset)
        print(f"[已代入上次参数] 记录时间: {last_preset.get('saved_at', '未知')}")

    outline = args.outline if args.outline is not None else (base.outline if base else None)
    if outline is None:
        raise ValueError("请指定 -O/--outline 大纲文件，或使用 --use-last 代入上次参数 / --gui 启动图形界面")

    return MergeConfig(
        outline=outline,
        input_dir=args.input_dir if args.input_dir is not None else (base.input_dir if base else Path("output")),
        output_dir=args.output_dir if args.output_dir is not None else (base.output_dir if base else None),
        output=args.output if args.output is not None else (base.output if base else None),
        level=args.level if args.level is not None else (base.level if base else "4"),
        min_similarity=(
            args.min_similarity
            if args.min_similarity is not None
            else (base.min_similarity if base else 0.72)
        ),
        min_code_only_similarity=(
            args.min_code_only_similarity
            if args.min_code_only_similarity is not None
            else (base.min_code_only_similarity if base else 0.0)
        ),
        missing_policy=(
            args.missing_policy
            if args.missing_policy is not None
            else (base.missing_policy if base else "placeholder")
        ),
        strip_duplicate_title=(
            args.strip_duplicate_title
            if args.strip_duplicate_title is not None
            else (base.strip_duplicate_title if base else False)
        ),
        report=args.report if args.report is not None else (base.report if base else None),
        dry_run=bool(args.dry_run),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    last_config_path: Path | None = args.last_config_file

    if args.gui:
        try:
            from merge_bid_gui import launch_gui
        except ImportError as exc:
            print(
                f"错误: 启动图形界面需要 PySide6 ({exc})。\n"
                "请使用项目虚拟环境运行: .venv/bin/python merge_bid.py --gui",
                file=sys.stderr,
            )
            return 2
        return launch_gui(config_path=last_config_path)

    try:
        config = _build_config_from_args(args, last_config_path)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if args.use_last:
        print(f"  大纲: {config.outline}")
        print(f"  目录: {config.input_dir}")
        if config.output_dir is not None:
            print(f"  输出文件夹: {config.output_dir}")
        if config.output is not None:
            print(f"  输出文件: {config.output}")

    try:
        result = run_merge_pipeline(config)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    save_last_run_state(config.to_preset_dict(), config_path=last_config_path)

    exact_count = sum(1 for m in result.matches.values() if m.match_type == "exact")
    fuzzy_matches = [m for m in result.matches.values() if m.match_type != "exact"]
    pre_rebased_warnings = [w for w in result.asset_warnings if w.kind == "pre_rebased_for_output"]
    missing_asset_warnings = [w for w in result.asset_warnings if w.kind == "missing_asset"]

    print(
        f"大纲标题总数: {len(result.nodes)} | 待填充末级章节: {len(result.target_nodes)} | 扫描文件数: {len(result.files)}"
    )
    print(
        f"匹配成功: {len(result.matches)}/{len(result.target_nodes)} "
        f"(精确匹配: {exact_count}, 智能容错匹配: {len(fuzzy_matches)}, 缺失: {len(result.missing_nodes)}, 未被使用文件: {len(result.orphan_files)})"
    )
    print(f"图片/资源路径重算: {result.rebased_count} 处 | 资源告警: {len(result.asset_warnings)} 条")

    if fuzzy_matches:
        print("\n[提示] 以下章节通过智能容错规则匹配，建议确认:")
        for m in fuzzy_matches:
            print(f"  - [{m.match_type} | {m.score:.2f}] {m.warning}")

    if result.missing_nodes:
        print("\n[警告] 以下大纲章节未找到对应文件:", file=sys.stderr)
        for n in result.missing_nodes:
            print(f"  - {n.raw_line}", file=sys.stderr)

    if result.orphan_files:
        print("\n[提示] 输入目录中以下文件未被大纲引用:")
        for chap in result.orphan_files:
            print(f"  - {chap.rel_path}")

    if pre_rebased_warnings:
        print("\n[提示] 以下资源路径已按输出目录基准预写，保留原路径（单章独立预览时可能断链）:")
        for w in pre_rebased_warnings:
            print(f"  - {w.message}")

    if missing_asset_warnings:
        print("\n[警告] 以下资源路径在章节目录与输出目录下均不存在（可能断链）:", file=sys.stderr)
        for w in missing_asset_warnings:
            print(f"  - {w.message}", file=sys.stderr)

    if result.report_path is not None:
        print(f"\n匹配报告已写入: {result.report_path}")

    if result.exit_code != 0:
        print(f"\n错误: {result.error_message}", file=sys.stderr)
        return result.exit_code

    if config.dry_run:
        print("\n[dry-run] 检查完成，未写入合并文件。")
        return 0

    print(f"\n合并完成: {result.output_path}")

    if result.missing_nodes:
        action_note = (
            "已在正文中插入 <!-- [MISSING] ... --> 占位标记"
            if config.missing_policy == "placeholder"
            else "已仅保留对应大纲标题"
        )
        print(
            f"\n[注意] 本次合并共有 {len(result.missing_nodes)} 个缺失章节（{action_note}），请补充对应文件后重新合并:"
        )
        for n in result.missing_nodes:
            print(f"  - {n.raw_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
