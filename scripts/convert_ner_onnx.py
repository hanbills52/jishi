"""一次性脚本：把下载的 HF 权重转为 ONNX（含标签表元数据）。

用法：.venv\\Scripts\\python.exe scripts\\convert_ner_onnx.py
依赖：torch + transformers（仅转换时需要，运行时用 onnxruntime）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "app" / "resources" / "models" / "ner"


def main() -> None:
    import torch
    from transformers import AutoModelForTokenClassification

    model = AutoModelForTokenClassification.from_pretrained(str(MODEL_DIR), torch_dtype=torch.float32)
    model.eval()

    ids = torch.tensor([[101, 872, 1962, 6821, 102]], dtype=torch.int64)  # [CLS] 测试文 [SEP]
    mask = torch.ones_like(ids)

    out_path = MODEL_DIR / "ner.onnx"
    with torch.no_grad():
        torch.onnx.export(
            model, (ids, mask), str(out_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                          "attention_mask": {0: "batch", 1: "seq"},
                          "logits": {0: "batch", 1: "seq"}},
            opset_version=14,
        )

    # 标签表写入元数据，运行时不再依赖 config.json
    import json as _json
    import onnx
    labels = model.config.id2label
    m = onnx.load(str(out_path))
    meta = m.metadata_props.add()
    meta.key, meta.value = "label_names", _json.dumps(labels, ensure_ascii=False)
    onnx.save(m, str(out_path))

    # 验证：ONNX 与 PyTorch 输出一致
    import onnxruntime as ort
    import numpy as np
    sess = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
    ort_logits = sess.run(None, {"input_ids": ids.numpy(), "attention_mask": mask.numpy()})[0]
    with torch.no_grad():
        pt_logits = model(input_ids=ids, attention_mask=mask).logits.numpy()
    diff = float(np.abs(ort_logits - pt_logits).max())
    print(f"已导出 {out_path.name}（{out_path.stat().st_size / 1e6:.0f} MB），标签数 {len(labels)}")
    print(f"ONNX 与 PyTorch 最大输出差异：{diff:.2e}（应 < 1e-4）")
    if diff > 1e-4:
        sys.exit(1)

    # 真实句子正确性验证（防止权重未加载时 PT/ONNX 一致地错）
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    sent = "马云是阿里巴巴的创始人，他住在浙江省杭州市西湖区文一西路。"
    enc = tok(sent, return_tensors="pt")
    ort_out = sess.run(None, {"input_ids": enc["input_ids"].numpy(),
                              "attention_mask": enc["attention_mask"].numpy()})[0]
    tag_ids = ort_out[0].argmax(-1).tolist()
    tag_names = [labels[t] for t in tag_ids]
    print("ONNX 标签：", tag_names)
    if not any("-name" in t or "-company" in t or "-address" in t for t in tag_names):
        print("错误：ONNX 未识别出任何实体，转换有问题")
        sys.exit(1)

    # 权重文件转完即可删，减小分发包（先释放内存映射）
    del model
    import gc
    gc.collect()
    (MODEL_DIR / "pytorch_model.bin").unlink(missing_ok=True)
    print("已删除 pytorch_model.bin（仅转换用）")


if __name__ == "__main__":
    main()
