"""块 requirements.txt 策略：依赖白名单 + @wheel/@gcs 私有包引用（决策 11 / 供应链加固）。

与「pyflowhub_pack」方案对齐：
- 多模块逻辑打进 wheel，块脚本只做薄 wrapper；
- requirements 可含 @gcs: 或 @wheel: 行，Cloud Build 阶段拉取并 pip install；
- pip 包名需在白名单内（可配置关闭）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.errors import PYFLOW_EXEC_INPUT_INVALID, BusinessException

_WHEEL_PREFIX = "@wheel:"
_GCS_PREFIX = "@gcs:"
_COMMENT_OR_BLANK = re.compile(r"^\s*(#|$)")
_REQ_LINE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(?:\[[^\]]+\])?(?:\s*[=<>!~].*)?$"
)


@dataclass
class ParsedRequirements:
    wheel_refs: list[dict[str, str]]
    pypi_lines: list[str]
    pip_options: list[str]


def _split_csv(raw: str) -> set[str]:
    return {x.strip().lower() for x in (raw or "").split(",") if x.strip()}


def parse_requirements(text: str) -> ParsedRequirements:
    """解析 requirements：分离 @wheel/@gcs、pip 选项行与普通 PyPI 依赖。"""
    wheel_refs: list[dict[str, str]] = []
    pypi_lines: list[str] = []
    pip_options: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(_WHEEL_PREFIX):
            wheel_refs.append({"kind": "minio", "ref": stripped[len(_WHEEL_PREFIX):].strip()})
            continue
        if stripped.startswith(_GCS_PREFIX):
            wheel_refs.append({"kind": "gcs", "ref": stripped[len(_GCS_PREFIX):].strip()})
            continue
        if stripped.startswith("-") or stripped.startswith("--"):
            pip_options.append(stripped)
            continue
        pypi_lines.append(stripped)
    return ParsedRequirements(wheel_refs=wheel_refs, pypi_lines=pypi_lines, pip_options=pip_options)


def package_name(line: str) -> str:
    """从 requirements 行提取包名（小写）。"""
    token = line.split("#", 1)[0].strip()
    if "@" in token and not token.startswith("@"):
        token = token.split("@", 1)[0].strip()
    token = re.split(r"[=<>!~\[]", token, maxsplit=1)[0].strip()
    return token.lower()


def validate_requirements(text: str, settings: Settings) -> ParsedRequirements:
    """校验 requirements；启用白名单时拒绝未授权包。"""
    parsed = parse_requirements(text)
    if not settings.pip_require_whitelist:
        return parsed

    allowed = _split_csv(settings.pip_allowed_packages)
    sdist_ok = _split_csv(settings.pip_allow_sdist_packages)
    if not allowed:
        return parsed

    for line in parsed.pypi_lines:
        name = package_name(line)
        if not name:
            continue
        if name not in allowed and name.replace("_", "-") not in allowed:
            raise BusinessException(
                PYFLOW_EXEC_INPUT_INVALID,
                f"依赖包 {name} 不在白名单；请联系平台管理员加入 PYFLOW_PIP_ALLOWED_PACKAGES",
            )
        if name in sdist_ok or name.replace("_", "-") in sdist_ok:
            continue
    return parsed


def resolve_wheel_urls(parsed: ParsedRequirements, settings: Settings) -> list[str]:
    """将 @wheel/@gcs 引用解析为 Cloud Build 可 curl 的 URL 列表。"""
    urls: list[str] = []
    minio_ep = settings.effective_block_minio_endpoint().rstrip("/")
    bucket = settings.block_artifacts_bucket or "pyflow-artifacts"
    gcs_bucket = settings.effective_cloudbuild_staging_bucket()

    for item in parsed.wheel_refs:
        ref = item["ref"].lstrip("/")
        if item["kind"] == "minio":
            if not minio_ep:
                raise BusinessException(
                    PYFLOW_EXEC_INPUT_INVALID,
                    f"MinIO wheel 引用需要配置 MINIO  endpoint: {ref}",
                )
            urls.append(f"http://{minio_ep}/{bucket}/{ref}")
        else:
            urls.append(f"https://storage.googleapis.com/{gcs_bucket}/{ref}")
    return urls


def render_pypi_requirements(parsed: ParsedRequirements) -> str:
    """仅 PyPI 行 + pip 选项，供 Dockerfile requirements_pypi.txt。"""
    lines = list(parsed.pip_options) + list(parsed.pypi_lines)
    return "\n".join(lines) + ("\n" if lines else "")


def build_install_script(
    wheel_urls: list[str],
    *,
    allow_sdist: set[str],
    pypi_text: str,
    embed_wheels: bool = False,
) -> str:
    """生成 install_deps.sh（Cloud Build 上下文内执行；requirements_pypi.txt 单独 COPY）。

    embed_wheels=True 时跳过 curl（wheel 已通过 build context 打包进来），直接 pip install。
    """
    sdist_flags = " ".join(f"--no-binary {pkg}" for pkg in sorted(allow_sdist))
    lines = ["#!/bin/bash", "set -euo pipefail", "mkdir -p /tmp/wheels"]
    if wheel_urls:
        if embed_wheels:
            # wheels 已通过 context tarball 打包到 wheels/ 目录，直接安装
            lines.append("pip install --no-cache-dir /tmp/wheels/*.whl")
        else:
            for u in wheel_urls:
                fname = u.split("/")[-1]
                lines.append(f'curl -fsSL "{u}" -o "/tmp/wheels/{fname}"')
            lines.append("pip install --no-cache-dir /tmp/wheels/*.whl")
    lines.append("if [ -s /tmp/requirements_pypi.txt ]; then")
    if sdist_flags:
        lines.append(
            f"  pip install --no-cache-dir {sdist_flags} -r /tmp/requirements_pypi.txt || "
            "pip install --no-cache-dir -r /tmp/requirements_pypi.txt"
        )
    else:
        lines.append(
            "  pip install --no-cache-dir --only-binary :all: -r /tmp/requirements_pypi.txt || "
            "pip install --no-cache-dir -r /tmp/requirements_pypi.txt"
        )
    lines.append("fi")
    lines.append("")
    return "\n".join(lines)
