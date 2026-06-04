"""幂等状态机 + fence_token CAS（决策 5/7）：抢占/重复/接管/心跳/单调性。"""

from __future__ import annotations

import pytest

from pyflow_runtime.idempotency import (
    IdempotencyStore,
    build_idempotency_id,
    extract_business_id,
    fence_key,
    state_key,
)

LEASE = 30
STATE_TTL = 600


def _store(fake_redis, clock, pod="pod-A"):
    return IdempotencyStore(fake_redis, pod, time_fn=clock)


def test_business_id_prefers_snowflake():
    assert extract_business_id({"header": {"snowflakeId": "SF1"}}, "mid") == "SF1"


def test_business_id_falls_back_to_message_id():
    assert extract_business_id({"header": {}}, "mid") == "mid"


def test_business_id_falls_back_to_body_sha():
    bid = extract_business_id({"a": 1}, None)
    assert len(bid) == 64  # sha256 hex


def test_idempotency_id_appends_retry_count():
    assert build_idempotency_id("SF1", 2) == "SF1:2"


def test_keys_share_hash_tag():
    # state 与 fence 用同一 {idem_id} hash tag，保证 Cluster 同 slot（决策 5）
    assert state_key("SF1:0") == "pyflow:exec:state:{SF1:0}"
    assert fence_key("SF1:0") == "pyflow:exec:fence:{SF1:0}"


async def test_first_claim_succeeds(fake_redis, clock):
    store = _store(fake_redis, clock)
    claim = await store.claim("SF1:0", LEASE, STATE_TTL)
    assert claim.claimed is True
    assert claim.fence_token == 1


async def test_duplicate_processing_not_claimed(fake_redis, clock):
    store_a = _store(fake_redis, clock, "pod-A")
    store_b = _store(fake_redis, clock, "pod-B")
    await store_a.claim("SF1:0", LEASE, STATE_TTL)
    claim_b = await store_b.claim("SF1:0", LEASE, STATE_TTL)
    assert claim_b.claimed is False
    assert claim_b.existing_status == "PROCESSING"


async def test_success_terminal_seen_by_duplicate(fake_redis, clock):
    store = _store(fake_redis, clock)
    claim = await store.claim("SF1:0", LEASE, STATE_TTL)
    await store.set_terminal("SF1:0", claim.fence_token, "SUCCESS", {"v": 9}, STATE_TTL)
    dup = await store.claim("SF1:0", LEASE, STATE_TTL)
    assert dup.claimed is False
    assert dup.existing_status == "SUCCESS"
    assert dup.existing_result == {"v": 9}


async def test_take_over_after_lease_expiry_with_monotonic_fence(fake_redis, clock):
    store_a = _store(fake_redis, clock, "pod-A")
    store_b = _store(fake_redis, clock, "pod-B")
    claim_a = await store_a.claim("SF1:0", LEASE, STATE_TTL)
    assert claim_a.fence_token == 1
    # lease 过期 → 新副本接管，fence 严格单调递增（接管 token 必大于老 owner）
    clock.advance(LEASE + 1)
    claim_b = await store_b.claim("SF1:0", LEASE, STATE_TTL)
    assert claim_b.claimed is True
    assert claim_b.fence_token > claim_a.fence_token


async def test_old_owner_heartbeat_fails_after_takeover(fake_redis, clock):
    store_a = _store(fake_redis, clock, "pod-A")
    store_b = _store(fake_redis, clock, "pod-B")
    claim_a = await store_a.claim("SF1:0", LEASE, STATE_TTL)
    clock.advance(LEASE + 1)
    claim_b = await store_b.claim("SF1:0", LEASE, STATE_TTL)
    # 老 owner（fence=1）心跳应失败（已被 fence=2 接管）
    assert await store_a.heartbeat("SF1:0", claim_a.fence_token, LEASE, STATE_TTL) is False
    # 新 owner（fence=2）心跳成功
    assert await store_b.heartbeat("SF1:0", claim_b.fence_token, LEASE, STATE_TTL) is True


async def test_set_terminal_rejects_stale_fence(fake_redis, clock):
    store_a = _store(fake_redis, clock, "pod-A")
    store_b = _store(fake_redis, clock, "pod-B")
    claim_a = await store_a.claim("SF1:0", LEASE, STATE_TTL)
    clock.advance(LEASE + 1)
    await store_b.claim("SF1:0", LEASE, STATE_TTL)
    # 老 owner 写终态应被 CAS 拒绝（fence 失配），不覆盖接管者
    ok = await store_a.set_terminal("SF1:0", claim_a.fence_token, "SUCCESS", {"stale": True}, STATE_TTL)
    assert ok is False


async def test_heartbeat_renews_lease(fake_redis, clock):
    store = _store(fake_redis, clock)
    claim = await store.claim("SF1:0", LEASE, STATE_TTL)
    clock.advance(LEASE - 5)
    assert await store.heartbeat("SF1:0", claim.fence_token, LEASE, STATE_TTL) is True
    # 续租后再推进，仍未过期 → 重复 claim 视为 PROCESSING
    clock.advance(10)
    dup = await store.claim("SF1:0", LEASE, STATE_TTL)
    assert dup.existing_status == "PROCESSING"


async def test_fence_ttl_covers_state_ttl(fake_redis, clock):
    store = _store(fake_redis, clock)
    await store.claim("SF1:0", LEASE, STATE_TTL)
    # fence 键 TTL 必须 ≥ state_ttl（R 修正），保证 token 单调
    assert await fake_redis.ttl(fence_key("SF1:0")) >= STATE_TTL


async def test_mark_reply_sent_cas(fake_redis, clock):
    store = _store(fake_redis, clock)
    claim = await store.claim("SF1:0", LEASE, STATE_TTL)
    await store.set_terminal("SF1:0", claim.fence_token, "SUCCESS", {"v": 1}, STATE_TTL)
    assert await store.mark_reply_sent("SF1:0", claim.fence_token, STATE_TTL) is True
    state = await store.get_state("SF1:0")
    assert state["reply_sent"] is True
