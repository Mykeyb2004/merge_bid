"""Unit tests for merge_bid.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from merge_bid import main


class MergeBidTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cfg_dir = tempfile.TemporaryDirectory()
        self._old_cfg_env = os.environ.get("MERGE_BID_CONFIG_FILE")
        os.environ["MERGE_BID_CONFIG_FILE"] = str(Path(self._cfg_dir.name) / "last_run.json")

    def tearDown(self) -> None:
        if self._old_cfg_env is None:
            os.environ.pop("MERGE_BID_CONFIG_FILE", None)
        else:
            os.environ["MERGE_BID_CONFIG_FILE"] = self._old_cfg_env
        self._cfg_dir.cleanup()

    def test_tolerant_filename_matching_and_hierarchy_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outline = root / "outline.md"
            chapters_dir = root / "chapters"
            nested_dir = chapters_dir / "sub"
            nested_dir.mkdir(parents=True)
            out_file = root / "merged.md"

            outline.write_text(
                "\n".join(
                    [
                        "# 测试项目总标题",
                        "",
                        "## 1. 第一章：管理制度",
                        "### 1.1 人员培训",
                        "#### 1.1.1 岗前培训/准入与“考核”制度",
                        "#### 1.1.10 特殊字符:边界*控制?规范",
                        "#### 1.1.2 超长标题在文件系统限制下被截断的完整测试名称示例说明",
                        "#### 1.1.3 编号被调整但标题一致的章节",
                        "#### 1.1.4 缺失的章节",
                    ]
                ),
                encoding="utf-8",
            )

            # 1) Illegal chars replaced with '_' and quotes stripped, NFD/fullwidth variation
            (chapters_dir / "1.1.1 岗前培训_准入与考核制度.md").write_text(
                "\ufeff一、岗前要求\n\n正文内容A。\n", encoding="utf-8"
            )
            # 2) Dash code + zero-padded + missing spaces + illegal chars replaced by '-'
            (nested_dir / "1-1-10_特殊字符-边界-控制-规范.md").write_text(
                "一、边界控制\n\n正文内容B。\n", encoding="utf-8"
            )
            # 3) Truncated filename
            (chapters_dir / "1.1.2 超长标题在文件系统限制下被截断.md").write_text(
                "一、截断章节\n\n正文内容C。\n", encoding="utf-8"
            )
            # 4) Renumbered in outline (file has old code 1.1.9)
            (chapters_dir / "1.1.9 编号被调整但标题一致的章节.md").write_text(
                "一、调整编号章节\n\n正文内容D。\n", encoding="utf-8"
            )
            # 5) Unused orphan file
            (chapters_dir / "9.9.9 废弃章节.md").write_text("废弃内容\n", encoding="utf-8")

            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                rc = main(
                    [
                        "--outline",
                        str(outline),
                        "--input-dir",
                        str(chapters_dir),
                        "--output",
                        str(out_file),
                    ]
                )
            self.assertEqual(rc, 0)
            stdout_text = stdout_buf.getvalue()
            self.assertIn("合并完成:", stdout_text)
            self.assertIn("[注意] 本次合并共有 1 个缺失章节", stdout_text)
            self.assertIn("#### 1.1.4 缺失的章节", stdout_text.split("合并完成:")[-1])

            merged = out_file.read_text(encoding="utf-8")
            self.assertIn("# 测试项目总标题", merged)
            self.assertIn("## 1. 第一章：管理制度", merged)
            self.assertIn("### 1.1 人员培训", merged)
            self.assertIn("#### 1.1.1 岗前培训/准入与“考核”制度\n\n一、岗前要求", merged)
            self.assertIn("#### 1.1.10 特殊字符:边界*控制?规范\n\n一、边界控制", merged)
            self.assertIn("#### 1.1.2 超长标题在文件系统限制下被截断的完整测试名称示例说明\n\n一、截断章节", merged)
            self.assertIn("#### 1.1.3 编号被调整但标题一致的章节\n\n一、调整编号章节", merged)
            self.assertIn("<!-- [MISSING] 未找到匹配章节文件: 1.1.4 缺失的章节 -->", merged)
            self.assertNotIn("废弃内容", merged)
            self.assertNotIn("\ufeff", merged)

    def test_leaf_mode_and_strip_duplicate_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outline = root / "outline.md"
            chapters_dir = root / "chapters"
            chapters_dir.mkdir()
            out_file = root / "merged.md"

            outline.write_text(
                "\n".join(
                    [
                        "# 项目",
                        "## 1. 第一部分",
                        "### 1.1 三级叶子章节",
                        "## 2. 第二部分",
                        "### 2.1 分组标题",
                        "#### 2.1.1 四级叶子章节",
                    ]
                ),
                encoding="utf-8",
            )
            (chapters_dir / "1.1 三级叶子章节.md").write_text(
                "### 1.1 三级叶子章节\n\n一、三级正文\n", encoding="utf-8"
            )
            (chapters_dir / "2.1.1 四级叶子章节.md").write_text(
                "一、四级正文\n", encoding="utf-8"
            )

            rc = main(
                [
                    "--outline",
                    str(outline),
                    "--input-dir",
                    str(chapters_dir),
                    "--output",
                    str(out_file),
                    "--level",
                    "leaf",
                    "--strip-duplicate-title",
                    "--missing-policy",
                    "error",
                ]
            )
            self.assertEqual(rc, 0)
            merged = out_file.read_text(encoding="utf-8")
            self.assertEqual(merged.count("1.1 三级叶子章节"), 1)
            self.assertIn("一、三级正文", merged)
            self.assertIn("一、四级正文", merged)

    def test_default_output_dir_is_sibling_of_input_dir_and_rebases_chinese_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            other_cwd = root / "elsewhere"
            chapters_dir = project / "output"
            pics_dir = project / "pics" / "2.3.1_年度计划图_待确认"
            chapters_dir.mkdir(parents=True)
            pics_dir.mkdir(parents=True)
            other_cwd.mkdir()

            outline = project / "投标大纲-v03.md"
            outline.write_text(
                "# 总标题\n\n#### 2.3.1 项目年度总体实施计划\n",
                encoding="utf-8",
            )
            (pics_dir / "01_年度实施进度.png").write_bytes(b"PNG")
            (chapters_dir / "2.3.1 项目年度总体实施计划.md").write_text(
                "正文开始。\n\n"
                "![年度图](../pics/2.3.1_年度计划图_待确认/01_年度实施进度.png)\n",
                encoding="utf-8",
            )

            old_cwd = Path.cwd()
            stdout_buf = io.StringIO()
            try:
                os.chdir(other_cwd)
                with contextlib.redirect_stdout(stdout_buf):
                    rc = main(
                        [
                            "--outline",
                            str(outline),
                            "--input-dir",
                            str(chapters_dir),
                        ]
                    )
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 0)
            expected_out = project / "投标大纲-v03-合并版.md"
            self.assertTrue(expected_out.is_file())
            merged = expected_out.read_text(encoding="utf-8")
            self.assertIn("![年度图](pics/2.3.1_年度计划图_待确认/01_年度实施进度.png)", merged)
            self.assertIn("图片/资源路径重算: 1 处", stdout_buf.getvalue())

    def test_nested_subdirs_and_custom_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters_dir = root / "chapters"
            nested_dir = chapters_dir / "sub" / "nested"
            pics_dir = root / "pics"
            dist_dir = root / "dist"
            nested_dir.mkdir(parents=True)
            pics_dir.mkdir(parents=True)

            outline = root / "outline.md"
            outline.write_text("# 项目\n\n#### 1.1.1 嵌套章节\n", encoding="utf-8")
            (pics_dir / "a.png").write_bytes(b"PNG")
            (nested_dir / "1.1.1 嵌套章节.md").write_text(
                "![嵌套图](../../../pics/a.png)\n", encoding="utf-8"
            )

            rc = main(
                [
                    "-O",
                    str(outline),
                    "-i",
                    str(chapters_dir),
                    "--output-dir",
                    str(dist_dir),
                ]
            )
            self.assertEqual(rc, 0)
            out_file = dist_dir / "outline-合并版.md"
            self.assertTrue(out_file.is_file())
            merged = out_file.read_text(encoding="utf-8")
            self.assertIn("![嵌套图](../pics/a.png)", merged)

    def test_asset_syntax_variants_code_blocks_and_external_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters_dir = root / "chapters"
            pics_dir = root / "pics"
            space_dir = pics_dir / "中文 目录"
            chapters_dir.mkdir(parents=True)
            space_dir.mkdir(parents=True)

            (pics_dir / "a.png").write_bytes(b"PNG")
            (pics_dir / "b.png").write_bytes(b"PNG")
            (pics_dir / "中文.png").write_bytes(b"PNG")
            (pics_dir / "图(1).png").write_bytes(b"PNG")
            (space_dir / "图 1.png").write_bytes(b"PNG")
            (space_dir / "图 2.png").write_bytes(b"PNG")

            outline = root / "outline.md"
            outline.write_text("# 项目\n\n#### 1.1.1 语法全覆盖\n", encoding="utf-8")
            encoded_cn = quote("中文.png")
            chapter_content = "\n".join(
                [
                    '![带标题](../pics/a.png "说明")',
                    "![尖括号](<../pics/中文 目录/图 1.png>)",
                    "![空格编码](../pics/中文%20目录/图%202.png)",
                    f"![中文编码](../pics/{encoded_cn})",
                    "![嵌套括号](../pics/图(1).png)",
                    '<img src="../pics/b.png" width="100" />',
                    "[![链接图片](../pics/a.png)](https://example.com)",
                    "行内代码 `![x](../pics/x.png)` 和 `<img src=\"../pics/y.png\">` 不改写。",
                    "![`行内代码alt`](../pics/a.png)",
                    "",
                    "```markdown",
                    "![代码块示例](../pics/a.png)",
                    '<img src="../pics/b.png" />',
                    "```",
                    "",
                    "~~~~",
                    "![波浪线代码块](../pics/a.png)",
                    "~~~~",
                    "",
                    "![外链](https://example.com/a.png)",
                    "![内嵌](data:image/png;base64,AAAA)",
                    "[锚点](#section)",
                    "![绝对](/abs/path.png)",
                ]
            )
            (chapters_dir / "1.1.1 语法全覆盖.md").write_text(chapter_content, encoding="utf-8")

            rc = main(["-O", str(outline), "-i", str(chapters_dir)])
            self.assertEqual(rc, 0)

            merged = (root / "outline-合并版.md").read_text(encoding="utf-8")
            self.assertIn('![带标题](pics/a.png "说明")', merged)
            self.assertIn("![尖括号](<pics/中文 目录/图 1.png>)", merged)
            self.assertIn("![空格编码](pics/中文%20目录/图%202.png)", merged)
            self.assertIn("![中文编码](pics/中文.png)", merged)
            self.assertIn("![嵌套括号](pics/图(1).png)", merged)
            self.assertIn('<img src="pics/b.png" width="100" />', merged)
            self.assertIn("[![链接图片](pics/a.png)](https://example.com)", merged)
            self.assertIn(
                "行内代码 `![x](../pics/x.png)` 和 `<img src=\"../pics/y.png\">` 不改写。",
                merged,
            )
            self.assertIn("![`行内代码alt`](pics/a.png)", merged)
            self.assertIn("```markdown\n![代码块示例](../pics/a.png)\n<img src=\"../pics/b.png\" />\n```", merged)
            self.assertIn("~~~~\n![波浪线代码块](../pics/a.png)\n~~~~", merged)
            self.assertIn("![外链](https://example.com/a.png)", merged)
            self.assertIn("![内嵌](data:image/png;base64,AAAA)", merged)
            self.assertIn("[锚点](#section)", merged)
            self.assertIn("![绝对](/abs/path.png)", merged)

    def test_pre_rebased_and_missing_asset_warnings_in_cli_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters_dir = root / "chapters"
            pics_dir = root / "pics"
            chapters_dir.mkdir(parents=True)
            pics_dir.mkdir(parents=True)
            (pics_dir / "exist.png").write_bytes(b"PNG")

            outline = root / "outline.md"
            outline.write_text("# 项目\n\n#### 1.1.1 告警章节\n", encoding="utf-8")
            (chapters_dir / "1.1.1 告警章节.md").write_text(
                "![预写根目录](pics/exist.png)\n\n![断链图](../pics/missing.png)\n",
                encoding="utf-8",
            )
            report_file = root / "report.json"

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                rc = main(
                    [
                        "-O",
                        str(outline),
                        "-i",
                        str(chapters_dir),
                        "--report",
                        str(report_file),
                    ]
                )

            self.assertEqual(rc, 0)
            merged = (root / "outline-合并版.md").read_text(encoding="utf-8")
            self.assertIn("![预写根目录](pics/exist.png)", merged)
            self.assertIn("![断链图](../pics/missing.png)", merged)

            self.assertIn("已按输出目录基准预写", stdout_buf.getvalue())
            self.assertIn("../pics/missing.png", stderr_buf.getvalue())

            report = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["rebased_image_count"], 0)
            self.assertEqual(report["summary"]["asset_warnings"], 2)
            kinds = {w["kind"] for w in report["asset_warnings"]}
            self.assertEqual(kinds, {"pre_rebased_for_output", "missing_asset"})

    def test_same_code_fallback_for_divergent_or_code_only_filenames_and_missing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters_dir = root / "chapters"
            chapters_dir.mkdir(parents=True)

            outline = root / "outline.md"
            outline.write_text(
                "\n".join(
                    [
                        "# 项目",
                        "#### 1.1.1 全面安全生产应急管理与风险防控实施细则",
                        "#### 2.3.1 项目年度总体实施计划与阶段交付框架",
                        "#### 2.3.2 暂无内容但需保留标题的章节",
                    ]
                ),
                encoding="utf-8",
            )
            # Divergent title text (< 0.20 similarity) with matching multi-level code
            (chapters_dir / "1.1.1 简表.md").write_text("安全应急正文。\n", encoding="utf-8")
            # Code-only filename with no title text
            (chapters_dir / "2.3.1.md").write_text("年度计划正文。\n", encoding="utf-8")

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                rc = main(
                    [
                        "-O",
                        str(outline),
                        "-i",
                        str(chapters_dir),
                        "--missing-policy",
                        "empty",
                    ]
                )

            self.assertEqual(rc, 0)
            merged = (root / "outline-合并版.md").read_text(encoding="utf-8")
            self.assertIn("#### 1.1.1 全面安全生产应急管理与风险防控实施细则\n\n安全应急正文。", merged)
            self.assertIn("#### 2.3.1 项目年度总体实施计划与阶段交付框架\n\n年度计划正文。", merged)
            self.assertIn("#### 2.3.2 暂无内容但需保留标题的章节\n", merged)
            self.assertNotIn("<!-- [MISSING]", merged)

            stdout_text = stdout_buf.getvalue()
            self.assertIn("文件名仅包含编号", stdout_text)
            self.assertIn("标题差异较大", stdout_text)
            self.assertIn("共有 1 个缺失章节（已仅保留对应大纲标题）", stdout_text)
            self.assertIn("#### 2.3.2 暂无内容但需保留标题的章节", stdout_text.split("合并完成:")[-1])

    def test_use_last_cli_repeats_and_allows_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters_dir = root / "chapters"
            dist1 = root / "dist1"
            dist2 = root / "dist2"
            chapters_dir.mkdir(parents=True)

            outline = root / "outline.md"
            outline.write_text("# 项目\n\n#### 1.1.1 第一节\n", encoding="utf-8")
            (chapters_dir / "1.1.1 第一节.md").write_text("#### 1.1.1 第一节\n\n正文内容。\n", encoding="utf-8")

            # Without prior run, --use-last returns error code 2
            stderr_buf = io.StringIO()
            with contextlib.redirect_stderr(stderr_buf):
                rc_empty = main(["--use-last"])
            self.assertEqual(rc_empty, 2)
            self.assertIn("未找到上次运行记录", stderr_buf.getvalue())

            # First run saves parameters
            rc1 = main(
                [
                    "-O",
                    str(outline),
                    "-i",
                    str(chapters_dir),
                    "-d",
                    str(dist1),
                    "--strip-duplicate-title",
                ]
            )
            self.assertEqual(rc1, 0)
            self.assertTrue((dist1 / "outline-合并版.md").is_file())

            # Repeat with --use-last and override output dir to dist2
            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                rc2 = main(["--use-last", "-d", str(dist2)])
            self.assertEqual(rc2, 0)
            self.assertIn("[已代入上次参数]", stdout_buf.getvalue())
            out2 = dist2 / "outline-合并版.md"
            self.assertTrue(out2.is_file())
            # Preserved --strip-duplicate-title from last run
            self.assertEqual(out2.read_text(encoding="utf-8").count("1.1.1 第一节"), 1)


if __name__ == "__main__":
    unittest.main()
