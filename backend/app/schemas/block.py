"""Block 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Port(BaseModel):
    name: str
    type: str = "any"
    required: bool = False


class EntrypointInfo(BaseModel):
    """脚本入口函数元信息（由 AST 扫描得出，可由用户补充描述）。"""

    name: str
    description: str = ""
    params: list[str] = []


class BlockComputeConfig(BaseModel):
    cpu_request: str = "100m"
    memory_request: str = "256Mi"
    cpu_limit: str = "1000m"
    memory_limit: str = "1Gi"
    gpu_enabled: bool = False
    gpu_type: str | None = None
    gpu_count: int = 1
    cuda_version: str = "12.2"
    use_spot_nodes: bool = True
    max_execution_time: int = 3600


class BlockCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    type: Literal["script", "notebook", "gcp_bigquery", "gcp_storage"] = "script"
    draft_code: str = ""
    input_ports: list[Port] = []
    output_ports: list[Port] = []
    env_vars: dict[str, str] = {}
    execution_mode: Literal["sync_http", "async_mq", "both"] = "sync_http"
    mq_config: dict[str, Any] = {}
    compute_config: BlockComputeConfig = BlockComputeConfig()


class BlockUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    draft_code: str | None = None
    input_ports: list[Port] | None = None
    output_ports: list[Port] | None = None
    env_vars: dict[str, str] | None = None
    execution_mode: Literal["sync_http", "async_mq", "both"] | None = None
    mq_config: dict[str, Any] | None = None
    compute_config: BlockComputeConfig | None = None


class BlockResponse(BaseModel):
    id: str
    name: str
    description: str
    owner_login_id: str
    type: str
    draft_code: str
    input_ports: list[Any]
    output_ports: list[Any]
    entrypoints: list[Any] = []
    execution_mode: str
    mq_config: dict[str, Any]
    compute_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BlockRunRequest(BaseModel):
    inputs: dict[str, Any] = {}
    # 调用脚本中的哪个入口函数（默认 run，支持一脚本多函数）
    entrypoint: str | None = None
