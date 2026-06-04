"""退避/重试队列拓扑命名与参数（决策 6）。"""

from __future__ import annotations

from pyflow_runtime import backoff_queue as bq


def test_queue_names():
    assert bq.main_queue("b1") == "block.b1.queue"
    assert bq.dlq_queue("b1") == "block.b1.dlq"
    assert bq.backoff_queue("b1") == "block.b1.backoff"
    assert bq.dead_queue("b1") == "block.b1.dead"


def test_main_queue_dead_letters_to_dlq():
    args = bq.queue_arguments("b1", 5000)
    assert args["x-dead-letter-routing-key"] == "block.b1.dlq"


def test_dlq_has_ttl_and_routes_back_to_main():
    args = bq.dlq_arguments("b1", 5000)
    assert args["x-message-ttl"] == 5000
    assert args["x-dead-letter-routing-key"] == "block.b1.queue"


def test_backoff_short_ttl_routes_back_to_main():
    args = bq.backoff_arguments("b1")
    assert args["x-message-ttl"] == bq.DEFAULT_BACKOFF_TTL_MS
    assert args["x-dead-letter-routing-key"] == "block.b1.queue"
