"""上传 wheel 到 MinIO + GCS（pyflowhub_pack 方案第 2 步）。

环境变量（与 FlowHub 块中间件一致，也可手动指定）：
  MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY
  GCP 凭据：Application Default Credentials（gcloud auth application-default login）

用法：
  python build_wheel.py
  python upload_artifacts.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUCKET = os.environ.get("PYFLOW_ARTIFACTS_BUCKET", "pyflow-artifacts")
GCS_BUCKET = os.environ.get("PYFLOW_GCS_BUILD_BUCKET", "lhy-styon-dev-4832-pyflow-build")
GCS_PREFIX = "pyflow/wheels"


def upload_minio(wheel: Path) -> None:
    from minio import Minio

    ep = os.environ.get("MINIO_ENDPOINT", "minio.lhy-styon.svc.cluster.local:9000")
    ak = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    sk = os.environ.get("MINIO_SECRET_KEY", "")
    if not sk:
        print("[skip] MINIO_SECRET_KEY 未设置，跳过 MinIO 上传")
        return
    client = Minio(ep, access_key=ak, secret_key=sk, secure=False)
    if not client.bucket_exists(BUCKET):
        client.make_bucket(BUCKET)
    key = f"wheels/{wheel.name}"
    client.fput_object(BUCKET, key, str(wheel))
    print(f"MinIO s3://{BUCKET}/{key}")


def upload_gcs(wheel: Path) -> None:
    dest = f"gs://{GCS_BUCKET}/{GCS_PREFIX}/{wheel.name}"
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", str(wheel), dest],
            check=True,
        )
        print(f"GCS {dest}")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[skip] GCS 上传失败（Cloud Build 需 GCS wheel）: {exc}")


def main() -> None:
    wheels = list(DIST.glob("*.whl"))
    if not wheels:
        print("请先运行: python build_wheel.py", file=sys.stderr)
        sys.exit(1)
    wheel = wheels[0]
    upload_minio(wheel)
    upload_gcs(wheel)
    print("\n请将 blocks/*/requirements.txt 中 @gcs: 行改为实际 wheel 文件名：")
    print(f"  @gcs:{GCS_PREFIX}/{wheel.name}")


if __name__ == "__main__":
    main()
