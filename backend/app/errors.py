"""错误码规范（对齐现有平台分段，pyflow 子区间 x18xx）。

号段：1xxxx 认证 / 4xxxx 请求 / 5xxxx 系统；pyflow 用每段内 x18xx 子区间避免冲突。
配套 i18n key lang.pyflow.{模块}.xxx，由 yml + 拦截器渲染。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

# 认证类 1xxxx —— pyflow 子区间 11800~11899
PYFLOW_AUTH_UNAUTHORIZED = (11801, "lang.pyflow.auth.unauthorized")
PYFLOW_AUTH_FORBIDDEN = (11802, "lang.pyflow.auth.forbidden")

# 请求错误 4xxxx —— pyflow 子区间 41800~41899
PYFLOW_BLOCK_NOT_FOUND = (41801, "lang.pyflow.block.not_found")
PYFLOW_FLOW_NOT_FOUND = (41802, "lang.pyflow.flow.not_found")
PYFLOW_VERSION_NOT_STABLE = (41803, "lang.pyflow.version.not_stable")
PYFLOW_EXEC_INPUT_INVALID = (41804, "lang.pyflow.exec.input_invalid")
PYFLOW_FLOW_DAG_INVALID = (41805, "lang.pyflow.flow.dag_invalid")
PYFLOW_FORBIDDEN_RESOURCE = (41806, "lang.pyflow.resource.forbidden")
PYFLOW_FLOW_IN_USE = (41807, "lang.pyflow.flow.in_use")

# 接口管理 4xxxx —— 41810~41819
PYFLOW_API_NOT_FOUND = (41810, "lang.pyflow.api.not_found")
PYFLOW_API_LOCKED = (41811, "lang.pyflow.api.locked")
PYFLOW_API_RATE_LIMITED = (41812, "lang.pyflow.api.rate_limited")
PYFLOW_API_PATH_EXISTS = (41813, "lang.pyflow.api.path_exists")

# 系统异常 5xxxx（网关统一友好提示）—— pyflow 子区间 51800~51899
PYFLOW_EXEC_TIMEOUT = (51801, "lang.pyflow.exec.timeout")
PYFLOW_EXEC_SANDBOX_ERROR = (51802, "lang.pyflow.exec.sandbox_error")
PYFLOW_K8S_DEPLOY_FAILED = (51803, "lang.pyflow.k8s.deploy_failed")
PYFLOW_MQ_PUBLISH_FAILED = (51804, "lang.pyflow.mq.publish_failed")


class BusinessException(Exception):
    """业务异常，统一携带错误码 + i18n key（安全规范：对外不暴露敏感信息）。"""

    def __init__(self, error: tuple[int, str], detail: str | None = None):
        self.code, self.msg_key = error
        self.detail = detail
        super().__init__(f"{self.code}:{self.msg_key}")

    @property
    def http_status(self) -> int:
        seg = self.code // 10000
        return {1: 401, 4: 400, 5: 500}.get(seg, 400)


async def business_exception_handler(_: Request, exc: BusinessException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "msgKey": exc.msg_key, "detail": exc.detail},
    )
