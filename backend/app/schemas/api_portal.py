"""API Portal 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.config import get_settings


class PublishApiRequest(BaseModel):
    """发布流程为接口。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    path: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    tags: str = ""
    flow_id: str
    # API 级全局入口函数；None = 各节点保持自己的 config.entrypoint（或默认 run）
    entrypoint: str | None = None
    # 节点级入口函数映射 {node_id: entrypoint_name}，优先级高于全局 entrypoint。
    # 用于多个调用块含同名函数时分别指定各块入口。
    entrypoint_map: dict[str, str] = {}


class ApiMqConfigRequest(BaseModel):
    """更新接口触发方式与 MQ 触发配置（决策 3.1 Flow 级）。"""

    # http：仅同步 HTTP；mq：仅 MQ 异步触发；both：两者皆可
    trigger_type: Literal["http", "mq", "both"]
    mq_config: dict[str, Any] = {}


class ApiPolicyRequest(BaseModel):
    """更新限流 / 负载均衡 / 降级策略。"""

    rate_limit_enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)
    load_balance_strategy: str | None = None
    degradation_enabled: bool | None = None
    degradation_fallback: dict[str, Any] | None = None


class LockApiRequest(BaseModel):
    lock_reason: str = ""


class ApiEncryptionRequest(BaseModel):
    """启用/禁用接口加密保护（AES-256-GCM）。

    首次将 ``enabled`` 置为 True 时服务端自动生成密钥；置为 False 不会清空已有密钥，
    便于重新启用时复用。``require_encrypted_request`` 控制是否拒绝明文请求。
    """

    enabled: bool
    require_encrypted_request: bool = False


class ApiEncryptionKeyResponse(BaseModel):
    """加密密钥响应（仅接口创建者可见，禁止下发到公开文档）。"""

    api_id: str
    encryption_enabled: bool
    require_encrypted_request: bool
    # 完整密钥（64 字符 hex），用于配置到调用方（如 Java flowhub.encryption.path-keys）
    encryption_key: str | None = None
    # 密钥指纹（前 8 字符），用于在不暴露完整密钥的场景下核对
    key_hint: str | None = None


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
    trigger_type: str
    mq_config: dict
    entrypoint: str | None
    entrypoint_map: dict
    is_locked: bool
    lock_reason: str | None
    locked_by: str | None
    locked_at: str | None
    rate_limit_enabled: bool
    rate_limit_per_minute: int
    load_balance_strategy: str
    degradation_enabled: bool
    degradation_fallback: dict
    # 加密保护（不含密钥本身，密钥仅通过 /encryption/key 单独获取）
    encryption_enabled: bool
    require_encrypted_request: bool
    total_calls: int
    success_calls: int
    error_calls: int
    avg_latency_ms: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def invoke_path(self) -> str:
        """对外完整可调路径（含网关前缀），供门户卡片/复制直接使用。"""
        return f"{get_settings().public_api_prefix}/api/public/{self.path}"


class ApiInstanceInfo(BaseModel):
    """接口实例信息（Phase 4+ 实时查 K8s；当前 dev 返回占位）。"""

    deployment_mode: str
    instance_count: int
    instances: list[dict]
