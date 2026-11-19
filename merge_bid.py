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
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

INVISIBLE_CHARS_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u200e\u200f\u2060]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

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

    # Tier 7: Exact section code fallback when title changed substantially (still above safety floor)
    if same_code and body_sim >= min_code_only_similarity:
        return (
            7,
            0.68 + 0.10 * body_sim,
            "code_fallback",
            f"仅编号一致且标题差异较大 (相似度 {body_sim:.2f})，请人工复核: 标题「{node.title}」<- 文件「{chap.rel_path}」",
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


def merge_document(
    nodes: list[OutlineNode],
    matches: dict[int, MatchResult],
    input_dir: Path,
    missing_policy: str,
    strip_duplicate_title: bool,
) -> str:
    """Assemble the final Markdown document preserving all outline headings."""
    chunks: list[str] = []

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
                chunks.append(body)
        elif missing_policy == "placeholder":
            chunks.append(f"<!-- [MISSING] 未找到匹配章节文件: {node.title} -->")

    return "\n\n".join(chunks) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="根据 Markdown 投标大纲合并各章节文件（支持文件名不规范/截断/编号差异智能匹配）"
    )
    parser.add_argument(
        "-O",
        "--outline",
        type=Path,
        required=True,
        help="投标大纲 Markdown 文件路径",
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        default=Path("output"),
        help="待合并章节 Markdown 所在目录（默认: output）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="合并后输出 Markdown 文件路径（默认: <大纲文件名>-合并版.md）",
    )
    parser.add_argument(
        "--level",
        default="4",
        choices=["1", "2", "3", "4", "5", "6", "leaf"],
        help="需要填充正文的大纲标题层级，或使用 leaf 自动识别末级标题（默认: 4）",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.72,
        help="跨编号模糊匹配的最低相似度阈值 0~1（默认: 0.72）",
    )
    parser.add_argument(
        "--min-code-only-similarity",
        type=float,
        default=0.20,
        help="仅编号相同时允许兜底匹配的最低标题相似度 0~1（默认: 0.20）",
    )
    parser.add_argument(
        "--missing-policy",
        choices=["placeholder", "empty", "error"],
        default="placeholder",
        help="缺失章节的处理方式: placeholder(插入注释占位)/empty(仅保留标题)/error(报错退出)（默认: placeholder）",
    )
    parser.add_argument(
        "--strip-duplicate-title",
        action="store_true",
        help="若章节正文首行重复写了当前四级标题，则自动剔除",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：输出 JSON 格式的匹配审计报告路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅执行解析与匹配检查并打印统计/告警，不写入合并文件",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    outline_path: Path = args.outline
    input_dir: Path = args.input_dir
    output_path: Path = args.output or Path(f"{outline_path.stem}-合并版.md")

    if not outline_path.is_file():
        print(f"错误: 大纲文件不存在: {outline_path}", file=sys.stderr)
        return 2
    if not input_dir.is_dir():
        print(f"错误: 章节目录不存在: {input_dir}", file=sys.stderr)
        return 2

    nodes = parse_outline(outline_path, args.level)
    target_nodes = [n for n in nodes if n.is_target]
    if not target_nodes:
        print(f"错误: 大纲中未找到目标层级 ({args.level}) 的标题", file=sys.stderr)
        return 2

    exclude = {outline_path, output_path}
    if args.report:
        exclude.add(args.report)
    files = scan_chapter_files(input_dir, exclude)

    matches, missing_nodes, orphan_files = match_chapters(
        nodes,
        files,
        min_similarity=args.min_similarity,
        min_code_only_similarity=args.min_code_only_similarity,
    )

    exact_count = sum(1 for m in matches.values() if m.match_type == "exact")
    fuzzy_matches = [m for m in matches.values() if m.match_type != "exact"]

    print(f"大纲标题总数: {len(nodes)} | 待填充末级章节: {len(target_nodes)} | 扫描文件数: {len(files)}")
    print(
        f"匹配成功: {len(matches)}/{len(target_nodes)} "
        f"(精确匹配: {exact_count}, 智能容错匹配: {len(fuzzy_matches)}, 缺失: {len(missing_nodes)}, 未被使用文件: {len(orphan_files)})"
    )

    if fuzzy_matches:
        print("\n[提示] 以下章节通过智能容错规则匹配，建议确认:")
        for m in fuzzy_matches:
            print(f"  - [{m.match_type} | {m.score:.2f}] {m.warning}")

    if missing_nodes:
        print("\n[警告] 以下大纲章节未找到对应文件:", file=sys.stderr)
        for n in missing_nodes:
            print(f"  - {n.raw_line}", file=sys.stderr)

    if orphan_files:
        print("\n[提示] 输入目录中以下文件未被大纲引用:")
        for chap in orphan_files:
            print(f"  - {chap.rel_path}")

    if args.report:
        report_payload = {
            "outline": str(outline_path),
            "input_dir": str(input_dir),
            "output": str(output_path),
            "summary": {
                "total_headings": len(nodes),
                "target_headings": len(target_nodes),
                "scanned_files": len(files),
                "matched": len(matches),
                "exact_matches": exact_count,
                "tolerant_matches": len(fuzzy_matches),
                "missing": len(missing_nodes),
                "orphan_files": len(orphan_files),
            },
            "matches": [asdict(matches[n.index]) for n in target_nodes if n.index in matches],
            "missing_headings": [n.title for n in missing_nodes],
            "orphan_files": [c.rel_path for c in orphan_files],
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n匹配报告已写入: {args.report}")

    if missing_nodes and args.missing_policy == "error":
        print("\n错误: 存在缺失章节且设置了 --missing-policy error，终止合并。", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n[dry-run] 检查完成，未写入合并文件。")
        return 0

    merged = merge_document(
        nodes,
        matches,
        input_dir=input_dir,
        missing_policy=args.missing_policy,
        strip_duplicate_title=args.strip_duplicate_title,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(merged, encoding="utf-8")
    print(f"\n合并完成: {output_path}")

    if missing_nodes:
        action_note = (
            "已在正文中插入 <!-- [MISSING] ... --> 占位标记"
            if args.missing_policy == "placeholder"
            else "已仅保留对应大纲标题"
        )
        print(
            f"\n[注意] 本次合并共有 {len(missing_nodes)} 个缺失章节（{action_note}），请补充对应文件后重新合并:"
        )
        for n in missing_nodes:
            print(f"  - {n.raw_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
