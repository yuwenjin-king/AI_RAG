# 部署（Kubernetes）

应用层（backend / ingest-worker / frontend）的 k8s 清单。有状态基础设施（PostgreSQL / Milvus / OpenSearch / Redis / Kafka / MinIO）**生产建议用云托管服务或官方 Helm Chart**，不在本目录内（开发用根目录 `docker-compose.yml`）。

> 镜像构建与开发运行见仓库根 `README.md`；这里聚焦生产 K8s 部署。

## 1. 构建并推送镜像

```bash
# 后端（BFF + 服务层）
docker build -t enterprise-rag/backend:latest ./backend
# 前端（nginx 托管 + /api 反代）
docker build -t enterprise-rag/frontend:latest ./frontend
# 推送到你的镜像仓库后，修改本目录 yaml 中的 image
```

## 2. 准备配置

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml       # 按生产 infra 地址修改
cp k8s/secret.yaml.example k8s/secret.yaml  # 填入真实密钥
kubectl apply -f k8s/secret.yaml
```

> `secret.yaml` 已在 `.gitignore`，勿提交真实密钥。

## 3. 部署应用层

```bash
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/backend-hpa.yaml
kubectl apply -f k8s/ingest-worker.yaml
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/ingress.yaml          # 改 host + ingressClassName
```

## 4. 建表

```bash
kubectl -n enterprise-rag exec deploy/backend -- alembic upgrade head
```

## 要点

| 项 | 说明 |
|---|---|
| 无状态扩缩容 | backend / frontend 无状态，HPA 按 CPU/内存自动扩缩；ingest-worker 按副本数并行消费 Kafka |
| SSE | ingress 已关 `proxy-buffering` + 长超时，保证对话流式 token 实时 |
| 探针 | backend readiness/liveness 打 `/api/v1/healthz` |
| 监控 | backend 暴露 `/metrics`；生产用 Prometheus Operator + ServiceMonitor 抓取，看板 JSON 复用 `monitoring/grafana/dashboards/` |
| 多 AZ | 无状态服务跨 ≥2 AZ 调度（`topologySpreadConstraints`，按需加）；有状态 infra 走托管多 AZ |

## 进阶（后续迭代）

- **基于队列积压的自动扩缩**：安装 [KEDA](https://keda.sh) 后 `kubectl apply -f k8s/ingest-worker-scaledobject.yaml`，`ingest-worker` 随 Kafka `rag.ingest` 消费组 lag 自动扩缩（设计书 §7）。可与 `backend-hpa.yaml`（CPU/内存）并存。
- **GPU 池**：`layout-worker` 独立 nodepool + `nodeSelector`/tolerations 调度 GPU，处理扫描件版面检测/OCR。
- **灰度/金丝雀**：ingress + 多 Deployment 权重，配合设计书 §9 A/B 测试框架。
