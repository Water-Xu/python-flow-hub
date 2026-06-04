"""PyFlowHub 执行侧共享库（决策 3.1 模型 A）。

控制面（dev local）与 runner 镜像（prod）的单一来源；两侧必须安装同一 pin 死版本，
避免控制面 ↔ 已部署镜像逻辑漂移。
"""

# pin 死版本：禁止范围号 / latest（决策 3.1 点 5）
__version__ = "0.1.0"

# 队列/退避命名、消息 header、回复契约、幂等键格式的契约版本号。
# 写入每条消息头与 Block Deployment 部署元数据（label pyflow.runtime/protocol）。
RUNTIME_PROTOCOL_VERSION = "1"

from pyflow_runtime.condition_engine import evaluate_condition  # noqa: E402
from pyflow_runtime.input_mapper import map_inputs  # noqa: E402
from pyflow_runtime.reply_builder import build_reply, render_reply_routing_key  # noqa: E402

__all__ = [
    "__version__",
    "RUNTIME_PROTOCOL_VERSION",
    "evaluate_condition",
    "map_inputs",
    "build_reply",
    "render_reply_routing_key",
]
