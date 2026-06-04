"""版本管理单测（Phase 3：sha 校验 / diff / requirements_hash）。零外部服务（内存 storage）。"""

from __future__ import annotations

import pytest

from app.core.storage.minio_client import sha256_hex
from app.core.versioning import diff_service, version_manager


class InMemoryStorage:
    """ObjectStorage 内存实现（AIR：不依赖 MinIO）。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = data
        return sha256_hex(data)

    async def get(self, key):
        return self.objects[key]

    async def exists(self, key):
        return key in self.objects

    async def delete(self, key):
        self.objects.pop(key, None)

    async def list_keys(self, prefix):
        return [k for k in self.objects if k.startswith(prefix)]


class FakeBlockVersion:
    def __init__(self, vid, code_path, sha, requirements_path=None, notebook_path=None):
        self.id = vid
        self.code_path = code_path
        self.content_sha256 = sha
        self.requirements_path = requirements_path
        self.notebook_path = notebook_path


def test_requirements_hash_normalized():
    a = version_manager.requirements_hash("requests==2.0\n# comment\n\nnumpy==1.0")
    b = version_manager.requirements_hash("numpy==1.0\nrequests==2.0\n")
    assert a == b  # 排序 + 去注释/空行后一致


async def test_get_block_version_content_sha_ok_and_tamper():
    storage = InMemoryStorage()
    code = "def run(inputs):\n    return inputs\n"
    sha = await storage.put("blocks/b1/v1/code.py", code.encode("utf-8"))
    version = FakeBlockVersion("v1", "blocks/b1/v1/code.py", sha)

    content = await version_manager.get_block_version_content(version, storage)
    assert content["code"] == code

    # 篡改对象 → sha 不匹配应报版本损坏
    storage.objects["blocks/b1/v1/code.py"] = b"tampered"
    with pytest.raises(Exception):
        await version_manager.get_block_version_content(version, storage)


def test_diff_stats_and_unified():
    old = "a\nb\nc\n"
    new = "a\nB\nc\nd\n"
    stats = diff_service.diff_stats(old, new)
    assert stats["added"] >= 1
    assert stats["removed"] >= 1
    payload = diff_service.diff_payload(old, new, old_label="v1", new_label="v2")
    assert payload["old"] == old
    assert payload["new"] == new
    assert "unified" in payload
