"""消费者编排（决策 6/7）：成功/条件跳过/失败重试/重复回复/退避/接管/协议。"""

from __future__ import annotations

import asyncio
import json

from pyflow_runtime import consumer as C
from pyflow_runtime.consumer import consume_with_idempotency, protocol_compatible
from pyflow_runtime.idempotency import IdempotencyStore, state_key

REPLY_MQ = {
    "reply_enabled": True,
    "reply_routing_key_template": "reply.{block_id}",
    "carry_fields": [{"source_path": "$.header.snowflakeId",
                      "target_field": "snowflakeId", "required": False}],
}


def _store(fake_redis, clock, pod="pod-A"):
    return IdempotencyStore(fake_redis, pod, time_fn=clock)


def _capturing_publisher():
    captured: list = []

    async def _publish(reply, cfg):
        captured.append(reply)

    return _publish, captured


def test_protocol_compatible_rules():
    assert protocol_compatible({}) is True                       # 缺失 → 宽松兼容
    assert protocol_compatible({"pyflow-protocol": "1"}) is True
    assert protocol_compatible({"pyflow-protocol": "999"}) is False


async def test_success_publishes_reply_and_marks_sent(fake_redis, clock):
    store = _store(fake_redis, clock)
    publish, captured = _capturing_publisher()
    body = {"header": {"snowflakeId": "SF1"}}
    block = {"mq_config": REPLY_MQ, "compute_config": {}}

    async def execute_fn(inputs):
        return {"value": 42}

    action = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m1", reply_publisher=publish
    )
    assert action == "ack"
    assert len(captured) == 1
    assert captured[0]["snowflakeId"] == "SF1"
    assert captured[0]["result"] == {"value": 42}
    state = await store.get_state("SF1:0")
    assert state["status"] == "SUCCESS"
    assert state["reply_sent"] is True


async def test_condition_not_satisfied_skips(fake_redis, clock):
    store = _store(fake_redis, clock)
    publish, captured = _capturing_publisher()
    body = {"header": {"type": "refund"}}
    block = {"mq_config": {"condition_expression": "header.type == 'order'",
                           "condition_language": "jmespath"}, "compute_config": {}}

    called = {"n": 0}

    async def execute_fn(inputs):
        called["n"] += 1
        return {"value": 1}

    action = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m2", reply_publisher=publish
    )
    assert action == "ack"
    assert called["n"] == 0          # 条件不命中：不执行
    assert captured == []            # 不发回复
    # 无 snowflakeId → business_id 回退 message_id="m2"，idem_id="m2:0"
    state = await store.get_state("m2:0")
    assert state["result"] == {"skipped": True}


async def test_execution_failure_returns_nack(fake_redis, clock):
    store = _store(fake_redis, clock)
    body = {"header": {"snowflakeId": "SF3"}}
    block = {"mq_config": {}, "compute_config": {}}

    async def execute_fn(inputs):
        raise RuntimeError("boom")

    action = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m3"
    )
    assert action == "nack"
    state = await store.get_state("SF3:0")
    assert state["status"] == "FAILED"


async def test_duplicate_success_republishes_once(fake_redis, clock):
    store = _store(fake_redis, clock)
    publish, captured = _capturing_publisher()
    body = {"header": {"snowflakeId": "SF4"}}
    block = {"mq_config": REPLY_MQ, "compute_config": {}}

    # 预置 SUCCESS 终态（reply_sent=False），模拟"回复未发即崩"
    claim = await store.claim("SF4:0", 30, 600)
    await store.set_terminal("SF4:0", claim.fence_token, "SUCCESS", {"value": 7}, 600)

    async def execute_fn(inputs):  # 不应被调用
        raise AssertionError("should not execute on duplicate")

    # 第一次重复投递：补发回复一次（至少一次）
    a1 = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m4", reply_publisher=publish
    )
    assert a1 == "ack"
    assert len(captured) == 1

    # 第二次重复投递：reply_sent 已置位 → 不再补发（降重）
    a2 = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m4", reply_publisher=publish
    )
    assert a2 == "ack"
    assert len(captured) == 1


async def test_processing_alive_returns_backoff(fake_redis, clock):
    store_a = _store(fake_redis, clock, "pod-A")
    store_b = _store(fake_redis, clock, "pod-B")
    body = {"header": {"snowflakeId": "SF5"}}
    block = {"mq_config": {}, "compute_config": {}}

    await store_a.claim("SF5:0", 30, 600)  # A 正在跑

    async def execute_fn(inputs):
        return {"value": 1}

    action = await consume_with_idempotency(
        body, {}, block, store_b, execute_fn, message_id="m5"
    )
    assert action == "backoff"


async def test_lease_lost_during_execution_returns_backoff(fake_redis, clock, monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_LEASE_TTL", 3)   # 心跳间隔 1s，加速测试
    store = _store(fake_redis, clock, "pod-A")
    body = {"header": {"snowflakeId": "SF6"}}
    block = {"mq_config": {}, "compute_config": {}}

    async def execute_fn(inputs):
        # 执行期间被其他副本接管：篡改 state 的 owner/fence
        idem = "SF6:0"
        st = json.loads(await fake_redis.get(state_key(idem)))
        st["owner_pod"] = "pod-B"
        st["fence_token"] = int(st["fence_token"]) + 1
        await fake_redis.set(state_key(idem), json.dumps(st), ex=600)
        await asyncio.sleep(5)
        return {"value": 1}

    action = await consume_with_idempotency(
        body, {}, block, store, execute_fn, message_id="m6"
    )
    assert action == "backoff"
