"""Flow 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FlowNodeSchema(BaseModel):
    id: str | None = None
    node_type: Literal["block", "condition_branch", "input", "note"] = "block"
    block_id: str | None = None
    config: dict[str, Any] = {}
    position: dict[str, float] = {}


class FlowEdgeSchema(BaseModel):
    id: str | None = None
    source_node_id: str
    target_node_id: str
    source_port: str = "output"
    target_port: str = "input"


class FlowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class FlowGraphRequest(BaseModel):
    """保存画布：节点 + 边（保存时做 DAG 无环校验）。"""

    nodes: list[FlowNodeSchema] = []
    edges: list[FlowEdgeSchema] = []
    # 单一 API 入口节点 ID（None 表示未指定，所有根节点均为入口）
    entry_node_id: str | None = None


class FlowResponse(BaseModel):
    id: str
    name: str
    description: str
    owner_login_id: str
    source: str = "blank"
    entry_node_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlowDetailResponse(FlowResponse):
    nodes: list[Any] = []
    edges: list[Any] = []
    tree: dict[str, Any] = {}
    resources: dict[str, Any] = {}


class FlowRunRequest(BaseModel):
    inputs: dict[str, Any] = {}


class FlowImportResponse(BaseModel):
    """zip 导入结果摘要。"""

    flow_id: str
    name: str
    block_count: int
    resource_count: int
