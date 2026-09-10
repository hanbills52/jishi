"""扫描件 PDF 的 OCR 解析：页面渲染为图片 → RapidOCR → 行级文字+坐标。

- 坐标统一转换为 PDF 点坐标（与文字型 PDF 的 redaction 坐标系一致）
- 结果模块级缓存：扫描阶段取文本、脱敏阶段取坐标，避免二次 OCR
- OCR 单例惰性加载：模型初始化约 1~2 秒，整个进程只加载一次
- 提速策略：关闭方向分类器、ONNX 线程随并行预算自适应、逐页并行推理（DPI 维持 200 保召回）
  多文件并行扫描时由 pipeline.scan_all 调用 set_thread_hint 调低单文件线程数
- progress_cb(page_no, total)：每页完成后回调（可能来自 OCR 工作线程，UI 需经信号转发）
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pymupdf

# OCR 渲染分辨率（DPI）：实测 160 会漏检（身份证页少 3 行），脱敏场景召回优先，保持 200
OCR_DPI = 200
# 单次加载进内存的页数上限（控制内存峰值）
_CHUNK_PAGES = 8

_ocr_instance = None
_ocr_lock = threading.Lock()
# 缓存：{(路径, mtime): [PageOcr, ...]}
_cache: dict[tuple[str, float], list["PageOcr"]] = {}
# 线程配置（首次创建 OCR 单例 / 每次 OCR 时生效）：
# 多文件并行扫描时由 pipeline 调低，避免 线程数×并行度 超额竞争
_intra_hint = 0            # 0 = 按默认 max(2, cpu-1)
_file_workers = 2          # 单文件内并行推理线程数


def set_thread_hint(intra: int, file_workers: int) -> None:
    """多文件并行扫描前设置线程预算（对已创建的 OCR 单例不生效）。"""
    global _intra_hint, _file_workers
    _intra_hint = intra
    _file_workers = max(1, file_workers)


@dataclass
class OcrLine:
    rect: pymupdf.Rect   # PDF 点坐标
    text: str
    confidence: float


@dataclass
class PageOcr:
    page_no: int
    lines: list[OcrLine]


def get_ocr():
    """RapidOCR 单例（首次调用时加载模型），关闭方向分类器提速。
    加锁：并行扫描时多个文件线程可能同时首次触发加载。"""
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                from rapidocr_onnxruntime import RapidOCR
                cpu = os.cpu_count() or 4
                _ocr_instance = RapidOCR(
                    use_cls=False,                     # 扫描件均为正向文本，省掉方向分类
                    intra_op_num_threads=_intra_hint or max(2, cpu - 1),
                    inter_op_num_threads=1,
                )
    return _ocr_instance


def _render_page(page, mat) -> np.ndarray:
    pix = page.get_pixmap(matrix=mat)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:  # RGBA → RGB
        img = img[:, :, :3]
    return img


def _ocr_page(ocr, img: np.ndarray, zoom: float) -> list[OcrLine]:
    result, _ = ocr(img)
    lines: list[OcrLine] = []
    for box, text, conf in (result or []):
        if not text.strip():
            continue
        xs = [p[0] / zoom for p in box]
        ys = [p[1] / zoom for p in box]
        rect = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
        lines.append(OcrLine(rect, text, float(conf)))
    return lines


def ocr_document(path: str,
                 progress_cb: Callable[[int, int], None] | None = None
                 ) -> list[PageOcr]:
    """对整份 PDF 做 OCR，返回每页行级结果（带缓存）。

    渲染在主线程（PyMuPDF 文档句柄非线程安全），推理双线程并行。
    """
    key = (str(Path(path).resolve()), Path(path).stat().st_mtime)
    if key in _cache:
        return _cache[key]

    ocr = get_ocr()
    zoom = OCR_DPI / 72
    mat = pymupdf.Matrix(zoom, zoom)
    pages: list[PageOcr] = []
    done = 0
    with pymupdf.open(path) as doc:
        total = doc.page_count
        for chunk_start in range(0, total, _CHUNK_PAGES):
            chunk_end = min(chunk_start + _CHUNK_PAGES, total)
            # 主线程渲染本块页面
            imgs = [_render_page(doc[i], mat) for i in range(chunk_start, chunk_end)]
            # 并行推理，结果按页序归位（线程数随并行扫描预算自适应）
            with ThreadPoolExecutor(max_workers=_file_workers) as pool:
                chunk_lines = list(pool.map(
                    lambda im: _ocr_page(ocr, im, zoom), imgs))
            for i, lines in enumerate(chunk_lines):
                pages.append(PageOcr(chunk_start + i, lines))
                done += 1
                if progress_cb:
                    progress_cb(done, total)
    _cache[key] = pages
    return pages


def extract_paragraphs(path: str,
                       progress_cb: Callable[[int, int], None] | None = None
                       ) -> list[str]:
    """供识别引擎扫描的文本（行粒度）。"""
    return [ln.text for pg in ocr_document(path, progress_cb) for ln in pg.lines]
