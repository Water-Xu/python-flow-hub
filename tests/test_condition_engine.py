"""条件引擎（决策 1/10）：仅 jmespath/jsonpath，杜绝 eval，边界/恶意输入防御。"""

from __future__ import annotations

import pytest

from pyflow_runtime.condition_engine import (
    MAX_EXPRESSION_LENGTH,
    ConditionError,
    evaluate_condition,
    extract_path,
)


def test_empty_expression_is_true():
    assert evaluate_condition("", "jmespath", {"a": 1}) is True


def test_jmespath_truthy_and_falsy():
    payload = {"header": {"type": "order"}}
    assert evaluate_condition("header.type == 'order'", "jmespath", payload) is True
    assert evaluate_condition("header.type == 'refund'", "jmespath", payload) is False


def test_jmespath_empty_list_is_falsy():
    assert evaluate_condition("items", "jmespath", {"items": []}) is False
    assert evaluate_condition("items", "jmespath", {"items": [1]}) is True


def test_jsonpath_match_and_nomatch():
    payload = {"data": {"value": 5}}
    assert evaluate_condition("$.data.value", "jsonpath", payload) is True
    assert evaluate_condition("$.data.missing", "jsonpath", payload) is False


def test_invalid_language_raises():
    with pytest.raises(ConditionError):
        evaluate_condition("a", "python", {"a": 1})


def test_invalid_jmespath_raises():
    with pytest.raises(ConditionError):
        evaluate_condition("a ===", "jmespath", {"a": 1})


def test_oversized_expression_rejected():
    huge = "a" * (MAX_EXPRESSION_LENGTH + 1)
    with pytest.raises(ConditionError):
        evaluate_condition(huge, "jmespath", {})


def test_extract_path_single_and_multi():
    payload = {"header": {"snowflakeId": "SF1"}, "items": [{"v": 1}, {"v": 2}]}
    assert extract_path("$.header.snowflakeId", payload) == "SF1"
    assert extract_path("$.items[*].v", payload) == [1, 2]
    assert extract_path("$.missing", payload) is None
