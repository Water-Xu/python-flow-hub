"""条件求值引擎（决策 1/10）。

只允许 jmespath / jsonpath，python 选项从类型定义中彻底移除，杜绝 eval RCE。
同步编排（控制面 condition_executor）与异步编舞（reply_builder / router runner）共用本引擎，
保证语义一致。
"""

from __future__ import annotations

from typing import Any

import jmespath
from jsonpath_ng.ext import parse as jsonpath_parse

# 防御性上限：超大表达式直接拒绝，避免恶意 JSONPath DoS
MAX_EXPRESSION_LENGTH = 4096


class ConditionError(ValueError):
    """条件表达式非法或求值失败。"""


def _truthy(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) > 0
    return bool(value)


def evaluate_condition(expression: str, language: str, payload: dict[str, Any]) -> bool:
    """对消息 payload 求值条件表达式，返回布尔结果。

    :param expression: 条件表达式（jmespath 或 jsonpath 语法）
    :param language: "jmespath" | "jsonpath"
    :param payload: 待求值的消息体
    :raises ConditionError: 语言不支持 / 表达式非法
    """
    if not expression:
        return True
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ConditionError("condition expression too long")

    if language == "jmespath":
        try:
            return _truthy(jmespath.search(expression, payload))
        except Exception as exc:  # noqa: BLE001
            raise ConditionError(f"invalid jmespath: {exc}") from exc

    if language == "jsonpath":
        try:
            matches = [m.value for m in jsonpath_parse(expression).find(payload)]
        except Exception as exc:  # noqa: BLE001
            raise ConditionError(f"invalid jsonpath: {exc}") from exc
        if not matches:
            return False
        return all(_truthy(m) for m in matches)

    raise ConditionError(f"unsupported condition_language: {language}")


def extract_path(path: str, payload: dict[str, Any], language: str = "jsonpath") -> Any:
    """按路径从 payload 取值（用于 input_mapping / carry_fields）。"""
    if language == "jmespath":
        return jmespath.search(path, payload)
    matches = [m.value for m in jsonpath_parse(path).find(payload)]
    if not matches:
        return None
    return matches[0] if len(matches) == 1 else matches
