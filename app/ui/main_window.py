"""主窗口：脱敏/回溯双模式（M2 起回溯开放，切换时清空队列并提示）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QProgressBar, QRadioButton, QSplitter,
                               QStackedWidget, QToolBar, QWidget)

from ..core.mapping.map_table import MapTable
from ..core.pipeline import BatchPipeline, ST_FAILED, ST_SCANNED
from ..core.recognize.engine import RecognizeEngine
from .dialogs import CustomTermDialog, PasswordDialog, SettingsDialog
from .file_queue import FileQueueWidget
from .mapping_panel import MappingPanel
from .preview import PreviewWidget
from .restore_widget import RestoreWidget


class ScanWorker(QObject):
    """扫描工作线程：逐文件识别并回传进度（含扫描件页级进度）。"""
    file_done = Signal(object)
    page_progress = Signal(object, int, int)   # doc, page_no, total
    finished = Signal()

    def __init__(self, pipeline: BatchPipeline) -> None:
        super().__init__()
        self.pipeline = pipeline

    def run(self) -> None:
        try:
            self.pipeline.scan_all(
                progress_cb=lambda d: self.file_done.emit(d),
                page_cb=lambda d, p, t: self.page_progress.emit(d, p, t))
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("基石 · 本地化批量文档脱敏工具")
        self.resize(1400, 860)

        self.table = MapTable()
        self.engine = RecognizeEngine()
        self._try_enable_ner()
        self.pipeline = BatchPipeline(self.engine, self.table)
        self._current_path: str | None = None
        self._scan_thread: QThread | None = None

        self._build_toolbar()
        self._build_body()
        self._wire_signals()

    def _try_enable_ner(self) -> None:
        """NER 开启且模型存在才加载第三识别层；默认关闭，缺失或加载失败静默降级。"""
        if not self.engine.settings.enable_ner:
            return
        try:
            from ..core.recognize.ner import NerProvider
            self.engine.set_ner_provider(NerProvider())
        except Exception:  # noqa: BLE001 模型缺失/加载失败均视为未安装
            self.engine._ner = None

    # ---------- 界面搭建 ----------

    def _build_toolbar(self) -> None:
        bar = QToolBar("主工具栏")
        bar.setMovable(False)
        self.addToolBar(bar)

        mode_box = QWidget()
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setContentsMargins(6, 0, 6, 0)
        self.redact_mode = QRadioButton("脱敏模式")
        self.redact_mode.setChecked(True)
        self.restore_mode = QRadioButton("回溯模式")
        self.restore_mode.setToolTip("导入 AI 处理后的文档 + 映射文件，还原出原文")
        mode_layout.addWidget(self.redact_mode)
        mode_layout.addWidget(self.restore_mode)
        bar.addWidget(mode_box)
        bar.addSeparator()

        self._mode_actions: list[QAction] = []
        for text, slot in (("导入文件", self.import_files),
                           ("导入文件夹", self.import_folder),
                           ("开始扫描", self.start_scan_manual),
                           ("批量导出", self.export_all),
                           ("设置", self.open_settings)):
            action = QAction(text, self)
            action.triggered.connect(slot)
            bar.addAction(action)
            self._mode_actions.append(action)

    def _build_body(self) -> None:
        self.queue_widget = FileQueueWidget()
        self.preview_widget = PreviewWidget()
        self.mapping_widget = MappingPanel()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.queue_widget)
        splitter.addWidget(self.preview_widget)
        splitter.addWidget(self.mapping_widget)
        splitter.setSizes([240, 760, 400])

        self.restore_widget = RestoreWidget()
        self.stack = QStackedWidget()
        self.stack.addWidget(splitter)          # 0 = 脱敏模式
        self.stack.addWidget(self.restore_widget)  # 1 = 回溯模式
        self.setCentralWidget(self.stack)

        # 状态栏：进度条 + 状态文字（扫描时可见）
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(280)
        self.progress.setVisible(False)
        self.status_label = QLabel("")
        self.statusBar().addWidget(self.progress)
        self.statusBar().addWidget(self.status_label, 1)

    def _wire_signals(self) -> None:
        self.queue_widget.file_selected.connect(self.show_document)
        self.mapping_widget.enabled_changed.connect(self.on_enabled_changed)
        self.mapping_widget.pending_resolved.connect(self.on_pending_resolved)
        self.mapping_widget.custom_added.connect(self.add_custom_term)
        self.mapping_widget.merge_requested.connect(self.on_merge_requested)
        self.mapping_widget.item_selected.connect(self.on_item_selected)
        self.mapping_widget.all_pending_ignored.connect(self.on_all_pending_ignored)
        self.redact_mode.toggled.connect(self._on_mode_toggled)

    # ---------- 模式切换 ----------

    def _on_mode_toggled(self, redact_checked: bool) -> None:
        if redact_checked:
            self.stack.setCurrentIndex(0)
            self._set_redact_actions(True)
        else:
            # 切到回溯：清空当前队列并提示
            if self.pipeline.docs:
                ret = QMessageBox.question(
                    self, "切换模式",
                    "切换到回溯模式将清空当前脱敏队列，是否继续？")
                if ret != QMessageBox.Yes:
                    self.redact_mode.setChecked(True)  # 回退，不再触发
                    return
                self.pipeline.clear()
                self.queue_widget.refresh(self.pipeline.docs)
                self.mapping_widget.set_files([])
                self.mapping_widget.refresh(self.table.items())
                self.preview_widget.set_document([], [])
                self._current_path = None
            self.restore_widget.reset()
            self.stack.setCurrentIndex(1)
            self._set_redact_actions(False)

    def _set_redact_actions(self, enabled: bool) -> None:
        for action in self._mode_actions:
            action.setEnabled(enabled)

    # ---------- 导入与扫描 ----------

    def import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文档", "",
            "文档 (*.docx *.pdf);;Word 文档 (*.docx);;PDF 文档 (*.pdf)")
        if paths:
            self._add_and_scan(paths)

    def import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self._add_and_scan([folder])

    def _add_and_scan(self, paths: list[str]) -> None:
        added, rejected = self.pipeline.add_paths(paths)
        if rejected:
            QMessageBox.information(self, "部分文件未导入", "\n".join(rejected))
        if not added:
            return
        self.queue_widget.refresh(self.pipeline.docs)
        self.mapping_widget.set_files([d.name for d in self.pipeline.docs])
        self._start_scan()

    def start_scan_manual(self) -> None:
        """工具栏"开始扫描"按钮：手动触发（自动扫描之外的双保险）。"""
        if self._scan_thread is not None:
            self.status_label.setText("正在扫描中，请稍候…")
            return
        if not self.pipeline.docs:
            self.status_label.setText("请先导入文件")
            return
        self._start_scan()

    def _start_scan(self) -> None:
        if self._scan_thread is not None:
            return  # 扫描中，新文件下轮处理
        pending = [d for d in self.pipeline.docs if d.status in ("待扫描", "扫描失败")]
        if not pending:
            return
        self._scan_total = len(pending)
        self._scan_done = 0
        self.progress.setMaximum(self._scan_total)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status_label.setText(f"开始扫描 {self._scan_total} 份文件…")

        self._scan_thread = QThread(self)
        self._worker = ScanWorker(self.pipeline)   # 必须保持强引用，否则被回收后扫描静默不执行
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._worker.run)
        self._worker.file_done.connect(self._on_file_scanned)
        self._worker.page_progress.connect(self._on_page_progress)
        self._worker.finished.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_page_progress(self, doc, page_no: int, total: int) -> None:
        """扫描件 OCR 页级进度：状态栏显示“第 x/N 页”。"""
        self.status_label.setText(
            f"已扫描 {self._scan_done}/{self._scan_total}：{doc.name}（OCR 第 {page_no}/{total} 页）")

    def _on_file_scanned(self, doc) -> None:
        self._scan_done += 1
        self.progress.setValue(self._scan_done)
        tag = "（扫描件 OCR，较慢）" if getattr(doc, "scanned", False) else ""
        self.status_label.setText(
            f"已扫描 {self._scan_done}/{self._scan_total}：{doc.name}{tag}")
        self.queue_widget.refresh(self.pipeline.docs)
        self.mapping_widget.refresh(self.table.items())
        if doc.path == self._current_path or self._current_path is None:
            self.show_document(doc.path if doc.path else self._current_path)

    def _on_scan_finished(self) -> None:
        self._scan_thread.quit()
        self._scan_thread.wait()
        self._scan_thread = None
        self._worker = None
        # 扫描期间可能有新文件加入
        if any(d.status == "待扫描" for d in self.pipeline.docs):
            self._start_scan()
            return
        self.progress.setVisible(False)
        self.status_label.setText("扫描完成，请在右侧确认待确认项后导出")

    # ---------- 预览 ----------

    def show_document(self, path: str | None) -> None:
        if not path:
            return
        self._current_path = path
        doc = next((d for d in self.pipeline.docs if d.path == path), None)
        if doc is None or doc.status in ("待扫描", "扫描中", ST_FAILED):
            return
        try:
            paragraphs = self.pipeline.paragraphs_of(path)
        except Exception as exc:
            QMessageBox.warning(self, "预览失败", str(exc))
            return
        self.preview_widget.set_document(paragraphs, self.table.effective_pairs(doc.name))

    # ---------- 映射面板回调 ----------

    def _after_mapping_change(self) -> None:
        self.pipeline.mark_dirty()
        self.mapping_widget.refresh(self.table.items())
        self.queue_widget.refresh(self.pipeline.docs)
        if self._current_path:
            self.show_document(self._current_path)

    def on_enabled_changed(self, original: str, enabled: bool) -> None:
        self.table.set_enabled(original, enabled)
        self._after_mapping_change()

    def on_pending_resolved(self, original: str, accept: bool) -> None:
        if accept:
            self.table.set_pending(original, False)
        else:
            self.table.remove(original)
        self._after_mapping_change()

    def on_all_pending_ignored(self, originals: list) -> None:
        """批量忽略：二次确认后从映射表移除，并刷新界面。"""
        ret = QMessageBox.question(
            self, "批量忽略",
            f"将忽略当前筛选范围内的 {len(originals)} 项待确认项，是否继续？")
        if ret != QMessageBox.Yes:
            return
        for original in originals:
            self.table.remove(original)
        self._after_mapping_change()

    def add_custom_term(self) -> None:
        dialog = CustomTermDialog(self)
        if dialog.exec():
            word, alias = dialog.values()
            if not word:
                return
            self.table.add_custom(word, alias)
            self._after_mapping_change()

    def on_item_selected(self, original: str) -> None:
        """点击映射项：切到第一个来源文件并在预览中定位高亮该词。"""
        item = self.table.get(original)
        if item is None:
            return
        if item.files:  # 全局项（files=None）保持当前预览
            target = next((d for d in self.pipeline.docs if d.name in item.files), None)
            if target and target.path != self._current_path:
                self.queue_widget.select_path(target.path)  # 触发 show_document
        self.preview_widget.locate(original, item.alias)

    def on_merge_requested(self, original: str) -> None:
        """别名分片合并：弹窗选择同类别目标项，合并后刷新并标脏。"""
        from ..core.mapping.map_table import ALIAS_CATEGORIES
        src = self.table.get(original)
        if src is None or src.category not in ALIAS_CATEGORIES:
            QMessageBox.information(self, "提示", "仅人名/公司/地址/自定义项支持合并")
            return
        candidates = [(it.original, it.alias) for it in self.table.items()
                      if it.category == src.category and it.original != original]
        if not candidates:
            QMessageBox.information(self, "提示", "没有可合并的同类别项")
            return
        dialog = MergeDialog(original, src.alias, candidates, self)
        if dialog.exec() and dialog.target_original():
            self.table.merge_into(original, dialog.target_original())
            self._after_mapping_change()

    # ---------- 导出与设置 ----------

    def export_all(self) -> None:
        if not self.pipeline.docs:
            QMessageBox.information(self, "提示", "请先导入文档")
            return
        pending = self.pipeline.pending_items()
        if pending:
            ret = QMessageBox.question(
                self, "存在待确认项",
                f"{len(pending)} 项待确认识别未生效，是否继续导出？")
            if ret != QMessageBox.Yes:
                return
        default_dir = str(Path(self.pipeline.docs[0].path).parent / "脱敏输出")
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录", default_dir)
        if not out_dir:
            return
        # 映射密码（两次输入校验）
        pwd_dialog = PasswordDialog(self)
        if not pwd_dialog.exec():
            return
        map_path = str(Path(out_dir) / f"映射_{datetime.now():%Y%m%d_%H%M%S}.json")
        result = self.pipeline.export(out_dir, map_path, pwd_dialog.password())
        self.queue_widget.refresh(self.pipeline.docs)
        msg = (f"成功导出 {len(result['exported'])} 份文档\n"
               f"映射文件：{result['map_path']}")
        if result["failed"]:
            msg += f"\n失败 {len(result['failed'])} 份：{'、'.join(result['failed'])}"
        if result.get("warnings"):
            msg += "\n\n溢出告警：\n" + "\n".join(result["warnings"][:10])
        QMessageBox.information(self, "导出完成", msg)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.engine.settings.mask_judicial,
                                self.engine.settings.enable_ner, self)
        if dialog.exec():
            ner_changed = dialog.enable_ner() != self.engine.settings.enable_ner
            self.engine.settings.mask_judicial = dialog.mask_judicial()
            self.engine.settings.enable_ner = dialog.enable_ner()
            if ner_changed:
                if self.engine.settings.enable_ner and self.engine._ner is None:
                    self._try_enable_ner()
                if self.pipeline.docs:
                    for doc in self.pipeline.docs.values():
                        doc.need_rescan = True
                    self._refresh_queue()
                    self.status.showMessage("NER 开关已变更，请重新扫描以应用")

    # ---------- 关闭保护 ----------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.pipeline.docs and not self.pipeline.mapping_exported:
            ret = QMessageBox.warning(
                self, "映射文件未导出",
                "映射文件未导出，关闭后无法还原本次脱敏。仍要关闭吗？",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
