"""沙箱安全配置常量（决策 1）。

控制面 core/sandbox 与 runner 镜像共享同一份，杜绝逻辑分叉。
- dev 本地：Docker + seccomp + cap_drop:ALL + 非 root + network:none，gVisor 仅 Linux 可选。
- prod：等价 Pod SecurityContext，由 manifest_generator 生成。
"""

from __future__ import annotations

import platform
import shutil
from typing import Any


def resolve_runtime(prefer_gvisor: bool = False) -> str | None:
    """解析 Docker runtime。

    仅 Linux 且显式开启且已安装 runsc 时返回 "runsc"；否则 None（标准 runc）。
    Windows/macOS 不支持 runsc，降级标准 Docker 隔离（仅开发调试）。
    """
    if not prefer_gvisor:
        return None
    if platform.system() != "Linux":
        return None
    if shutil.which("runsc") is None:
        return None
    return "runsc"


def build_docker_sandbox_config(prefer_gvisor: bool = False) -> dict[str, Any]:
    """dev 本地 Docker 沙箱安全配置（每次执行都应用）。"""
    return {
        "runtime": resolve_runtime(prefer_gvisor),
        "network_mode": "none",          # 默认断网，block 按需配置 NetworkPolicy
        "read_only": True,               # 只读根文件系统
        "tmpfs": {"/tmp": "size=100m"},
        "mem_limit": "1g",
        "cpu_period": 100000,
        "cpu_quota": 50000,              # 最多 0.5 核
        "security_opt": ["no-new-privileges", "seccomp=unconfined"],
        "cap_drop": ["ALL"],
        "user": "nobody",                # 非 root 用户
        "pids_limit": 256,               # 防 fork 炸弹
        # 不挂载任何宿主目录，代码通过环境变量或 stdin 注入
    }


# prod K8s 执行 Pod 的等价 SecurityContext（非 GPU 块附加 runtimeClassName: gvisor）
POD_SECURITY_CONTEXT: dict[str, Any] = {
    "runAsNonRoot": True,
    "runAsUser": 65534,                  # nobody
    "readOnlyRootFilesystem": True,
    "allowPrivilegeEscalation": False,
    "seccompProfile": {"type": "RuntimeDefault"},
    "capabilities": {"drop": ["ALL"]},
}

DEFAULT_EXECUTION_TIMEOUT_SECONDS = 300
