"""代称生成器：按 天干 → 地支 → 序号 的顺序为各类别生成批次内唯一的代称。

人名后缀"某"，公司后缀"公司"，单位后缀"单位"，地址后缀"地址"。
序列用尽 22 个基数后追加序号：甲某2、乙某2……
"""
from __future__ import annotations

HEAVENLY_STEMS = "甲乙丙丁戊己庚辛壬癸"
EARTHLY_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
_BASE = list(HEAVENLY_STEMS) + list(EARTHLY_BRANCHES)  # 22 个基数

# 只有这几类使用序列代称，其余类别走掩码
CATEGORY_SUFFIX = {
    "person": "某",
    "company": "公司",
    "org": "单位",
    "address": "地址",
    "custom": "某",
}


def _stem_at(index: int) -> tuple[str, int]:
    """返回 (天干/地支字, 序号)。序号 1 表示不加后缀数字。"""
    if index < len(_BASE):
        return _BASE[index], 1
    cycle, pos = divmod(index - len(_BASE), len(HEAVENLY_STEMS))
    return HEAVENLY_STEMS[pos], cycle + 2  # 序号从 2 开始


class AliasGenerator:
    """批次内单例使用；支持 reserve（用户自定义代称占用）与 release（删除映射时回收）。"""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._reserved: set[str] = set()
        self._pool: dict[str, list[str]] = {}  # 回收待复用的代称

    def _build(self, category: str, index: int) -> str:
        stem, seq = _stem_at(index)
        suffix = CATEGORY_SUFFIX.get(category, "某")
        return f"{stem}{suffix}" if seq == 1 else f"{stem}{suffix}{seq}"

    def next_alias(self, category: str) -> str:
        if self._pool.get(category):
            return self._pool[category].pop(0)
        i = self._counters.get(category, 0)
        while True:
            alias = self._build(category, i)
            i += 1
            if alias not in self._reserved:
                break
        self._counters[category] = i
        self._reserved.add(alias)
        return alias

    def reserve(self, alias: str) -> None:
        self._reserved.add(alias)

    def release(self, category: str, alias: str) -> None:
        """回收代称供同类再次分配；仅删除映射时调用，启停不回收。"""
        if alias in self._reserved:
            self._reserved.discard(alias)
            self._pool.setdefault(category, []).append(alias)
