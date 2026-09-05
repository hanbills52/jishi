"""回溯模式面板：AI 文档导入区 + 映射文件导入区 + 密码框 + 还原 + 未还原项面板。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QFileDialog, QFormLayout, QGroupBox, QLabel,
                               QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.mapping.restorer import RESTORABLE_EXTS, RestoreError, restore_document


class RestoreWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc_path: str | None = None
        self._map_path: str | None = None

        # 文档导入区
        doc_box = QGroupBox("① AI 处理后的文档（.docx / .txt / .md）")
        doc_layout = QVBoxLayout(doc_box)
        self.doc_label = QLabel("未选择")
        doc_btn = QPushButton("选择文档…")
        doc_btn.clicked.connect(self._pick_doc)
        doc_layout.addWidget(self.doc_label)
        doc_layout.addWidget(doc_btn)

        # 映射文件导入区
        map_box = QGroupBox("② 映射文件（脱敏导出时生成）")
        map_layout = QVBoxLayout(map_box)
        self.map_label = QLabel("未选择")
        map_btn = QPushButton("选择映射文件…")
        map_btn.clicked.connect(self._pick_map)
        map_layout.addWidget(self.map_label)
        map_layout.addWidget(map_btn)

        # 密码
        pwd_box = QGroupBox("③ 映射密码")
        pwd_form = QFormLayout(pwd_box)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        pwd_form.addRow("密码", self.pwd_edit)

        # 还原按钮
        self.restore_btn = QPushButton("开始还原")
        self.restore_btn.setMinimumHeight(36)
        self.restore_btn.clicked.connect(self._do_restore)

        # 未还原项面板
        unrestored_box = QGroupBox("未还原项（AI 删除了代称，无法还原的条目）")
        unrestored_layout = QVBoxLayout(unrestored_box)
        self.unrestored_list = QListWidget()
        unrestored_layout.addWidget(self.unrestored_list)

        layout = QVBoxLayout(self)
        for w in (doc_box, map_box, pwd_box, self.restore_btn, unrestored_box):
            layout.addWidget(w)
        layout.addStretch(1)

    def _pick_doc(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(RESTORABLE_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, "选择 AI 处理后文档", "",
                                              f"可还原文档 ({exts})")
        if path:
            self._doc_path = path
            self.doc_label.setText(Path(path).name)

    def _pick_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择映射文件", "",
                                              "映射文件 (*.json)")
        if path:
            self._map_path = path
            self.map_label.setText(Path(path).name)

    def _do_restore(self) -> None:
        if not self._doc_path or not self._map_path:
            QMessageBox.information(self, "提示", "请先选择文档和映射文件")
            return
        if not self.pwd_edit.text():
            QMessageBox.information(self, "提示", "请输入映射密码")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择还原输出目录")
        if not out_dir:
            return
        try:
            result = restore_document(self._doc_path, self._map_path,
                                      self.pwd_edit.text(), out_dir)
        except RestoreError as exc:
            QMessageBox.warning(self, "还原失败", str(exc))
            return

        # 未还原项展示 + 随还原文件存 未还原项.txt
        self.unrestored_list.clear()
        for u in result.unrestored:
            self.unrestored_list.addItem(
                f"代称「{u['alias']}」→ 原文「{u['original']}」（原出现 {u['occurrences']} 次）")
        if result.unrestored:
            report = Path(result.output_path).parent / "未还原项.txt"
            report.write_text(
                "未还原项清单\n" + "\n".join(
                    f"{u['alias']}\t{u['original']}\t原出现 {u['occurrences']} 次"
                    for u in result.unrestored),
                encoding="utf-8")

        msg = (f"还原完成：{result.output_path}\n替换 {result.replaced} 处，"
               f"未还原 {len(result.unrestored)} 项")
        if result.name_warning:
            msg = f"⚠ {result.name_warning}\n\n" + msg
        QMessageBox.information(self, "还原完成", msg)

    def reset(self) -> None:
        """模式切换时清空。"""
        self._doc_path = self._map_path = None
        self.doc_label.setText("未选择")
        self.map_label.setText("未选择")
        self.pwd_edit.clear()
        self.unrestored_list.clear()
