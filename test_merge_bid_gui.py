"""Headless unit tests for the PySide6 GUI in merge_bid_gui.py."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from merge_bid import MergeConfig, save_last_run_state
from merge_bid_gui import MergeBidMainWindow


class MergeBidGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_load_last_preset_and_run_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "last_run.json"
            chapters_dir = root / "chapters"
            pics_dir = root / "pics"
            dist_dir = root / "dist"
            chapters_dir.mkdir(parents=True)
            pics_dir.mkdir(parents=True)
            (pics_dir / "diagram.png").write_bytes(b"PNG")

            outline = root / "outline.md"
            outline.write_text(
                "# 项目\n#### 1.1.1 实施计划\n#### 1.1.2 缺失章节\n",
                encoding="utf-8",
            )
            (chapters_dir / "1.1.1.md").write_text(
                "#### 1.1.1 实施计划\n\n![图](../pics/diagram.png)\n",
                encoding="utf-8",
            )

            # 1) Empty history initially disables "代入上次参数"
            win_empty = MergeBidMainWindow(config_path=cfg_path)
            self.assertFalse(win_empty.load_last_btn.isEnabled())
            win_empty.close()

            # 2) Seed saved preset and test 1-click substitution
            preset = MergeConfig(
                outline=outline,
                input_dir=chapters_dir,
                output_dir=dist_dir,
                level="4",
                missing_policy="placeholder",
                strip_duplicate_title=True,
                min_similarity=0.75,
                min_code_only_similarity=0.0,
            ).to_preset_dict()
            save_last_run_state(preset, config_path=cfg_path)

            win = MergeBidMainWindow(config_path=cfg_path)
            self.assertTrue(win.load_last_btn.isEnabled())
            self.assertTrue(win.load_last_preset())

            self.assertEqual(Path(win.outline_edit.text()), outline.resolve())
            self.assertEqual(Path(win.input_dir_edit.text()), chapters_dir.resolve())
            self.assertEqual(Path(win.output_dir_edit.text()), dist_dir.resolve())
            self.assertTrue(win.strip_title_check.isChecked())
            self.assertAlmostEqual(win.min_sim_spin.value(), 0.75, places=2)

            # 3) Run merge via GUI worker and wait for completion
            win._start_run(dry_run=False)
            assert win.worker is not None
            win.worker.wait(5000)
            self.app.processEvents()

            out_file = dist_dir / "outline-合并版.md"
            self.assertTrue(out_file.is_file())
            merged = out_file.read_text(encoding="utf-8")
            self.assertIn("![图](../pics/diagram.png)", merged)
            self.assertIn("#### 1.1.2 缺失章节", merged)
            self.assertEqual(win.kpi_matched.value_label.text(), "1 / 2")
            self.assertEqual(win.kpi_missing.value_label.text(), "1")
            self.assertEqual(win.match_table.rowCount(), 2)
            self.assertFalse(win.open_file_btn.isHidden())
            self.assertFalse(win.open_dir_btn.isHidden())
            win.close()


if __name__ == "__main__":
    unittest.main()
