"""Unit tests for code/merge_bid.py."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from merge_bid import main


class MergeBidTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
