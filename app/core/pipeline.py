"""批次队列与文件状态机（M2：docx + pdf；扫描件 PDF 走 OCR 分支）。

状态流转：待扫描 → 扫描中 → 已扫描/扫描失败 → 已脱敏 → 已导出
映射变更后，已脱敏文件置 need_rescan 角标；失败文件不阻塞队列。
批量扫描按文件级线程池并行（OCR/NER/PDF 解析均释放 GIL），
>500 页大文件排批次最后单独处理，避免拖住常规文件。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .mapping.crypto import export_encrypted
from .mapping.exporter import build_mapping_json
from .mapping.map_table import MapTable
from .parser import docx_parser, pdf_parser, scanned_pdf_parser
from .parser.pdf_parser import probe_pdf
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
# 超过此页数的 PDF 视为大文件：排批次最后扫描，导入时预警
BIG_PAGE_THRESHOLD = 500
# 文件级并行扫描线程数上限（OCR/NER 推理释放 GIL，超出收益递减）
_MAX_SCAN_WORKERS = 4


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
    pages: int = 0          # PDF 页数（docx 无法统计，保持 0）

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def big(self) -> bool:
        """超大文件：排批次最后扫描，避免拖住常规文件。"""
        return self.pages > BIG_PAGE_THRESHOLD


class BatchPipeline:
    def __init__(self, engine: RecognizeEngine, table: MapTable) -> None:
        self.engine = engine
        self.table = table
        self.docs: list[DocItem] = []
        self._para_cache: dict[str, list[str]] = {}
        self.mapping_exported = False
        self.import_warnings: list[str] = []  # 最近一次 add_paths 的预警（大文件等）

    # ---------- 导入 ----------

    def add_paths(self, paths: list[str]) -> tuple[list[DocItem], list[str]]:
        """导入文件/文件夹，返回 (新增项, 被拒绝的路径及原因)；预警另存 import_warnings。"""
        added: list[DocItem] = []
        rejected: list[str] = []
        self.import_warnings = []
        known = {d.path for d in self.docs}
        for p in self._expand(paths):
            if p in known:
                continue
            if Path(p).suffix.lower() not in SUPPORTED_EXTS:
                rejected.append(f"{Path(p).name}：仅支持 .docx / .pdf")
                continue
            if Path(p).suffix.lower() == ".pdf":
                try:
                    textual, pages = probe_pdf(p)
                except Exception as exc:  # 损坏/非标准 PDF：不中断整批导入
                    rejected.append(f"{Path(p).name}：文件无法读取（{type(exc).__name__}）")
                    continue
            else:
                textual, pages = True, 0  # docx 无扫描件概念
            item = DocItem(p, scanned=not textual, pages=pages)
            if item.big:
                self.import_warnings.append(
                    f"{item.name}：超大文件（{pages} 页），扫描较慢，已排到批次最后")
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
        """批量扫描（建议由调用方放入工作线程），失败单文件标错不中断。

        文件级线程池并行（OCR/NER/PDF 解析的 C 库释放 GIL）；
        大文件排最后；结果按提交顺序应用，保证代称编号与串行一致。
        page_cb(doc, page_no, total)：扫描件 OCR 的页级进度（可能来自多个并行文件，消息自带文件名）。
        """
        pending = [d for d in self.docs if d.status in (ST_PENDING, ST_FAILED)]
        if not pending:
            return
        pending.sort(key=lambda d: d.big)  # 稳定排序：大文件排后，其余保持原顺序

        cpu = os.cpu_count() or 4
        workers = max(1, min(_MAX_SCAN_WORKERS, cpu // 2))
        if workers > 1 and len(pending) > 1:
            # 多文件并行时调低单文件 OCR 线程预算，总推理线程数 ≈ CPU 核数
            scanned_pdf_parser.set_thread_hint(max(2, cpu // workers), 1)

        for doc in pending:
            doc.status = ST_SCANNING
            doc.error = ""

        def work(doc: DocItem) -> tuple[DocItem, list[str], list]:
            cb = (lambda p, t: page_cb(doc, p, t)) if page_cb else None
            paragraphs = extract_paragraphs(doc.path, scanned=doc.scanned, page_cb=cb)
            findings = self.engine.scan_paragraphs(paragraphs)
            return doc, paragraphs, findings

        futures: list = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, d) for d in pending]
            for fut, doc in zip(futures, pending):
                try:
                    _, paragraphs, findings = fut.result()
                    self._para_cache[doc.path] = paragraphs
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
        # 恢复单文件默认线程预算，避免影响后续单文件重扫/预览
        scanned_pdf_parser.set_thread_hint(0, 2)

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
