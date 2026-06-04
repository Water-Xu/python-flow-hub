"""API Portal 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PublishApiRequest(BaseModel):
    """发布流程为接口。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    path: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    tags: str = ""
    flow_id: str


class ApiPolicyRequest(BaseModel):
    """更新限流 / 负载均衡 / 降级策略。"""

    rate_limit_enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)
    load_balance_strategy: str | None = None
    degradation_enabled: bool | None = None
    degradation_fallback: dict[str, Any] | None = None


class LockApiRequest(BaseModel):
    lock_reason: str = ""


class SwitchVersionRequest(BaseModel):
    """平滑过渡：将接口的实际调用流程切换到新版本。"""

    new_flow_id: str


class ApiResponse(BaseModel):
    id: str
    name: str
    description: str
    path: str
    tags: str
    flow_id: str
    active_flow_id: str | None
    owner_login_id: str
    status: str
    is_locked: bool
    lock_reason: str | None
    locked_by: str | None
    locked_at: str | None
    rate_limit_enabled: bool
    rate_limit_per_minute: int
    load_balance_strategy: str
    degradation_enabled: bool
    degradation_fallback: dict
    total_calls: int
    success_calls: int
    error_calls: int
    avg_latency_ms: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiInstanceInfo(BaseModel):
    """接口实例信息（Phase 4+ 实时查 K8s；当前 dev 返回占位）。"""

    deployment_mode: str
    instance_count: int
    instances: list[dict]
