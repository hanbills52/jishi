"""全局映射表：批次内单例，以原文为键，保证同批次同主体代称唯一。

- 序列代称类（人名/公司/单位/地址/自定义）：由 AliasGenerator 分配
- 掩码类（号码、邮箱、出生日期等）：按类别默认掩码规则生成
- 启停不回收代称；删除才回收
- 支持同名主体按文件拆分（split_entity）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .alias_gen import AliasGenerator

# 序列代称类类别
ALIAS_CATEGORIES = {"person", "company", "org", "address", "custom"}
# 掩码类各默认保留位数：(头部保留, 尾部保留)
MASK_KEEP = {
    "id_number": (3, 4), "phone": (3, 4), "bank_card": (4, 4),
    "passport": (2, 2), "permit_hk_macau": (2, 2), "social_security": (2, 2),
    "housing_fund": (2, 2), "uscc": (2, 2), "securities_account": (2, 2),
}

CATEGORY_LABELS = {
    "person": "人名", "company": "公司", "org": "单位", "address": "地址",
    "custom": "自定义", "id_number": "身份证号", "phone": "手机号",
    "bank_card": "银行卡号", "passport": "护照号", "permit_hk_macau": "港澳通行证",
    "social_security": "社保编号", "housing_fund": "公积金账号", "uscc": "统一社会信用代码",
    "email": "电子邮箱", "wechat": "微信号", "plate": "车牌号",
    "birth_date": "出生日期", "ethnicity": "民族", "securities_account": "证券账户",
}


def mask_value(text: str, category: str) -> str:
    """按类别默认规则生成掩码结果。"""
    if category == "email":
        return text[0] + "***@***"
    if category == "wechat":
        return "***"
    if category == "ethnicity":
        return "某族"
    if category == "plate":
        return text[:2] + "*" * (len(text) - 3) + text[-1]
    if category == "birth_date":
        return re.sub(r"(\d{4})年\d{1,2}月\d{1,2}日", r"\1年**月**日", text) \
            if "年" in text else re.sub(r"(\d{4})([-/])\d{1,2}\2\d{1,2}", r"\1\2**\2**", text)
    head, tail = MASK_KEEP.get(category, (2, 2))
    if len(text) <= head + tail:
        return text[0] + "*" * (len(text) - 1)
    return text[:head] + "*" * (len(text) - head - tail) + text[-tail:]


@dataclass
class MappingItem:
    id: int
    original: str
    category: str
    alias: str
    occurrences: int = 0
    enabled: bool = True
    source: str = "rule"          # rule | lexicon | ner | custom
    confidence: float = 0.99
    pending: bool = False          # 待确认项默认不生效
    files: set[str] | None = None  # None 表示作用于全部文件；拆分主体时为文件子集

    def applies_to(self, file_name: str) -> bool:
        return self.files is None or file_name in self.files


class MapTable:
    def __init__(self, alias_gen: AliasGenerator | None = None) -> None:
        self._items: dict[str, MappingItem] = {}
        self.alias_gen = alias_gen or AliasGenerator()
        self._next_id = 1

    # ---------- 增删改 ----------

    def add_finding(self, original: str, category: str, source: str,
                    confidence: float, pending: bool, file_name: str) -> MappingItem:
        item = self._items.get(original)
        if item is None:
            alias = (self.alias_gen.next_alias(category)
                     if category in ALIAS_CATEGORIES else mask_value(original, category))
            item = MappingItem(self._next_id, original, category, alias,
                               source=source, confidence=confidence,
                               pending=pending, files=set())
            self._next_id += 1
            self._items[original] = item
        item.occurrences += 1
        if item.files is not None:
            item.files.add(file_name)
        return item

    def add_custom(self, original: str, alias: str | None = None) -> MappingItem:
        original = original.strip()
        if not original:
            raise ValueError("敏感词不能为空")
        if original in self._items:
            item = self._items[original]
            item.enabled = True
            item.pending = False
            return item
        if alias:
            self.alias_gen.reserve(alias)
        else:
            alias = self.alias_gen.next_alias("custom")
        item = MappingItem(self._next_id, original, "custom", alias,
                           source="custom", confidence=1.0, files=None)
        self._next_id += 1
        self._items[original] = item
        return item

    def set_enabled(self, original: str, enabled: bool) -> None:
        """启停不回收代称。"""
        self._items[original].enabled = enabled

    def set_pending(self, original: str, pending: bool) -> None:
        item = self._items[original]
        item.pending = pending
        if not pending:
            item.enabled = True

    def remove(self, original: str) -> None:
        """删除并回收代称。"""
        item = self._items.pop(original, None)
        if item and item.category in ALIAS_CATEGORIES:
            self.alias_gen.release(item.category, item.alias)

    def merge_into(self, source: str, target: str) -> None:
        """别名分片合并：source 项改用 target 的代称（原文保留，文档中仍会被替换），
        回收 source 原代称；pending 状态跟随 target。用于 OCR 错别字产生的同主体分片。"""
        src, tgt = self._items.get(source), self._items.get(target)
        if src is None or tgt is None or source == target:
            return
        if src.category in ALIAS_CATEGORIES and src.alias != tgt.alias:
            self.alias_gen.release(src.category, src.alias)
        src.alias = tgt.alias
        src.pending = tgt.pending

    def split_entity(self, original: str, files: set[str]) -> MappingItem | None:
        """同名主体拆分：把指定文件的该原文拆为独立映射项，分配新代称。"""
        item = self._items.get(original)
        if item is None or item.files is None or not files:
            return None
        if not files.issubset(item.files) or files == item.files:
            return None
        item.files -= files
        new_alias = (self.alias_gen.next_alias(item.category)
                     if item.category in ALIAS_CATEGORIES else item.alias)
        new_item = MappingItem(self._next_id, original, item.category, new_alias,
                               source=item.source, confidence=item.confidence,
                               pending=item.pending, files=set(files))
        self._next_id += 1
        self._items[f"{original}#split#{new_alias}"] = new_item
        return new_item

    # ---------- 查询 ----------

    def items(self) -> list[MappingItem]:
        return list(self._items.values())

    def get(self, original: str) -> MappingItem | None:
        return self._items.get(original)

    def effective_pairs(self, file_name: str) -> list[tuple[str, str]]:
        """某文件实际生效的 (原文, 代称) 列表，按原文长度降序（防短词吞长词）。"""
        pairs = [(it.original, it.alias) for it in self._items.values()
                 if it.enabled and not it.pending and it.applies_to(file_name)]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)
        return pairs

    def clear(self) -> None:
        self._items.clear()
        self.alias_gen = AliasGenerator()
        self._next_id = 1
