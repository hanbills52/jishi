"""识别引擎：规则层 + 词典层 + （M3 接入的 NER 层）+ 仲裁器。

仲裁规则：
- 重叠区间按层优先级取舍：规则层 > 词典层 > NER 层，同层取更长区间
- 置信度 >= AUTO_THRESHOLD 直接生效（auto）；>= PENDING_THRESHOLD 进待确认（pending，不生效）；其余丢弃
- 司法人员姓名：mask_judicial=False 时丢弃（默认保留不脱敏）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import rules
from .lexicon import LexiconScanner
from .rules import RawHit

AUTO_THRESHOLD = 0.90
PENDING_THRESHOLD = 0.60

_LAYER_PRIORITY = {"rule": 0, "lexicon": 1, "custom": 1, "ner": 2}

# 类别冲突时的固定优先级（身份证优先于银行卡等）
_CATEGORY_PRIORITY = {
    "id_number": 0, "uscc": 1, "phone": 2, "bank_card": 3,
}

# 实体类类别（参与相邻碎片合并）；规则类类别（身份证/手机号等）不参与合并
_ENTITY_CATS = {"person", "company", "org", "address"}
# 合并后类别的选取优先级：取碎片中较长者的类别，等长时按此序
_MERGE_CAT_PRIORITY = {"company": 0, "org": 1, "address": 2, "person": 3}
# 合并碎片总长度上限，防止跨句链式蔓延
_MERGE_MAX_LEN = 60


@dataclass
class Finding:
    text: str
    category: str
    start: int          # 在所属段落内的偏移（仅供定位参考）
    end: int
    para_index: int     # 所属段落序号
    confidence: float
    source: str
    status: str         # auto | pending
    judicial: bool = False


@dataclass
class ScanSettings:
    mask_judicial: bool = False  # 司法人员（法官/书记员等）姓名是否脱敏
    enable_ner: bool = False     # 是否启用 NER 模型识别层（误报较多，默认关闭）


class RecognizeEngine:
    def __init__(self, lexicon: LexiconScanner | None = None,
                 settings: ScanSettings | None = None) -> None:
        self.lexicon = lexicon or LexiconScanner()
        self.settings = settings or ScanSettings()
        self._ner = None  # M3 接入：callable(text) -> list[RawHit]

    def set_ner_provider(self, provider) -> None:
        self._ner = provider

    def scan_paragraph(self, text: str, para_index: int) -> list[Finding]:
        hits: list[RawHit] = rules.scan(text) + self.lexicon.scan(text)
        if self._ner is not None and self.settings.enable_ner:
            hits += self._ner(text)
        merged = self._arbitrate(hits)
        findings: list[Finding] = []
        for h in merged:
            if h.judicial and not self.settings.mask_judicial:
                continue
            status = "auto" if h.confidence >= AUTO_THRESHOLD else (
                "pending" if h.confidence >= PENDING_THRESHOLD else None)
            if status is None:
                continue
            findings.append(Finding(h.text, h.category, h.start, h.end, para_index,
                                    h.confidence, h.source, status, h.judicial))
        return findings

    def scan_paragraphs(self, paragraphs: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        for i, para in enumerate(paragraphs):
            if para and para.strip():
                findings += self.scan_paragraph(para, i)
        return findings

    @staticmethod
    def _merge_fragments(hits: list[RawHit]) -> list[RawHit]:
        """合并实体类的相邻/包含碎片：同一实体被切成"莲花街|道|办事处"时
        还原为一个完整命中，避免碎片各占一个代称。规则类命中原样保留。"""
        rules_hits = [h for h in hits if h.category not in _ENTITY_CATS]
        ents = sorted((h for h in hits if h.category in _ENTITY_CATS),
                      key=lambda h: (h.start, -(h.end - h.start)))
        merged: list[RawHit] = []
        for h in ents:
            if merged and h.start <= merged[-1].end:  # 相邻或重叠才可能合并
                top = merged[-1]
                new_end = max(top.end, h.end)
                if new_end - top.start <= _MERGE_MAX_LEN:
                    if h.end > top.end:  # 延展尾部（被包含的碎片 end<=top.end 自动跳过）
                        top_len, h_len = top.end - top.start, h.end - h.start
                        overlap = top.end - h.start
                        top.text += h.text[overlap:]
                        top.end = new_end
                        if h_len > top_len or (
                                h_len == top_len and _MERGE_CAT_PRIORITY.get(h.category, 9)
                                < _MERGE_CAT_PRIORITY.get(top.category, 9)):
                            top.category = h.category
                    continue
            merged.append(RawHit(h.start, h.end, h.text, h.category,
                                 h.confidence, h.source, h.judicial))
        return rules_hits + merged

    @staticmethod
    def _arbitrate(hits: list[RawHit]) -> list[RawHit]:
        """实体碎片合并后，贪心选取互不重叠的命中（规则层绝对优先）。"""
        def sort_key(h: RawHit):
            return (h.start, _LAYER_PRIORITY.get(h.source, 9),
                    _CATEGORY_PRIORITY.get(h.category, 50), -(h.end - h.start))

        accepted: list[RawHit] = []
        for h in sorted(RecognizeEngine._merge_fragments(hits), key=sort_key):
            if all(h.end <= a.start or h.start >= a.end for a in accepted):
                accepted.append(h)
        return accepted
