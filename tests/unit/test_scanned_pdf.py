"""扫描件 OCR 脱敏：构造图片型 PDF → OCR 识别 → 覆盖抹除 → 代称写入。

验证方式为 OCR 闭环：脱敏后的 PDF 重新 OCR，原文应消失、代称应出现。
"""
from __future__ import annotations

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.parser import scanned_pdf_parser
from app.core.redact.scanned_pdf_redactor import redact_document

_FONT = "C:/Windows/Fonts/msyh.ttc"


def make_scanned_pdf(path, lines: list[str]) -> None:
    """把文字渲染成图片再放入 PDF（模拟扫描件，无文本层）。"""
    img = Image.new("RGB", (900, 60 + 50 * len(lines)), (250, 248, 245))  # 仿纸张底色
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(_FONT, 26)
    y = 20
    for ln in lines:
        d.text((30, y), ln, font=font, fill=(20, 20, 20))
        y += 50
    doc = pymupdf.open()
    page = doc.new_page(width=900, height=img.height)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()


@pytest.fixture(autouse=True)
def clear_ocr_cache():
    scanned_pdf_parser._cache.clear()
    yield
    scanned_pdf_parser._cache.clear()


def test_ocr_extract(tmp_path):
    pdf = tmp_path / "s.pdf"
    make_scanned_pdf(pdf, ["借款人：张三", "身份证号110105199003077550"])
    lines = scanned_pdf_parser.extract_paragraphs(str(pdf))
    joined = "\n".join(lines)
    assert "张三" in joined and "110105199003077550" in joined


def test_scanned_redact(tmp_path):
    src = tmp_path / "s.pdf"
    dst = tmp_path / "out.pdf"
    make_scanned_pdf(src, ["出借人：张三，借款人：李四"])
    count, warnings = redact_document(str(src), str(dst),
                                      [("张三", "甲某"), ("李四", "乙某")])
    assert count == 2
    # OCR 闭环：脱敏后重新 OCR，原文应被抹除、代称应可见
    scanned_pdf_parser._cache.clear()
    after = "\n".join(scanned_pdf_parser.extract_paragraphs(str(dst)))
    assert "张三" not in after and "李四" not in after
    assert "甲某" in after and "乙某" in after


def test_scanned_keeps_other_content(tmp_path):
    """非敏感内容（如合同标题、条款文字）应保持不变。"""
    src = tmp_path / "s.pdf"
    dst = tmp_path / "out.pdf"
    make_scanned_pdf(src, ["借款合同", "借款人：张三", "借款金额五万元整"])
    redact_document(str(src), str(dst), [("张三", "甲某")])
    scanned_pdf_parser._cache.clear()
    after = "\n".join(scanned_pdf_parser.extract_paragraphs(str(dst)))
    assert "借款合同" in after and "借款金额五万元整" in after
    assert "张三" not in after
