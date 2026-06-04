FROM python:3.11-slim

WORKDIR /app

# 系统依赖（asyncpg/构建）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

# 先装 pyflow_runtime（执行侧共享库，与控制面同 pin 版本，决策 3.1 点 5）
COPY pyflow_runtime /opt/pyflow_runtime
RUN pip install --no-cache-dir /opt/pyflow_runtime

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/

ENV PYFLOW_DEPLOYMENT_MODE=k8s
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
