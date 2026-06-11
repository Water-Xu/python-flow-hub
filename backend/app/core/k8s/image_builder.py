"""runner 镜像构建（决策 11 + Phase 4b 供应链加固 + wheel 分层）。

块 requirements 支持：
- 普通 PyPI 行（白名单校验）；
- @wheel:bucket/key.whl（MinIO HTTP，供集群内构建）；
- @gcs:path/key.whl（GCS，供 Cloud Build 拉取，与 pyflowhub_pack 方案一致）。
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from typing import Any

from app.config import get_settings
from app.core.k8s.requirements_policy import (
    build_install_script,
    parse_requirements,
    render_pypi_requirements,
    resolve_wheel_urls,
    validate_requirements,
)
from app.errors import PYFLOW_K8S_DEPLOY_FAILED, BusinessException
from app.observability.logging import get_logger

logger = get_logger("pyflow.k8s.build")
settings = get_settings()

_CLOUDBUILD_API = "https://cloudbuild.googleapis.com/v1/projects/{project}/builds"


def dependency_image_tag(requirements_hash: str, *, gpu: bool = False, cuda_version: str = "") -> str:
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
    """生成 Cloud Build 配置（含 wheel 安装 + 依赖审计）。"""
    parsed = validate_requirements(requirements_text, settings)
    wheel_urls = resolve_wheel_urls(parsed, settings)
    pypi_text = render_pypi_requirements(parsed)
    sdist = {x.strip().lower() for x in settings.pip_allow_sdist_packages.split(",") if x.strip()}
    install_sh = build_install_script(wheel_urls, allow_sdist=sdist, pypi_text=pypi_text)

    base_image = (
        f"nvidia/cuda:{cuda_version}-runtime-ubuntu22.04" if gpu else "python:3.11-slim"
    )
    index_args = ""
    if settings.pip_index_url:
        index_args = f"--index-url {settings.pip_index_url}"

    dockerfile = "\n".join([
        f"FROM {base_image}",
        "RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \\",
        "    && rm -rf /var/lib/apt/lists/* || true",
        "RUN useradd -u 65534 -m nobody || true",
        "WORKDIR /app",
        "COPY install_deps.sh /tmp/install_deps.sh",
        "COPY requirements_pypi.txt /tmp/requirements_pypi.txt",
        "RUN chmod +x /tmp/install_deps.sh && /tmp/install_deps.sh",
        "COPY pyflow_runtime/ /app/pyflow_runtime/",
        "COPY runner/ /app/runner/",
        f"ENV PIP_INDEX_URL={settings.pip_index_url or ''}",
        "USER 65534",
        'ENTRYPOINT ["python", "-m", "runner.entrypoint"]',
    ])

    staging_object = f"deps/{image_tag.rsplit(':', 1)[-1]}/context.tar.gz"
    bucket = settings.effective_cloudbuild_staging_bucket()

    result = {
        "source": {
            "storageSource": {
                "bucket": bucket,
                "object": staging_object,
            }
        },
        "steps": [
            {
                "name": "python:3.11-slim",
                "entrypoint": "bash",
                "args": [
                    "-c",
                    "pip install pip-audit && "
                    "pip-audit -r requirements_pypi.txt || "
                    "(grep -q . requirements_pypi.txt && exit 1 || exit 0)",
                ],
                "dir": "/workspace",
            },
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["build", "-t", image_tag, "-f", "Dockerfile", "."],
                "dir": "/workspace",
            },
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["push", image_tag],
            },
        ],
        "images": [image_tag],
        "options": {"logging": "CLOUD_LOGGING_ONLY"},
        "_dockerfile": dockerfile,
        "_install_sh": install_sh,
        "_pypi_text": pypi_text,
        "_staging_bucket": bucket,
        "_staging_object": staging_object,
    }
    # 只有明确配置了 builder SA 才传 serviceAccount（空值让 Cloud Build 用默认 SA）
    if settings.cloudbuild_builder_sa.strip():
        result["serviceAccount"] = (
            f"projects/{settings.gcp_project}/serviceAccounts/{settings.cloudbuild_builder_sa}"
        )
    return result


async def ensure_dependency_image(
    requirements_text: str,
    requirements_hash: str,
    *,
    gpu: bool = False,
    cuda_version: str = "12.4",
) -> str:
    if not settings.cloudbuild_enabled:
        return settings.gpu_runner_image if gpu else settings.runner_image

    image_tag = dependency_image_tag(requirements_hash, gpu=gpu, cuda_version=cuda_version)
    if await _image_exists(image_tag):
        logger.info("dep_image_cache_hit", image=image_tag)
        return image_tag

    config = build_cloudbuild_config(requirements_text, image_tag, gpu=gpu, cuda_version=cuda_version)
    await _upload_build_context(config)
    await _submit_build(config)
    logger.info("dep_image_built", image=image_tag, hash=requirements_hash)
    return image_tag


def _credentials_token() -> str:
    try:
        import google.auth  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
    except ImportError as exc:
        raise BusinessException(PYFLOW_K8S_DEPLOY_FAILED, "google-auth not available") from exc
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


async def _upload_build_context(config: dict[str, Any]) -> None:
    """打包 Dockerfile + install 脚本 + pyflow_runtime/runner 上传到 GCS staging。"""

    def _do() -> None:
        import os
        from pathlib import Path

        import httpx

        root = Path(__file__).resolve().parents[4]  # repo root（含 pyflow_runtime/ runner/）
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            def add_text(name: str, text: str) -> None:
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

            add_text("Dockerfile", config["_dockerfile"])
            add_text("install_deps.sh", config["_install_sh"])
            add_text("requirements_pypi.txt", config["_pypi_text"])

            for folder in ("pyflow_runtime", "runner"):
                base = root / folder
                if not base.is_dir():
                    continue
                for path in base.rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        arc = f"{folder}/{path.relative_to(base).as_posix()}"
                        tar.add(path, arcname=arc)

        bucket = config["_staging_bucket"]
        obj = config["_staging_object"]
        token = _credentials_token()
        url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
            f"?uploadType=media&name={obj.replace('/', '%2F')}"
        )
        with httpx.Client(timeout=120) as cli:
            resp = cli.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"},
                content=buf.getvalue(),
            )
            if resp.status_code >= 300:
                raise BusinessException(
                    PYFLOW_K8S_DEPLOY_FAILED,
                    f"upload build context failed: {resp.text[:300]}",
                )

    await asyncio.to_thread(_do)


async def _image_exists(image_tag: str) -> bool:
    def _do() -> bool:
        import httpx

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
    except Exception as exc:  # noqa: BLE001
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
