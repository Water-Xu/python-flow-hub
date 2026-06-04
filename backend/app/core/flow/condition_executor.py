"""分支节点路径激活逻辑（同步编排，决策 10）。

纯逻辑已下沉到 pyflow_runtime.flow_dag，控制面与 runner 共享单一来源。
"""

from __future__ import annotations

from pyflow_runtime.flow_dag import resolve_branch

__all__ = ["resolve_branch"]
