# 统一 runner 基础镜像（决策 11）：Python 运行时 + pyflow_runtime + sandbox 启动器。
# Block 代码不烧进镜像，启动时由 entrypoint 从 MinIO 拉取注入。
# 依赖按 requirements_hash 分层缓存：相同依赖集复用同一依赖层（CI 据此构建）。
FROM python:3.11-slim

WORKDIR /runner

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 共享执行库（与控制面同 pin 版本，决策 3.1 点 5）
COPY pyflow_runtime /opt/pyflow_runtime
RUN pip install --no-cache-dir /opt/pyflow_runtime fastapi==0.115.0 uvicorn==0.30.6 minio==7.2.8

# 用户依赖层占位：Cloud Build 据 requirements_hash 在此叠加 pip install -r block-requirements.txt

COPY runner/entrypoint.py /runner/entrypoint.py

# 非 root 运行（决策 1：与 Pod SecurityContext 对齐）
USER 65534

ENV PYFLOW_RUNNER_ROLE=consumer
ENTRYPOINT ["python", "/runner/entrypoint.py"]
