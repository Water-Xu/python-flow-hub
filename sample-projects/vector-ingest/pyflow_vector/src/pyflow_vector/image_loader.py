"""图片加载：HTTP(S) URL、MinIO 路径、base64 data URL。"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

_MAX_BYTES = int(os.environ.get("PYFLOW_VECTOR_IMAGE_MAX_BYTES", str(15 * 1024 * 1024)))
_TIMEOUT = float(os.environ.get("PYFLOW_VECTOR_IMAGE_TIMEOUT", "30"))
_ALLOWED_SCHEMES = {"http", "https", "minio", "s3"}
_DATA_URL = re.compile(r"^data:image/[\w+.-]+;base64,", re.I)


def _normalize_urls(raw: Any) -> list[str]:
    if raw is None:
        raise ValueError("inputs.image_urls 不能为空")
    if isinstance(raw, str):
        items = [raw.strip()]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        raise ValueError("inputs.image_urls 必须是 string 或 string[]")
    if not items:
        raise ValueError("inputs.image_urls 解析后为空")
    return items


def _domain_allowed(url: str) -> bool:
    allow = (os.environ.get("PYFLOW_VECTOR_IMAGE_DOMAIN_ALLOWLIST") or "").strip()
    if not allow:
        return True
    host = urlparse(url).hostname or ""
    allowed = {x.strip().lower() for x in allow.split(",") if x.strip()}
    return host.lower() in allowed or any(host.endswith("." + d) for d in allowed)


def _load_minio_object(ref: str) -> bytes:
    try:
        from minio import Minio
    except ImportError as exc:
        raise RuntimeError("读取 minio:// 需要 minio 包") from exc

    endpoint = os.environ.get("MINIO_ENDPOINT", "")
    ak = os.environ.get("MINIO_ACCESS_KEY", "")
    sk = os.environ.get("MINIO_SECRET_KEY", "")
    if not endpoint or not ak:
        raise RuntimeError("未配置 MINIO_ENDPOINT / MINIO_ACCESS_KEY")

    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    path = ref.split("://", 1)[-1]
    bucket, _, key = path.partition("/")
    if not bucket or not key:
        raise ValueError(f"无效的 MinIO 路径: {ref}")

    client = Minio(endpoint, access_key=ak, secret_key=sk, secure=secure)
    resp = client.get_object(bucket, key)
    try:
        data = resp.read(_MAX_BYTES + 1)
    finally:
        resp.close()
        resp.release_conn()
    if len(data) > _MAX_BYTES:
        raise ValueError(f"图片超过大小限制 {_MAX_BYTES} 字节: {ref}")
    return data


def _load_http(url: str) -> bytes:
    if not _domain_allowed(url):
        raise ValueError(f"图片域名不在白名单: {url}")
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            if ctype and not ctype.startswith("image/"):
                raise ValueError(f"URL 非图片 Content-Type: {ctype}")
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise ValueError(f"图片超过大小限制 {_MAX_BYTES} 字节: {url}")
                chunks.append(chunk)
    return b"".join(chunks)


def _load_data_url(url: str) -> bytes:
    payload = url.split(",", 1)[-1]
    data = base64.b64decode(payload, validate=True)
    if len(data) > _MAX_BYTES:
        raise ValueError(f"base64 图片超过大小限制 {_MAX_BYTES} 字节")
    return data


def load_image_bytes(url: str) -> bytes:
    """按 URL 加载图片二进制。"""
    url = url.strip()
    if _DATA_URL.match(url):
        return _load_data_url(url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in ("minio", "s3"):
        return _load_minio_object(url)
    if scheme not in ("http", "https"):
        raise ValueError(f"不支持的图片 URL scheme: {scheme}")
    return _load_http(url)


def load_images_to_temp(urls: list[str]) -> tuple[list[str], tempfile.TemporaryDirectory[str]]:
    """下载/解码图片到临时目录，返回本地路径列表与 temp 句柄（调用方需保持引用）。"""
    tmp = tempfile.TemporaryDirectory(prefix="pyflow_vec_img_")
    paths: list[str] = []
    for idx, url in enumerate(urls):
        data = load_image_bytes(url)
        suffix = _guess_suffix(url, data)
        local = os.path.join(tmp.name, f"{idx:04d}{suffix}")
        Path(local).write_bytes(data)
        paths.append(local)
    return paths, tmp


def _guess_suffix(url: str, data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    path = urlparse(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        if path.endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"
    return ".jpg"


def auto_ids(urls: list[str]) -> list[str]:
    return [hashlib.sha256(u.encode("utf-8")).hexdigest()[:32] for u in urls]
