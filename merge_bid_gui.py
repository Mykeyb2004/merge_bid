#!/usr/bin/env python3
"""PySide6 desktop GUI for merge_bid.py.

Provides a modern, responsive workbench for configuring outline-driven bid
merging, loading/repeating previous run parameters in one click, inspecting
fuzzy matches and missing headings, and auditing rebased image/asset paths.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from merge_bid import (
    MergeConfig,
    MergeRunResult,
    format_cli_command,
    load_last_run_state,
    resolve_output_path,
    save_last_run_state,
    run_merge_pipeline,
)

APP_STYLESHEET = """
QMainWindow, QWidget#RootCanvas {
    background-color: #F4F7FB;
    color: #0F172A;
    font-family: -apple-system, "PingFang SC", "SF Pro Text", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}

QFrame#TopHeader {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E2E8F0;
}

QLabel#AppTitle {
    font-size: 18px;
    font-weight: 700;
    color: #0F172A;
}

QLabel#AppSubtitle {
    font-size: 12px;
    color: #64748B;
}

QFrame#Card, QFrame#KpiCard {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}

QLabel#CardTitle {
    font-size: 14px;
    font-weight: 700;
    color: #1E293B;
}

QLabel#FieldLabel {
    font-size: 12px;
    font-weight: 600;
    color: #334155;
}

QLabel#HintText {
    font-size: 11.5px;
    color: #64748B;
}

QLabel#PreviewPathLabel {
    font-size: 11.5px;
    color: #1D4ED8;
    background-color: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    padding: 6px 10px;
}

QLabel#StatusPill {
    font-size: 11.5px;
    font-weight: 600;
    color: #0F766E;
    background-color: #CCFBF1;
    border-radius: 10px;
    padding: 3px 9px;
}

QLabel#KpiTitle {
    font-size: 11.5px;
    font-weight: 600;
    color: #64748B;
}

QLabel#KpiValue {
    font-size: 22px;
    font-weight: 700;
    color: #0F172A;
}

QLabel#KpiSub {
    font-size: 11.5px;
    color: #64748B;
}

QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 6px 10px;
    color: #0F172A;
    selection-background-color: #DBEAFE;
    selection-color: #1E3A8A;
}

QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {
    border: 1.5px solid #2563EB;
}

QLineEdit:read-only {
    background-color: #F8FAFC;
}

QPushButton {
    background-color: #FFFFFF;
    color: #1E293B;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 7px 13px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #F8FAFC;
    border-color: #94A3B8;
}

QPushButton:pressed {
    background-color: #F1F5F9;
}

QPushButton:disabled {
    color: #94A3B8;
    background-color: #F8FAFC;
    border-color: #E2E8F0;
}

QPushButton#PrimaryButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #1D4ED8;
    padding: 9px 18px;
    font-size: 13.5px;
}

QPushButton#PrimaryButton:hover {
    background-color: #1D4ED8;
}

QPushButton#PrimaryButton:pressed {
    background-color: #1E40AF;
}

QPushButton#PrimaryButton:disabled {
    background-color: #93C5FD;
    border-color: #93C5FD;
    color: #FFFFFF;
}

QPushButton#AccentSoftButton {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
}

QPushButton#AccentSoftButton:hover {
    background-color: #DBEAFE;
    border-color: #93C5FD;
}

QPushButton#AccentSoftButton:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
    border-color: #E2E8F0;
}

QPushButton#FilterPill {
    background-color: #F1F5F9;
    color: #475569;
    border: 1px solid transparent;
    border-radius: 14px;
    padding: 4px 12px;
    font-size: 12px;
}

QPushButton#FilterPill:checked {
    background-color: #2563EB;
    color: #FFFFFF;
}

QCheckBox {
    spacing: 8px;
    color: #1E293B;
    font-weight: 500;
}

QTabWidget::pane {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    top: -1px;
}

QTabBar::tab {
    background-color: #E2E8F0;
    color: #475569;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1D4ED8;
    border: 1px solid #E2E8F0;
    border-bottom-color: #FFFFFF;
}

QTableWidget {
    background-color: #FFFFFF;
    border: none;
    gridline-color: #F1F5F9;
    alternate-background-color: #F8FAFC;
}

QHeaderView::section {
    background-color: #F8FAFC;
    color: #475569;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #E2E8F0;
}

QProgressBar {
    background-color: #E2E8F0;
    border: none;
    border-radius: 3px;
    height: 5px;
}

QProgressBar::chunk {
    background-color: #2563EB;
    border-radius: 3px;
}

QFrame#StatusBanner {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}
"""


class DropLineEdit(QLineEdit):
    """Line edit supporting drag-and-drop for files or directories."""

    def __init__(self, mode: str, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = mode  # "file" or "dir"
        self.setAcceptDrops(True)
        if placeholder:
            self.setPlaceholderText(placeholder)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            super().dropEvent(event)
            return
        local_path = Path(urls[0].toLocalFile())
        if self.mode == "dir" and local_path.is_file():
            local_path = local_path.parent
        self.setText(str(local_path))
        event.acceptProposedAction()


class MergeWorker(QThread):
    """Background worker executing run_merge_pipeline without freezing the Qt UI."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, config: MergeConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config

    def run(self) -> None:
        try:
            result = run_merge_pipeline(self.config)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class KpiCard(QFrame):
    """Compact metric card displayed above the inspection tabs."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("KpiTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("KpiValue")
        self.sub_label = QLabel("等待运行")
        self.sub_label.setObjectName("KpiSub")
        self.sub_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.sub_label)

    def set_metric(self, value: str, subtitle: str, color: str = "#0F172A") -> None:
        self.value_label.setText(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 700;")
        self.sub_label.setText(subtitle)


class MergeBidMainWindow(QMainWindow):
    """Main desktop window for bid outline merging and asset path verification."""

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self.config_path = config_path
        self.worker: MergeWorker | None = None
        self.last_result: MergeRunResult | None = None
        self.last_config: MergeConfig | None = None
        self._match_rows_cache: list[tuple[str, str, str, str, str, str]] = []
        self._active_filter = "all"

        self.setWindowTitle("标书智能合并工作台 — MergeBid")
        self.resize(1240, 820)
        self.setMinimumSize(980, 660)

        self._build_ui()
        self._bind_shortcuts()
        self._refresh_preset_controls()
        self._update_output_preview()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("RootCanvas")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())

        body_container = QWidget()
        body_layout = QVBoxLayout(body_container)
        body_layout.setContentsMargins(16, 14, 16, 14)
        body_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([440, 760])

        body_layout.addWidget(splitter, 1)
        root_layout.addWidget(body_container, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("TopHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("标书智能合并工作台")
        title.setObjectName("AppTitle")
        subtitle = QLabel("大纲驱动章节合并 · 多级序号容错匹配 · 相对图片路径自动重算")
        subtitle.setObjectName("AppSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, 1)

        self.preset_hint_label = QLabel("")
        self.preset_hint_label.setObjectName("StatusPill")
        self.preset_hint_label.setVisible(False)
        layout.addWidget(self.preset_hint_label)

        self.load_last_btn = QPushButton("代入上次参数")
        self.load_last_btn.setObjectName("AccentSoftButton")
        self.load_last_btn.clicked.connect(self.load_last_preset)
        layout.addWidget(self.load_last_btn)

        self.history_btn = QPushButton("最近记录")
        self.history_menu = QMenu(self)
        self.history_btn.setMenu(self.history_menu)
        layout.addWidget(self.history_btn)

        self.copy_cli_btn = QPushButton("复制 CLI 命令")
        self.copy_cli_btn.clicked.connect(self._copy_cli_command)
        layout.addWidget(self.copy_cli_btn)

        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 8, 0)
        panel_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form_col = QVBoxLayout(scroll_content)
        form_col.setContentsMargins(0, 0, 4, 0)
        form_col.setSpacing(12)

        # Card 1: Paths
        path_card = QFrame()
        path_card.setObjectName("Card")
        path_layout = QVBoxLayout(path_card)
        path_layout.setContentsMargins(16, 14, 16, 14)
        path_layout.setSpacing(10)

        card1_title = QLabel("1. 文件与目录配置（支持拖拽）")
        card1_title.setObjectName("CardTitle")
        path_layout.addWidget(card1_title)

        # Outline
        path_layout.addWidget(self._make_field_label("大纲文件 (-O / --outline)"))
        outline_row = QHBoxLayout()
        outline_row.setSpacing(8)
        self.outline_edit = DropLineEdit("file", "选择或拖入投标大纲 Markdown 文件 (.md)")
        self.outline_edit.textChanged.connect(self._update_output_preview)
        outline_btn = QPushButton("浏览文件")
        outline_btn.clicked.connect(self._browse_outline)
        outline_row.addWidget(self.outline_edit, 1)
        outline_row.addWidget(outline_btn)
        path_layout.addLayout(outline_row)

        # Input Dir
        input_hdr = QHBoxLayout()
        input_hdr.addWidget(self._make_field_label("待合并文件夹 (-i / --input-dir)"))
        self.md_count_label = QLabel("")
        self.md_count_label.setObjectName("HintText")
        input_hdr.addStretch(1)
        input_hdr.addWidget(self.md_count_label)
        path_layout.addLayout(input_hdr)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input_dir_edit = DropLineEdit("dir", "选择或拖入章节所在目录（递归扫描 .md）")
        self.input_dir_edit.textChanged.connect(self._on_input_dir_changed)
        input_btn = QPushButton("浏览目录")
        input_btn.clicked.connect(self._browse_input_dir)
        input_row.addWidget(self.input_dir_edit, 1)
        input_row.addWidget(input_btn)
        path_layout.addLayout(input_row)

        # Output Dir
        out_hdr = QHBoxLayout()
        out_hdr.addWidget(self._make_field_label("输出文件夹 (-d / --output-dir)"))
        self.reset_out_dir_btn = QPushButton("恢复同级默认")
        self.reset_out_dir_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.reset_out_dir_btn.clicked.connect(lambda: self.output_dir_edit.clear())
        out_hdr.addStretch(1)
        out_hdr.addWidget(self.reset_out_dir_btn)
        path_layout.addLayout(out_hdr)

        out_dir_row = QHBoxLayout()
        out_dir_row.setSpacing(8)
        self.output_dir_edit = DropLineEdit("dir", "留空默认：待合并文件夹的同级目录")
        self.output_dir_edit.textChanged.connect(self._update_output_preview)
        out_dir_btn = QPushButton("浏览目录")
        out_dir_btn.clicked.connect(self._browse_output_dir)
        out_dir_row.addWidget(self.output_dir_edit, 1)
        out_dir_row.addWidget(out_dir_btn)
        path_layout.addLayout(out_dir_row)

        # Optional custom output filename
        path_layout.addWidget(self._make_field_label("自定义输出文件名/路径 (-o，可选)"))
        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("留空默认：<大纲文件名>-合并版.md")
        self.output_name_edit.textChanged.connect(self._update_output_preview)
        path_layout.addWidget(self.output_name_edit)

        self.output_preview_label = QLabel("预计输出路径: 待选择大纲文件与待合并文件夹")
        self.output_preview_label.setObjectName("PreviewPathLabel")
        self.output_preview_label.setWordWrap(True)
        path_layout.addWidget(self.output_preview_label)

        form_col.addWidget(path_card)

        # Card 2: Rules
        rule_card = QFrame()
        rule_card.setObjectName("Card")
        rule_layout = QVBoxLayout(rule_card)
        rule_layout.setContentsMargins(16, 14, 16, 14)
        rule_layout.setSpacing(10)

        card2_title = QLabel("2. 合并规则与容错设置")
        card2_title.setObjectName("CardTitle")
        rule_layout.addWidget(card2_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(self._make_field_label("大纲填充层级"), 0, 0)
        self.level_combo = QComboBox()
        for val, text in [
            ("4", "4 级标题 (#### 默认)"),
            ("leaf", "leaf (自动识别末级标题)"),
            ("1", "1 级标题 (#)"),
            ("2", "2 级标题 (##)"),
            ("3", "3 级标题 (###)"),
            ("5", "5 级标题 (#####)"),
            ("6", "6 级标题 (######)"),
        ]:
            self.level_combo.addItem(text, val)
        grid.addWidget(self.level_combo, 1, 0)

        grid.addWidget(self._make_field_label("缺失章节处理"), 0, 1)
        self.missing_policy_combo = QComboBox()
        for val, text in [
            ("placeholder", "保留标题 + 占位注释 (默认)"),
            ("empty", "仅保留空缺标题"),
            ("error", "存在缺失即报错终止"),
        ]:
            self.missing_policy_combo.addItem(text, val)
        grid.addWidget(self.missing_policy_combo, 1, 1)

        grid.addWidget(self._make_field_label("跨编号模糊阈值"), 2, 0)
        self.min_sim_spin = QDoubleSpinBox()
        self.min_sim_spin.setRange(0.0, 1.0)
        self.min_sim_spin.setSingleStep(0.05)
        self.min_sim_spin.setDecimals(2)
        self.min_sim_spin.setValue(0.72)
        grid.addWidget(self.min_sim_spin, 3, 0)

        grid.addWidget(self._make_field_label("同编号兜底阈值"), 2, 1)
        self.min_code_sim_spin = QDoubleSpinBox()
        self.min_code_sim_spin.setRange(0.0, 1.0)
        self.min_code_sim_spin.setSingleStep(0.05)
        self.min_code_sim_spin.setDecimals(2)
        self.min_code_sim_spin.setValue(0.00)
        self.min_code_sim_spin.setToolTip("0.00 表示只要多级序号一致（含纯编号文件名如 2.3.1.md）即可兜底匹配")
        grid.addWidget(self.min_code_sim_spin, 3, 1)

        rule_layout.addLayout(grid)

        self.strip_title_check = QCheckBox("自动剔除章节首行重复的大纲标题 (--strip-duplicate-title)")
        rule_layout.addWidget(self.strip_title_check)

        rule_layout.addWidget(self._make_field_label("审计报告 JSON 路径 (--report，可选)"))
        report_row = QHBoxLayout()
        report_row.setSpacing(8)
        self.report_edit = QLineEdit()
        self.report_edit.setPlaceholderText("留空不生成；填写则导出匹配与图片路径审计 JSON")
        report_btn = QPushButton("选择路径")
        report_btn.clicked.connect(self._browse_report)
        report_row.addWidget(self.report_edit, 1)
        report_row.addWidget(report_btn)
        rule_layout.addLayout(report_row)

        form_col.addWidget(rule_card)
        form_col.addStretch(1)
        scroll.setWidget(scroll_content)
        panel_layout.addWidget(scroll, 1)

        # Sticky Action Bar
        action_card = QFrame()
        action_card.setObjectName("Card")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_layout.setSpacing(10)

        self.dry_run_btn = QPushButton("预检 (Dry Run)")
        self.dry_run_btn.setToolTip("仅执行匹配与图片路径重算检查，不写入合并文件")
        self.dry_run_btn.clicked.connect(lambda: self._start_run(dry_run=True))

        self.merge_btn = QPushButton("开始合并")
        self.merge_btn.setObjectName("PrimaryButton")
        self.merge_btn.clicked.connect(lambda: self._start_run(dry_run=False))

        action_layout.addWidget(self.dry_run_btn, 1)
        action_layout.addWidget(self.merge_btn, 2)
        panel_layout.addWidget(action_card)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(12)

        # KPI Cards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.kpi_matched = KpiCard("匹配章节")
        self.kpi_fuzzy = KpiCard("容错匹配")
        self.kpi_missing = KpiCard("空缺保留标题")
        self.kpi_assets = KpiCard("图片路径重算 / 告警")
        for card in (self.kpi_matched, self.kpi_fuzzy, self.kpi_missing, self.kpi_assets):
            kpi_row.addWidget(card, 1)
        layout.addLayout(kpi_row)

        # Status Banner + Open Output Actions
        banner = QFrame()
        banner.setObjectName("StatusBanner")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(6)

        top_line = QHBoxLayout()
        self.status_label = QLabel("就绪：请配置大纲文件与待合并文件夹，或点击右上角「代入上次参数」。")
        self.status_label.setWordWrap(True)
        top_line.addWidget(self.status_label, 1)

        self.open_file_btn = QPushButton("打开合并文件")
        self.open_file_btn.setVisible(False)
        self.open_file_btn.clicked.connect(self._open_output_file)
        self.open_dir_btn = QPushButton("打开输出目录")
        self.open_dir_btn.setVisible(False)
        self.open_dir_btn.clicked.connect(self._open_output_dir)
        top_line.addWidget(self.open_file_btn)
        top_line.addWidget(self.open_dir_btn)
        banner_layout.addLayout(top_line)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        banner_layout.addWidget(self.progress_bar)

        layout.addWidget(banner)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_matches_tab(), "章节匹配明细")
        self.tabs.addTab(self._build_assets_tab(), "图片/资源路径检查")
        self.tabs.addTab(self._build_missing_orphan_tab(), "缺失标题与未使用文件")
        self.tabs.addTab(self._build_preview_tab(), "合并预览与日志")
        layout.addWidget(self.tabs, 1)

        return panel

    def _build_matches_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in [
            ("all", "全部"),
            ("exact", "精确匹配"),
            ("fuzzy", "容错匹配"),
            ("missing", "缺失标题"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("FilterPill")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda _checked=False, k=key: self._set_match_filter(k))
            self.filter_buttons[key] = btn
            filter_bar.addWidget(btn)

        filter_bar.addStretch(1)
        self.match_search_edit = QLineEdit()
        self.match_search_edit.setPlaceholderText("搜索大纲标题或文件名...")
        self.match_search_edit.setMaximumWidth(240)
        self.match_search_edit.textChanged.connect(self._refresh_match_table)
        filter_bar.addWidget(self.match_search_edit)
        layout.addLayout(filter_bar)

        self.match_table = QTableWidget(0, 5)
        self.match_table.setHorizontalHeaderLabels(["大纲标题", "状态", "匹配文件", "相似度", "提示说明"])
        self.match_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.match_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.match_table.setAlternatingRowColors(True)
        self.match_table.verticalHeader().setVisible(False)
        hdr = self.match_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.match_table.setColumnWidth(0, 240)
        self.match_table.setColumnWidth(2, 220)
        layout.addWidget(self.match_table, 1)
        return tab

    def _build_assets_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.asset_summary_label = QLabel("尚未运行检查。合并时会自动重算相对图片路径，并标记断链与预写路径。")
        self.asset_summary_label.setObjectName("HintText")
        self.asset_summary_label.setWordWrap(True)
        layout.addWidget(self.asset_summary_label)

        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setHorizontalHeaderLabels(["告警类型", "章节文件", "原资源路径", "说明"])
        self.asset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.asset_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.asset_table.setAlternatingRowColors(True)
        self.asset_table.verticalHeader().setVisible(False)
        hdr = self.asset_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.asset_table.setColumnWidth(1, 220)
        self.asset_table.setColumnWidth(2, 220)
        layout.addWidget(self.asset_table, 1)
        return tab

    def _build_missing_orphan_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.addWidget(self._make_field_label("空缺实际内容的保留标题（需补充正文）"))
        self.missing_list = QListWidget()
        left_col.addWidget(self.missing_list, 1)

        right_col = QVBoxLayout()
        right_col.addWidget(self._make_field_label("待合并目录中未被大纲引用的文件"))
        self.orphan_list = QListWidget()
        right_col.addWidget(self.orphan_list, 1)

        layout.addLayout(left_col, 1)
        layout.addLayout(right_col, 1)
        return tab

    def _build_preview_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(self._make_field_label("运行总结与合并结果预览"))
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setStyleSheet(
            'font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 12px;'
        )
        layout.addWidget(self.preview_edit, 1)
        return tab

    @staticmethod
    def _make_field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.load_last_preset)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self._start_run(dry_run=False))

    def _browse_outline(self) -> None:
        start_dir = str(Path(self.outline_edit.text().strip()).parent) if self.outline_edit.text().strip() else str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择投标大纲 Markdown 文件",
            start_dir,
            "Markdown 文件 (*.md *.markdown);;所有文件 (*)",
        )
        if path:
            self.outline_edit.setText(path)

    def _browse_input_dir(self) -> None:
        start_dir = self.input_dir_edit.text().strip() or str(Path.cwd())
        path = QFileDialog.getExistingDirectory(self, "选择待合并章节文件夹", start_dir)
        if path:
            self.input_dir_edit.setText(path)

    def _browse_output_dir(self) -> None:
        start_dir = (
            self.output_dir_edit.text().strip()
            or self.input_dir_edit.text().strip()
            or str(Path.cwd())
        )
        path = QFileDialog.getExistingDirectory(self, "选择合并文件输出文件夹", start_dir)
        if path:
            self.output_dir_edit.setText(path)

    def _browse_report(self) -> None:
        start_dir = self.output_dir_edit.text().strip() or str(Path.cwd())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择审计报告保存路径",
            str(Path(start_dir) / "merge_report.json"),
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if path:
            self.report_edit.setText(path)

    def _on_input_dir_changed(self) -> None:
        raw = self.input_dir_edit.text().strip()
        if not raw:
            self.md_count_label.setText("")
        else:
            p = Path(raw)
            if p.is_dir():
                count = sum(1 for item in p.rglob("*.md") if item.is_file() and not any(part.startswith(".") for part in item.relative_to(p).parts))
                self.md_count_label.setText(f"检测到 {count} 个 .md 文件")
            else:
                self.md_count_label.setText("目录不存在")
        self._update_output_preview()

    def _update_output_preview(self) -> None:
        outline_raw = self.outline_edit.text().strip()
        input_raw = self.input_dir_edit.text().strip()
        if not outline_raw or not input_raw:
            self.output_preview_label.setText("预计输出路径: 待选择大纲文件与待合并文件夹")
            return
        out_dir_raw = self.output_dir_edit.text().strip()
        out_name_raw = self.output_name_edit.text().strip()
        try:
            resolved = resolve_output_path(
                outline_path=Path(outline_raw),
                input_dir=Path(input_raw),
                output_dir_arg=Path(out_dir_raw) if out_dir_raw else None,
                output_arg=Path(out_name_raw) if out_name_raw else None,
            )
            self.output_preview_label.setText(f"预计输出路径: {resolved}")
        except ValueError as exc:
            self.output_preview_label.setText(f"输出路径提示: {exc}")

    def _refresh_preset_controls(self) -> None:
        last_preset, history = load_last_run_state(self.config_path)
        self.history_menu.clear()

        if last_preset is None:
            self.load_last_btn.setEnabled(False)
            self.load_last_btn.setToolTip("暂无历史运行记录，成功或预检运行一次后即可一键代入")
            self.history_btn.setEnabled(False)
            self.preset_hint_label.setVisible(False)
            return

        self.load_last_btn.setEnabled(True)
        outline_name = Path(str(last_preset.get("outline", ""))).name
        input_name = Path(str(last_preset.get("input_dir", ""))).name
        saved_at = str(last_preset.get("saved_at", ""))
        self.load_last_btn.setToolTip(
            f"大纲: {last_preset.get('outline')}\n"
            f"目录: {last_preset.get('input_dir')}\n"
            f"输出目录: {last_preset.get('output_dir') or '待合并文件夹同级'}\n"
            f"保存时间: {saved_at}"
        )
        self.preset_hint_label.setText(f"上次记录: {outline_name} · {input_name}")
        self.preset_hint_label.setVisible(True)

        self.history_btn.setEnabled(bool(history))
        for item in history:
            o_name = Path(str(item.get("outline", ""))).name
            i_name = Path(str(item.get("input_dir", ""))).name
            ts = str(item.get("saved_at", ""))
            action = QAction(f"{o_name}  |  {i_name}  ({ts})", self)
            action.triggered.connect(lambda _checked=False, p=item: self.apply_preset(p))
            self.history_menu.addAction(action)

    def apply_preset(self, preset: dict[str, object]) -> None:
        """Populate all form controls from a saved preset dictionary."""
        cfg = MergeConfig.from_preset_dict(preset)
        self.outline_edit.setText(str(cfg.outline))
        self.input_dir_edit.setText(str(cfg.input_dir))
        self.output_dir_edit.setText(str(cfg.output_dir) if cfg.output_dir is not None else "")
        self.output_name_edit.setText(str(cfg.output) if cfg.output is not None else "")

        lvl_idx = self.level_combo.findData(cfg.level)
        if lvl_idx >= 0:
            self.level_combo.setCurrentIndex(lvl_idx)
        pol_idx = self.missing_policy_combo.findData(cfg.missing_policy)
        if pol_idx >= 0:
            self.missing_policy_combo.setCurrentIndex(pol_idx)

        self.min_sim_spin.setValue(cfg.min_similarity)
        self.min_code_sim_spin.setValue(cfg.min_code_only_similarity)
        self.strip_title_check.setChecked(cfg.strip_duplicate_title)
        self.report_edit.setText(str(cfg.report) if cfg.report is not None else "")

        saved_at = preset.get("saved_at", "")
        self.status_label.setText(f"已快速代入运行参数（记录时间: {saved_at or '未知'}），可直接点击「预检」或「开始合并」。")

    def load_last_preset(self) -> bool:
        """Load the most recent saved run parameters into the GUI form."""
        last_preset, _ = load_last_run_state(self.config_path)
        if last_preset is None:
            QMessageBox.information(self, "暂无记录", "尚未检测到历史运行参数，请先执行一次预检或合并。")
            return False
        self.apply_preset(last_preset)
        return True

    def build_config_from_ui(self, dry_run: bool = False) -> MergeConfig:
        """Validate UI inputs and build a MergeConfig."""
        outline_raw = self.outline_edit.text().strip()
        input_raw = self.input_dir_edit.text().strip()
        if not outline_raw:
            raise ValueError("请先选择或拖入投标大纲 Markdown 文件。")
        if not input_raw:
            raise ValueError("请先选择或拖入待合并文件夹。")

        out_dir_raw = self.output_dir_edit.text().strip()
        out_name_raw = self.output_name_edit.text().strip()
        report_raw = self.report_edit.text().strip()

        return MergeConfig(
            outline=Path(outline_raw),
            input_dir=Path(input_raw),
            output_dir=Path(out_dir_raw) if out_dir_raw else None,
            output=Path(out_name_raw) if out_name_raw else None,
            level=str(self.level_combo.currentData()),
            min_similarity=float(self.min_sim_spin.value()),
            min_code_only_similarity=float(self.min_code_sim_spin.value()),
            missing_policy=str(self.missing_policy_combo.currentData()),
            strip_duplicate_title=self.strip_title_check.isChecked(),
            report=Path(report_raw) if report_raw else None,
            dry_run=dry_run,
        )

    def _copy_cli_command(self) -> None:
        try:
            config = self.build_config_from_ui(dry_run=False)
        except ValueError as exc:
            QMessageBox.warning(self, "参数不完整", str(exc))
            return
        cmd = format_cli_command(config)
        QApplication.clipboard().setText(cmd)
        self.status_label.setText(f"已复制等效 CLI 命令到剪贴板: {cmd}")

    def _set_running_state(self, running: bool, message: str) -> None:
        self.dry_run_btn.setEnabled(not running)
        self.merge_btn.setEnabled(not running)
        self.load_last_btn.setEnabled((not running) and load_last_run_state(self.config_path)[0] is not None)
        self.progress_bar.setVisible(running)
        self.status_label.setText(message)

    def _start_run(self, dry_run: bool) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            config = self.build_config_from_ui(dry_run=dry_run)
        except ValueError as exc:
            QMessageBox.warning(self, "请检查配置", str(exc))
            return

        self.last_config = config
        self.open_file_btn.setVisible(False)
        self.open_dir_btn.setVisible(False)
        mode_text = "正在执行预检与图片路径校验..." if dry_run else "正在合并章节并重算图片路径..."
        self._set_running_state(True, mode_text)

        self.worker = MergeWorker(config, self)
        self.worker.succeeded.connect(self._on_run_succeeded)
        self.worker.failed.connect(self._on_run_failed)
        self.worker.start()

    def _on_run_failed(self, error_text: str) -> None:
        self._set_running_state(False, f"执行失败: {error_text}")
        QMessageBox.critical(self, "合并失败", error_text)

    def _on_run_succeeded(self, result: MergeRunResult) -> None:
        self.last_result = result
        assert self.last_config is not None
        save_last_run_state(self.last_config.to_preset_dict(), config_path=self.config_path)
        self._refresh_preset_controls()

        exact_count = sum(1 for m in result.matches.values() if m.match_type == "exact")
        fuzzy_count = len(result.matches) - exact_count
        missing_count = len(result.missing_nodes)
        pre_rebased_count = sum(1 for w in result.asset_warnings if w.kind == "pre_rebased_for_output")
        broken_count = sum(1 for w in result.asset_warnings if w.kind == "missing_asset")

        self.kpi_matched.set_metric(
            f"{len(result.matches)} / {len(result.target_nodes)}",
            f"精确 {exact_count} · 容错 {fuzzy_count} · 扫描 {len(result.files)} 文件",
            "#059669" if missing_count == 0 else "#2563EB",
        )
        self.kpi_fuzzy.set_metric(
            str(fuzzy_count),
            "建议复核编号/标题差异章节" if fuzzy_count > 0 else "全部为精确文件名匹配",
            "#D97706" if fuzzy_count > 0 else "#0F172A",
        )
        self.kpi_missing.set_metric(
            str(missing_count),
            "已保留空缺标题并汇总提示" if missing_count > 0 else "无缺失章节",
            "#DC2626" if missing_count > 0 else "#059669",
        )
        self.kpi_assets.set_metric(
            f"{result.rebased_count} / {len(result.asset_warnings)}",
            f"重算 {result.rebased_count} 处 · 预写提示 {pre_rebased_count} · 断链 {broken_count}",
            "#DC2626" if broken_count > 0 else ("#D97706" if pre_rebased_count > 0 else "#059669"),
        )

        self._populate_match_cache(result)
        self._refresh_match_table()
        self._populate_asset_table(result)
        self._populate_missing_orphan_lists(result)
        self._populate_preview(result, self.last_config)

        if result.exit_code != 0:
            self._set_running_state(False, f"终止: {result.error_message}")
            QMessageBox.warning(self, "存在缺失章节", result.error_message or "合并已终止")
            return

        if result.written_output:
            msg = f"合并完成: {result.output_path}"
            if missing_count > 0:
                msg += f"（其中 {missing_count} 个空缺章节已保留标题，请查看「缺失标题与未使用文件」标签页）"
            self._set_running_state(False, msg)
            self.open_file_btn.setVisible(True)
            self.open_dir_btn.setVisible(True)
        else:
            self._set_running_state(
                False,
                f"预检完成（未写入文件）。预计输出: {result.output_path}",
            )

    def _populate_match_cache(self, result: MergeRunResult) -> None:
        rows: list[tuple[str, str, str, str, str, str]] = []
        for node in result.target_nodes:
            m = result.matches.get(node.index)
            if m is None:
                rows.append(("missing", node.title, "缺失（已保留标题）", "—", "—", "未找到对应章节文件"))
            elif m.match_type == "exact":
                rows.append(("exact", node.title, "精确匹配", m.file_path, f"{m.score:.2f}", ""))
            else:
                rows.append(
                    ("fuzzy", node.title, f"容错 ({m.match_type})", m.file_path, f"{m.score:.2f}", m.warning or "")
                )
        self._match_rows_cache = rows

    def _set_match_filter(self, key: str) -> None:
        self._active_filter = key
        for k, btn in self.filter_buttons.items():
            btn.setChecked(k == key)
        self._refresh_match_table()

    def _refresh_match_table(self) -> None:
        query = self.match_search_edit.text().strip().lower()
        filtered = [
            row
            for row in self._match_rows_cache
            if (self._active_filter == "all" or row[0] == self._active_filter)
            and (not query or query in row[1].lower() or query in row[3].lower() or query in row[5].lower())
        ]
        self.match_table.setRowCount(len(filtered))
        for r_idx, (kind, title, status_text, file_path, score_text, note) in enumerate(filtered):
            items = [
                QTableWidgetItem(title),
                QTableWidgetItem(status_text),
                QTableWidgetItem(file_path),
                QTableWidgetItem(score_text),
                QTableWidgetItem(note),
            ]
            items[3].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if kind == "exact":
                items[1].setForeground(QColor("#059669"))
            elif kind == "fuzzy":
                items[1].setForeground(QColor("#D97706"))
            else:
                items[1].setForeground(QColor("#DC2626"))
            for c_idx, item in enumerate(items):
                item.setToolTip(item.text())
                self.match_table.setItem(r_idx, c_idx, item)

    def _populate_asset_table(self, result: MergeRunResult) -> None:
        warnings = result.asset_warnings
        self.asset_summary_label.setText(
            f"本次共重算 {result.rebased_count} 处相对图片/资源路径；发现 {len(warnings)} 条路径提醒/断链告警。"
        )
        self.asset_table.setRowCount(len(warnings))
        for r_idx, w in enumerate(warnings):
            type_label = "预写根目录路径" if w.kind == "pre_rebased_for_output" else "断链告警"
            items = [
                QTableWidgetItem(type_label),
                QTableWidgetItem(w.chapter_path),
                QTableWidgetItem(w.asset_url),
                QTableWidgetItem(w.message),
            ]
            items[0].setForeground(QColor("#D97706" if w.kind == "pre_rebased_for_output" else "#DC2626"))
            for c_idx, item in enumerate(items):
                item.setToolTip(item.text())
                self.asset_table.setItem(r_idx, c_idx, item)

    def _populate_missing_orphan_lists(self, result: MergeRunResult) -> None:
        self.missing_list.clear()
        if not result.missing_nodes:
            item = QListWidgetItem("无缺失章节，所有目标标题均已匹配到内容。")
            item.setForeground(QColor("#059669"))
            self.missing_list.addItem(item)
        else:
            for node in result.missing_nodes:
                item = QListWidgetItem(node.raw_line)
                item.setForeground(QColor("#DC2626"))
                self.missing_list.addItem(item)

        self.orphan_list.clear()
        if not result.orphan_files:
            item = QListWidgetItem("输入目录中所有 .md 文件均已被大纲引用。")
            item.setForeground(QColor("#059669"))
            self.orphan_list.addItem(item)
        else:
            for chap in result.orphan_files:
                self.orphan_list.addItem(QListWidgetItem(chap.rel_path))

    def _populate_preview(self, result: MergeRunResult, config: MergeConfig) -> None:
        max_chars = 40000
        body_preview = result.merged_text[:max_chars]
        if len(result.merged_text) > max_chars:
            body_preview += f"\n\n... [预览已截断，完整文档共 {len(result.merged_text)} 字符] ..."

        summary_lines = [
            f"等效 CLI 命令: {format_cli_command(config)}",
            f"目标输出文件: {result.output_path}",
            f"匹配统计: {len(result.matches)}/{len(result.target_nodes)} | 缺失: {len(result.missing_nodes)} | 未使用文件: {len(result.orphan_files)}",
            f"图片/资源路径重算: {result.rebased_count} 处 | 资源告警: {len(result.asset_warnings)} 条",
            "-" * 72,
            body_preview,
        ]
        self.preview_edit.setPlainText("\n".join(summary_lines))

    def _open_output_file(self) -> None:
        if self.last_result and self.last_result.output_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result.output_path.resolve())))

    def _open_output_dir(self) -> None:
        if self.last_result and self.last_result.output_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result.output_dir.resolve())))


def launch_gui(config_path: Path | None = None) -> int:
    """Create and run the PySide6 desktop application."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    window = MergeBidMainWindow(config_path=config_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch_gui())
