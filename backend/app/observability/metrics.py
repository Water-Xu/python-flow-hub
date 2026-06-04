"""Prometheus 自定义指标（决策 13，抓取走 GMP PodMonitoring / label 发现）。"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

EXEC_COUNT = Counter(
    "pyflow_execution_total", "块执行次数", ["block_id", "status"]
)
EXEC_DURATION = Histogram(
    "pyflow_execution_duration_seconds", "块执行耗时", ["block_id"]
)
FLOW_RUN_COUNT = Counter(
    "pyflow_flow_run_total", "整流执行次数", ["flow_id", "status"]
)
DEP_UP = Gauge(
    "pyflow_dependency_up", "依赖连通性（1=up,0=down）", ["dependency"]
)

# ── MQ 异步触发指标（决策 6/13）──────────────────────────────────────────────
MQ_CONSUMED = Counter(
    "pyflow_mq_consumed_total", "MQ 消息消费处置计数",
    ["block_id", "action"],   # action: ack | backoff | nack | protocol_reject
)
MQ_REPLY_PUBLISHED = Counter(
    "pyflow_mq_reply_published_total", "MQ 回复发布计数", ["block_id"]
)
MQ_QUEUE_DEPTH = Gauge(
    "pyflow_mq_queue_depth", "MQ 队列就绪深度（main/dlq）", ["block_id", "queue"]
)

# ── 版本双写对账（决策 8/13）────────────────────────────────────────────────
VERSION_RECONCILE = Gauge(
    "pyflow_version_reconcile",
    "版本双写对账：孤儿对象/悬挂指针/损坏数",
    ["kind"],   # kind: orphan_objects | missing_objects | corrupted
)

# ── K8s 部署与扩缩（决策 12/Phase 4a）──────────────────────────────────────
K8S_DEPLOY = Counter(
    "pyflow_k8s_deploy_total", "K8s 部署动作计数", ["action", "result"]
)
K8S_BLOCK_REPLICAS = Gauge(
    "pyflow_k8s_block_replicas", "Block Deployment 当前副本数", ["resource_prefix", "block_id"]
)
