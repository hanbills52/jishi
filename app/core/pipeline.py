"""批次队列与文件状态机（M2：docx + pdf；扫描件 PDF 走 OCR 分支）。

状态流转：待扫描 → 扫描中 → 已扫描/扫描失败 → 已脱敏 → 已导出
映射变更后，已脱敏文件置 need_rescan 角标；失败文件不阻塞队列。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .mapping.crypto import export_encrypted
from .mapping.exporter import build_mapping_json
from .mapping.map_table import MapTable
from .parser import docx_parser, pdf_parser, scanned_pdf_parser
from .recognize.engine import RecognizeEngine
from .redact import docx_redactor, pdf_redactor, scanned_pdf_redactor

# 状态常量
ST_PENDING = "待扫描"
ST_SCANNING = "扫描中"
ST_SCANNED = "已扫描"
ST_FAILED = "扫描失败"
ST_REDACTED = "已脱敏"
ST_EXPORTED = "已导出"

SUPPORTED_EXTS = {".docx", ".pdf"}


def is_scanned_pdf(path: str) -> bool:
    return Path(path).suffix.lower() == ".pdf" and not pdf_parser.is_textual(path)


def extract_paragraphs(path: str, scanned: bool = False,
                       page_cb: Callable[[int, int], None] | None = None) -> list[str]:
    """按文件类型分发解析器；扫描件 PDF 走 OCR，page_cb 回报页级进度。"""
    if Path(path).suffix.lower() == ".pdf":
        if scanned:
            return scanned_pdf_parser.extract_paragraphs(path, page_cb)
        return pdf_parser.extract_paragraphs(path)
    return docx_parser.extract_paragraphs(path)


def redact_document(src_path: str, dst_path: str, pairs: list[tuple[str, str]],
                    scanned: bool = False) -> tuple[int, list[str]]:
    """按文件类型分发替换器，返回 (替换次数, 告警列表)。"""
    if Path(src_path).suffix.lower() == ".pdf":
        if scanned:
            return scanned_pdf_redactor.redact_document(src_path, dst_path, pairs)
        return pdf_redactor.redact_document(src_path, dst_path, pairs)
    return docx_redactor.redact_document(src_path, dst_path, pairs), []


@dataclass
class DocItem:
    path: str
    status: str = ST_PENDING
    error: str = ""
    need_rescan: bool = False
    scanned: bool = False   # 扫描件 PDF（OCR 识别，需人工复核）

    @property
    def name(self) -> str:
        return Path(self.path).name


class BatchPipeline:
    def __init__(self, engine: RecognizeEngine, table: MapTable) -> None:
        self.engine = engine
        self.table = table
        self.docs: list[DocItem] = []
        self._para_cache: dict[str, list[str]] = {}
        self.mapping_exported = False

    # ---------- 导入 ----------

    def add_paths(self, paths: list[str]) -> tuple[list[DocItem], list[str]]:
        """导入文件/文件夹，返回 (新增项, 被拒绝的路径及原因)。"""
        added: list[DocItem] = []
        rejected: list[str] = []
        known = {d.path for d in self.docs}
        for p in self._expand(paths):
            if p in known:
                continue
            if Path(p).suffix.lower() not in SUPPORTED_EXTS:
                rejected.append(f"{Path(p).name}：仅支持 .docx / .pdf")
                continue
            item = DocItem(p, scanned=is_scanned_pdf(p))
            self.docs.append(item)
            known.add(p)
            added.append(item)
        return added, rejected

    def _expand(self, paths: list[str]) -> Iterator[str]:
        for p in paths:
            pp = Path(p)
            if pp.is_dir():
                for child in sorted(pp.rglob("*")):
                    if child.is_file():
                        yield str(child)
            elif pp.is_file():
                yield str(pp)

    # ---------- 扫描 ----------

    def scan_all(self, progress_cb: Callable[[DocItem], None] | None = None,
                 page_cb: Callable[[DocItem, int, int], None] | None = None) -> None:
        """逐文件扫描（建议由调用方放入工作线程），失败单文件标错不中断。

        page_cb(doc, page_no, total)：扫描件 OCR 的页级进度。
        """
        for doc in self.docs:
            if doc.status not in (ST_PENDING, ST_FAILED):
                continue
            doc.status = ST_SCANNING
            doc.error = ""
            try:
                cb = (lambda d: (lambda p, t: page_cb(d, p, t)))(doc) if page_cb else None
                paragraphs = extract_paragraphs(doc.path, scanned=doc.scanned, page_cb=cb)
                self._para_cache[doc.path] = paragraphs
                findings = self.engine.scan_paragraphs(paragraphs)
                for f in findings:
                    self.table.add_finding(f.text, f.category, f.source,
                                           f.confidence, pending=(f.status == "pending"),
                                           file_name=doc.name)
                doc.status = ST_SCANNED
            except Exception as exc:  # 损坏/加密/被占用等
                doc.status = ST_FAILED
                doc.error = f"{type(exc).__name__}: {exc}"
            if progress_cb:
                progress_cb(doc)

    def paragraphs_of(self, path: str) -> list[str]:
        if path not in self._para_cache:
            doc = next((d for d in self.docs if d.path == path), None)
            self._para_cache[path] = extract_paragraphs(
                path, scanned=bool(doc and doc.scanned))
        return self._para_cache[path]

    # ---------- 映射变更 ----------

    def mark_dirty(self) -> None:
        """映射变更后：已脱敏/已导出文件回退角标，需重新脱敏导出。"""
        for doc in self.docs:
            if doc.status in (ST_REDACTED, ST_EXPORTED):
                doc.status = ST_SCANNED
                doc.need_rescan = True
        self.mapping_exported = False

    # ---------- 导出 ----------

    def export(self, out_dir: str, map_path: str, password: str) -> dict:
        """批量脱敏导出 + 加密映射文件（AES-256-GCM）。返回结果摘要。"""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        done, failed = [], []
        warnings: list[str] = []
        for doc in self.docs:
            if doc.status in (ST_PENDING, ST_SCANNING, ST_FAILED):
                continue
            pairs = self.table.effective_pairs(doc.name)
            target = self._unique_target(out / doc.name)
            try:
                _, doc_warnings = redact_document(doc.path, str(target), pairs,
                                                  scanned=doc.scanned)
                warnings += [f"{doc.name}：{w}" for w in doc_warnings]
                doc.status = ST_EXPORTED
                doc.need_rescan = False
                done.append(doc.name)
            except Exception as exc:
                doc.status = ST_FAILED
                doc.error = f"导出失败：{type(exc).__name__}: {exc}"
                failed.append(doc.name)
        data = build_mapping_json(self.table, [d.path for d in self.docs])
        export_encrypted(data, password, map_path)
        self.mapping_exported = True
        return {"exported": done, "failed": failed, "map_path": map_path,
                "warnings": warnings}

    @staticmethod
    def _unique_target(target: Path) -> Path:
        """重名自动追加 _1、_2 序号。"""
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        i = 1
        while (target.parent / f"{stem}_{i}{suffix}").exists():
            i += 1
        return target.parent / f"{stem}_{i}{suffix}"

    def pending_items(self):
        return [it for it in self.table.items() if it.pending]

    def clear(self) -> None:
        self.docs.clear()
        self._para_cache.clear()
        self.table.clear()
        self.mapping_exported = False
