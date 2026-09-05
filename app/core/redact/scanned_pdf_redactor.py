"""扫描件 PDF 脱敏：OCR 坐标回推 → 像素级抹除 → 原位写入代称。

与文字型 PDF 的差异：底层是图片，redaction 需开启 PDF_REDACT_IMAGE_PIXELS
把图片像素真正抹除；底色从原图采样（扫描件底色通常不是纯白）。
坐标估算：OCR 行框内按字宽权重（CJK≈1.0，ASCII≈0.55）比例划分子区域，
外扩 padding 保证盖严——宁可多盖，不可漏盖。
"""
from __future__ import annotations

import numpy as np
import pymupdf

from ..parser.scanned_pdf_parser import OCR_DPI, PageOcr, ocr_document

_MIN_FONTSIZE = 6.0
_PAD = 2.0          # 覆盖框外扩（PDF 点）
_ALIAS_COLOR = (0, 0, 0)


def _char_weight(ch: str) -> float:
    return 1.0 if ord(ch) > 0x2E7F else 0.55


def _sub_rect(line_rect: pymupdf.Rect, text: str, start: int, end: int) -> pymupdf.Rect:
    """按字宽权重把行框切出 [start, end) 的子区域。"""
    weights = [_char_weight(c) for c in text]
    total = sum(weights) or 1.0
    x0 = line_rect.x0 + line_rect.width * sum(weights[:start]) / total
    x1 = line_rect.x0 + line_rect.width * sum(weights[:end]) / total
    r = pymupdf.Rect(x0 - _PAD, line_rect.y0 - _PAD, x1 + _PAD, line_rect.y1 + _PAD)
    return r & line_rect  # 限制在行框内，外扩只往上下


def _sample_bg(pix_samples: np.ndarray, zoom: float, rect: pymupdf.Rect,
               img_h: int, img_w: int) -> tuple[float, float, float]:
    """从原图采样覆盖框上边缘外侧一行的中位色作为底色。"""
    y = int(rect.y0 * zoom) - 3
    y = max(0, min(y, img_h - 1))
    x0 = max(0, int(rect.x0 * zoom))
    x1 = min(img_w, int(rect.x1 * zoom))
    if x1 <= x0:
        return (1, 1, 1)
    row = pix_samples[y, x0:x1, :3].reshape(-1, 3)
    med = np.median(row, axis=0) / 255.0
    return float(med[0]), float(med[1]), float(med[2])


def _fit_fontsize(alias: str, width: float, base: float) -> float | None:
    size = base
    while size >= _MIN_FONTSIZE:
        if pymupdf.get_text_length(alias, fontname="china-s", fontsize=size) <= width:
            return size
        size -= 0.5
    return None


def _page_fragments(page_ocr: PageOcr, original: str) -> list[tuple[pymupdf.Rect, int]]:
    """在单页 OCR 文本中定位 original，返回 [(子区域, 命中内字符偏移)]（跨行拆分）。

    OCR 常向文本中插入空格/全角空格，故先做"去空白规范化"再匹配，
    通过下标映射回到原行坐标；跨行命中逐行切出子区域。
    每段 fragment 附带它在整个命中中的字符偏移，用于判断代称写在哪段。
    """
    lines = page_ocr.lines
    norm_chars: list[str] = []
    index_map: list[tuple[int, int]] = []  # 规范串下标 -> (行号, 行内字符下标)
    for li, ln in enumerate(lines):
        for ci, ch in enumerate(ln.text):
            if ch.isspace() or ch == "　":
                continue
            norm_chars.append(ch)
            index_map.append((li, ci))
    norm = "".join(norm_chars)
    needle = "".join(c for c in original if not c.isspace() and c != "　")
    if not needle or not norm:
        return []

    fragments: list[tuple[pymupdf.Rect, int]] = []
    start = 0
    while True:
        idx = norm.find(needle, start)
        if idx < 0:
            break
        end = idx + len(needle)
        ni = idx
        while ni < end:
            li = index_map[ni][0]
            run = ni
            while run < end and index_map[run][0] == li:  # 同行连续段
                run += 1
            ln = lines[li]
            s_ci = index_map[ni][1]
            e_ci = index_map[run - 1][1] + 1
            fragments.append((_sub_rect(ln.rect, ln.text, s_ci, e_ci), ni - idx))
            ni = run
        start = idx + 1
    return fragments


def _covered_by(rect: pymupdf.Rect, claimed: list[pymupdf.Rect]) -> bool:
    """rect 是否大部分已被已认领区域覆盖（>60% 面积重叠视为重复）。"""
    for c in claimed:
        inter = rect & c
        if not inter.is_empty and rect.get_area() > 0 and \
                inter.get_area() / rect.get_area() > 0.6:
            return True
    return False


def redact_document(src_path: str, dst_path: str,
                    pairs: list[tuple[str, str]]) -> tuple[int, list[str]]:
    """扫描件脱敏导出。返回 (替换处数, 溢出告警)。

    pairs 按原文长度降序处理：长命中先认领区域，短命中（多为同一
    实体的截断变体）落在已认领区域内时跳过，避免覆盖框互相冲突。
    """
    ocr_pages = ocr_document(src_path)
    zoom = OCR_DPI / 72
    count = 0
    warnings: list[str] = []
    pairs = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    doc = pymupdf.open(src_path)
    try:
        for page in doc:
            page_ocr = ocr_pages[page.number]
            if not page_ocr.lines:
                continue
            # 渲染原图用于底色采样
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = img[:, :, :3]

            has_annot = False
            claimed: list[pymupdf.Rect] = []
            for original, alias in pairs:
                fragments = _page_fragments(page_ocr, original)
                for rect, char_offset in fragments:
                    if _covered_by(rect, claimed):
                        continue
                    bg = _sample_bg(img, zoom, rect, pix.height, pix.width)
                    if char_offset == 0:
                        base = rect.height * 0.7
                        size = _fit_fontsize(alias, rect.width, base)
                        if size is None:
                            size = _MIN_FONTSIZE
                            warnings.append(
                                f"第{page.number + 1}页「{original}」→「{alias}」超出原区域，已按最小字号写入")
                        page.add_redact_annot(rect, text=alias, fontname="china-s",
                                              fontsize=size, fill=bg,
                                              text_color=_ALIAS_COLOR)
                    else:
                        # 跨行命中的后续段只抹除不写代称
                        page.add_redact_annot(rect, fill=bg)
                    claimed.append(rect)
                    count += 1
                    has_annot = True
            if has_annot:
                # 图片像素级抹除：原敏感信息真正从图像中消失
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
        doc.save(dst_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return count, warnings
