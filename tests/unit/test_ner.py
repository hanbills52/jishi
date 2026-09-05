"""NER 层单元测试：模型存在才执行（CI/无模型环境自动跳过）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.core.recognize.engine import RecognizeEngine  # noqa: E402
from app.core.recognize.ner import NerProvider  # noqa: E402
from app.core.recognize.rules import RawHit  # noqa: E402

MODEL_DIR = ROOT / "app" / "resources" / "models" / "ner"
pytestmark = pytest.mark.skipif(
    not (MODEL_DIR / "ner.onnx").exists(), reason="NER 模型未安装")


@pytest.fixture(scope="module")
def provider() -> NerProvider:
    return NerProvider()


def test_person_company_address(provider: NerProvider) -> None:
    hits = provider("马云是阿里巴巴的创始人，他住在浙江省杭州市西湖区文一西路。")
    by_cat = {h.category: h for h in hits}
    assert by_cat["person"].text == "马云"
    assert by_cat["company"].text == "阿里巴巴"
    assert "文一西路" in by_cat["address"].text


def test_source_and_confidence(provider: NerProvider) -> None:
    hits = provider("证人赵小红到庭陈述了案件经过。")
    person = [h for h in hits if h.category == "person"]
    assert person and person[0].text == "赵小红"
    assert person[0].source == "ner"
    assert 0.6 <= person[0].confidence < 0.9  # 进待确认组，不自动生效


def test_empty_and_short(provider: NerProvider) -> None:
    assert provider("") == []
    assert provider("  ") == []


def test_engine_integration(provider: NerProvider) -> None:
    """接入引擎后：NER 命中与其他层仲裁合并，状态为 pending；司法人员按默认策略丢弃。"""
    engine = RecognizeEngine()
    engine.settings.enable_ner = True
    engine.set_ner_provider(provider)
    findings = engine.scan_paragraph("审判长王建国认为，被告人李明多次联系证人赵小红。", 0)
    persons = {f.text for f in findings if f.category == "person"}
    assert {"李明", "赵小红"} <= persons
    assert "王建国" not in persons  # 司法人员默认保留原文
    ner_persons = [f for f in findings if f.category == "person" and f.source == "ner"]
    assert ner_persons and all(f.status == "pending" for f in ner_persons)


def test_span_alignment(provider: NerProvider) -> None:
    """命中区间与原文切片一致（分词器偏移正确性）。"""
    text = "原告代理律师陈志远提交了新证据。"
    for h in provider(text):
        assert isinstance(h, RawHit)
        assert text[h.start:h.end] == h.text
