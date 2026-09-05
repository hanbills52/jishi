"""CLUENER 评测：现有识别引擎（规则+词典）在人名/公司/地址上的基线水平。

用法：.venv\\Scripts\\python.exe tests\\eval_cluener.py [样本数]
数据：corpus/cluener/dev.json（1343 条，含 name/company/government/organization/address 标注）
指标：精确率 / 召回率 / F1（字符区间完全匹配才算命中）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.recognize.engine import RecognizeEngine  # noqa: E402

# 金标类别 → 引擎类别
CAT_MAP = {"name": "person", "company": "company",
           "government": "org", "organization": "org", "address": "address"}
CATS = ["person", "company", "org", "address"]


def load_gold(path: Path, limit: int) -> list[dict]:
    samples = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if len(samples) >= limit:
                break
            samples.append(json.loads(line))
    return samples


def gold_spans(sample: dict) -> dict[str, set[tuple[int, int]]]:
    """金标区间 [start, end]（闭区间）→ (start, end_exclusive) 集合，按引擎类别归并。"""
    result: dict[str, set[tuple[int, int]]] = {c: set() for c in CATS}
    for label, entities in sample.get("label", {}).items():
        cat = CAT_MAP.get(label)
        if cat is None:
            continue
        for positions in entities.values():
            for start, end in positions:
                result[cat].add((start, end + 1))
    return result


def pred_spans(engine: RecognizeEngine, text: str) -> dict[str, set[tuple[int, int]]]:
    result: dict[str, set[tuple[int, int]]] = {c: set() for c in CATS}
    for f in engine.scan_paragraph(text, 0):
        if f.category in result:
            result[f.category].add((f.start, f.end))
    return result


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--ner"]
    limit = int(args[0]) if args else 1343
    use_ner = "--ner" in sys.argv
    data_path = ROOT / "corpus" / "cluener" / "dev.json"
    samples = load_gold(data_path, limit)
    engine = RecognizeEngine()
    if use_ner:
        from app.core.recognize.ner import NerProvider
        engine.settings.enable_ner = True
        engine.set_ner_provider(NerProvider())
        print("已启用 NER 层")

    tp = {c: 0 for c in CATS}
    fp = {c: 0 for c in CATS}
    fn = {c: 0 for c in CATS}
    for s in samples:
        gold = gold_spans(s)
        pred = pred_spans(engine, s["text"])
        for c in CATS:
            tp[c] += len(gold[c] & pred[c])
            fp[c] += len(pred[c] - gold[c])
            fn[c] += len(gold[c] - pred[c])

    print(f"样本数：{len(samples)}（CLUENER dev）")
    print(f"{'类别':<10}{'精确率':>8}{'召回率':>8}{'F1':>8}{'漏检':>6}{'误报':>6}")
    for c in CATS:
        p = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        r = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        print(f"{c:<10}{p:>8.1%}{r:>8.1%}{f1:>8.1%}{fn[c]:>6}{fp[c]:>6}")


if __name__ == "__main__":
    main()
