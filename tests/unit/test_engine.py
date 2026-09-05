"""M1-4 自查：仲裁器与置信度分桶。"""
from app.core.recognize.engine import RecognizeEngine, ScanSettings
from app.core.recognize.rules import RawHit


def test_arbitrate_prefers_rule_and_longer_span():
    # 同一区间：词典层人名 vs 规则层身份证 → 规则层胜出
    hits = [
        RawHit(0, 18, "11010519900307755X", "id_number", source="rule"),
        RawHit(0, 4, "1101", "address", 0.7, source="lexicon"),
        RawHit(20, 22, "张三", "person", 0.85, source="lexicon"),
        RawHit(20, 23, "张三丰", "person", 0.85, source="lexicon"),  # 同层取更长
    ]
    merged = RecognizeEngine._arbitrate(hits)
    texts = [h.text for h in merged]
    assert "11010519900307755X" in texts
    assert "1101" not in texts
    assert "张三丰" in texts and "张三" not in texts


def test_confidence_bucket():
    engine = RecognizeEngine()
    findings = engine.scan_paragraph("原告：张三，男。", 0)
    person = next(f for f in findings if f.text == "张三")
    assert person.status == "pending"  # 0.85 → 待确认，不直接生效


def test_rule_hit_auto():
    engine = RecognizeEngine()
    findings = engine.scan_paragraph("手机号13812345678。", 0)
    phone = next(f for f in findings if f.category == "phone")
    assert phone.status == "auto"


def test_judicial_filtered_by_default():
    engine = RecognizeEngine()
    findings = engine.scan_paragraph("审判长：李四\n", 0)
    assert not any(f.text == "李四" for f in findings)
    engine_on = RecognizeEngine(settings=ScanSettings(mask_judicial=True))
    findings_on = engine_on.scan_paragraph("审判长：李四\n", 0)
    assert any(f.text == "李四" for f in findings_on)


def test_merge_adjacent_fragments_into_one():
    """同一实体被多层切成相邻碎片时合并为一个命中（真实案例：街道办被切5段）。"""
    hits = [
        RawHit(0, 9, "深圳市福田区莲花街", "address", 0.7, source="ner"),
        RawHit(9, 10, "道", "org", 0.75, source="ner"),
        RawHit(10, 12, "办事", "org", 0.75, source="ner"),
        RawHit(12, 13, "处", "org", 0.75, source="ner"),
        RawHit(10, 13, "办事处", "org", 0.75, source="lexicon"),
    ]
    merged = RecognizeEngine._arbitrate(hits)
    assert len(merged) == 1
    assert merged[0].text == "深圳市福田区莲花街道办事处"
    assert (merged[0].start, merged[0].end) == (0, 13)


def test_merge_contained_fragment_dropped():
    """被完整包含的碎片直接丢弃，不再单独占位。"""
    hits = [
        RawHit(0, 9, "深圳市福田区", "address", 0.7, source="ner"),
        RawHit(3, 5, "福田", "address", 0.7, source="lexicon"),
    ]
    merged = RecognizeEngine._arbitrate(hits)
    assert len(merged) == 1 and merged[0].text == "深圳市福田区"


def test_merge_never_touches_rule_hits():
    """规则类命中（身份证/手机号）不参与实体合并，且不被实体覆盖。"""
    hits = [
        RawHit(0, 4, "某市某区", "address", 0.7, source="ner"),
        RawHit(5, 23, "440300199001011234", "id_number", source="rule"),
        RawHit(5, 9, "4403", "address", 0.7, source="ner"),
    ]
    merged = RecognizeEngine._arbitrate(hits)
    texts = [h.text for h in merged]
    assert "440300199001011234" in texts
    assert "4403" not in texts  # 与规则命中重叠的实体碎片被丢弃


def test_merge_respects_max_length():
    """超长链不合并，防止跨句蔓延。"""
    a = RawHit(0, 40, "甲" * 40, "address", 0.7, source="ner")
    b = RawHit(40, 70, "乙" * 30, "address", 0.7, source="ner")
    merged = RecognizeEngine._merge_fragments([a, b])
    assert len(merged) == 2  # 70 字 > 上限 60，不合并


def test_merge_not_for_separated_entities():
    """不相邻的两个实体各自保留。"""
    hits = [
        RawHit(0, 2, "张三", "person", 0.85, source="lexicon"),
        RawHit(5, 7, "李四", "person", 0.85, source="lexicon"),
    ]
    merged = RecognizeEngine._arbitrate(hits)
    assert {h.text for h in merged} == {"张三", "李四"}
