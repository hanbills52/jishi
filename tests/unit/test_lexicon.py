"""M1-3 自查：词典/上下文识别层。"""
from app.core.recognize.lexicon import LexiconScanner


def scan(text):
    return LexiconScanner().scan(text)


def test_person_by_prompt_word():
    hits = scan("原告：张三，男，汉族，住北京市海淀区。")
    assert any(h.text == "张三" and h.category == "person" for h in hits)
    assert any(h.text == "汉族" and h.category == "ethnicity" for h in hits)


def test_person_by_gender_pattern():
    hits = scan("李四，男，1985年3月7日出生。")
    assert any(h.text == "李四" and h.category == "person" for h in hits)


def test_judicial_stopword_never_person():
    hits = scan("北京市海淀区人民法院依法判决如下。")
    assert not any(h.category == "person" for h in hits)


def test_judicial_person_marked():
    hits = scan("审判长：李四\n书记员：王五\n")
    persons = {h.text: h for h in hits if h.category == "person"}
    assert persons.get("李四") is not None and persons["李四"].judicial
    assert persons.get("王五") is not None and persons["王五"].judicial


def test_company_strips_prompt_prefix():
    hits = scan("原告北京某某科技有限公司诉称。")
    companies = [h.text for h in hits if h.category == "company"]
    assert "北京某某科技有限公司" in companies
    assert not any(c.startswith("原告") for c in companies)


def test_address():
    hits = scan("住所地：北京市海淀区中关村大街28号院3号楼。")
    assert any(h.category == "address" for h in hits)


def test_address_tolerates_ocr_space():
    """OCR 断字带空格：'西 8号' 中间的空格不应阻断地址匹配。"""
    hits = scan("地址：广东省惠州市仲恺高新区和畅五路西 8号投资控股大厦21楼。")
    assert any(h.category == "address" and "和畅五路" in h.text for h in hits)


def test_region_anchored_address_without_keyword():
    """行政区锚定兜底：无'路/号'关键字的区域表述也能进待确认。"""
    hits = scan("申请人现住惠州市仲恺高新区附近。")
    assert any(h.category == "address" and h.text.startswith("惠州市") for h in hits)


def test_region_addr_rejects_institution_suffix():
    """行政区+机构名（人民法院）不得被当成地址。"""
    hits = scan("本案由北京市海淀区人民法院审理。")
    assert not any(h.category == "address" and "人民法院" in h.text for h in hits)


def test_custom_names_hit(tmp_path, monkeypatch):
    """自定义人名学习库：写入名单后扫描即命中。"""
    import app.core.recognize.lexicon as lex
    lex_dir = tmp_path / "lexicons"
    lex_dir.mkdir()
    for name in ("surnames.txt", "ethnicities.txt", "judicial_stopwords.txt",
                 "prompt_words.txt", "titles.txt"):
        (lex_dir / name).write_text("", encoding="utf-8")
    (lex_dir / "custom_names.txt").write_text("陈志强\n", encoding="utf-8")
    scanner = lex.LexiconScanner(lexicon_dir=lex_dir)
    hits = scanner.scan("申请人陈志强于2023年入职。")
    assert any(h.text == "陈志强" and h.confidence == 0.9 and h.source == "custom"
               for h in hits)
