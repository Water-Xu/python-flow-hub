"""接口加密工具：AES-256-GCM 认证加密。

用于 API Portal 公开接口的请求/响应载荷端到端加密，与 Java common 侧
``FlowHubCryptoUtil`` 协议完全对称：

密文格式（base64 编码）::

    base64( iv[12 bytes] || ciphertext || tag[16 bytes] )

其中 GCM 的 16 字节认证标签由底层库追加在密文末尾（``AESGCM.encrypt`` 行为），
解密时整体校验，篡改即抛错。密钥为 32 字节（AES-256），以 hex 字符串（64 chars）存储与传输。
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# GCM 推荐 96-bit（12 字节）随机 IV
_IV_LEN = 12


def generate_key() -> str:
    """生成一个新的 AES-256 密钥。

    :return: 32 字节密钥的 hex 字符串（64 个十六进制字符）
    """
    return os.urandom(32).hex()


def _load_key(hex_key: str) -> bytes:
    """将 hex 密钥解析为 32 字节，非法长度抛出 ``ValueError``。

    :param hex_key: 64 字符 hex 密钥
    :return: 32 字节密钥
    """
    key = bytes.fromhex(hex_key)
    if len(key) != 32:
        raise ValueError("encryption key must be 32 bytes (64 hex chars)")
    return key


def encrypt(hex_key: str, data: Any) -> str:
    """将任意可 JSON 序列化对象加密为 base64 密文。

    :param hex_key: 64 字符 hex 密钥
    :param data: 待加密对象（通常为 dict）
    :return: ``base64(iv || ciphertext || tag)``
    """
    key = _load_key(hex_key)
    iv = os.urandom(_IV_LEN)
    plaintext = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    return base64.b64encode(iv + ciphertext).decode("ascii")


def decrypt(hex_key: str, payload: str) -> Any:
    """解密 base64 密文并 JSON 反序列化。

    :param hex_key: 64 字符 hex 密钥
    :param payload: ``base64(iv || ciphertext || tag)``
    :return: 反序列化后的对象
    :raises ValueError: 密文格式非法 / 解密或认证失败（密钥错误或数据被篡改）
    """
    key = _load_key(hex_key)
    try:
        raw = base64.b64decode(payload)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid base64 ciphertext") from exc
    if len(raw) <= _IV_LEN:
        raise ValueError("ciphertext too short")
    iv, ciphertext = raw[:_IV_LEN], raw[_IV_LEN:]
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    except InvalidTag as exc:
        raise ValueError("decryption failed: wrong key or tampered data") from exc
    return json.loads(plaintext.decode("utf-8"))
