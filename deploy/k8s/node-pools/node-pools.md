# PyFlowHub 专用节点池（决策 12：与现有业务物理隔离）

> ⚠️ 现集群 `lhy-styon-dev` = `3 × e2-standard-2 = 6 vCPU / 24GB` 已满载。
> 新增节点池前必须先确认 GCE 配额；GPU 配额默认 0，须提前申请。

## 控制面节点池（pyflow-control）

```bash
gcloud container node-pools create pyflow-control \
  --cluster=lhy-styon-dev --zone=us-central1-a \
  --machine-type=e2-standard-2 --num-nodes=1 \
  --enable-autoscaling --min-nodes=1 --max-nodes=2 \
  --node-labels=pyflow-pool=control \
  --project=lhy-styon-dev-4832
```

## 执行节点池（pyflow-workers）

```bash
gcloud container node-pools create pyflow-workers \
  --cluster=lhy-styon-dev --zone=us-central1-a \
  --machine-type=e2-standard-4 --num-nodes=0 \
  --enable-autoscaling --min-nodes=0 --max-nodes=3 \
  --node-labels=pyflow-pool=workers \
  --node-taints=pyflow-workers=true:NoSchedule \
  --spot \
  --project=lhy-styon-dev-4832
```

## GPU 节点池（pyflow-gpu-workers，Phase 4c）

```bash
# GPU 配额须先申请；T4/L4/A100 + Spot 在 us-central1-a 可用性不确定
gcloud container node-pools create pyflow-gpu-workers \
  --cluster=lhy-styon-dev --zone=us-central1-a \
  --machine-type=n1-standard-8 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --num-nodes=0 --enable-autoscaling --min-nodes=0 --max-nodes=2 \
  --node-taints=pyflow-gpu=true:NoSchedule \
  --spot \
  --project=lhy-styon-dev-4832
```

`maxReplicaCount` = 节点池可用核数 / 单 Block limit（保守取值），KEDA `value` 按单条消息处理耗时标定，
均由部署时根据节点池规格计算，**不硬编码 20/5**（决策 12）。
