"""退避/重试队列拓扑命名与参数（决策 6）。

队列以接口/Flow 维度命名 flow.{api_id}.*（决策 3.1 重写为 Flow 级模型 A）：
跨流程版本切换时队列稳定，消费者每条消息按 active_flow_id 跑整条 DAG。
"""

from __future__ import annotations

from pyflow_runtime import backoff_queue as bq


def test_queue_names():
    assert bq.main_queue("api1") == "flow.api1.queue"
    assert bq.dlq_queue("api1") == "flow.api1.dlq"
    assert bq.backoff_queue("api1") == "flow.api1.backoff"
    assert bq.dead_queue("api1") == "flow.api1.dead"


def test_main_queue_dead_letters_to_dlq():
    args = bq.queue_arguments("api1", 5000)
    assert args["x-dead-letter-routing-key"] == "flow.api1.dlq"


def test_dlq_has_ttl_and_routes_back_to_main():
    args = bq.dlq_arguments("api1", 5000)
    assert args["x-message-ttl"] == 5000
    assert args["x-dead-letter-routing-key"] == "flow.api1.queue"


def test_backoff_short_ttl_routes_back_to_main():
    args = bq.backoff_arguments("api1")
    assert args["x-message-ttl"] == bq.DEFAULT_BACKOFF_TTL_MS
    assert args["x-dead-letter-routing-key"] == "flow.api1.queue"
