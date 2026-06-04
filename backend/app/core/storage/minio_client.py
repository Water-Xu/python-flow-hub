"""MinIO 对象存储客户端（决策 8：版本大字段存 MinIO，DB 只存指针）。

提供异步包装（同步 minio SDK 走线程池），统一 sha256 校验，供 version_manager 双写：
先写 MinIO（幂等 PUT，key 含 version_id）→ 校验 sha → 再写 DB 指针。
读路径按 content_sha256 校验，不一致即视为版本损坏（PYFLOW_VERSION_NOT_STABLE）。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Protocol

from app.config import get_settings
from app.observability.logging import get_logger

logger = get_logger("pyflow.storage")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStorage(Protocol):
    """对象存储抽象，便于单测注入内存实现（AIR：不依赖外部服务）。"""

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def list_keys(self, prefix: str) -> list[str]: ...


class MinioStorage:
    """基于 minio SDK 的对象存储实现（生产）。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None
        self._bucket = self._settings.minio_bucket

    def _ensure_client(self):
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self._settings.minio_endpoint,
                access_key=self._settings.minio_access_key,
                secret_key=self._settings.minio_secret_key,
                secure=self._settings.minio_secure,
            )
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        return self._client

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        def _do() -> str:
            client = self._ensure_client()
            result = client.put_object(
                self._bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
            )
            return result.etag

        return await asyncio.to_thread(_do)

    async def get(self, key: str) -> bytes:
        def _do() -> bytes:
            client = self._ensure_client()
            resp = client.get_object(self._bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(_do)

    async def exists(self, key: str) -> bool:
        def _do() -> bool:
            from minio.error import S3Error

            client = self._ensure_client()
            try:
                client.stat_object(self._bucket, key)
                return True
            except S3Error:
                return False

        return await asyncio.to_thread(_do)

    async def delete(self, key: str) -> None:
        def _do() -> None:
            client = self._ensure_client()
            client.remove_object(self._bucket, key)

        await asyncio.to_thread(_do)

    async def list_keys(self, prefix: str) -> list[str]:
        def _do() -> list[str]:
            client = self._ensure_client()
            return [obj.object_name for obj in client.list_objects(self._bucket, prefix=prefix, recursive=True)]

        return await asyncio.to_thread(_do)


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = MinioStorage()
    return _storage


def set_storage(storage: ObjectStorage) -> None:
    """测试注入点。"""
    global _storage
    _storage = storage
