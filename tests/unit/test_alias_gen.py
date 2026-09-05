"""M1-1 自查：代称生成器。"""
from app.core.mapping.alias_gen import AliasGenerator


def test_sequence_stem_branch_number():
    gen = AliasGenerator()
    aliases = [gen.next_alias("person") for _ in range(23)]
    assert aliases[0] == "甲某"
    assert aliases[9] == "癸某"      # 天干用尽
    assert aliases[10] == "子某"     # 地支开始
    assert aliases[21] == "亥某"     # 地支用尽
    assert aliases[22] == "甲某2"    # 序号模式


def test_category_suffix():
    gen = AliasGenerator()
    assert gen.next_alias("company") == "甲公司"
    assert gen.next_alias("address") == "甲地址"
    assert gen.next_alias("org") == "甲单位"
    # 各类别独立计数
    assert gen.next_alias("company") == "乙公司"


def test_reserve_and_release():
    gen = AliasGenerator()
    gen.reserve("乙某")
    assert gen.next_alias("person") == "甲某"
    assert gen.next_alias("person") == "丙某"  # 乙某被占用跳过
    gen.release("person", "乙某")
    assert gen.next_alias("person") == "乙某"  # 回收后优先复用
