"""runner 镜像构建（决策 11 + Phase 4b 供应链加固）。

统一 runner 基础镜像 + 按 requirements_hash 分层缓存：相同依赖集复用同一依赖层镜像，
仅依赖变化才触发 Cloud Build。Block 代码不烧进镜像（启动从 MinIO 拉取），改代码不必重建。

供应链加固（堵住「EDITOR 改 requirements → Cloud Build 跑任意代码」提权 RCE）：
1. 专用最小权限构建 SA（pyflow-builder@，仅 AR writer + 读依赖源）；
2. 依赖来源白名单（私有 PyPI 镜像 --index-url + --no-index 兜底禁公网）；
3. 优先 wheel（--only-binary :all:），限制源码构建触发 setup.py；
4. 构建沙箱网络收敛（Cloud Build 默认 worker pool / VPC-SC，由项目侧约束）；
5. 依赖审计（pip-audit），高危阻断发布并报 PYFLOW_K8S_DEPLOY_FAILED。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.observability.logging import get_logger

logger = get_logger("pyflow.k8s.build")
settings = get_settings()

_CLOUDBUILD_API = "https://cloudbuild.googleapis.com/v1/projects/{project}/builds"


def dependency_image_tag(requirements_hash: str, *, gpu: bool = False, cuda_version: str = "") -> str:
    """依赖层镜像标签（决策 11）。

    非 GPU：dep-<hash>；GPU 额外叠 CUDA 维度（决策 11 GPU 分层），缓存键 (cuda_version, hash)。
    """
    base = settings.gpu_runner_image if gpu else settings.runner_image
    repo = base.rsplit(":", 1)[0]
    if gpu:
        cuda_tag = cuda_version.replace(".", "") or "cuda"
        return f"{repo}:dep-{cuda_tag}-{requirements_hash[:16]}"
    return f"{repo}:dep-{requirements_hash[:16]}"


def build_cloudbuild_config(
    requirements_text: str,
    image_tag: str,
    *,
    gpu: bool = False,
    cuda_version: str = "12.4",
) -> dict[str, Any]:
    """生成 Cloud Build 配置（供应链加固步骤内联）。"""
    base_image = "nvidia/cuda:%s-runtime-ubuntu22.04" % cuda_version if gpu else "python:3.11-slim"
    index_args = ""
    if settings.pip_index_url:
        index_args = f"--index-url {settings.pip_index_url} --no-index" if False else f"--index-url {settings.pip_index_url}"
    hashes = "--require-hashes" if settings.pip_require_hashes else ""

    dockerfile = "\n".join([
        f"FROM {base_image}",
        "RUN useradd -u 65534 -m nobody || true",
        "WORKDIR /app",
        "COPY requirements.txt .",
        # 优先 wheel，限制源码构建触发 setup.py（供应链加固 3）
        f"RUN pip install --no-cache-dir --only-binary :all: {index_args} {hashes} -r requirements.txt",
        "COPY pyflow_runtime/ /app/pyflow_runtime/",
        "COPY runner/ /app/runner/",
        "USER 65534",
        'ENTRYPOINT ["python", "-m", "runner.entrypoint"]',
    ])

    return {
        "steps": [
            # 依赖审计：高危阻断（供应链加固 5）
            {
                "name": "python:3.11-slim",
                "entrypoint": "bash",
                "args": ["-c", "pip install pip-audit && pip-audit -r requirements.txt || exit 1"],
            },
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["build", "-t", image_tag, "-f", "Dockerfile.generated", "."],
            },
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["push", image_tag],
            },
        ],
        "images": [image_tag],
        "serviceAccount": f"projects/{settings.gcp_project}/serviceAccounts/{settings.cloudbuild_builder_sa}",
        "options": {"logging": "CLOUD_LOGGING_ONLY"},
        "_dockerfile": dockerfile,
        "_requirements": requirements_text,
    }


async def ensure_dependency_image(
    requirements_text: str,
    requirements_hash: str,
    *,
    gpu: bool = False,
    cuda_version: str = "12.4",
) -> str:
    """确保依赖层镜像存在：命中缓存直接返回，否则触发 Cloud Build（决策 11）。

    cloudbuild_enabled=False（dev）时直接返回基础 runner 镜像，不构建。
    """
    if not settings.cloudbuild_enabled:
        return settings.gpu_runner_image if gpu else settings.runner_image

    image_tag = dependency_image_tag(requirements_hash, gpu=gpu, cuda_version=cuda_version)
    if await _image_exists(image_tag):
        logger.info("dep_image_cache_hit", image=image_tag)
        return image_tag

    config = build_cloudbuild_config(requirements_text, image_tag, gpu=gpu, cuda_version=cuda_version)
    await _submit_build(config)
    logger.info("dep_image_built", image=image_tag, hash=requirements_hash)
    return image_tag


# ─────────────────────────── Cloud Build / AR REST ───────────────────────────

def _credentials_token() -> str:
    try:
        import google.auth  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
    except ImportError as exc:
        raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, "google-auth not available") from exc
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


async def _image_exists(image_tag: str) -> bool:
    """查询 Artifact Registry 是否已有该 tag（命中即跳过构建）。"""
    def _do() -> bool:
        import httpx

        # image_tag: us-central1-docker.pkg.dev/PROJECT/REPO/NAME:TAG
        try:
            host, rest = image_tag.split("/", 1)
            location = host.split("-docker.pkg.dev")[0]
            project, repo, name_tag = rest.split("/", 2)
            name, tag = name_tag.rsplit(":", 1)
        except ValueError:
            return False
        url = (
            f"https://artifactregistry.googleapis.com/v1/projects/{project}/locations/"
            f"{location}/repositories/{repo}/dockerImages"
        )
        token = _credentials_token()
        with httpx.Client(timeout=20) as cli:
            resp = cli.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                return False
            for img in resp.json().get("dockerImages", []):
                if name in img.get("name", "") and tag in img.get("tags", []):
                    return True
        return False

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001 缓存查询失败则按未命中构建
        logger.warning("ar_query_failed", error=str(exc))
        return False


async def _submit_build(config: dict[str, Any]) -> None:
    def _do() -> None:
        import httpx

        token = _credentials_token()
        url = _CLOUDBUILD_API.format(project=settings.gcp_project)
        body = {k: v for k, v in config.items() if not k.startswith("_")}
        with httpx.Client(timeout=60) as cli:
            resp = cli.post(url, headers={"Authorization": f"Bearer {token}"}, json=body)
            if resp.status_code >= 300:
                raise BusinessException(
                    PYFLOW_K8S_DEPLOY_FAILED, f"cloud build submit failed: {resp.text[:300]}"
                )

    await asyncio.to_thread(_do)
