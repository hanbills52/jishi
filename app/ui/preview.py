"""中栏：预览控件。M1 为文本级渲染，脱敏处高亮，支持 原文/脱敏文 对照切换。"""
from __future__ import annotations

import html

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget

_ORIGIN_STYLE = "background-color:#ffd9d9;"
_MASKED_STYLE = "background-color:#fff0a8;font-weight:bold;"


class PreviewWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paragraphs: list[str] = []
        self._pairs: list[tuple[str, str]] = []
        self._show_masked = True

        self.btn_origin = QPushButton("原文")
        self.btn_masked = QPushButton("脱敏文")
        for b in (self.btn_origin, self.btn_masked):
            b.setCheckable(True)
        self.btn_masked.setChecked(True)
        self.btn_origin.clicked.connect(lambda: self._switch(False))
        self.btn_masked.clicked.connect(lambda: self._switch(True))

        self.browser = QTextBrowser()
        top = QHBoxLayout()
        top.addWidget(self.btn_origin)
        top.addWidget(self.btn_masked)
        top.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.browser)
        self._render()

    def set_document(self, paragraphs: list[str], pairs: list[tuple[str, str]]) -> None:
        self._paragraphs = paragraphs
        self._pairs = pairs  # 已按原文长度降序
        self._render()

    def locate(self, *texts: str) -> bool:
        """查找并高亮任一文本（脱敏文视图查代称、原文视图查原文），滚动到可视区。"""
        for text in texts:
            if not text:
                continue
            cursor = self.browser.document().find(text)
            if not cursor.isNull():
                self.browser.setTextCursor(cursor)
                self.browser.centerCursor()
                return True
        return False

    def _switch(self, masked: bool) -> None:
        self._show_masked = masked
        self.btn_masked.setChecked(masked)
        self.btn_origin.setChecked(not masked)
        self._render()

    def _render(self) -> None:
        if not self._paragraphs:
            self.browser.setHtml("<p style='color:#999'>导入文档后在此预览</p>")
            return
        parts = []
        for para in self._paragraphs:
            parts.append(f"<p>{self._render_paragraph(para)}</p>")
        self.browser.setHtml("".join(parts))

    def _render_paragraph(self, text: str) -> str:
        """高亮敏感内容：脱敏文视图替换为代称并高亮，原文视图仅高亮命中处。"""
        # 先切分出命中区间，再逐段转义，保证 HTML 安全
        spans: list[tuple[int, int, str]] = []
        occupied = [False] * len(text)
        for original, alias in self._pairs:
            pos = 0
            while True:
                idx = text.find(original, pos)
                if idx < 0:
                    break
                end = idx + len(original)
                if not any(occupied[idx:end]):
                    spans.append((idx, end, alias))
                    for i in range(idx, end):
                        occupied[i] = True
                pos = idx + 1
        if not spans:
            return html.escape(text)
        spans.sort()
        out, cursor = [], 0
        for s, e, alias in spans:
            out.append(html.escape(text[cursor:s]))
            if self._show_masked:
                out.append(f"<span style='{_MASKED_STYLE}'>{html.escape(alias)}</span>")
            else:
                out.append(f"<span style='{_ORIGIN_STYLE}'>{html.escape(text[s:e])}</span>")
            cursor = e
        out.append(html.escape(text[cursor:]))
        return "".join(out)
