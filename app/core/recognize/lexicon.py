"""词典/上下文识别层：人名、公司、地址、民族。

人名命中置信度 0.85（M1 阶段进入待确认组，由人工采纳）；
公司 0.8、地址 0.7；民族 0.9。所有命中先经司法停用词过滤。
"""
from __future__ import annotations

import re
from pathlib import Path

from .rules import RawHit

_LEXICON_DIR = Path(__file__).resolve().parent.parent.parent / "resources" / "lexicons"


def _load(directory: Path, name: str) -> list[str]:
    path = directory / name
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# 姓名后允许出现的边界字符（避免把"原告认为"的"认为"吞进人名）
_NAME_BOUNDARY = r"，,。；;：:、\s　\n\r（(【\-—~·男为女住身公民汉族"
# 不能以这些机构词结尾（词级匹配），防止误吞机构词
_NAME_BAD_SUFFIX = ("院", "局", "公司", "所", "会", "部", "庭", "处", "厅",
                    "司", "署", "中心", "集团", "银行", "学校")
# 地址/公司命中前不允许出现的前置动词/介词/助词（负向后行），
# 防止"其曾在深圳市…"把"其曾在"吞进地址、"确认北京…公司"把"确认"吞进公司
_ADDR_BAD_PREFIX = ("其", "曾", "在", "于", "由", "向", "从", "到", "及", "和", "与",
                    "被", "为", "是", "有", "称", "住", "对", "将", "该", "此", "确认",
                    "认为", "现", "经", "并", "且", "或", "因", "按", "依", "据", "至")
_COMPANY_BAD_PREFIX = _ADDR_BAD_PREFIX


class LexiconScanner:
    def __init__(self, lexicon_dir: Path | None = None) -> None:
        # 实例级词典目录，不修改全局，避免测试间/实例间互相污染
        directory = Path(lexicon_dir) if lexicon_dir is not None else _LEXICON_DIR
        self.surnames: frozenset[str] = frozenset(_load(directory, "surnames.txt"))
        self.ethnicities: frozenset[str] = frozenset(_load(directory, "ethnicities.txt"))
        self.stopwords: frozenset[str] = frozenset(_load(directory, "judicial_stopwords.txt"))
        prompt_words = sorted(_load(directory, "prompt_words.txt"), key=len, reverse=True)
        titles = sorted(_load(directory, "titles.txt"), key=len, reverse=True)

        prompt_alt = "|".join(re.escape(w) for w in prompt_words)
        title_alt = "|".join(re.escape(w) for w in titles)
        # 公司/地址命中前缀剥除：避免"原告北京某公司"把"原告"吞入
        self._prefix_words = tuple(prompt_words + titles)
        # 上下文提示词后的 2~4 字人名；允许提示词与姓名之间夹带括号角色标注
        # 如"借款人（乙方）：李四"（首字须命中姓氏表，后续在代码中校验）
        self._person_re = re.compile(
            rf"(?:{prompt_alt})[:：\s　]*(?:（[^）]{{1,6}}）[:：\s　]*)?"
            rf"([一-龥·]{{2,4}})(?=[{_NAME_BOUNDARY}]|$)"
        )
        # 司法职务后的人名（单独标记 judicial）
        self._judicial_re = re.compile(
            rf"(?:{title_alt})[:：\s　]*([一-龥·]{{2,4}})(?=[{_NAME_BOUNDARY}]|$)"
        )
        # "某某，男/女" 称谓模式
        self._gender_re = re.compile(r"([一-龥·]{2,4})，(?:男|女)[，,。\s]")
        self._company_re = re.compile(
            r"[一-龥A-Za-z0-9（）()]{2,40}?"
            r"(?:有限责任公司|股份有限公司|有限公司|律师事务所|会计师事务所|事务所|银行|集团|分公司)"
        )
        # 地址：容忍段间空白（OCR/排版空格），扩充关键字（楼/层/座/幢/房）
        _S = r"[\s　]*"
        self._address_re = re.compile(
            rf"(?:[一-龥]{{2,10}}{_S}(?:省|市|自治区|区|县|镇|乡|州){_S}){{0,3}}"
            rf"[一-龥0-9]{{1,20}}{_S}"
            rf"(?:路|街|巷|大道|大街|胡同|弄|里|号院|号楼|小区|大厦|广场|园|栋|幢|座|单元|室|楼|层|房)"
            rf"(?:{_S}[一-龥0-9]{{1,8}}(?:号|楼|层|室|栋|幢|座|单元|房)){{0,4}}"
        )
        # 行政区划锚定的地址：以省市词开头、后接 4~25 字（无关键字的长地址兜底），
        # 置信度 0.65 进待确认，由人工把关，机构后缀与停用词拦截
        regions = sorted(_load(directory, "regions.txt"), key=len, reverse=True)
        self.custom_names = _load(directory, "custom_names.txt")
        if regions:
            region_alt = "|".join(re.escape(r) for r in regions)
            self._region_addr_re = re.compile(
                rf"(?:{region_alt}){_S}[一-龥0-9]{{4,25}}(?=[，,。；;：:、\s　\n\r）)]|$)"
            )
        else:
            self._region_addr_re = None
        # 机构后缀（地址不能以这些结尾）
        self._addr_bad_suffix = ("院", "局", "公司", "所", "会", "部", "庭", "处", "厅",
                                 "司", "署", "中心", "集团", "银行", "学校", "认为", "申请")

    def _is_stopword_hit(self, text: str, start: int, end: int) -> bool:
        """命中片段若属于某个司法停用词的一部分则过滤。"""
        window = text[max(0, start - 4): end + 4]
        return any(sw in window and text[start:end] in sw or sw in text[start:end]
                   for sw in self.stopwords if sw in window)

    @staticmethod
    def _strip_prefix(val: str, start: int, prefixes) -> tuple[str, int]:
        """循环剥除命中开头匹配到的提示词前缀，返回 (新值, 新起点)。"""
        changed = True
        while changed:
            changed = False
            for pw in prefixes:
                if val.startswith(pw) and len(val) > len(pw):
                    val = val[len(pw):]
                    start += len(pw)
                    changed = True
        return val, start

    @staticmethod
    def _strip_leading_bad(val: str, start: int, bad_prefixes) -> tuple[str, int]:
        """剥除命中开头的前置动词/介词/助词（按长度从长到短逐个尝试）。"""
        # 先长后短，确保"确认"先于"确"被剥掉
        ordered = sorted(bad_prefixes, key=len, reverse=True)
        changed = True
        while changed:
            changed = False
            for bp in ordered:
                if val.startswith(bp) and len(val) > len(bp):
                    val = val[len(bp):]
                    start += len(bp)
                    changed = True
        return val, start

    def _valid_name(self, name: str) -> bool:
        if name in self.stopwords:
            return False
        if any(name.endswith(w) for w in _NAME_BAD_SUFFIX):
            return False
        # 复姓优先，其次单姓
        return any(name.startswith(s) for s in self.surnames)

    def scan(self, text: str) -> list[RawHit]:
        hits: list[RawHit] = []
        seen: set[tuple[int, int]] = set()

        def add(m: re.Match, name: str, category: str, conf: float, judicial: bool = False) -> None:
            start = m.start(1)
            end = start + len(name)
            key = (start, end)
            if key in seen or not self._valid_name(name):
                return
            if self._is_stopword_hit(text, start, end):
                return
            seen.add(key)
            hits.append(RawHit(start, end, name, category, conf, source="lexicon", judicial=judicial))

        for m in self._judicial_re.finditer(text):
            add(m, m.group(1), "person", 0.85, judicial=True)
        for m in self._person_re.finditer(text):
            add(m, m.group(1), "person", 0.85)
        for m in self._gender_re.finditer(text):
            add(m, m.group(1), "person", 0.85)

        for m in self._company_re.finditer(text):
            val = m.group(0)
            start = m.start()
            val, start = self._strip_prefix(val, start, self._prefix_words)
            val, start = self._strip_leading_bad(val, start, _COMPANY_BAD_PREFIX)
            if len(val) < 4 or any(sw in val for sw in self.stopwords):
                continue
            hits.append(RawHit(start, start + len(val), val, "company", 0.8, source="lexicon"))

        for m in self._address_re.finditer(text):
            val = m.group(0)
            start = m.start()
            val, start = self._strip_prefix(val, start, ("住址", "位于", "住"))
            val, start = self._strip_leading_bad(val, start, _ADDR_BAD_PREFIX)
            if len(val.replace(" ", "").replace("　", "")) < 6:
                continue
            hits.append(RawHit(start, start + len(val), val, "address", 0.7, source="lexicon"))

        if self._region_addr_re is not None:
            for m in self._region_addr_re.finditer(text):
                val = m.group(0)
                start = m.start()
                val, start = self._strip_prefix(val, start, self._prefix_words)
                val, start = self._strip_leading_bad(val, start, _ADDR_BAD_PREFIX)
                if val.endswith(self._addr_bad_suffix):
                    continue
                if any(sw in val for sw in self.stopwords):
                    continue
                hits.append(RawHit(start, start + len(val), val, "address", 0.65,
                                   source="lexicon"))

        for name in self.custom_names:  # 用户学习库中的人名，0.9 进待确认
            start = 0
            while True:
                idx = text.find(name, start)
                if idx < 0:
                    break
                if not self._is_stopword_hit(text, idx, idx + len(name)):
                    hits.append(RawHit(idx, idx + len(name), name, "person", 0.9,
                                       source="custom"))
                start = idx + len(name)

        for eth in self.ethnicities:
            start = 0
            while True:
                idx = text.find(eth, start)
                if idx < 0:
                    break
                hits.append(RawHit(idx, idx + len(eth), eth, "ethnicity", 0.9, source="lexicon"))
                start = idx + len(eth)
        return hits
