"""状态机式幂等 + fence_token CAS（决策 5/7）。

区分"在跑（owner 存活）"、"owner 已死可接管"、"已终态"三类，解决去重与崩溃恢复的矛盾。
所有同 idempotency_id 的 key 用 {idempotency_id} 作 Redis hash tag，强制同 slot，杜绝 CROSSSLOT。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

# 跨 key 的 Lua 脚本只操作同一 hash tag 下的 key（CI 校验 KEYS 同 slot）
_LUA_TAKE_OVER = """
local cur = redis.call('GET', KEYS[1])
if cur then
  local st = cjson.decode(cur)
  if st.status == 'PROCESSING' and tonumber(st.lease_expire_at) > tonumber(ARGV[1]) then
    return nil
  end
end
local fence = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[5])
local val = cjson.encode({status='PROCESSING', owner_pod=ARGV[2],
  fence_token=fence, lease_expire_at=tonumber(ARGV[1]) + tonumber(ARGV[3])})
redis.call('SET', KEYS[1], val, 'EX', ARGV[4])
return fence
"""

_LUA_HEARTBEAT = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
local st = cjson.decode(cur)
if st.fence_token ~= tonumber(ARGV[1]) or st.owner_pod ~= ARGV[2] then
  return 0
end
st.lease_expire_at = tonumber(ARGV[3]) + tonumber(ARGV[4])
redis.call('SET', KEYS[1], cjson.encode(st), 'EX', ARGV[5])
return 1
"""

_LUA_SET_TERMINAL = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
local st = cjson.decode(cur)
if st.fence_token ~= tonumber(ARGV[1]) or st.owner_pod ~= ARGV[2] then
  return 0
end
st.status = ARGV[3]
st.result = cjson.decode(ARGV[4])
st.reply_sent = false
redis.call('SET', KEYS[1], cjson.encode(st), 'EX', ARGV[5])
return 1
"""

# 标记回复已发出（CAS 校验 fence_token+owner），用于"至少一次回复"降重（决策 6）
_LUA_MARK_REPLY = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
local st = cjson.decode(cur)
if st.fence_token ~= tonumber(ARGV[1]) or st.owner_pod ~= ARGV[2] then
  return 0
end
st.reply_sent = true
redis.call('SET', KEYS[1], cjson.encode(st), 'EX', ARGV[3])
return 1
"""


def extract_business_id(message_body: dict[str, Any], message_id: str | None = None) -> str:
    """优先取 $.header.snowflakeId，缺失回退 message_id，再缺失用 body sha256。"""
    header = message_body.get("header") or {}
    snowflake = header.get("snowflakeId")
    if snowflake:
        return str(snowflake)
    if message_id:
        return message_id
    raw = json.dumps(message_body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_idempotency_id(business_id: str, retry_count: int) -> str:
    """idempotency_id = 业务ID + ":" + 本队列本地 x-retry-count（决策 6/7）。"""
    return f"{business_id}:{retry_count}"


def state_key(idem_id: str) -> str:
    # {idem_id} 是字面 hash tag，确保与 fence_key 同 slot
    return f"pyflow:exec:state:{{{idem_id}}}"


def fence_key(idem_id: str) -> str:
    return f"pyflow:exec:fence:{{{idem_id}}}"


@dataclass
class ClaimResult:
    claimed: bool
    fence_token: int | None
    existing_status: str | None
    existing_result: Any | None


class IdempotencyStore:
    """基于 Redis 的幂等状态机。redis 为 redis.asyncio 客户端（单机或 Cluster）。"""

    def __init__(self, redis: Any, pod_name: str, *, time_fn: Any = time.time):
        self.redis = redis
        self.pod_name = pod_name
        # 注入时钟便于单测确定性地推进 lease 过期（AIR：可重复）
        self._now = time_fn

    async def claim(self, idem_id: str, lease_ttl: int, state_ttl: int) -> ClaimResult:
        """抢占执行权。返回是否抢到及 fence_token。"""
        sk = state_key(idem_id)
        fk = fence_key(idem_id)

        fence_token = await self.redis.incr(fk)
        # R 修正：fence 键 TTL 必须 ≥ state_ttl，防过期重置破坏单调性
        await self.redis.expire(fk, state_ttl + 60)

        now = int(self._now())
        value = json.dumps({
            "status": "PROCESSING",
            "owner_pod": self.pod_name,
            "fence_token": fence_token,
            "lease_expire_at": now + lease_ttl,
        })
        claimed = await self.redis.set(sk, value, nx=True, ex=state_ttl)
        if claimed:
            return ClaimResult(True, fence_token, None, None)

        raw = await self.redis.get(sk)
        state = json.loads(raw) if raw else {}
        status = state.get("status")

        if status == "SUCCESS":
            return ClaimResult(False, None, "SUCCESS", state.get("result"))
        if status == "PROCESSING" and state.get("lease_expire_at", 0) > now:
            return ClaimResult(False, None, "PROCESSING", None)

        # PROCESSING 但 lease 过期 / FAILED → CAS 接管
        new_token = await self.try_take_over(idem_id, lease_ttl, state_ttl)
        if new_token is None:
            return ClaimResult(False, None, "PROCESSING", None)
        return ClaimResult(True, new_token, None, None)

    async def try_take_over(self, idem_id: str, lease_ttl: int, state_ttl: int) -> int | None:
        now = int(self._now())
        result = await self.redis.eval(
            _LUA_TAKE_OVER, 2, state_key(idem_id), fence_key(idem_id),
            now, self.pod_name, lease_ttl, state_ttl, state_ttl + 60,
        )
        return int(result) if result is not None else None

    async def heartbeat(self, idem_id: str, fence_token: int, lease_ttl: int, state_ttl: int) -> bool:
        now = int(self._now())
        ok = await self.redis.eval(
            _LUA_HEARTBEAT, 1, state_key(idem_id),
            fence_token, self.pod_name, now, lease_ttl, state_ttl,
        )
        return bool(ok)

    async def set_terminal(self, idem_id: str, fence_token: int, status: str,
                           result: Any, state_ttl: int) -> bool:
        ok = await self.redis.eval(
            _LUA_SET_TERMINAL, 1, state_key(idem_id),
            fence_token, self.pod_name, status,
            json.dumps(result), state_ttl,
        )
        return bool(ok)

    async def get_state(self, idem_id: str) -> dict[str, Any] | None:
        """读取当前幂等状态（用于重复投递时判断 reply_sent / 复用 result）。"""
        raw = await self.redis.get(state_key(idem_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    async def mark_reply_sent(self, idem_id: str, fence_token: int, state_ttl: int) -> bool:
        """CAS 标记回复已发出（决策 6：至少一次回复 + reply_sent 降重）。"""
        ok = await self.redis.eval(
            _LUA_MARK_REPLY, 1, state_key(idem_id),
            fence_token, self.pod_name, state_ttl,
        )
        return bool(ok)
