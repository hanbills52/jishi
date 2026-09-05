"""映射文件导出/读取（M1 为明文 JSON；M2 起由 crypto.py 加解密外壳）。

结构见实施方案第 4 章：version / batch_id / created_at / doc_manifest / mappings。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .map_table import MapTable

FORMAT_VERSION = "1.0"


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_mapping_json(table: MapTable, files: list[str], batch_id: str | None = None) -> dict:
    return {
        "version": FORMAT_VERSION,
        "batch_id": batch_id or str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "doc_manifest": [
            {"file": Path(f).name, "sha256": sha256_of(f)}
            for f in files if Path(f).exists()
        ],
        "mappings": [
            {
                "id": it.id,
                "category": it.category,
                "original": it.original,
                "alias": it.alias,
                "occurrences": it.occurrences,
                "enabled": it.enabled,
                "source": it.source,
                "confidence": it.confidence,
            }
            for it in table.items()
        ],
    }


def save_mapping(table: MapTable, files: list[str], path: str | Path,
                 batch_id: str | None = None) -> dict:
    data = build_mapping_json(table, files, batch_id)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_mapping(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != FORMAT_VERSION:
        raise ValueError(f"映射文件版本不支持：{data.get('version')}")
    if "mappings" not in data or "batch_id" not in data:
        raise ValueError("映射文件结构非法")
    return data
