"""MQ 配置服务端校验（决策 1/6/10：拦截非法配置进入运行期）。

保存/更新 async_mq / both 块时校验：
- condition_expression 必须是合法 jmespath/jsonpath（杜绝运行期才暴露的语法错误，且绝不 eval）；
- input_mapping 必须是 dict[str, str]；
- reply_enabled 时必须指定 reply_routing_key_template 或 reply_exchange；
- carry_fields 每项必须含 source_path + target_field；
- max_retry / retry_delay_ms 取值合法。
非法即抛 BusinessException(PYFLOW_EXEC_INPUT_INVALID)。
"""

from __future__ import annotations

from typing import Any

from app.errors import PYFLOW_EXEC_INPUT_INVALID, BusinessException

_VALID_LANGUAGES = {"jmespath", "jsonpath"}


def _fail(detail: str) -> None:
    raise BusinessException(PYFLOW_EXEC_INPUT_INVALID, detail)


def validate_mq_config(mq_config: dict[str, Any] | None, execution_mode: str) -> None:
    """校验 MQ 配置；sync_http 块无需 mq_config 直接放行。"""
    if execution_mode not in ("async_mq", "both"):
        return
    cfg = mq_config or {}

    language = cfg.get("condition_language", "jmespath")
    if language not in _VALID_LANGUAGES:
        _fail(f"condition_language 必须为 jmespath/jsonpath，得到 {language}")

    expression = cfg.get("condition_expression")
    if expression:
        # 延迟导入，避免控制面强依赖 runtime 解析库的导入顺序
        from pyflow_runtime.condition_engine import ConditionError, evaluate_condition
        try:
            evaluate_condition(expression, language, {})
        except ConditionError as exc:
            _fail(f"条件表达式非法（{language}）：{exc}")

    input_mapping = cfg.get("input_mapping")
    if input_mapping is not None:
        if not isinstance(input_mapping, dict):
            _fail("input_mapping 必须是对象 {目标字段: 源路径}")
        for key, value in input_mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                _fail("input_mapping 的键与值都必须是字符串")

    if cfg.get("reply_enabled"):
        if not (cfg.get("reply_routing_key_template") or cfg.get("reply_exchange")):
            _fail("启用回复时必须指定 reply_routing_key_template 或 reply_exchange")
        for rule in cfg.get("carry_fields") or []:
            if not isinstance(rule, dict) or not rule.get("source_path") or not rule.get("target_field"):
                _fail("carry_fields 每项必须包含 source_path 与 target_field")

    max_retry = cfg.get("max_retry", 3)
    if not isinstance(max_retry, int) or not (0 <= max_retry <= 10):
        _fail("max_retry 必须是 0~10 的整数")

    retry_delay_ms = cfg.get("retry_delay_ms", 5000)
    if not isinstance(retry_delay_ms, int) or not (100 <= retry_delay_ms <= 600000):
        _fail("retry_delay_ms 必须是 100~600000 的整数（毫秒）")
