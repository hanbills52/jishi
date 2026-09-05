"""docx 原位替换器：跨 run 合并匹配、按 run 边界拆分替换，保留原样式。

算法（与实施方案 M1-6 一致）：
1. 拼接段落全部 run 文本得到 full
2. 按 (原文, 代称) 列表（已按原文长度降序）在 full 中定位替换区间，区间互不重叠
3. 逐 run 重建文本：代称写入区间起始 run，被覆盖的其余 run 置空
   （run 节点保留，仅清空文本，样式 rPr 不受影响）
"""
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

from ..parser.docx_parser import iter_text_parts, iter_paragraph_elements


def _find_spans(full: str, pairs: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    """定位替换区间 (start, end, alias)，长词优先且互不重叠。"""
    spans: list[tuple[int, int, str]] = []
    occupied = bytearray(len(full))
    for original, alias in pairs:
        pos = 0
        while True:
            idx = full.find(original, pos)
            if idx < 0:
                break
            end = idx + len(original)
            if not any(occupied[idx:end]):
                spans.append((idx, end, alias))
                occupied[idx:end] = b"\x01" * (end - idx)
            pos = idx + 1
    return spans


def _replace_in_paragraph(p_el, pairs: list[tuple[str, str]]) -> int:
    """在单个 w:p 元素内执行替换，返回替换次数。"""
    run_nodes = []
    for r in p_el.iter(qn("w:r")):
        ts = [t for t in r.iter(qn("w:t"))]
        if ts:
            run_nodes.append(ts)
    if not run_nodes:
        return 0

    texts = ["".join(t.text or "" for t in ts) for ts in run_nodes]
    full = "".join(texts)
    if not full:
        return 0

    spans = _find_spans(full, pairs)
    if not spans:
        return 0
    spans.sort()

    replaced = 0
    pos = 0
    for ts, old_text in zip(run_nodes, texts):
        run_start, run_end = pos, pos + len(old_text)
        pos = run_end
        pieces: list[str] = []
        cursor = run_start
        for s, e, alias in spans:
            if e <= run_start or s >= run_end:
                continue
            if s > cursor:
                pieces.append(full[cursor:s])
            if run_start <= s < run_end:
                pieces.append(alias)
                replaced += 1
            cursor = max(cursor, min(e, run_end))
        if cursor < run_end:
            pieces.append(full[cursor:run_end])
        new_text = "".join(pieces)
        if new_text != old_text:
            ts[0].text = new_text
            ts[0].set(qn("xml:space"), "preserve")  # 保留首尾空格
            for t in ts[1:]:
                t.text = ""
    return replaced


def redact_document(src_path: str, dst_path: str, pairs: list[tuple[str, str]]) -> int:
    """对文档执行替换并另存为 dst_path，返回总替换次数。"""
    doc = Document(src_path)
    count = 0
    for part in iter_text_parts(doc.part.package):
        for p_el in iter_paragraph_elements(part):
            count += _replace_in_paragraph(p_el, pairs)
    doc.save(dst_path)
    return count
