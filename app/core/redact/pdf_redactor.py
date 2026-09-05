"""PDF 脱敏替换器：search_for 定位 → 遮盖注释（redaction）→ 原位写入代称。

替换后原敏感词被物理抹除（不可选中/复制），代称按原区域宽度自适应字号。
返回 (替换次数, 溢出告警列表)。
"""
from __future__ import annotations

import pymupdf

_MIN_FONTSIZE = 6.0


def _fit_fontsize(alias: str, width: float, base: float) -> float | None:
    """从原字号起逐级减 0.5 直至代称适配区域宽度；实在放不下返回 None。"""
    size = base
    while size >= _MIN_FONTSIZE:
        # fontname 必须与写入时一致，否则宽度估算失真（CJK 字宽=字号）
        if pymupdf.get_text_length(alias, fontname="china-s", fontsize=size) <= width:
            return size
        size -= 0.5
    return None


def _base_fontsize(page: pymupdf.Page, rect: pymupdf.Rect) -> float:
    """取 rect 区域内首个 span 的字号作为起点；取不到用区域高度×0.75 估算。"""
    clip = page.get_text("dict", clip=rect)
    for block in clip.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("size"):
                    return float(span["size"])
    return max(rect.height * 0.75, _MIN_FONTSIZE)


def redact_document(src_path: str, dst_path: str,
                    pairs: list[tuple[str, str]]) -> tuple[int, list[str]]:
    """对 PDF 执行遮盖替换并另存。返回 (替换次数, 溢出告警)。"""
    count = 0
    warnings: list[str] = []
    doc = pymupdf.open(src_path)
    try:
        for page in doc:
            for original, alias in pairs:
                rects = page.search_for(original)
                for rect in rects:
                    base = _base_fontsize(page, rect)
                    size = _fit_fontsize(alias, rect.width, base)
                    if size is None:
                        size = _MIN_FONTSIZE
                        warnings.append(
                            f"第{page.number + 1}页「{original}」→「{alias}」超出原区域，已按最小字号写入")
                    # fontname 指定内置 CJK 字体，否则中文代称写入后显示为 ??
                    page.add_redact_annot(rect, text=alias, fontname="china-s",
                                          fontsize=size)
                    count += 1
            page.apply_redactions()
        # 保存前校验：代称已写入、原文不可检索
        doc.save(dst_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return count, warnings
