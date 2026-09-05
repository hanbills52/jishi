"""M2-2 自查：映射文件加解密。"""
from __future__ import annotations

import pytest

from app.core.mapping.crypto import (WrongPasswordError, export_encrypted,
                                     load_encrypted)


@pytest.fixture
def mapping():
    return {
        "version": "1.0",
        "batch_id": "test-batch",
        "doc_manifest": [{"file": "借款合同.docx", "sha256": "abc"}],
        "mappings": [
            {"id": 1, "category": "person", "original": "张三", "alias": "甲某",
             "occurrences": 2, "enabled": True, "source": "lexicon", "confidence": 0.85},
        ],
    }


def test_roundtrip(mapping, tmp_path):
    path = tmp_path / "m.json"
    export_encrypted(mapping, "口令123", path)
    assert load_encrypted(path, "口令123") == mapping


def test_wrong_password(mapping, tmp_path):
    path = tmp_path / "m.json"
    export_encrypted(mapping, "正确密码", path)
    with pytest.raises(WrongPasswordError):
        load_encrypted(path, "错误密码")


def test_corrupted_file_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"enc": "AES-256-GCM"}', encoding="utf-8")
    with pytest.raises(WrongPasswordError):
        load_encrypted(path, "任意")


def test_no_plaintext_leak(mapping, tmp_path):
    """密文文件头不含明文映射内容。"""
    path = tmp_path / "m.json"
    export_encrypted(mapping, "口令123", path)
    raw = path.read_bytes()
    assert "张三".encode("utf-8") not in raw
    assert "甲某".encode("utf-8") not in raw
    assert "借款合同".encode("utf-8") not in raw
