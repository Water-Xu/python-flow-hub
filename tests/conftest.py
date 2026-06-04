"""pyflow_runtime 单测公共夹具（AIR：全自动 / 独立 / 可重复，零外部服务）。

提供一个纯 Python 的异步 Redis 假实现 FakeAsyncRedis：
- 覆盖 IdempotencyStore 用到的 incr / expire / set(nx,ex) / get / eval；
- eval 按 idempotency 模块内的脚本常量身份分发，逐条复刻 Lua 语义（CAS / fence 单调 / 接管），
  从而无需 lupa/cjson 即可验证幂等状态机的 Python 编排正确性。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# 让测试可直接 import pyflow_runtime（仓库根加入 sys.path）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# 让测试可直接 import app.*（控制面 backend 加入 sys.path）
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from pyflow_runtime import idempotency as _idem  # noqa: E402


class FakeAsyncRedis:
    """最小可用的异步 Redis 假实现（支持 TTL 与本模块用到的 Lua 脚本语义）。"""

    def __init__(self, *, clock=None) -> None:
        self._data: dict[str, str] = {}
        self._expire_at: dict[str, float] = {}
        self._clock = clock or time.time

    # ── 过期处理 ──────────────────────────────────────────────────────────
    def _now(self) -> float:
        return self._clock()

    def _evict(self, key: str) -> None:
        exp = self._expire_at.get(key)
        if exp is not None and exp <= self._now():
            self._data.pop(key, None)
            self._expire_at.pop(key, None)

    # ── 基础命令 ──────────────────────────────────────────────────────────
    async def incr(self, key: str) -> int:
        self._evict(key)
        val = int(self._data.get(key, "0")) + 1
        self._data[key] = str(val)
        return val

    async def expire(self, key: str, ttl: int) -> bool:
        self._evict(key)
        if key in self._data:
            self._expire_at[key] = self._now() + int(ttl)
            return True
        return False

    async def set(self, key: str, value, *, nx: bool = False, ex: int | None = None) -> bool | None:
        self._evict(key)
        if nx and key in self._data:
            return None
        self._data[key] = value if isinstance(value, str) else json.dumps(value)
        if ex is not None:
            self._expire_at[key] = self._now() + int(ex)
        return True

    async def get(self, key: str):
        self._evict(key)
        return self._data.get(key)

    async def ttl(self, key: str) -> int:
        self._evict(key)
        if key not in self._data:
            return -2
        exp = self._expire_at.get(key)
        return int(exp - self._now()) if exp is not None else -1

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    # ── eval 分发（按脚本常量身份复刻 Lua 语义）─────────────────────────────
    async def eval(self, script: str, numkeys: int, *args):
        keys = list(args[:numkeys])
        argv = [str(a) for a in args[numkeys:]]
        if script == _idem._LUA_TAKE_OVER:
            return await self._take_over(keys, argv)
        if script == _idem._LUA_HEARTBEAT:
            return await self._heartbeat(keys, argv)
        if script == _idem._LUA_SET_TERMINAL:
            return await self._set_terminal(keys, argv)
        if script == _idem._LUA_MARK_REPLY:
            return await self._mark_reply(keys, argv)
        raise NotImplementedError("unknown lua script in FakeAsyncRedis")

    async def _take_over(self, keys, argv):
        state_key, fence_key = keys
        now, pod, lease_ttl, state_ttl, fence_ttl = (
            float(argv[0]), argv[1], int(argv[2]), int(argv[3]), int(argv[4])
        )
        cur = await self.get(state_key)
        if cur:
            st = json.loads(cur)
            if st.get("status") == "PROCESSING" and float(st.get("lease_expire_at", 0)) > now:
                return None
        fence = await self.incr(fence_key)
        await self.expire(fence_key, fence_ttl)
        val = json.dumps({
            "status": "PROCESSING", "owner_pod": pod,
            "fence_token": fence, "lease_expire_at": now + lease_ttl,
        })
        await self.set(state_key, val, ex=state_ttl)
        return fence

    async def _heartbeat(self, keys, argv):
        (state_key,) = keys
        fence, pod, now, lease_ttl, state_ttl = (
            int(argv[0]), argv[1], float(argv[2]), int(argv[3]), int(argv[4])
        )
        cur = await self.get(state_key)
        if not cur:
            return 0
        st = json.loads(cur)
        if int(st.get("fence_token", -1)) != fence or st.get("owner_pod") != pod:
            return 0
        st["lease_expire_at"] = now + lease_ttl
        await self.set(state_key, json.dumps(st), ex=state_ttl)
        return 1

    async def _set_terminal(self, keys, argv):
        (state_key,) = keys
        fence, pod, status, result_json, state_ttl = (
            int(argv[0]), argv[1], argv[2], argv[3], int(argv[4])
        )
        cur = await self.get(state_key)
        if not cur:
            return 0
        st = json.loads(cur)
        if int(st.get("fence_token", -1)) != fence or st.get("owner_pod") != pod:
            return 0
        st["status"] = status
        st["result"] = json.loads(result_json)
        st["reply_sent"] = False
        await self.set(state_key, json.dumps(st), ex=state_ttl)
        return 1

    async def _mark_reply(self, keys, argv):
        (state_key,) = keys
        fence, pod, state_ttl = int(argv[0]), argv[1], int(argv[2])
        cur = await self.get(state_key)
        if not cur:
            return 0
        st = json.loads(cur)
        if int(st.get("fence_token", -1)) != fence or st.get("owner_pod") != pod:
            return 0
        st["reply_sent"] = True
        await self.set(state_key, json.dumps(st), ex=state_ttl)
        return 1


class MutableClock:
    """可手动推进的时钟，用于测试 lease 过期 / 接管。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def fake_redis(clock: MutableClock) -> FakeAsyncRedis:
    return FakeAsyncRedis(clock=clock)
