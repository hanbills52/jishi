"""回溯还原：AI 处理后的文档 + 映射文件 + 密码 → 还原出原文。

流程：
1. 解密映射文件（密码错/结构非法 → 拒绝）
2. 文档名校验（不在 doc_manifest → 警告但允许继续；哈希不同属预期，不校验）
3. 逆替换：按代称长度降序，docx 走 docx_redactor 同一替换器，txt/md 直接字符串替换
4. 生成"未还原项"报告：启用但未在文档中出现的代称清单
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..redact.docx_redactor import redact_document as docx_replace
from .crypto import load_encrypted
from .exporter import FORMAT_VERSION

RESTORABLE_EXTS = {".docx", ".txt", ".md"}


class RestoreError(Exception):
    """还原前置校验失败。"""


@dataclass
class RestoreResult:
    output_path: str
    replaced: int                 # 替换次数
    unrestored: list[dict]        # 未还原项 [{alias, original, occurrences}]
    name_warning: str = ""        # 文档名不在清单中的警告


def _validate_mapping(data: dict) -> None:
    if data.get("version") != FORMAT_VERSION:
        raise RestoreError(f"映射文件版本不支持：{data.get('version')}")
    if not isinstance(data.get("mappings"), list):
        raise RestoreError("映射文件结构非法")


def restore_document(doc_path: str, map_path: str, password: str,
                     out_dir: str) -> RestoreResult:
    """还原单个文档。返回 RestoreResult；校验失败抛 RestoreError。"""
    src = Path(doc_path)
    if src.suffix.lower() not in RESTORABLE_EXTS:
        raise RestoreError(f"仅支持还原 .docx / .txt / .md（PDF 遮盖为物理抹除，不可逆）")

    try:
        data = load_encrypted(map_path, password)
    except Exception as exc:
        raise RestoreError(str(exc)) from exc
    _validate_mapping(data)

    # 文档名校验：不在清单 → 警告但继续
    manifest_names = {m.get("file") for m in data.get("doc_manifest", [])}
    name_warning = ""
    if manifest_names and src.name not in manifest_names:
        name_warning = f"{src.name} 不在本批次文档清单中，请确认映射文件批次正确"

    # 逆替换对：启用项按代称长度降序
    pairs = [(m["alias"], m["original"]) for m in data["mappings"]
             if m.get("enabled", True)]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dst = out / f"{src.stem}_已还原{src.suffix}"

    # 未还原项以"替换前的 AI 文档"为准：代称压根没出现 = AI 删除了该代称
    replaced = 0
    if src.suffix.lower() == ".docx":
        from ..parser.docx_parser import extract_paragraphs
        source_text = "\n".join(extract_paragraphs(str(src)))
        replaced = docx_replace(str(src), str(dst), pairs)
    else:
        source_text = src.read_text(encoding="utf-8")
        text = source_text
        for alias, original in pairs:
            n = text.count(alias)
            if n:
                text = text.replace(alias, original)
                replaced += n
        dst.write_text(text, encoding="utf-8")

    unrestored = [
        {"alias": m["alias"], "original": m["original"],
         "occurrences": m.get("occurrences", 0)}
        for m in data["mappings"]
        if m.get("enabled", True) and m["alias"] not in source_text
    ]
    return RestoreResult(str(dst), replaced, unrestored, name_warning)
