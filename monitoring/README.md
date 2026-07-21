# 监控（Prometheus + Grafana）

`docker compose up` 已包含 `prometheus` 与 `grafana`，开箱即用。

## 访问

| 服务 | 地址 | 凭据 |
|---|---|---|
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / admin |

Grafana 启动时自动：
- 配置 Prometheus 数据源（`provisioning/datasources/`）
- 导入 **「Enterprise RAG 概览」** 看板（`provisioning/dashboards/` + `dashboards/rag-overview.json`）

## 抓取

Prometheus 抓取 `backend:8000/metrics`（见 `prometheus.yml`）。后端指标定义在 `backend/app/core/metrics.py`。

## 看板指标（对应设计书 §9 评估/监控）

- 对话请求速率（按租户）
- 端到端对话延迟 P50/P95/P99（目标 P95 ≤ 3s）
- 纯检索延迟 P50/P95/P99（目标 P95 ≤ 300ms）
- HTTP 请求延迟 P95（按路径）
- LLM 调用速率（按状态 ok/failed/mock）+ LLM 失败率
- 文档处理速率（indexed / failed）+ 索引写入速率（chunks/s）
- 降级事件速率（按类型，设计书 §7 降级可观测）
