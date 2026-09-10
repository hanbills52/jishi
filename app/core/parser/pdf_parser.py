"""PDF 文本提取：按页产出 span 级文本，判定扫描件。

与 docx_parser 的段落模型对齐：对外仍提供段落列表供识别引擎扫描；
PDF 的"段落"按文本行（line）粒度产出，偏移信息仅供定位参考。
"""
from __future__ import annotations

import pymupdf


class ScannedPdfError(Exception):
    """无文本层的扫描件/图片型 PDF。"""


def probe_pdf(path: str) -> tuple[bool, int]:
    """一次打开同时探测：是否含文本层、总页数（供大文件预警）。"""
    with pymupdf.open(path) as doc:
        pages = doc.page_count
        textual = any(page.get_text("words") for page in doc)
    return textual, pages


def is_textual(path: str) -> bool:
    """PDF 是否含可选中文字（有文本层）。"""
    return probe_pdf(path)[0]


def extract_paragraphs(path: str) -> list[str]:
    """提取全部文本行；完全无文本层时抛 ScannedPdfError。

    用 text 模式而非 dict 模式：部分 PDF（如银行系统嵌入的 OCR 文本层）
    dict 模式逐字符处理病态字体极慢（实测 16 页 9.4s → 0.25s），输出完全一致。
    """
    lines: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            lines += (ln for ln in page.get_text("text").splitlines() if ln.strip())
    if not lines:
        raise ScannedPdfError("未检测到文本层（扫描件/图片型 PDF），暂不支持")
    return lines
