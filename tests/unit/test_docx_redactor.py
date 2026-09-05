"""M1-6 自查：docx 跨 run 替换、样式保留、表格/页眉覆盖、长词优先。"""
from docx import Document

from app.core.parser.docx_parser import extract_paragraphs
from app.core.redact.docx_redactor import redact_document


def build_sample(path):
    doc = Document()
    # 跨 3 个 run 的"张三"，中间 run 加粗
    p = doc.add_paragraph()
    p.add_run("原告张")
    bold = p.add_run("三")
    bold.bold = True
    p.add_run("，男，手机13812345678。")
    # 表格内的姓名
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].add_run("被告：张三丰")
    # 页眉内的姓名
    header = doc.sections[0].header
    header.paragraphs[0].add_run("案卷：张三卷")
    doc.save(path)


def test_cross_run_replace_keeps_style(tmp_path):
    src = tmp_path / "src.docx"
    dst = tmp_path / "dst.docx"
    build_sample(str(src))
    pairs = [("张三丰", "乙某"), ("张三", "甲某"), ("13812345678", "138****5678")]
    count = redact_document(str(src), str(dst), pairs)
    assert count == 4  # 正文张三 + 手机号 + 表格张三丰 + 页眉张三

    doc = Document(str(dst))
    text = "\n".join(extract_paragraphs(str(dst)))
    assert "张三" not in text
    assert "甲某，男，手机138****5678。" in text
    assert "被告：乙某" in text      # 长词优先，不是"甲某丰"
    assert "案卷：甲某卷" in text    # 页眉覆盖

    # 代称写入区间起始 run（run0），中间加粗 run 置空但样式保留
    p = doc.paragraphs[0]
    assert len(p.runs) == 3
    assert "甲某" in p.runs[0].text
    assert p.runs[1].text == "" and p.runs[1].bold is True
    # 表格结构不变
    assert len(doc.tables) == 1 and len(doc.tables[0].rows) == 1


def test_no_match_no_change(tmp_path):
    src = tmp_path / "src.docx"
    dst = tmp_path / "dst.docx"
    build_sample(str(src))
    count = redact_document(str(src), str(dst), [("不存在", "代称")])
    assert count == 0
    assert extract_paragraphs(str(dst)) == extract_paragraphs(str(src))
