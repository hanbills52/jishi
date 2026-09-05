"""docx 段落提取：覆盖正文、表格（含嵌套）、页眉页脚、脚注、文本框。

统一在 XML 层遍历所有 w:p 元素，保证与替换器使用同一遍历路径，
避免"扫得到但换不掉"或反之的不一致。
"""
from __future__ import annotations

from typing import Iterator

from docx import Document
from docx.oxml.ns import qn

# 需要遍历的 Word 部件（按 partname 关键字识别）
_PART_KEYS = ("document", "header", "footer", "footnotes", "endnotes", "comments")


def iter_text_parts(package) -> Iterator:
    """产出文档包内所有含文本的 XML 部件。"""
    for part in package.iter_parts():
        element = getattr(part, "element", None)
        if element is None:
            continue
        content_type = getattr(part, "content_type", "") or ""
        if "wordprocessingml" not in content_type:
            continue
        if any(k in str(part.partname) for k in _PART_KEYS):
            yield part


def iter_paragraph_elements(part) -> Iterator:
    """产出部件内全部 w:p 元素（含表格、文本框内的段落）。"""
    yield from part.element.iter(qn("w:p"))


def paragraph_text(p_el) -> str:
    return "".join(t.text or "" for t in p_el.iter(qn("w:t")))


def extract_paragraphs(path: str) -> list[str]:
    """提取文档全部段落文本（含空文本段落之外的全部内容）。"""
    doc = Document(path)
    paragraphs: list[str] = []
    for part in iter_text_parts(doc.part.package):
        for p_el in iter_paragraph_elements(part):
            text = paragraph_text(p_el)
            if text:
                paragraphs.append(text)
    return paragraphs
