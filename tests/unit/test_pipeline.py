"""批次队列状态机、导出、映射文件（M2 起加密）。"""
from docx import Document

from app.core.mapping.crypto import load_encrypted
from app.core.mapping.map_table import MapTable
from app.core.pipeline import (BatchPipeline, ST_EXPORTED, ST_FAILED, ST_SCANNED)
from app.core.recognize.engine import RecognizeEngine

_EXPORT_PW = "test-pw"


def make_docx(path, text):
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))


def build_pipeline(tmp_path):
    make_docx(tmp_path / "a.docx", "出借人张三，手机号13812345678。")
    make_docx(tmp_path / "b.docx", "借款人李四。")
    (tmp_path / "bad.docx").write_text("损坏内容", encoding="utf-8")  # 非法 docx
    table = MapTable()
    pipe = BatchPipeline(RecognizeEngine(), table)
    return pipe, table


def test_scan_failure_does_not_block(tmp_path):
    pipe, table = build_pipeline(tmp_path)
    added, _ = pipe.add_paths([str(tmp_path / "a.docx"), str(tmp_path / "bad.docx"),
                               str(tmp_path / "b.docx")])
    assert len(added) == 3
    pipe.scan_all()
    statuses = {d.name: d.status for d in pipe.docs}
    assert statuses["bad.docx"] == ST_FAILED and pipe.docs[1].error
    assert statuses["a.docx"] == statuses["b.docx"] == ST_SCANNED
    # 张三手机号进映射表，张三/李四为待确认
    assert table.get("13812345678") is not None
    assert table.get("张三").pending


def test_mark_dirty_and_export(tmp_path):
    pipe, table = build_pipeline(tmp_path)
    pipe.add_paths([str(tmp_path / "a.docx")])
    pipe.scan_all()
    table.set_pending("张三", False)  # 采纳人名

    out_dir = tmp_path / "out"
    result = pipe.export(str(out_dir), str(out_dir / "映射.json"), _EXPORT_PW)
    assert result["exported"] == ["a.docx"]
    assert pipe.docs[0].status == ST_EXPORTED
    assert pipe.mapping_exported

    # 映射变更后：已导出文件回退"已扫描"并置"需重扫"角标
    table.set_enabled("13812345678", False)
    pipe.mark_dirty()
    assert pipe.docs[0].need_rescan
    assert pipe.docs[0].status == ST_SCANNED
    assert not pipe.mapping_exported

    data = load_encrypted(out_dir / "映射.json", _EXPORT_PW)
    assert data["version"] == "1.0" and data["batch_id"]
    by_original = {m["original"]: m for m in data["mappings"]}
    assert by_original["13812345678"]["alias"] == "138****5678"
    assert by_original["张三"]["alias"] == "甲某"

    # 导出文件内容已脱敏且源文件未被改动
    from app.core.parser.docx_parser import extract_paragraphs
    exported_text = "\n".join(extract_paragraphs(str(out_dir / "a.docx")))
    assert "甲某" in exported_text and "张三" not in exported_text
    src_text = "\n".join(extract_paragraphs(str(tmp_path / "a.docx")))
    assert "张三" in src_text


def test_export_no_overwrite_same_name(tmp_path):
    pipe, _ = build_pipeline(tmp_path)
    pipe.add_paths([str(tmp_path / "a.docx")])
    pipe.scan_all()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    make_docx(out_dir / "a.docx", "已存在的同名文件")  # 已有同名文件
    result = pipe.export(str(out_dir), str(out_dir / "映射.json"), _EXPORT_PW)
    assert "a.docx" in result["exported"]
    assert (out_dir / "a_1.docx").exists()  # 自动追加序号
