# PyFlowHub — Python 可视化调用中台

> 生产级 Python 可视化调用中台，以 **Flow** 为部署单元，支持 Docker 沙箱隔离执行、可视化编排、
> RabbitMQ 异步触发（含幂等/DLQ）、Sa-Token RBAC 接入、KEDA 云原生扩缩容。
> 与现有 GKE / RabbitMQ / Redis Cluster / MinIO 基础设施完全对齐。

本仓库当前实现 **Phase 1a 执行内核 MVP**（不穿网关）+ 完整的部署/CICD/K8s 骨架，后续 Phase 1b~5 按方案分批接入。

---

## 目录

- [整体架构](#整体架构)
- [仓库结构](#仓库结构)
- [快速开始（本地 dev）](#快速开始本地-dev)
- [使用流程](#使用流程)
- [核心架构决策速查](#核心架构决策速查)
- [部署到 GCP（CICD）](#部署到-gcp-cicd)
- [错误码](#错误码)
- [当前实现进度](#当前实现进度)
- [安全说明](#安全说明)

---

## 整体架构

```
前端 Vue3 + VueFlow ──REST/WS──> [现有 Spring Cloud Gateway + Sa-Token]
                                          │
                                          ▼
                            FastAPI 控制面（多副本，编排/部署/拓扑生成）
                ┌──────────────┬──────────────┬──────────────┐
                ▼              ▼              ▼              ▼
         Redis Cluster   RabbitMQ        PostgreSQL      MinIO
        (输出PubSub/幂等) (vhost=/lhy-styon) (元数据+指针)  (代码/大字段)
                                          │
                                          ▼
                            运行时（两种模式）
              dev: Docker + (gVisor 可选)   |   prod: GKE Pod + KEDA
```

- **控制面绝不在 Pod 内跑 Docker**：dev 本地由开发者机器 / 本地 Linux runner 的 Docker daemon 承载；
  生产执行 = Block 自己的常驻 Deployment（`pyflow_runtime` 自消费 MQ / 暴露 `/invoke`，决策 3.1 模型 A）。
- **执行框架下沉为共享库 `pyflow_runtime`**：控制面（dev local）与 runner 镜像（prod）单一来源、同 pin 版本。

---

## 仓库结构

```
lhy-styon-python-flow-hub/
├── backend/                 # FastAPI 控制面（编排/部署/拓扑生成，不常驻消费生产队列）
│   ├── app/
│   │   ├── api/             # REST/WS 路由：blocks/flows/exec/deployments/rbac/ws/health
│   │   ├── core/            # sandbox(docker执行) / flow(DAG+runner) / ws(Redis PubSub)
│   │   ├── auth/            # sa_token_client + rbac（平台级角色 + 资源级 ACL）
│   │   ├── models/          # SQLAlchemy ORM（收敛版数据模型）
│   │   ├── observability/   # structlog / Prometheus / OTel
│   │   └── migrations/      # Alembic（独立 Cloud SQL 库）
│   └── Dockerfile
├── pyflow_runtime/          # 执行侧共享库：幂等状态机/条件引擎/输入映射/回复/退避/沙箱常量
├── runner/                  # runner 镜像（基础镜像 + pyflow_runtime；启动从 MinIO 拉代码）
├── frontend/                # Vue3 + Vite + Element Plus + VueFlow
├── deploy/k8s/              # namespace / pyflow-hub / migration-job / keda / ingress / node-pools
├── docker-compose.yml       # 本地依赖（PostgreSQL + Redis + RabbitMQ + MinIO）
├── cloudbuild.yaml          # Cloud Build：构建三镜像 + 迁移 + 滚动更新
└── .github/workflows/       # GitHub Actions：push master 自动部署 GCP
```

---

## 快速开始（本地 dev）

### 前置

- Python 3.11+、Node 22+、Docker（dev 沙箱执行需要；Windows 用 Docker Desktop）

### 1. 启动依赖中间件

```bash
docker compose up -d
```

### 2. 启动后端控制面

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install -e ../pyflow_runtime
copy ..\.env.example .env                          # 按需修改
uvicorn app.main:app --reload --port 8000
```

- 接口文档：http://localhost:8000/docs
- 健康检查：`/health/live`、`/health/ready`、`/metrics`

> 1a 默认 `PYFLOW_AUTH_ENABLED=false`，dev 默认用户视为 ADMIN，方便本地端到端。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

- 访问 http://localhost:5173（Vite 已代理 `/api`、`/ws` 到 8000）

> ⚠️ Windows 本机无 Docker 时，块执行会降级为 in-process（**仅 dev 调试，无隔离**）。生产务必走 Docker / K8s Pod。

---

## 使用流程

1. **新建调用块**：调用块库 → 新建 → 编写 `def run(inputs): ...` → 运行（Docker 沙箱）→ 实时查看 xterm 输出。
2. **编排流程**：流程编排 → 新建 Flow → 拖入块节点 / 条件分支节点 → 连线 → 保存（自动 DAG 无环校验）。
3. **运行整流**：Flow 编辑器「运行整流」→ 控制面按 DAG 拓扑序依次执行各块、内存传递 output→input、
   条件分支控制面求值后只激活命中路径（决策 10 同步编排在 dev 本地的等价路径）。
4. **执行历史**：查看每次执行的输入/返回值/stdout/stderr。
5. **部署中心**：创建 FlowDeployment（K8s 实际编排在 Phase 4a 接入）。

调用块代码约定：

```python
def run(inputs: dict) -> dict:
    # inputs 来自上游 output 或手动输入 JSON
    return {"result": inputs.get("value", 0) * 2}
```

---

## 核心架构决策速查

| 决策 | 要点 |
| --- | --- |
| 1 执行隔离 | venv 废弃；dev=Docker(+可选 gVisor)，prod=K8s Pod 原生隔离；控制面不跑 Docker |
| 2 鉴权 | 接现有 Sa-Token 网关（只校登录态）+ FastAPI 内平台级 RBAC |
| 3.1 MQ 模型 A | 生产异步单元=Block 常驻 Deployment 自消费；执行框架打进 runner 镜像 |
| 5 WS 路由 | 输出经 Redis Pub/Sub 跨副本；key 用 hash tag 杜绝 CROSSSLOT |
| 6 重试 | TTL+DLX 延迟重试 + 退避重入队列（防 KEDA 抖动） |
| 7 幂等 | 状态机 + fence_token CAS，区分在跑/可接管/终态，崩溃恢复不双跑 |
| 8 版本存储 | 大字段存 MinIO，DB 存指针；先 MinIO 后 DB + 对账 |
| 10 拓扑 | 同步编排（控制面调 /invoke）/ 异步编舞（Block 互发队列）二选一 |
| 12 容量 | 现集群 6vCPU 满载，专用节点池隔离，扩缩参数按容量推导不硬编码 |
| 13 可观测性 | 接现有 Cloud Trace + Cloud Logging + Prometheus（GMP PodMonitoring） |
| 15 资源级权限 | owner + grant 表，编辑/部署/查看三面粒度对称 |

完整决策见 `.cursor/plans/pyflowhub_平台_*.plan.md`。

---

## 部署到 GCP (CICD)

推送到 `master` 分支即自动触发 GitHub Actions → Cloud Build → GKE 滚动更新。

```
git push master
  → GitHub Actions（google-github-actions/auth + gcloud builds submit --async）
  → Cloud Build：构建 pyflow-hub / pyflow-runner / pyflow-web 三镜像 → 推 Artifact Registry
  → Alembic 迁移 Job（成功才滚动；失败中止发布）
  → kubectl set image 滚动更新控制面 + 前端
```

### 一次性配置（详见安装的 deploy skill）

1. 创建 GitHub Actions SA 并授权（cloudbuild/storage/serviceusage/container.developer 等）。
2. 生成 SA key，加密上传到仓库 Secret `GCP_SA_KEY`。
3. 创建专用节点池（`deploy/k8s/node-pools/node-pools.md`）。
4. 创建 K8s Secret `pyflow-hub-secret`（DB/Redis/RabbitMQ/MinIO 真实凭据，不落仓库明文）。

> 关键参数：GCP 项目 `lhy-styon-dev-4832`、区域 `us-central1-a`、集群 `lhy-styon-dev`、
> AR 仓库 `us-central1-docker.pkg.dev/lhy-styon-dev-4832/lhy-styon`、namespace `pyflow-blocks`。

---

## 错误码

号段对齐现有平台（1xxxx 认证 / 4xxxx 请求 / 5xxxx 系统），PyFlowHub 用每段内 `x18xx` 子区间：

| 错误码 | 含义 |
| --- | --- |
| 11801 / 11802 | 未登录·Token 无效 / 无操作权限（RBAC 不足） |
| 41801~41806 | 块/流不存在、版本未稳定、输入非法、DAG 成环、资源级权限不足 |
| 51801~51804 | 执行超时、沙箱错误、K8s 部署失败、MQ 发布失败 |

---

## 当前实现进度

| Phase | 状态 | 说明 |
| --- | --- | --- |
| 1a 执行内核 MVP | ✅ 已实现 | Block CRUD、Docker 沙箱执行、dev-local 整流编排、DAG 校验、WS 输出、VueFlow 画布、条件分支、Alembic 独立库 |
| 1b 网关/鉴权 | 🟡 骨架 | sa_token_client / rbac / ingress patch 已就位，待接入网关发布 |
| 2 异步触发 | 🟡 骨架 | pyflow_runtime 消费者/幂等/退避/回复已实现，待接 MQ 面板 |
| 3 版本管理 | ⬜ 规划 | MinIO 大字段 + diff |
| 4a/4b/4c K8s/供应链/GPU | 🟡 骨架 | RBAC/KEDA 模板/节点池/runner 镜像就位，待编排器接入 |
| 5 Jupyter | ⬜ 规划 | dev 专属 |

---

## 安全说明

- 输入校验、AES/SHA-256 加密、`BusinessException` + 错误码体系、资源及时释放（遵循工作区安全规范）。
- 敏感值只存 K8s Secret / Secret Manager，**不落 PostgreSQL、不写日志、不进仓库明文**。
- `env_vars` 命中疑似密钥正则（SECRET/TOKEN/PASSWORD/KEY/...）即拒绝，敏感值走 `secret_refs`。
- 条件表达式仅 jmespath/jsonpath，杜绝 `eval` RCE。
```
