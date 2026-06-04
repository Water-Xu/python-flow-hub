"""调用现有 Sa-Token 鉴权服务校验 token 并解析 loginId（决策 2）。

1a：auth_enabled=false 时直接返回 dev 默认用户兜底；
1b：经网关登录态校验后，FastAPI 内部用本客户端解析 loginId。
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.errors import PYFLOW_AUTH_UNAUTHORIZED, BusinessException

settings = get_settings()


async def resolve_login_id(token: str | None) -> str:
    """从 token 解析平台统一用户 ID。"""
    if not settings.auth_enabled:
        return settings.dev_default_login_id

    if not token:
        raise BusinessException(PYFLOW_AUTH_UNAUTHORIZED, "missing token")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                settings.satoken_verify_url,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            raise BusinessException(PYFLOW_AUTH_UNAUTHORIZED, "token verify failed")
        data = resp.json()
        login_id = data.get("loginId") or (data.get("data") or {}).get("loginId")
        if not login_id:
            raise BusinessException(PYFLOW_AUTH_UNAUTHORIZED, "loginId not resolved")
        return str(login_id)
    except httpx.HTTPError as exc:
        raise BusinessException(PYFLOW_AUTH_UNAUTHORIZED, f"auth service error: {exc}") from exc
