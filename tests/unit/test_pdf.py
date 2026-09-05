"""M2-1 自查：PDF 解析与替换。"""
from __future__ import annotations

import pymupdf
import pytest

from app.core.parser.pdf_parser import ScannedPdfError, extract_paragraphs, is_textual
from app.core.redact.pdf_redactor import redact_document


def make_pdf(path, lines: list[str]) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for ln in lines:
        # china-s：PyMuPDF 内置 CJK 字体（默认 helv 不含中文字形）
        page.insert_text((72, y), ln, fontsize=12, fontname="china-s")
        y += 20
    doc.save(str(path))
    doc.close()


def make_scanned_pdf(path) -> None:
    """无文本层的扫描件（仅图片）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100))
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    doc.save(str(path))
    doc.close()


def test_extract_paragraphs(tmp_path):
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, ["借款人：张三", "身份证号110105199003077550"])
    lines = extract_paragraphs(str(pdf))
    assert any("张三" in ln for ln in lines)


def test_scanned_pdf_rejected(tmp_path):
    pdf = tmp_path / "scan.pdf"
    make_scanned_pdf(pdf)
    assert not is_textual(str(pdf))
    with pytest.raises(ScannedPdfError):
        extract_paragraphs(str(pdf))


def test_redact_replaces_and_erases(tmp_path):
    src = tmp_path / "a.pdf"
    dst = tmp_path / "out.pdf"
    make_pdf(src, ["出借人：张三，住北京市海淀区中关村大街28号院3号楼502室"])
    count, warnings = redact_document(str(src), str(dst),
                                      [("张三", "甲某"), ("北京市海淀区中关村大街28号院3号楼502室", "甲地址")])
    assert count == 2 and not warnings
    # 原文不可检索，代称可见
    with pymupdf.open(str(dst)) as doc:
        text = doc[0].get_text()
        assert "张三" not in text and "甲某" in text
        assert "甲地址" in text
        assert not doc[0].search_for("张三")


def test_long_alias_shrinks_font(tmp_path):
    """短原文→长代称：字号缩小适配（3 字代称入 2 字区域，8pt 可放下），不误报告警。"""
    src = tmp_path / "a.pdf"
    dst = tmp_path / "out.pdf"
    make_pdf(src, ["甲方：张三"])
    count, warnings = redact_document(str(src), str(dst), [("张三", "甲某某")])
    assert count == 1 and not warnings


def test_unfittable_alias_warns(tmp_path):
    """极小区域+长代称：触发溢出告警。"""
    src = tmp_path / "a.pdf"
    dst = tmp_path / "out.pdf"
    make_pdf(src, ["甲方：张三"])
    long_alias = "非常非常长的一个代称标识符号甲某某某某某某某某"
    count, warnings = redact_document(str(src), str(dst), [("张三", long_alias)])
    assert count == 1 and warnings and "张三" in warnings[0]
