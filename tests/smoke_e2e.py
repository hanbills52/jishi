"""端到端冒烟：M1 全流程（导入→扫描→采纳→导出）+ 界面可实例化校验。

运行：.venv\\Scripts\\python.exe tests\\smoke_e2e.py
（文件名不以 test_ 开头，pytest 不会自动收集）
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from docx import Document

from app.core.mapping.map_table import MapTable
from app.core.pipeline import BatchPipeline
from app.core.recognize.engine import RecognizeEngine
from app.core.recognize.rules import _ID_CHECK, _ID_WEIGHTS


def make_id() -> str:
    base = "11010519900307755"
    return base + _ID_CHECK[sum(int(c) * w for c, w in zip(base, _ID_WEIGHTS)) % 11]


def main() -> None:
    idn = make_id()
    contract = (
        "借款合同\n"
        f"出借人（甲方）：张三，男，汉族，1985年3月7日出生，"
        f"住北京市海淀区中关村大街28号院3号楼502室，身份证号{idn}。\n"
        "借款人（乙方）：李四，手机号13812345678，微信号：wxid_lisi88，"
        "邮箱lisi@example.com。\n"
        "丙方（保证人）：北京恒信担保有限公司，统一社会信用代码见附页。\n"
        "审判长：王五\n"  # 司法人员默认不脱敏
    )

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "借款合同.docx"
        doc = Document()
        for line in contract.split("\n"):
            doc.add_paragraph(line)
        doc.save(str(src))

        table = MapTable()
        pipe = BatchPipeline(RecognizeEngine(), table)
        added, rejected = pipe.add_paths([str(src)])
        assert added and not rejected, rejected
        pipe.scan_all()

        print("== 扫描结果 ==")
        for it in table.items():
            print(f"  [{it.category}]{'(待确认)' if it.pending else ''} "
                  f"{it.original} -> {it.alias} ×{it.occurrences}")

        # 采纳全部待确认项（模拟用户在面板点击"采纳"）
        for it in table.items():
            if it.pending:
                table.set_pending(it.original, False)

        out_dir = Path(tmp) / "脱敏输出"
        result = pipe.export(str(out_dir), str(out_dir / "映射.json"), "smoke-pw")
        print("== 导出 ==", result["exported"], "失败:", result["failed"])

        from app.core.parser.docx_parser import extract_paragraphs
        text = "\n".join(extract_paragraphs(str(out_dir / "借款合同.docx")))
        print("== 脱敏后文本 ==")
        print(text)

        # 关键断言
        assert "张三" not in text and "甲某" in text
        assert "李四" not in text and "乙某" in text      # 带括号角色标注的人名
        assert "汉族" not in text and "某族" in text
        assert "1985年3月7日" not in text                # 出生日期（尾随语境）
        assert "住北京市" not in text                    # 地址前缀"住"已剥除
        assert "lisi@example.com" not in text            # 邮箱（CJK 边界场景）
        assert idn not in text and "110***********" in text
        assert "13812345678" not in text and "138****5678" in text
        assert "北京恒信担保有限公司" not in text
        assert "王五" in text  # 司法人员默认保留
        # 映射文件已加密：直接读是密文外壳，解密后结构正确
        from app.core.mapping.crypto import load_encrypted
        envelope = json.loads((out_dir / "映射.json").read_text(encoding="utf-8"))
        assert envelope["enc"] == "AES-256-GCM"
        mapping = load_encrypted(out_dir / "映射.json", "smoke-pw")
        assert mapping["version"] == "1.0" and mapping["mappings"]

        # 回溯：模拟 AI 修改后还原
        from app.core.mapping.restorer import restore_document
        restore_dir = Path(tmp) / "还原"
        restored = restore_document(str(out_dir / "借款合同.docx"),
                                    str(out_dir / "映射.json"), "smoke-pw",
                                    str(restore_dir))
        restored_text = "\n".join(extract_paragraphs(restored.output_path))
        assert "张三" in restored_text and "甲某" not in restored_text

    # 界面可实例化（离屏模式）
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    qt_app = QApplication([])
    window = MainWindow()
    assert window.windowTitle().startswith("基石")
    print("== UI 实例化 OK ==")
    print("冒烟测试全部通过")


if __name__ == "__main__":
    main()
