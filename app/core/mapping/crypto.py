"""映射文件加解密外壳：AES-256-GCM + scrypt 派生密钥。

文件结构：{"enc": "AES-256-GCM", "kdf": "scrypt", "salt": b64, "nonce": b64, "data": b64密文}
密钥 = scrypt(用户密码, salt, n=2^14, r=8, p=1)；密码不明文落盘。
解密失败（密码错/数据被篡改）统一抛 WrongPasswordError，不提供找回。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32  # AES-256


class WrongPasswordError(Exception):
    """密码错误或密文被篡改。"""


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(password.encode("utf-8"))


def export_encrypted(mapping: dict, password: str, path: str | Path) -> None:
    """将映射 JSON 加密写入 path。"""
    if not password:
        raise ValueError("密码不能为空")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    plaintext = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    envelope = {
        "enc": "AES-256-GCM",
        "kdf": "scrypt",
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }
    Path(path).write_text(json.dumps(envelope, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def load_encrypted(path: str | Path, password: str) -> dict:
    """读取并解密映射文件；密码错误或结构非法抛 WrongPasswordError。"""
    try:
        envelope = json.loads(Path(path).read_text(encoding="utf-8"))
        salt = base64.b64decode(envelope["salt"])
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["data"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise WrongPasswordError("映射文件结构非法或已损坏") from exc
    key = _derive_key(password, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise WrongPasswordError("密码错误或映射文件已被篡改") from exc
    return json.loads(plaintext.decode("utf-8"))
