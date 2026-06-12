"""API 访问认证 — HMAC-SHA256 请求签名验证。

签名规范（与 Java FlowHubAuthInterceptor 对齐）：
  待签字符串："{timestamp}\\n{path}\\n{body_md5}"
  签名算法：HMAC-SHA256(secret_hex, canonical_string, encoding=UTF-8)
  请求头：
    X-FlowHub-Timestamp: Unix 毫秒时间戳（字符串）
    X-FlowHub-Token: 签名 hex（小写，64 字符）

有效期：±5 分钟（防重放）。
"""

from __future__ import annotations

import hashlib
import hmac
import time


# 签名有效窗口（毫秒）
_WINDOW_MS = 5 * 60 * 1000


def compute_signature(secret_hex: str, timestamp_ms: str, path: str, body_md5: str) -> str:
    """计算 HMAC-SHA256 签名（小写 hex）。

    :param secret_hex: 接口 auth_secret（64 位 hex）
    :param timestamp_ms: 请求时间戳（毫秒，字符串）
    :param path: 接口路径（不含前缀，如 vector-search）
    :param body_md5: 请求体 MD5（小写 hex），空体用 d41d8cd98f00b204e9800998ecf8427e
    :return: HMAC-SHA256 签名（小写 hex，64 字符）
    """
    canonical = f"{timestamp_ms}\n{path}\n{body_md5}"
    key = bytes.fromhex(secret_hex)
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def body_md5(raw: bytes) -> str:
    """计算请求体 MD5（小写 hex）。"""
    return hashlib.md5(raw).hexdigest()


def validate_request(
    secret_hex: str,
    path: str,
    raw_body: bytes,
    timestamp_header: str | None,
    token_header: str | None,
) -> tuple[bool, str]:
    """校验 HMAC 签名。

    :return: (ok, reason) — ok=True 表示通过；reason 为失败原因（用于日志）
    """
    if not timestamp_header or not token_header:
        return False, "缺少认证头 X-FlowHub-Timestamp / X-FlowHub-Token"
    try:
        ts_ms = int(timestamp_header)
    except ValueError:
        return False, "X-FlowHub-Timestamp 格式非法"
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_ms) > _WINDOW_MS:
        return False, f"时间戳过期（差值 {abs(now_ms - ts_ms)}ms，窗口 {_WINDOW_MS}ms）"
    expected = compute_signature(secret_hex, timestamp_header, path, body_md5(raw_body))
    if not hmac.compare_digest(expected, token_header.lower()):
        return False, "HMAC 签名不匹配"
    return True, ""
