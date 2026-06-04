# PyFlowHub IAM / Workload Identity 配置（决策 11/14）

## 1. 专用最小权限构建 SA（Phase 4b 供应链加固）

```bash
PROJECT=lhy-styon-dev-4832
gcloud iam service-accounts create pyflow-builder \
  --display-name="PyFlow runner image builder" --project=$PROJECT

# 仅授 Artifact Registry writer + 读依赖源；禁止任何业务数据/Secret/部署权限
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:pyflow-builder@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:pyflow-builder@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
```

## 2. 按块类型隔离的托管块 GSA（Phase 4c，决策 14）

```bash
# BigQuery 块：仅 dataViewer + jobUser
gcloud iam service-accounts create pyflow-block-bq --project=$PROJECT
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:pyflow-block-bq@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:pyflow-block-bq@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

# GCS 块：仅 objectViewer（需写再单授 objectAdmin 到指定 bucket）
gcloud iam service-accounts create pyflow-block-gcs --project=$PROJECT
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:pyflow-block-gcs@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

## 3. Workload Identity 绑定（KSA ↔ GSA）

```bash
for pair in "pyflow-block-bq:pyflow-block-bq" "pyflow-block-gcs:pyflow-block-gcs"; do
  KSA="${pair%%:*}"; GSA="${pair##*:}"
  gcloud iam service-accounts add-iam-policy-binding \
    "$GSA@$PROJECT.iam.gserviceaccount.com" \
    --role="roles/iam.workloadIdentityUser" \
    --member="serviceAccount:$PROJECT.svc.id.goog[pyflow-blocks/$KSA]"
done
kubectl apply -f deploy/k8s/workload-identity/ksa.yaml
```

> dev local：用开发者个人 ADC / 显式短期凭据，**禁止把生产 GSA key 下发到本地容器**（决策 14）。
> 资源 scope 预检：块声明 `gcp_resource_scope`，部署前校验对应 GSA 是否已授权该资源，未授权拒绝部署（PYFLOW_K8S_DEPLOY_FAILED）。
