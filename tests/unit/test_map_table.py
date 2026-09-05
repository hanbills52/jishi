"""M1-5 自查：全局映射表。"""
from app.core.mapping.map_table import MapTable, mask_value


def add_person(table, name, file_name="a.docx"):
    return table.add_finding(name, "person", "lexicon", 0.85, pending=False, file_name=file_name)


def test_same_original_same_alias_across_files():
    t = MapTable()
    a = add_person(t, "张三", "a.docx")
    b = add_person(t, "张三", "b.docx")
    assert a.alias == b.alias == "甲某"
    assert b.occurrences == 2


def test_toggle_keeps_alias():
    t = MapTable()
    add_person(t, "张三")
    t.set_enabled("张三", False)
    t.set_enabled("张三", True)
    assert t.get("张三").alias == "甲某"


def test_remove_releases_alias():
    t = MapTable()
    add_person(t, "张三")
    add_person(t, "李四")
    t.remove("张三")
    add_person(t, "王五")
    assert t.get("王五").alias == "甲某"  # 回收复用


def test_custom_term_auto_alias_and_reserve():
    t = MapTable()
    item = t.add_custom("内部项目X")
    assert item.alias == "甲某"
    dup = t.add_custom("内部项目X")  # 重复添加幂等
    assert dup.alias == "甲某"
    manual = t.add_custom("某代号", alias="乙某")
    assert manual.alias == "乙某"
    auto = t.add_custom("另一代号")
    assert auto.alias == "丙某"  # 乙某被 reserve


def test_mask_rules():
    assert mask_value("13812345678", "phone") == "138****5678"
    assert mask_value("11010519900307755X", "id_number") == "110***********755X"
    assert mask_value("zhangsan@example.com", "email") == "z***@***"
    assert mask_value("1985年3月7日", "birth_date") == "1985年**月**日"


def test_mask_plate_exact():
    assert mask_value("京A12345", "plate") == "京A****5"


def test_split_entity_by_file():
    t = MapTable()
    add_person(t, "张伟", "a.docx")
    add_person(t, "张伟", "b.docx")
    new_item = t.split_entity("张伟", {"b.docx"})
    assert new_item is not None and new_item.alias == "乙某"
    pairs_a = dict(t.effective_pairs("a.docx"))
    pairs_b = dict(t.effective_pairs("b.docx"))
    assert pairs_a["张伟"] == "甲某"
    assert pairs_b["张伟"] == "乙某"


def test_effective_pairs_longest_first():
    t = MapTable()
    add_person(t, "张三")
    add_person(t, "张三丰")
    pairs = t.effective_pairs("a.docx")
    originals = [p[0] for p in pairs]
    assert originals.index("张三丰") < originals.index("张三")


def test_pending_not_effective():
    t = MapTable()
    t.add_finding("张三", "person", "lexicon", 0.85, pending=True, file_name="a.docx")
    assert t.effective_pairs("a.docx") == []
    t.set_pending("张三", False)
    assert ("张三", "甲某") in t.effective_pairs("a.docx")


def test_merge_into_shares_alias_and_releases():
    """分片合并：source 改用 target 代称、回收原代称、原文仍生效。"""
    t = MapTable()
    t.add_finding("智盛信息技术有限公司", "company", "lexicon", 0.8,
                  pending=False, file_name="a.pdf")
    t.add_finding("智盛信意裁术有限公司", "company", "lexicon", 0.8,
                  pending=False, file_name="a.pdf")  # OCR 错别字分片
    assert t.get("智盛信息技术有限公司").alias == "甲公司"
    assert t.get("智盛信意裁术有限公司").alias == "乙公司"
    t.merge_into("智盛信意裁术有限公司", "智盛信息技术有限公司")
    assert t.get("智盛信意裁术有限公司").alias == "甲公司"
    pairs = dict(t.effective_pairs("a.pdf"))
    assert pairs["智盛信意裁术有限公司"] == "甲公司"  # 原文仍会被替换
    assert pairs["智盛信息技术有限公司"] == "甲公司"
    # 原"乙公司"代称已回收，新公司复用
    t.add_finding("另一家公司", "company", "lexicon", 0.8,
                  pending=False, file_name="a.pdf")
    assert t.get("另一家公司").alias == "乙公司"


def test_merge_into_pending_follows_target():
    """待确认分片合并到已确认项后立即可生效。"""
    t = MapTable()
    t.add_finding("张三", "person", "lexicon", 0.85, pending=False, file_name="a.pdf")
    t.add_finding("张二", "person", "lexicon", 0.85, pending=True, file_name="a.pdf")
    t.merge_into("张二", "张三")
    assert t.get("张二").pending is False
    assert ("张二", "甲某") in t.effective_pairs("a.pdf")
