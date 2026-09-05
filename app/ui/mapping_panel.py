"""右栏：映射面板。

结构：顶部 [+添加自定义脱敏项] + 筛选行（文件筛选 / 仅看待确认）+ 搜索框；
下方 QTreeWidget，首个分组为"待确认"（黄色标识，采纳/忽略），其后按类别分组。
每项：原文 → 代称（×次数）+ 来源文件标注，复选框控制启停。

视图层筛选不改变映射表全局唯一性：同一原文跨文件仍共享同一代称。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLineEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.mapping.map_table import CATEGORY_LABELS, MappingItem

_PENDING_GROUP = "待确认（默认不生效）"
_CATEGORY_ORDER = ["person", "company", "org", "address", "custom",
                   "id_number", "phone", "bank_card", "passport", "permit_hk_macau",
                   "social_security", "housing_fund", "uscc", "email", "wechat",
                   "plate", "birth_date", "ethnicity", "securities_account"]
_ALL_FILES = "全部文件"


class MappingPanel(QWidget):
    enabled_changed = Signal(str, bool)      # original, enabled
    pending_resolved = Signal(str, bool)     # original, 采纳=True/忽略=False
    custom_added = Signal()
    merge_requested = Signal(str)            # original（待合并项，目标由主窗口弹窗选择）
    item_selected = Signal(str)              # original（点击定位原文）
    all_pending_ignored = Signal(list)       # [original, ...] 批量忽略当前可见待确认项

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[MappingItem] = []

        self.add_btn = QPushButton("+ 添加自定义脱敏项")
        self.add_btn.clicked.connect(lambda: self.custom_added.emit())

        # 筛选行：按文件筛选 + 仅看待确认
        self.file_filter = QComboBox()
        self.file_filter.addItem(_ALL_FILES)
        self.file_filter.currentTextChanged.connect(lambda _: self._rebuild())
        self.pending_only = QCheckBox("仅看待确认")
        self.pending_only.toggled.connect(lambda _: self._rebuild())

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索原文或代称")
        self.search_edit.textChanged.connect(lambda _: self._rebuild())

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # 选中项加深底色，清楚标识当前选中行（含窗口失焦状态）
        self.tree.setStyleSheet(
            "QTreeWidget::item:selected { background-color: #c7d9f2; color: #1a1a1a; }"
            "QTreeWidget::item:selected:!active { background-color: #dde6f2; color: #1a1a1a; }"
            "QTreeWidget::item:hover { background-color: #eef3fa; }")
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        self.accept_btn = QPushButton("采纳")
        self.accept_btn.setProperty("primary", True)
        self.ignore_btn = QPushButton("忽略")
        self.ignore_all_btn = QPushButton("全部忽略")
        self.ignore_all_btn.setToolTip("忽略当前筛选范围内全部待确认项（可先用文件筛选缩小范围）")
        self.merge_btn = QPushButton("合并到…")
        self.merge_btn.setToolTip("把选中项合并到同类别另一项的代称下（OCR 错别字分片）")
        self.accept_btn.clicked.connect(lambda: self._resolve_pending(True))
        self.ignore_btn.clicked.connect(lambda: self._resolve_pending(False))
        self.ignore_all_btn.clicked.connect(self._ignore_all_pending)
        self.merge_btn.clicked.connect(self._request_merge)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.file_filter, 1)
        filter_row.addWidget(self.pending_only)

        actions = QHBoxLayout()
        actions.addWidget(self.accept_btn)
        actions.addWidget(self.ignore_btn)
        actions.addWidget(self.ignore_all_btn)
        actions.addWidget(self.merge_btn)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.add_btn)
        layout.addLayout(filter_row)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.tree, 1)
        layout.addLayout(actions)
        self._refresh_action_buttons()

    # ---------- 数据刷新 ----------

    def set_files(self, file_names: list[str]) -> None:
        """批次队列变化时更新文件筛选下拉（保留当前选择）。"""
        current = self.file_filter.currentText()
        self.file_filter.blockSignals(True)
        self.file_filter.clear()
        self.file_filter.addItem(_ALL_FILES)
        self.file_filter.addItems(file_names)
        idx = self.file_filter.findText(current)
        self.file_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.file_filter.blockSignals(False)
        self._rebuild()

    def refresh(self, items: list[MappingItem]) -> None:
        self._items = items
        self._rebuild()

    def _visible(self, it: MappingItem) -> bool:
        """三重过滤：文件筛选 / 仅看待确认 / 关键字。"""
        file_name = self.file_filter.currentText()
        if file_name != _ALL_FILES:
            if it.files is not None and file_name not in it.files:
                return False
        if self.pending_only.isChecked() and not it.pending:
            return False
        keyword = self.search_edit.text().strip()
        if keyword and keyword not in it.original and keyword not in it.alias:
            return False
        return True

    @staticmethod
    def _source_label(it: MappingItem) -> str:
        """来源文件标注：全局项=全部文件；单文件=文件名；多文件=N个文件。"""
        if it.files is None:
            return "全部文件"
        names = sorted(it.files)
        if len(names) == 1:
            return names[0]
        return f"{len(names)}个文件"

    def _rebuild(self) -> None:
        items = [it for it in self._items if self._visible(it)]
        self.tree.blockSignals(True)
        self.tree.clear()
        pending = [it for it in items if it.pending]
        if pending:
            group = self._add_group(f"{_PENDING_GROUP} ({len(pending)})", QColor("#b8860b"))
            for it in pending:
                self._add_item(group, it, checkable=False)
        groups: dict[str, QTreeWidgetItem] = {}
        for it in items:
            if it.pending:
                continue
            label = CATEGORY_LABELS.get(it.category, it.category)
            if label not in groups:
                groups[label] = self._add_group(f"▼ {label}")
            self._add_item(groups[label], it, checkable=True)
        for label, g in groups.items():
            g.setText(0, f"▼ {label} ({g.childCount()})")
        self.tree.blockSignals(False)
        self.tree.expandAll()
        self._refresh_action_buttons()

    def _add_group(self, title: str, color: QColor | None = None) -> QTreeWidgetItem:
        group = QTreeWidgetItem([title])
        if color:
            group.setForeground(0, color)
        self.tree.addTopLevelItem(group)
        return group

    def _add_item(self, group: QTreeWidgetItem, it: MappingItem, checkable: bool) -> QTreeWidgetItem:
        src = self._source_label(it)
        child = QTreeWidgetItem([f"{it.original} → {it.alias}  (×{it.occurrences})  📄{src}"])
        child.setData(0, Qt.UserRole, it.original)
        files_text = "、".join(sorted(it.files)) if it.files else "全部文件"
        child.setToolTip(0, f"来源文件：{files_text}\n识别来源：{it.source}　置信度：{it.confidence:.2f}")
        if checkable:
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Checked if it.enabled else Qt.Unchecked)
        group.addChild(child)
        return child

    # ---------- 交互 ----------

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        original = item.data(0, Qt.UserRole)
        if original is None:
            return
        self.enabled_changed.emit(original, item.checkState(0) == Qt.Checked)

    def _on_selection_changed(self) -> None:
        self._refresh_action_buttons()
        original = self._selected_original()
        if original:
            self.item_selected.emit(original)

    def _selected_original(self) -> str | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    def _resolve_pending(self, accept: bool) -> None:
        original = self._selected_original()
        if original:
            self.pending_resolved.emit(original, accept)

    def _ignore_all_pending(self) -> None:
        """批量忽略当前筛选范围内可见的全部待确认项。"""
        originals = [it.original for it in self._items if it.pending and self._visible(it)]
        if originals:
            self.all_pending_ignored.emit(originals)

    def _request_merge(self) -> None:
        original = self._selected_original()
        if original:
            self.merge_requested.emit(original)

    def _refresh_action_buttons(self) -> None:
        original = self._selected_original()
        self.accept_btn.setEnabled(original is not None)
        self.ignore_btn.setEnabled(original is not None)
        self.merge_btn.setEnabled(original is not None)
        has_pending = any(it.pending and self._visible(it) for it in self._items)
        self.ignore_all_btn.setEnabled(has_pending)
