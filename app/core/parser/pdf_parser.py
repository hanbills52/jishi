"""PDF 文本提取：按页产出 span 级文本，判定扫描件。

与 docx_parser 的段落模型对齐：对外仍提供段落列表供识别引擎扫描；
PDF 的"段落"按文本行（line）粒度产出，偏移信息仅供定位参考。
"""
from __future__ import annotations

import pymupdf


class ScannedPdfError(Exception):
    """无文本层的扫描件/图片型 PDF。"""


def is_textual(path: str) -> bool:
    """PDF 是否含可选中文字（有文本层）。"""
    with pymupdf.open(path) as doc:
        return any(page.get_text("words") for page in doc)


def extract_paragraphs(path: str) -> list[str]:
    """提取全部文本行；完全无文本层时抛 ScannedPdfError。"""
    lines: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:  # 0=文本块，1=图片块
                    continue
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", []))
                    if text.strip():
                        lines.append(text)
    if not lines:
        raise ScannedPdfError("未检测到文本层（扫描件/图片型 PDF），暂不支持")
    return lines
