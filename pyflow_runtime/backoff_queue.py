"""退避重入队列（决策 6，防 KEDA 抖动）。

队列以接口/Flow 维度命名（flow.{scope_id}.*，scope_id 即 PublishedApi.id）。
owner 存活 / 接管竞争失败时不裸 requeue（会抖动队列 + KEDA 误扩），
改投递到短 TTL 的延迟重入队列（flow.{scope_id}.backoff），DLX 指回主队列。
"""

from __future__ import annotations

DEFAULT_BACKOFF_TTL_MS = 2000


def main_queue(scope_id: str) -> str:
    return f"flow.{scope_id}.queue"


def dlq_queue(scope_id: str) -> str:
    return f"flow.{scope_id}.dlq"


def dead_queue(scope_id: str) -> str:
    return f"flow.{scope_id}.dead"


def backoff_queue(scope_id: str) -> str:
    return f"flow.{scope_id}.backoff"


def queue_arguments(scope_id: str, retry_delay_ms: int) -> dict:
    """主队列声明参数：失败经 DLX 路由到 dlq。"""
    return {
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": dlq_queue(scope_id),
    }


def dlq_arguments(scope_id: str, retry_delay_ms: int) -> dict:
    """DLQ 设 TTL，到期经 DLX 回主队列（重投时 x-retry-count+1）。"""
    return {
        "x-message-ttl": retry_delay_ms,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": main_queue(scope_id),
    }


def backoff_arguments(scope_id: str, backoff_ttl_ms: int = DEFAULT_BACKOFF_TTL_MS) -> dict:
    """退避队列短 TTL，到期 DLX 指回主队列；退避期间不计入主队列 ready 深度。"""
    return {
        "x-message-ttl": backoff_ttl_ms,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": main_queue(scope_id),
    }
