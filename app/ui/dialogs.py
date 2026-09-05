"""弹窗：自定义脱敏项、设置、别名合并。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit, QMessageBox,
                               QVBoxLayout)


class CustomTermDialog(QDialog):
    """添加自定义脱敏项：敏感词必填，代称留空则自动分配。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加自定义脱敏项")
        self.word_edit = QLineEdit()
        self.word_edit.setPlaceholderText("要脱敏的原始内容，如：某内部项目名称")
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("留空则自动分配（甲某、乙某…）")
        form = QFormLayout()
        form.addRow("敏感词", self.word_edit)
        form.addRow("代称", self.alias_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str | None]:
        alias = self.alias_edit.text().strip()
        return self.word_edit.text().strip(), (alias or None)


class SettingsDialog(QDialog):
    def __init__(self, mask_judicial: bool, enable_ner: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.judicial_check = QCheckBox("脱敏司法人员姓名（法官/书记员等）")
        self.judicial_check.setChecked(mask_judicial)
        self.ner_check = QCheckBox("启用 NER 模型识别（实验性，误报较多）")
        self.ner_check.setChecked(enable_ner)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.judicial_check)
        layout.addWidget(self.ner_check)
        layout.addWidget(buttons)

    def mask_judicial(self) -> bool:
        return self.judicial_check.isChecked()

    def enable_ner(self) -> bool:
        return self.ner_check.isChecked()


class MergeDialog(QDialog):
    """别名分片合并：把选中项合并到同类别另一项的代称下（OCR 错别字分片场景）。"""

    def __init__(self, source_original: str, source_alias: str,
                 candidates: list[tuple[str, str]], parent=None) -> None:
        """candidates: [(目标原文, 目标代称), ...] 同类别的其他映射项。"""
        super().__init__(parent)
        self.setWindowTitle("合并到已有代称")
        hint = QLabel(f"「{source_original}」（{source_alias}）将改用所选代称，\n"
                      f"原文仍会正常脱敏；适用于 OCR 把同一主体识别成多个写法的情况。")
        hint.setWordWrap(True)
        self.combo = QComboBox()
        for original, alias in candidates:
            self.combo.addItem(f"{alias}（{original}）", original)
        form = QFormLayout()
        form.addRow("合并到", self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def target_original(self) -> str | None:
        return self.combo.currentData()


class PasswordDialog(QDialog):
    """设置映射文件密码：两次输入校验，不一致或为空不允许确认。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置映射密码")
        hint = QLabel("映射文件将以此密码加密（AES-256-GCM）。\n"
                      "密码是还原脱敏内容的唯一凭证，遗失无法找回，请妥善保管。")
        hint.setWordWrap(True)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setPlaceholderText("至少 6 位")
        self.pwd2_edit = QLineEdit()
        self.pwd2_edit.setEchoMode(QLineEdit.Password)
        self.pwd2_edit.setPlaceholderText("再次输入")
        form = QFormLayout()
        form.addRow("密码", self.pwd_edit)
        form.addRow("确认密码", self.pwd2_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        pwd = self.pwd_edit.text()
        if len(pwd) < 6:
            QMessageBox.warning(self, "密码过短", "密码至少 6 位")
            return
        if pwd != self.pwd2_edit.text():
            QMessageBox.warning(self, "不一致", "两次输入的密码不一致")
            return
        self.accept()

    def password(self) -> str:
        return self.pwd_edit.text()
