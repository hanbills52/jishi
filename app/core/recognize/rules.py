"""规则识别层：固定格式号码类敏感信息。

每条规则返回 RawHit 列表；带校验位的字段（身份证、银行卡、统一社会信用代码）
必须通过校验算法才生效，以压制假阳性。规则层命中置信度固定 0.99（直接生效）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator


@dataclass
class RawHit:
    start: int
    end: int
    text: str
    category: str
    confidence: float = 0.99
    source: str = "rule"
    judicial: bool = False  # 司法人员姓名标记（由词典层使用）


# ---------- 校验算法 ----------

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def valid_id_number(s: str) -> bool:
    """GB11643 身份证校验位验证。"""
    if len(s) != 18:
        return False
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CHECK[total % 11] == s[17].upper()


def valid_luhn(s: str) -> bool:
    """Luhn 算法，银行卡号校验。"""
    digits = [int(c) for c in s]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"  # 31 个字符，无 I/O/S/V/Z
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def valid_uscc(s: str) -> bool:
    """统一社会信用代码第 18 位校验。"""
    if len(s) != 18:
        return False
    try:
        total = sum(_USCC_CHARS.index(s[i]) * _USCC_WEIGHTS[i] for i in range(17))
    except ValueError:
        return False
    check = (31 - total % 31) % 31
    return _USCC_CHARS[check] == s[17]


# ---------- 规则定义 ----------

_ID_RE = re.compile(r"(?<![0-9Xx])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9Xx])")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_BANKCARD_RE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_PASSPORT_RE = re.compile(r"(?<![A-Za-z0-9])[EGeg]\d{8}(?![A-Za-z0-9])")
_PERMIT_RE = re.compile(r"(?<![A-Za-z0-9])[HMhm]\d{8,10}(?![A-Za-z0-9])")
# 边界断言仅按 ASCII 判定：Python \w 含 CJK，"邮箱lisi@x.com" 中"箱"会误触发阻断
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9_.])")
_USCC_RE = re.compile(r"(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-Z])")
_PLATE_RE = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-HJ-NP-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9挂学警港澳]")
_WECHAT_RE = re.compile(r"(?:微信号?|WeChat)[:：\s]*([a-zA-Z][a-zA-Z0-9_-]{5,19})")
_SOCIAL_RE = re.compile(r"(?:社保(?:号|编号|卡号)?|社会保险号)[:：\s]*(\d{9,18})")
_FUND_RE = re.compile(r"(?:公积金(?:账号|账户|编号)?)[:：\s]*(\d{9,18})")
_SECURITIES_RE = re.compile(r"(?:证券账户|资金账号|股东账户)[:：\s]*([A-Za-z0-9]{6,20})")
_BIRTH_RE = re.compile(r"(?:出生(?:日期|年月)?|生于)[:：\s]*(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2})")
# 尾随语境："……，1985年3月7日出生"（日期在"出生"之前；"日"已被日期本体消费）
_BIRTH_TAIL_RE = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2})(?=出生)")


def _hits(regex: re.Pattern, category: str, text: str,
          validator: Callable[[str], bool] | None = None,
          group: int = 0) -> Iterator[RawHit]:
    for m in regex.finditer(text):
        value = m.group(group)
        if validator and not validator(value):
            continue
        start, end = m.span(group)
        yield RawHit(start, end, value, category)


def scan(text: str) -> list[RawHit]:
    """对单段文本跑全部号码类规则。"""
    hits: list[RawHit] = []
    hits += list(_hits(_ID_RE, "id_number", text, valid_id_number))
    hits += list(_hits(_PHONE_RE, "phone", text))
    hits += list(_hits(_BANKCARD_RE, "bank_card", text, valid_luhn))
    hits += list(_hits(_PASSPORT_RE, "passport", text))
    hits += list(_hits(_PERMIT_RE, "permit_hk_macau", text))
    hits += list(_hits(_EMAIL_RE, "email", text))
    hits += list(_hits(_USCC_RE, "uscc", text, valid_uscc))
    hits += list(_hits(_PLATE_RE, "plate", text))
    hits += list(_hits(_WECHAT_RE, "wechat", text, group=1))
    hits += list(_hits(_SOCIAL_RE, "social_security", text, group=1))
    hits += list(_hits(_FUND_RE, "housing_fund", text, group=1))
    hits += list(_hits(_SECURITIES_RE, "securities_account", text, group=1))
    hits += list(_hits(_BIRTH_RE, "birth_date", text, group=1))
    hits += list(_hits(_BIRTH_TAIL_RE, "birth_date", text, group=1))
    return hits
