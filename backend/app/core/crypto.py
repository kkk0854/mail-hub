"""凭据加密（Fernet 对称加密）与脱敏工具。数据库永远不保存明文凭据（§20）。"""
from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet

from .config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.encryption_key.encode())
    return _fernet


def encrypt_str(value: str | None) -> str:
    if value is None or value == "":
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_str(value: str | None) -> str:
    if not value:
        return ""
    return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def mask_secret(value: str | None) -> str:
    """后端响应默认脱敏：只保留末 2 位。"""
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "•" * (min(len(value) - 2, 10)) + value[-2:]


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
