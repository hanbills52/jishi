"""NER 识别层：ONNX RoBERTa(BERT) 中文实体识别，运行时仅依赖 onnxruntime。

模型：uer/roberta-base-finetuned-cluener2020-chinese（CLUENER 微调，BMES 标注），
离线转 ONNX 后随程序分发；分词器为内置的简化 BERT WordPiece 实现（中文逐字 + 西文最长匹配）。

类别映射：name→person、company→company、government/organization→org、address→address；
book/game/movie/position/scene 与脱敏无关，丢弃。

置信度策略：模型不输出概率阈值可调的分数，故按类别赋固定置信度，
全部落在 [PENDING_THRESHOLD, AUTO_THRESHOLD) 区间 → 进待确认组，由人工采纳。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort

from .rules import RawHit


def _model_dir() -> Path:
    """模型目录：打包版优先找 exe 同级的 models\\ner（大模型按需外置），
    找不到再回落到源码/内置资源路径；均缺失时由上层静默降级。"""
    if getattr(sys, "frozen", False):
        ext = Path(sys.executable).resolve().parent / "models" / "ner"
        if (ext / "ner.onnx").exists():
            return ext
    return Path(__file__).resolve().parent.parent.parent / "resources" / "models" / "ner"


_MODEL_DIR = _model_dir()
_MAX_LEN = 510  # 512 减去 [CLS]/[SEP]

# BMES → 引擎类别；未列出的标签丢弃
_LABEL_CATS = {"name": "person", "company": "company",
               "government": "org", "organization": "org", "address": "address"}
_CAT_CONF = {"person": 0.80, "company": 0.80, "org": 0.75, "address": 0.70}


class _WordPieceTokenizer:
    """简化 BERT 分词器：CJK 逐字；西文/数字连续段做贪心最长匹配 + ## 子词。"""

    def __init__(self, vocab_path: Path) -> None:
        self.vocab: dict[str, int] = {}
        # 注意：词表含 Python 专属换行符（\x85 等），splitlines 会多切行导致 id 偏移；
        # 必须与 HF 加载一致：严格按 \n 切分、去掉行尾 \r
        raw = vocab_path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(raw):
            self.vocab[line.rstrip("\r")] = i
        self.unk = self.vocab["[UNK]"]
        self.cls = self.vocab["[CLS]"]
        self.sep = self.vocab["[SEP]"]

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff" or ch in "，。；：、！？（）【】《》""''—…·"

    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if self._is_cjk(ch) or ch.isspace():
                tokens.append(ch)
                i += 1
                continue
            # 西文/数字连续段
            j = i
            while j < len(text) and not self._is_cjk(text[j]) and not text[j].isspace():
                j += 1
            word = text[i:j]
            tokens.extend(self._greedy_split(word))
            i = j
        return tokens

    def _greedy_split(self, word: str) -> list[str]:
        pieces: list[str] = []
        i = 0
        while i < len(word):
            piece = None
            for j in range(len(word), i, -1):
                cand = word[i:j]
                key = cand if i == 0 else "##" + cand
                if key in self.vocab:
                    piece = key
                    i = j
                    break
            if piece is None:  # 逐字符降级（含 [UNK]）
                ch = word[i]
                pieces.append(ch if ch in self.vocab else "[UNK]")
                i += 1
            else:
                pieces.append(piece)
        return pieces

    def encode(self, text: str) -> tuple[list[int], list[str]]:
        tokens = self.tokenize(text)[:_MAX_LEN]
        ids = [self.cls] + [self.vocab.get(t, self.unk) for t in tokens] + [self.sep]
        return ids, tokens


class NerProvider:
    """识别引擎第三层：__call__(text) -> list[RawHit]，线程安全（单例锁串行推理）。"""

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir or _MODEL_DIR
        self._session: ort.InferenceSession | None = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> ort.InferenceSession:
        """懒加载：首次调用时才把模型读入内存（约 2~4 秒），避免拖慢应用启动。"""
        if self._session is None:
            with self._lock:
                if self._session is None:
                    onnx_path = self._model_dir / "ner.onnx"
                    if not onnx_path.exists():
                        raise FileNotFoundError(f"NER 模型缺失：{onnx_path}")
                    self.tokenizer = _WordPieceTokenizer(self._model_dir / "vocab.txt")
                    so = ort.SessionOptions()
                    so.intra_op_num_threads = 0  # 交给全局线程池
                    self._session = ort.InferenceSession(
                        str(onnx_path), so, providers=["CPUExecutionProvider"])
                    self.input_name = self._session.get_inputs()[0].name
        return self._session

    def __call__(self, text: str) -> list[RawHit]:
        if not text.strip():
            return []
        session = self._ensure_loaded()
        ids, tokens = self.tokenizer.encode(text)
        if len(ids) < 3:
            return []
        input_ids = np.array([ids], dtype=np.int64)
        attention = np.ones_like(input_ids)
        with self._lock:
            logits = session.run(None, {self.input_name: input_ids,
                                        "attention_mask": attention})[0]
        tags = np.argmax(logits[0], axis=-1).tolist()  # 每个位置的标签 id（含 CLS/SEP）
        return self._decode(tags, tokens, text)

    # ---------- BMES 解码 ----------

    def _decode(self, tag_ids: list[int], tokens: list[str], text: str) -> list[RawHit]:
        # label 名从 ONNX 元数据或固定表获取
        label_names = self._label_names()
        hits: list[RawHit] = []
        # 逐 token 还原字符区间：CJK/空格 token 对应 1 字符；西文段多 token 合并后对应原连续段
        spans = self._token_char_spans(tokens, text)

        cur_cat, cur_start, cur_end = None, -1, -1
        for i, tid in enumerate(tag_ids[1:1 + len(tokens)]):  # 跳过 CLS
            label = label_names[tid] if 0 <= tid < len(label_names) else "O"
            if label == "[PAD]" or label == "O":
                kind, cat = "O", None
            else:
                kind, _, cat = label.partition("-")
            if kind == "B" or kind == "S":
                if cur_cat is not None:  # 上一个实体闭合
                    hits.append(self._hit(text, cur_start, cur_end, cur_cat))
                    cur_cat = None
                if kind == "B" and cat in _LABEL_CATS:
                    cur_cat, cur_start, cur_end = cat, spans[i][0], spans[i][1]
                elif kind == "S" and cat in _LABEL_CATS:
                    hits.append(self._hit(text, spans[i][0], spans[i][1], cat))
            elif kind == "I" and cat == cur_cat and cur_cat is not None:
                cur_end = spans[i][1]
            elif kind == "I":  # 断链 I：按新实体起点处理
                if cur_cat is not None:
                    hits.append(self._hit(text, cur_start, cur_end, cur_cat))
                    cur_cat = None
                if cat in _LABEL_CATS:
                    cur_cat, cur_start, cur_end = cat, spans[i][0], spans[i][1]
        if cur_cat is not None:
            hits.append(self._hit(text, cur_start, cur_end, cur_cat))
        return hits

    def _label_names(self) -> list[str]:
        if not hasattr(self, "_labels"):
            meta = {k: v for k, v in
                    self._ensure_loaded().get_modelmeta().custom_metadata_map.items()}
            import json
            self._labels = (list(json.loads(meta["label_names"]).values())
                            if "label_names" in meta else _DEFAULT_LABELS)
        return self._labels

    @staticmethod
    def _token_char_spans(tokens: list[str], text: str) -> list[tuple[int, int]]:
        """每个 token 在原文中的 (start, end)。依据：CJK 逐字、西文段贪心拼接后长度对齐。"""
        spans: list[tuple[int, int]] = []
        pos = 0  # 原文游标
        for tok in tokens:
            surface = tok[2:] if tok.startswith("##") else tok
            if tok == "[UNK]":
                # 贪婪跳过原文直到下一个 token 能对齐；UNK 常见于生僻字，退化为 1 字符
                surface = text[pos] if pos < len(text) else ""
            spans.append((pos, pos + len(surface)))
            pos += len(surface)
        return spans

    @staticmethod
    def _hit(text: str, start: int, end: int, cat: str) -> RawHit:
        val = text[start:end]
        return RawHit(start, end, val, _LABEL_CATS[cat], _CAT_CONF[_LABEL_CATS[cat]], source="ner")


# BMES 标签表（与 uer/cluener 模型 config.json id2label 一致；ONNX 元数据优先）
_DEFAULT_LABELS = ["O", "B-address", "I-address", "B-book", "I-book", "B-company", "I-company",
                   "B-game", "I-game", "B-government", "I-government", "B-movie", "I-movie",
                   "B-name", "I-name", "B-organization", "I-organization", "B-position",
                   "I-position", "B-scene", "I-scene", "S-address", "S-book", "S-company",
                   "S-game", "S-government", "S-movie", "S-name", "S-organization",
                   "S-position", "S-scene", "[PAD]"]
