# PyFlowHub — Python 可视化调用中台

> **面向 Python 开发者的核心定位**：PyFlowHub 是一个「写 Python 函数 → 拖线连接 → 一键发布 API / MQ 订阅」的中台。
> 你只需要写 `def run(inputs: dict) -> dict`，平台负责隔离执行、DAG 编排、HTTP/MQ 触发、K8s 弹性扩缩。
> Redis / RabbitMQ / PostgreSQL / MinIO 等连接自动注入到你的函数运行环境，无需任何手工配置。

生产级实现（Phase 1a → Phase 5 全链路）：Docker 沙箱隔离、可视化编排、RabbitMQ 异步触发（幂等/DLQ/退避）、
Sa-Token RBAC、KEDA 云原生扩缩、GKE 部署，完全对齐现有基础设施。

---

## 目录

- [整体架构](#整体架构)
- [Python 开发者指南：写一个调用块](#python-开发者指南写一个调用块)
- [可注入的中间件全量参考](#可注入的中间件全量参考)
- [Flow 编排：连接多个块](#flow-编排连接多个块)
- [发布 API 与触发方式](#发布-api-与触发方式)
  - [HTTP 触发](#http-触发)
  - [MQ 异步触发](#mq-异步触发)
  - [input_mapping 配置详解](#input_mapping-配置详解)
- [打包与导入（zip 方式）](#打包与导入zip-方式)
- [部署指南](#部署指南)
  - [本地 dev 启动](#本地-dev-启动)
  - [手动部署到 GCP（绕过 CI/CD）](#手动部署到-gcp绕过-cicd)
  - [自动 CICD（GitHub Actions + Cloud Build）](#自动-cicddgithub-actions--cloud-build)
- [环境变量优先级与平台设置](#环境变量优先级与平台设置)
- [链路监控与执行历史](#链路监控与执行历史)
- [错误码速查](#错误码速查)
- [AI Agent 操作手册](#ai-agent-操作手册)

---

## 整体架构

```
 调用方（HTTP / RabbitMQ 消息）
         │
         ▼
  Spring Cloud Gateway + Sa-Token（现有，只校验登录态）
         │
         ▼
  FastAPI 控制面  ←──── PostgreSQL（元数据+指针）
  （多副本，编排/部署/拓扑）      │
         │              MinIO（代码/大字段/版本快照）
         │
    ┌────┴────┐
    │         │
  dev       prod
Docker 沙箱  GKE Pod（常驻 invoke Deployment）
             + KEDA（按 MQ 队列深度弹性扩缩）
             + Flow-Consumer（MQ 整流触发）

共享基础设施（所有块均可注入连接）：
  Redis Cluster / RabbitMQ / PostgreSQL / MinIO
  Elasticsearch / Milvus / Nacos / OTel Collector
```

**核心约束**：
- 控制面**绝不在自身 Pod 内跑 Docker**。生产执行 = K8s Pod 原生隔离。
- `pyflow_runtime` 是共享执行库，控制面（dev）与 runner 镜像（prod）使用同一代码版本。
- MQ 消费单元 = 接口级 Flow-Consumer Pod，消费 `flow.{api_id}.queue`，按 DAG 驱动整条 Flow。

---

## Python 开发者指南：写一个调用块

### 最简 Block

```python
# 文件名即为块名（建议 snake_case）
def run(inputs: dict) -> dict:
    """必须有 run 函数作为默认入口。

    Args:
        inputs: 来自 HTTP/MQ 触发的入参，或上游节点 output 的合并结果。

    Returns:
        dict，自动传递给下游节点作为 inputs。
    """
    name = inputs.get("name", "World")
    return {"greeting": f"Hello, {name}!", "length": len(name)}
```

### 多入口 Block

一个脚本可以暴露多个入口函数，在 API / Flow 节点配置中选择调用哪个：

```python
def run(inputs: dict) -> dict:
    """默认入口：通用处理"""
    return process(inputs, mode="normal")

def run_fast(inputs: dict) -> dict:
    """快速模式入口：跳过 embedding 等重计算"""
    return process(inputs, mode="fast")

def run_batch(inputs: dict) -> dict:
    """批量模式入口"""
    items = inputs.get("items", [])
    return {"results": [process({"item": x}, mode="normal") for x in items]}

def process(inputs, mode):
    # 公共逻辑
    ...
```

### 流式 Block（SSE 推送）

```python
from typing import Generator

def run(inputs: dict) -> Generator[dict, None, None]:
    """流式入口：yield 每个 chunk，前端 SSE 实时接收。"""
    prompt = inputs.get("prompt", "")
    for word in prompt.split():
        yield {"token": word, "done": False}
    yield {"token": "", "done": True}
```

### 使用中间件

```python
import os
import redis
import psycopg2
import pika
from minio import Minio

def run(inputs: dict) -> dict:
    # ─── Redis ───
    redis_client = redis.from_url(os.environ["REDIS_URL"])
    redis_client.set("my_key", inputs.get("value", ""))
    cached = redis_client.get("my_key")

    # ─── PostgreSQL（DATABASE_URL = pyflow 控制库，或用 PG* 组件自建连接到其他库）───
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    # 或者连接到任意有权限的业务库：
    conn2 = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname="my_biz_db",          # 自行指定库名
    )

    # ─── MinIO ───
    minio_client = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )

    # ─── RabbitMQ（发布消息）───
    params = pika.URLParameters(os.environ["RABBITMQ_URL"])
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.basic_publish(exchange="", routing_key="my_queue", body=b"hello")
    connection.close()

    return {"status": "ok"}
```

### 安装依赖

在块编辑器的「依赖」标签页填写 `requirements.txt` 格式：

```
redis>=4.6
psycopg2-binary>=2.9
minio>=7.2
pika>=1.3
langchain>=0.1
# 本地 wheel（已上传 MinIO 的私有包）：
pyflow_vector @ file:///wheels/pyflow_vector-0.1.0-py3-none-any.whl
```

> 部署时会触发 Cloud Build 构建依赖层镜像（`requirements_hash` 变化才重建，有缓存）。

---

## 可注入的中间件全量参考

部署时 orchestrator 自动渲染共享 K8s Secret `pyflow-block-middleware` 并通过 `envFrom` 注入所有块 Pod。

### 始终注入的环境变量

| 环境变量 | 说明 | 示例值 |
|---|---|---|
| `REDIS_URL` | Redis Cluster 连接 URL | `redis://10.0.1.x:6379/0` |
| `RABBITMQ_URL` | RabbitMQ AMQP 连接串（含 vhost） | `amqp://lhy-styon:pwd@rabbitmq.lhy-styon.svc.cluster.local:5672//lhy-styon` |
| `DATABASE_URL` | PostgreSQL asyncpg DSN（默认指向 pyflow 控制库） | `postgresql+asyncpg://pyflow:pwd@host:5432/pyflow` |
| `PGHOST` | PostgreSQL 主机（libpq 标准变量，可连任意库） | `10.0.0.x` |
| `PGPORT` | PostgreSQL 端口 | `5432` |
| `PGUSER` | PostgreSQL 用户 | `pyflow` |
| `PGPASSWORD` | PostgreSQL 密码 | `...` |
| `MINIO_ENDPOINT` | MinIO 地址（不含 scheme） | `minio.lhy-styon.svc.cluster.local:9000` |
| `MINIO_ACCESS_KEY` | MinIO Access Key | `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO Secret Key | `...` |

### 配置后注入的可选变量

| 环境变量 | 中间件 | 配置方式 |
|---|---|---|
| `MILVUS_URI` | Milvus 向量库 | 平台设置 → `PYFLOW_BLOCK_MILVUS_URI` |
| `ELASTICSEARCH_URL` | Elasticsearch | 平台设置 → `PYFLOW_BLOCK_ES_URL` |
| `NACOS_SERVER_ADDR` | Nacos 注册中心 | 平台设置 → `PYFLOW_BLOCK_NACOS_ADDR` |

### 自定义环境变量（三层优先级）

优先级：**全局 < 部署 < 块**（更具体的覆盖更宽泛的）。

| 层级 | 配置入口 | 说明 |
|---|---|---|
| **全局** | 前端「平台设置」→「全局环境变量」/ `POST /api/platform/env` | 注入所有部署的所有块 |
| **部署** | 部署中心详情「环境变量」/ `PUT /api/deployments/{id}/env` | 注入该部署的所有块 |
| **块** | 块编辑器「计算配置」/ Block.compute_config.env_vars | 只注入该块 |

> ⚠️ 敏感值（含 SECRET/TOKEN/PASSWORD/KEY 等关键字）**不能存 env_vars**，必须走 `secret_refs`（引用 K8s Secret 名称）。

### NetworkPolicy Egress 白名单

块 Pod 默认 deny-all。中间件 Secret 注入时，orchestrator 同步放行以下出口：

- `PYFLOW_MIDDLEWARE_NAMESPACE` 命名空间内端口（`PYFLOW_MIDDLEWARE_NS_PORTS`，默认 5432/6379/5672/15672/9000/9200/8848/19530）
- `PYFLOW_BLOCK_EGRESS_CIDRS`（额外 CIDR，如 Cloud SQL 私网 IP）
- Cloud SQL Proxy / Memorystore VPC IP

---

## Flow 编排：连接多个块

### 数据流规则

1. **根节点**（无入边的节点）接收 HTTP/MQ 触发时的 `inputs`。
2. **中间节点**：上游所有节点的 `output` dict **全量 merge** 后作为本节点 `inputs`。
3. **条件分支节点**：根据上游 output 的 jmespath 表达式，只激活命中分支的下游节点（未命中分支跳过）。
4. **output 字段优先级**：下游覆盖上游（后合并的覆盖先合并的），字段名相同取最新。

```
Flow 示例：
  [fetch_data] ──output──> [clean_data] ──output──> [save_result]
       │                        │
       └──(条件: output.rows > 0 → "has_data" 端口)──> [send_notification]
```

### 入口函数选择优先级

```
接口级 entrypoint_map[node_id]  >  接口级全局 entrypoint
  >  节点 config.entrypoint  >  默认 "run"
```

### Flow 图保存 API

```
PUT /api/flows/{flow_id}/graph
Body: {
  "nodes": [...],  // VueFlow 节点对象
  "edges": [...],  // 边（含 source_port / target_port）
  "entry_node_id": "xxx"  // 可选，指定入口节点
}
```

---

## 发布 API 与触发方式

### 发布接口

```
POST /api/portal/apis
Body: {
  "name": "数据清洗接口",
  "path": "data/clean",          // 公开调用路径（不含前缀）
  "flow_id": "xxx",
  "trigger_type": "http",        // "http" | "mq" | "both"
  "http_config": {
    "input_mapping": {           // 见下方 input_mapping 说明
      "csv_data": "$.body.data",
      "cols": "$.body.columns"
    }
  }
}
```

### HTTP 触发

```
# 同步调用
POST /api/public/{path}
Authorization: Bearer <token>
Content-Type: application/json

{
  "inputs": {
    "csv_data": "...",
    "cols": ["name", "age"]
  }
}

# 响应
{
  "outputs": { "rows": [...], "count": 100 },
  "status": "succeeded",
  "flow_run_id": "uuid",
  "latency_ms": 243
}
```

```
# 流式调用（SSE）
POST /api/public/{path}/stream
# 响应 Content-Type: text/event-stream
# 每 chunk: data: {"token": "...", "done": false}
# 结束:     data: {"token": "", "done": true}
```

### MQ 异步触发

发布接口时设置 `trigger_type: "mq"` 或 `"both"`，平台自动建队列拓扑：

| 队列名 | 用途 |
|---|---|
| `flow.{api_id}.queue` | 主消费队列 |
| `flow.{api_id}.dlq` | 死信队列（超出重试次数后落此） |
| `flow.{api_id}.backoff` | 退避重入队列（延迟重试） |

**发布消息**：

```python
import pika, json, uuid

params = pika.URLParameters("amqp://lhy-styon:pwd@rabbitmq:5672//lhy-styon")
conn = pika.BlockingConnection(params)
ch = conn.channel()

# 消息体：按 input_mapping 配置的源路径填写
body = {
    "data": "col1,col2\nval1,val2",   # 源字段（由 input_mapping 映射到 Flow inputs）
    "columns": ["col1", "col2"],
    "pyflow-idempotency-key": str(uuid.uuid4()),  # 幂等 key（可选，防重复消费）
}

ch.basic_publish(
    exchange="",
    routing_key=f"flow.{api_id}.queue",  # api_id 见接口管理页
    body=json.dumps(body),
    properties=pika.BasicProperties(
        content_type="application/json",
        headers={"pyflow-protocol": "1"},
    ),
)
conn.close()
```

**MQ 配置字段（`mq_config`）**：

```json
{
  "input_mapping": { "csv_data": "$.data", "cols": "$.columns" },
  "condition": "$.data != null",          // 可选：消费前判断是否执行（jmespath）
  "reply_exchange": "biz.reply",          // 可选：执行完后将 output 发到此 exchange
  "reply_routing_key": "pyflow.result",
  "retry_max": 3,                         // 可选：最大重试次数（默认 3）
  "retry_backoff_ms": 5000               // 可选：退避等待毫秒（默认 5000）
}
```

### input_mapping 配置详解

`input_mapping` 把 HTTP 请求体或 MQ 消息体字段**映射**成 Flow 入口 inputs。

格式：`{ "Flow 入参字段名": "JSONPath 表达式" }`

```json
// HTTP 请求体：{ "body": { "file_url": "s3://...", "config": {...} } }
// MQ 消息体：{ "file_url": "s3://...", "config": {...} }

"input_mapping": {
  "url":    "$.body.file_url",    // HTTP 从 $.body.xxx 取
  "config": "$.body.config",

  "url":    "$.file_url",         // MQ 直接从根 $.xxx 取
  "config": "$.config"
}

// Flow 入口 inputs 结果：
// { "url": "s3://...", "config": {...} }
```

**不配置 `input_mapping` 时**：HTTP 取 `body.inputs`，MQ 取消息体整体。

---

## 打包与导入（zip 方式）

将多个 Block 脚本 + requirements 打成 zip 一次性导入：

```
my-toolkit/
├── data_cleaner.py      # def run(inputs) → Block
├── data_analyzer.py     # def run(inputs) + def run_summary(inputs) → Block
├── requirements.txt     # 公共依赖
└── pack.py              # 可选打包脚本
```

```python
# pack.py
import zipfile, pathlib

with zipfile.ZipFile("my-toolkit.zip", "w") as z:
    for f in pathlib.Path(".").glob("*.py"):
        z.write(f)
    z.write("requirements.txt")
print("打包完成: my-toolkit.zip")
```

```bash
# 上传到 PyFlowHub（需登录态 token）
curl -X POST http://localhost:8000/api/flows/import-zip \
  -H "Authorization: Bearer <token>" \
  -F "file=@my-toolkit.zip" \
  -F "name=数据分析工具包"
```

导入后，每个 `.py` 文件自动成为一个 Block，AST 扫描暴露的函数作为 entrypoints，有合法入口的块自动发布稳定版本到 MinIO。

---

## 部署指南

### 本地 dev 启动

**前置**：Python 3.11+、Node 22+、Docker Desktop

```bash
# 1. 启动依赖中间件
docker compose up -d
# 包含：PostgreSQL(5432) / Redis(6379) / RabbitMQ(5672,15672) / MinIO(9000,9001)

# 2. 启动后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
pip install -e ../pyflow_runtime
copy ..\.env.example .env       # Windows
# cp ../.env.example .env       # Linux/macOS
# 按需修改 .env（默认 PYFLOW_AUTH_ENABLED=false，dev 用户视为 ADMIN）
uvicorn app.main:app --reload --port 8000

# 3. 启动前端
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173
# API 文档 http://localhost:8000/docs
```

> ⚠️ Windows 本机无 Docker daemon 时，块执行降级为 in-process（**仅调试，无隔离**）。生产必须走 Docker / K8s。

---

### 手动部署到 GCP（绕过 CI/CD）

当 GitHub Actions 不可用时，直接用 `gcloud builds submit` 手动触发 Cloud Build：

```powershell
# 1. 确认登录与项目
gcloud auth login
gcloud config set project lhy-styon-dev-4832

# 2. 确认 kubectl 上下文
gcloud container clusters get-credentials lhy-styon-dev --zone us-central1-a --project lhy-styon-dev-4832

# 3. 提交构建（从仓库根目录执行）
cd d:\projects\lhy-styon-python-flow-hub
$sha = git rev-parse --short HEAD
gcloud builds submit . `
  --config=cloudbuild.yaml `
  --project=lhy-styon-dev-4832 `
  --substitutions="_SHORT_SHA=$sha" `
  --async

# 4. 查看构建进度
gcloud builds list --project=lhy-styon-dev-4832 --limit=3
gcloud builds log <BUILD_ID> --project=lhy-styon-dev-4832 --stream

# 5. 验证部署
kubectl get pods -n pyflow-blocks
kubectl rollout status deployment/pyflow-hub -n pyflow-blocks
kubectl logs -n pyflow-blocks deploy/pyflow-hub --tail=50
```

构建流程（`cloudbuild.yaml` 自动完成）：
1. 构建 `pyflow-hub` 镜像（控制面，context=仓库根）
2. 构建 `pyflow-runner` 镜像（执行侧，context=仓库根）
3. 构建 `pyflow-web` 镜像（前端，context=frontend/）
4. 推送三个镜像到 Artifact Registry
5. 执行 Alembic 迁移 Job（成功才继续，失败中止）
6. 滚动更新 GKE Deployment

**关键参数**：

| 参数 | 值 |
|---|---|
| GCP 项目 | `lhy-styon-dev-4832` |
| 区域/可用区 | `us-central1` / `us-central1-a` |
| GKE 集群 | `lhy-styon-dev` |
| AR 仓库 | `us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon` |
| K8s 命名空间 | `pyflow-blocks` |
| Cloud Build 超时 | 2400s（E2_HIGHCPU_8） |

---

### 自动 CICD（GitHub Actions + Cloud Build）

```bash
# 推送到 master 分支自动触发
git push origin master

# 跟踪进度
gcloud builds list --project=lhy-styon-dev-4832 --limit=3
```

**一次性配置**（已配置则跳过）：

```powershell
$PROJECT = "lhy-styon-dev-4832"
$SA = "github-actions-sa@$PROJECT.iam.gserviceaccount.com"

# 生成新 key
gcloud iam service-accounts keys create gha-key.json --iam-account=$SA --project=$PROJECT

# 上传到 GitHub Secret（需要 PyNaCl）
# pip install PyNaCl
python -c "
import base64, json, ssl, urllib.request
from nacl import encoding, public

TOKEN = '<GITHUB_PAT>'
REPO = 'lhy-AIstyle/lhy-styon-python-flow-hub'
h = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github+json',
     'User-Agent': 'x', 'Content-Type': 'application/json'}
ctx = ssl.create_default_context()

def get(u): return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), context=ctx).read())
def put(u, d): return urllib.request.urlopen(urllib.request.Request(u, data=json.dumps(d).encode(), headers=h, method='PUT'), context=ctx).status

pk = get(f'https://api.github.com/repos/{REPO}/actions/secrets/public-key')
box = public.SealedBox(public.PublicKey(pk['key'].encode(), encoding.Base64Encoder()))
enc = base64.b64encode(box.encrypt(open('gha-key.json').read().strip().encode())).decode()
print(put(f'https://api.github.com/repos/{REPO}/actions/secrets/GCP_SA_KEY',
          {'encrypted_value': enc, 'key_id': pk['key_id']}))
# 201=created / 204=updated
"

# 完成后删除本地 key 文件
Remove-Item gha-key.json
```

**K8s Secret（真实凭据，首次或更换密码时执行）**：

```bash
kubectl create secret generic pyflow-hub-secret -n pyflow-blocks \
  --from-literal=PYFLOW_DB_DSN="postgresql+asyncpg://pyflow:<PWD>@<CLOUDSQL_IP>:5432/pyflow" \
  --from-literal=PYFLOW_REDIS_URL="redis://10.0.1.x:6379/0" \
  --from-literal=PYFLOW_RABBITMQ_URL="amqp://lhy-styon:<PWD>@rabbitmq.lhy-styon.svc.cluster.local:5672//lhy-styon" \
  --from-literal=PYFLOW_MINIO_ENDPOINT="minio.lhy-styon.svc.cluster.local:9000" \
  --from-literal=PYFLOW_MINIO_ACCESS_KEY="minioadmin" \
  --from-literal=PYFLOW_MINIO_SECRET_KEY="<PWD>" \
  --from-literal=PYFLOW_BOOTSTRAP_ADMIN="<admin_loginId>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

**常见部署问题**：

| 现象 | 原因 / 解决 |
|---|---|
| `Authenticate to Google Cloud` 失败 | 仓库缺 `GCP_SA_KEY`，上传后 rerun |
| 迁移 Job 失败 | pyflow 库/用户未建，或 Secret DSN 占位未覆盖 |
| 控制面 NotReady | `/health/ready` 依赖 PostgreSQL，查 `pyflow-hub-secret` DSN |
| 块执行 `SANDBOX_ERROR` | 控制面 Pod 内无 Docker（设计如此），prod 走 K8s Pod |
| `caller does not have permission to act as service account` | 给 github-actions-sa 授 Compute 默认 SA 的 `iam.serviceAccountUser` |

---

## 环境变量优先级与平台设置

```
全局环境变量（平台设置）
  ↓（被覆盖）
部署级环境变量（部署中心 → 环境变量标签页）
  ↓（被覆盖）
块级计算配置（块编辑器 → 计算配置 → env_vars）
  ↓
注入块 Pod 容器
```

**API**：
```
# 全局变量管理
GET  /api/platform/env          # 列出所有全局变量
POST /api/platform/env          # 新增/更新  { env_key, env_value, description }
DELETE /api/platform/env/{id}   # 删除

# 部署级变量
PUT /api/deployments/{id}/env   # { env_vars: {...}, secret_refs: {...} }

# 查看中间件连接信息（注入块的变量预览）
GET /api/platform/middleware
```

---

## 链路监控与执行历史

### 首页链路看板（Dashboard）

- 资源计数：调用块 / 流程 / 运行部署 / 发布接口
- 24h 执行成功率环形图 + 趋势柱状图
- 调用记录列表（HTTP/MQ/手动，点击查看完整 trace）
- 中间件依赖连通性实时检测

### 执行历史（Execution History）

列表展示所有以 Flow 为整体的执行记录（`GET /api/exec/flow-runs`），含：
- 触发源（HTTP API / 流式 API / MQ 消息 / 手动）
- 流程名 / 接口名 / 节点进度 / 状态 / 耗时

点击记录打开详情抽屉，含三个标签页：
1. **调用链路图**：可视化 HTTP/MQ/手动三种模式的完整调用路径（客户端 → 网关 → 服务 → 各块节点），每节点含状态/耗时/错误，底部甘特图式耗时分布
2. **入参 / 出参**：Flow 触发时传入的参数 和 最终返回值（JSON 展示）
3. **节点步骤 / 关联块执行**：每个节点的详细执行记录含 stdout/stderr

### Trace API

```
GET /api/dashboard/flow-runs/{run_id}/trace
```

返回结构：
```json
{
  "run": {
    "id": "...",
    "flow_name": "...",
    "trigger_source": "http|mq|manual|stream",
    "api_name": "...",
    "api_path": "...",
    "status": "succeeded|failed|running",
    "duration_ms": 243,
    "inputs": { ... },    // Flow 触发时的入参
    "output": { ... }     // Flow 最终出参
  },
  "steps": [
    {
      "node_id": "...",
      "node_name": "fetch_data",   // 从 dag_snapshot 提取
      "status": "done|failed|skipped",
      "duration_ms": 120,
      "hit_port": "success",       // 条件分支激活的端口
      "output": { ... },
      "error": null
    }
  ],
  "executions": [
    {
      "block_name": "fetch_data",
      "status": "success",
      "duration_ms": 120,
      "inputs": { ... },
      "output": { ... },
      "stdout": "...",
      "stderr": ""
    }
  ],
  "call_chain": {
    "type": "http",       // http|stream|mq|manual
    "total_ms": 243,
    "nodes": [            // 完整调用链路节点序列（含基础设施节点）
      { "id": "client",  "type": "client",  "label": "调用客户端" },
      { "id": "gateway", "type": "gateway", "label": "API 网关" },
      { "id": "portal",  "type": "service", "label": "API Portal" },
      { "id": "orchestrator", "type": "orchestrator", "label": "Flow 编排",
        "children": [ ... ]  // 各 Block 子节点
      },
      { "id": "response", "type": "response", "label": "HTTP 响应" }
    ]
  }
}
```

---

## 错误码速查

号段对齐现有平台（`x18xx` 子区间）：

| 错误码 | 含义 | 触发场景 |
|---|---|---|
| 11801 | Token 无效 / 未登录 | 所有需鉴权接口 |
| 11802 | RBAC 权限不足 | 操作需要更高角色 |
| 41801 | 块不存在 | 执行 / 版本操作 |
| 41802 | 流程不存在 | Flow 操作 |
| 41803 | 版本未稳定或 sha 校验失败 | 部署时加载版本 |
| 41804 | 输入参数非法 | invoke 入参校验 |
| 41805 | DAG 有环或拓扑非法 | 保存 Flow 图 |
| 41806 | 资源级权限不足 | 非 owner 且未授权 |
| 41810 | 接口不存在 | 公开调用 |
| 41811 | 接口已锁定 | 尝试修改已锁定接口 |
| 41812 | 请求过于频繁 | 限流 |
| 41813 | 接口路径已存在 | 发布时路径冲突 |
| 51801 | 执行超时 | 块执行超时 |
| 51802 | 沙箱执行失败 | Docker/Pod 执行错误 |
| 51803 | K8s 部署失败 | manifest apply / 镜像构建 |
| 51804 | MQ 发布失败 | RabbitMQ 连接问题 |
| 51805 | 存储服务异常 | MinIO 读写失败 |

---

## AI Agent 操作手册

> 本节供 AI Agent 快速理解系统能力并直接执行操作。读完本节可直接调用 API 完成所有操作。

### 系统概述（机读摘要）

```
SYSTEM: PyFlowHub
TYPE: Python 可视化调用中台
BASE_URL: http://localhost:8000 (dev) | https://gateway/lhy-styon-pyflow (prod)
AUTH: Bearer token（Sa-Token，dev 模式 PYFLOW_AUTH_ENABLED=false 可跳过）

核心实体：
  Block: Python 函数包装体，entrypoint = def run(inputs: dict) -> dict
  Flow:  Block 组成的有向无环图（DAG），节点间 output->inputs merge 传递
  PublishedApi: 绑定 Flow 的公开接口，支持 HTTP/MQ/both 触发
  FlowDeployment: Flow 部署到 K8s 的实例（block_mode 或 flow_mode）
  FlowRun: 一次 Flow 执行记录（trigger_source: http|mq|manual|stream）
  ExecutionRecord: 一次 Block 执行记录（含 inputs/output/stdout/stderr）
```

### REST API 快速参考

```yaml
# ── Block ──
GET    /api/blocks                          # 列出所有 Block
POST   /api/blocks                          # 创建 Block {name, description, type, draft_code}
GET    /api/blocks/{id}                     # 获取 Block 详情（含 draft_code）
PUT    /api/blocks/{id}                     # 更新 Block
DELETE /api/blocks/{id}                     # 删除 Block
POST   /api/blocks/{id}/discover-entrypoints # AST 扫描暴露的入口函数

# ── Flow ──
GET    /api/flows                           # 列出所有 Flow
POST   /api/flows                           # 创建 Flow {name, description}
GET    /api/flows/{id}                      # 获取 Flow（含 graph/nodes/edges）
PUT    /api/flows/{id}/graph                # 保存 DAG {nodes, edges, entry_node_id}
POST   /api/flows/{id}/run                  # 手动运行 Flow {inputs: {...}}
POST   /api/flows/import-zip               # 导入 zip 包（multipart: file, name）

# ── 版本管理 ──
GET    /api/versions/blocks/{block_id}      # Block 版本列表
POST   /api/versions/blocks/{block_id}      # 发布版本 {version_tag, commit_message, set_stable}
POST   /api/versions/block-versions/{id}/stable  # 设为稳定版

# ── 接口管理 ──
GET    /api/portal/apis                     # 列出发布的接口
POST   /api/portal/apis                     # 发布接口（见上方字段说明）
PUT    /api/portal/apis/{id}/mq             # 更新 MQ 配置
POST   /api/portal/apis/{id}/invoke         # 平台内调用测试（需登录）
POST   /api/public/{path}                   # 公开调用（无需登录，需 auth_token 如配置）
POST   /api/public/{path}/stream            # 公开流式调用

# ── 部署 ──
GET    /api/deployments                     # 列出部署
POST   /api/deployments                     # 创建部署 {flow_id, name, environment, deployment_type}
POST   /api/deployments/{id}/deploy         # 一键部署到 K8s
DELETE /api/deployments/{id}               # 销毁部署
GET    /api/deployments/{id}/status         # K8s 实时状态
GET    /api/deployments/{id}/pods           # Pod 列表
GET    /api/deployments/{id}/pods/{name}/logs # Pod 日志
GET    /api/deployments/{id}/resources      # 资源配置（CPU/内存/GPU）
PUT    /api/deployments/{id}/env            # 更新环境变量

# ── 执行历史 ──
GET    /api/exec/flow-runs                  # Flow 执行列表（?flow_id=&trigger_source=&limit=）
GET    /api/exec/records                    # Block 执行列表（?block_id=&limit=）
GET    /api/exec/records/{id}               # Block 执行详情（含 inputs/output/stdout/stderr）

# ── 链路看板 ──
GET    /api/dashboard/overview              # 总览（计数+统计+趋势+最近链路）
GET    /api/dashboard/flow-runs/{id}/trace  # Flow trace（含 call_chain+steps+executions）
GET    /api/dashboard/exec/{id}            # Block 执行详情（含关联 flow_run）

# ── 平台设置 ──
GET    /api/platform/env                    # 全局环境变量列表
POST   /api/platform/env                    # 新增/更新全局变量
DELETE /api/platform/env/{id}              # 删除全局变量
GET    /api/platform/middleware             # 中间件连接信息

# ── MQ 监控 ──
GET    /api/mq/monitors                     # MQ 接口监控列表
POST   /api/mq/monitors/{id}/start          # 启动消费者
POST   /api/mq/monitors/{id}/stop           # 停止消费者
POST   /api/mq/monitors/{id}/test-run       # 发送测试消息
GET    /api/mq/monitors/{id}/dlq            # DLQ 消息列表
POST   /api/mq/monitors/{id}/dlq/requeue    # DLQ 消息重入队列

# ── 健康 ──
GET    /health/live                         # liveness（始终 200）
GET    /health/ready                        # readiness（PostgreSQL 连通才 200）
GET    /health/deps                         # 依赖连通性（PG/Redis/MQ/MinIO）
```

### 典型操作流程（Step-by-Step）

```
任务：从零创建并发布一个 HTTP API

Step 1: 创建 Block
  POST /api/blocks
  { "name": "my_processor", "draft_code": "def run(inputs):\n    return {'out': inputs}" }
  → 得到 block_id

Step 2: 发布稳定版本
  POST /api/versions/blocks/{block_id}
  { "version_tag": "v1.0", "set_stable": true }

Step 3: 创建 Flow
  POST /api/flows
  { "name": "my_flow" }
  → 得到 flow_id

Step 4: 保存 DAG（单节点 Flow）
  PUT /api/flows/{flow_id}/graph
  { "nodes": [{"id": "n1", "type": "BlockNode", "data": {"block_id": "<block_id>", "label": "处理器"}}],
    "edges": [], "entry_node_id": "n1" }

Step 5: 测试运行
  POST /api/flows/{flow_id}/run
  { "inputs": { "value": 42 } }
  → 确认输出正确

Step 6: 发布接口
  POST /api/portal/apis
  { "name": "处理接口", "path": "process/v1", "flow_id": "<flow_id>",
    "trigger_type": "http",
    "http_config": { "input_mapping": { "value": "$.inputs.value" } } }

Step 7: 公开调用
  POST /api/public/process/v1
  { "inputs": { "value": 42 } }
  → { "outputs": { "out": 42 }, "status": "succeeded" }
```

### Block 代码模板速查

```python
# ─── 最简块 ───
def run(inputs: dict) -> dict:
    return {"result": inputs.get("data")}

# ─── 连接 Redis ───
import os, redis
def run(inputs: dict) -> dict:
    r = redis.from_url(os.environ["REDIS_URL"])
    r.set(inputs["key"], inputs["value"])
    return {"ok": True}

# ─── 连接 PostgreSQL（自定义库）───
import os, psycopg2
def run(inputs: dict) -> dict:
    conn = psycopg2.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"],
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname="my_biz_db"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM orders")
        count = cur.fetchone()[0]
    conn.close()
    return {"order_count": count}

# ─── 上传文件到 MinIO ───
import os
from minio import Minio
import io
def run(inputs: dict) -> dict:
    client = Minio(os.environ["MINIO_ENDPOINT"],
                   os.environ["MINIO_ACCESS_KEY"],
                   os.environ["MINIO_SECRET_KEY"], secure=False)
    data = inputs["content"].encode()
    client.put_object("my-bucket", inputs["filename"], io.BytesIO(data), len(data))
    return {"url": f"minio://{inputs['filename']}"}

# ─── 条件分支（返回特定端口触发下游）───
def run(inputs: dict) -> dict:
    score = inputs.get("score", 0)
    if score >= 90:
        return {"__port__": "high_score", "score": score, "grade": "A"}
    else:
        return {"__port__": "normal", "score": score, "grade": "B"}
# Flow 编辑器中将此节点连两条边：
# edge1: source_port="high_score" → 优质用户处理块
# edge2: source_port="normal" → 普通处理块

# ─── 发布 MQ 消息给其他接口 ───
import os, pika, json, uuid
def run(inputs: dict) -> dict:
    params = pika.URLParameters(os.environ["RABBITMQ_URL"])
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.basic_publish(
        exchange="", routing_key=f"flow.{inputs['target_api_id']}.queue",
        body=json.dumps({"payload": inputs["data"], "pyflow-idempotency-key": str(uuid.uuid4())}),
        properties=pika.BasicProperties(content_type="application/json", headers={"pyflow-protocol": "1"})
    )
    conn.close()
    return {"sent": True}

# ─── 流式输出 ───
from typing import Generator
def run(inputs: dict) -> Generator[dict, None, None]:
    for chunk in process_stream(inputs):
        yield {"chunk": chunk, "done": False}
    yield {"done": True}
```

### 注意事项（AI 操作时必读）

1. **敏感值不入 `env_vars`**：含 SECRET/TOKEN/PASSWORD/KEY 关键字的变量必须用 `secret_refs` 引用 K8s Secret。
2. **版本必须 stable 才能部署**：`set_stable: true` 或调用 `/stable` 端点后才能在 FlowDeployment 中使用。
3. **DAG 必须无环**：`PUT /api/flows/{id}/graph` 服务端自动校验，有环会返回 41805。
4. **ZIP 导入会自动 AST 扫描**：确保 Block 函数签名为 `def xxx(inputs: dict) -> dict`，否则 entrypoint 扫描失败（非致命错误，可手动配置）。
5. **MQ 消费者 dev 模式**：控制面本地启动后，访问「MQ 监控」手动 start 消费者；prod 模式消费者是独立 Pod。
6. **GCP 手动部署**：从仓库根目录执行 `gcloud builds submit . --config=cloudbuild.yaml --project=lhy-styon-dev-4832 --substitutions="_SHORT_SHA=$(git rev-parse --short HEAD)" --async`。

---

## 仓库结构

```
lhy-styon-python-flow-hub/
├── backend/                 # FastAPI 控制面
│   ├── app/
│   │   ├── api/             # 路由：blocks/flows/exec/portal/deployments/versions/mq/platform/rbac/jupyter/ws/health/dashboard/gateway
│   │   ├── core/
│   │   │   ├── k8s/         # manifest_generator / orchestrator / deployment_manager / keda / middleware / image_builder
│   │   │   ├── flow/        # flow_runner / flow_run_store(lease+fence 续跑)
│   │   │   ├── mq/          # topology_builder / consumer_manager(dev-local)
│   │   │   ├── versioning/  # version_manager(先MinIO后DB+对账) / diff_service
│   │   │   ├── sandbox/     # docker_executor / k8s_executor
│   │   │   └── storage/     # MinIO 客户端
│   │   ├── models/          # SQLAlchemy ORM（Block/Flow/FlowRun/ExecutionRecord/PublishedApi/...）
│   │   └── migrations/      # Alembic 迁移（独立 pyflow 库）
│   └── Dockerfile           # build context = 仓库根（需要 pyflow_runtime）
├── pyflow_runtime/          # 共享执行库（executor/flow_dag/consumer/input_mapper/...）
├── runner/                  # runner 镜像（flow_consumer / flow_runner 角色）
│   └── Dockerfile           # build context = 仓库根
├── frontend/                # Vue3 + Vite + Element Plus + VueFlow
│   └── Dockerfile           # build context = frontend/
├── tests/                   # 单测（pytest -q，69 项，零外部服务）
├── deploy/
│   ├── k8s/                 # namespace / pyflow-hub / migration-job / keda / ingress / node-pools / network-policies
│   └── iam/                 # 最小权限 SA + Workload Identity
├── docker-compose.yml       # 本地依赖（PostgreSQL + Redis + RabbitMQ + MinIO）
├── cloudbuild.yaml          # Cloud Build：三镜像构建 + 迁移 + 滚动更新
└── sample-projects/         # 示例项目（data-toolkit / vector-ingest）
```
