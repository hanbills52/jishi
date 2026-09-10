"""左栏：文件队列控件。文件名 + 状态图标，失败原因悬浮提示。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ..core.pipeline import DocItem, ST_FAILED

_STATUS_ICON = {
    "待扫描": "○", "扫描中": "…", "已扫描": "◆",
    "扫描失败": "⚠", "已脱敏": "●", "已导出": "✔",
}
# 状态配色：待扫描灰 / 扫描中蓝 / 已扫描绿 / 失败红 / 已导出深绿
_STATUS_COLOR = {
    "待扫描": "#8a93a3", "扫描中": "#2563eb", "已扫描": "#16a34a",
    "扫描失败": "#dc2626", "已脱敏": "#16a34a", "已导出": "#15803d",
}


class FileQueueWidget(QListWidget):
    file_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._docs: list[DocItem] = []
        self.currentRowChanged.connect(self._on_select)

    def refresh(self, docs: list[DocItem]) -> None:
        current_path = self._docs[self.currentRow()].path if 0 <= self.currentRow() < len(self._docs) else None
        self._docs = docs
        self.clear()
        row_to_select = -1
        for i, doc in enumerate(docs):
            icon = _STATUS_ICON.get(doc.status, "○")
            suffix = "（需重扫）" if doc.need_rescan else ""
            tag = "🖨 " if getattr(doc, "scanned", False) else ""  # 扫描件标记
            big = "⏱ " if getattr(doc, "big", False) else ""      # 超大文件标记
            item = QListWidgetItem(f"{icon} {tag}{big}{doc.name}  [{doc.status}{suffix}]")
            color = _STATUS_COLOR.get(doc.status)
            if color:
                item.setForeground(QColor(color))
            if doc.status == ST_FAILED and doc.error:
                item.setToolTip(doc.error)
            elif getattr(doc, "big", False):
                item.setToolTip(f"超大文件（{doc.pages} 页）：扫描较慢，已排到批次最后")
            elif getattr(doc, "scanned", False):
                item.setToolTip("扫描件：OCR 识别可能有误差，请人工复核待确认项")
            self.addItem(item)
            if doc.path == current_path:
                row_to_select = i
        if row_to_select >= 0:
            self.setCurrentRow(row_to_select)

    def _on_select(self, row: int) -> None:
        if 0 <= row < len(self._docs):
            self.file_selected.emit(self._docs[row].path)

    def select_path(self, path: str) -> bool:
        """选中指定路径的队列项（供映射面板点击定位时联动切换）。"""
        for i, doc in enumerate(self._docs):
            if doc.path == path:
                self.setCurrentRow(i)
                return True
        return False
