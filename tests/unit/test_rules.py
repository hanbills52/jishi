"""M1-2 自查：规则识别层（正样本命中 + 负样本过滤）。"""
from app.core.recognize import rules
from app.core.recognize.rules import (_ID_CHECK, _ID_WEIGHTS, _USCC_CHARS,
                                      _USCC_WEIGHTS, valid_luhn)


def make_id() -> str:
    base = "11010519900307755"  # 6地址码+8出生日期+3顺序码
    check = _ID_CHECK[sum(int(c) * w for c, w in zip(base, _ID_WEIGHTS)) % 11]
    return base + check


def make_bank_card() -> str:
    prefix = "622202100111234"  # 15 位，补一位使满足 Luhn
    for d in range(10):
        if valid_luhn(prefix + str(d)):
            return prefix + str(d)
    raise AssertionError("无法构造 Luhn 号码")


def make_uscc() -> str:
    body = "91" + "110108" + "00000000" + "0"  # 2+6+9 = 17 位主体
    total = sum(_USCC_CHARS.index(c) * w for c, w in zip(body, _USCC_WEIGHTS))
    return body + _USCC_CHARS[(31 - total % 31) % 31]


def texts_of(hits):
    return {(h.category, h.text) for h in hits}


def test_id_number():
    idn = make_id()
    hits = rules.scan(f"身份证号：{idn}")
    assert ("id_number", idn) in texts_of(hits)


def test_id_number_bad_checksum_rejected():
    bad = make_id()[:-1] + ("0" if make_id()[-1] != "0" else "1")
    assert ("id_number", bad) not in texts_of(rules.scan(f"身份证号：{bad}"))


def test_phone():
    assert ("phone", "13812345678") in texts_of(rules.scan("手机13812345678。"))
    assert ("phone", "12812345678") not in texts_of(rules.scan("号码12812345678。"))


def test_bank_card():
    card = make_bank_card()
    assert ("bank_card", card) in texts_of(rules.scan(f"卡号{card}"))
    bad = card[:-1] + ("0" if card[-1] != "0" else "1")
    assert ("bank_card", bad) not in texts_of(rules.scan(f"卡号{bad}"))


def test_email_and_wechat():
    assert ("email", "zhang.san@example.com") in texts_of(rules.scan("邮箱 zhang.san@example.com "))
    assert ("wechat", "wxid_abc123") in texts_of(rules.scan("微信号：wxid_abc123"))


def test_uscc():
    code = make_uscc()
    assert ("uscc", code) in texts_of(rules.scan(f"统一社会信用代码：{code}"))


def test_plate_and_birth():
    assert ("plate", "京A12345") in texts_of(rules.scan("车牌京A12345 "))
    assert ("birth_date", "1985年3月7日") in texts_of(rules.scan("出生于1985年3月7日"))
    # 尾随语境："……，1985年3月7日出生"
    assert ("birth_date", "1985年3月7日") in texts_of(rules.scan("男，1985年3月7日出生，住北京市"))


def test_social_and_fund_and_securities():
    assert ("social_security", "123456789") in texts_of(rules.scan("社保号：123456789"))
    assert ("housing_fund", "987654321") in texts_of(rules.scan("公积金账号：987654321"))
    assert ("securities_account", "A123456789") in texts_of(rules.scan("证券账户：A123456789"))
