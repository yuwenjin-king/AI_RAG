# 规模化与性能（设计书 §2.2 / §4.3 / §7）

压测方法论、目标与可调旋钮。脚本在 `loadtest/`（k6）。

## 目标（设计书 §2.2）

| 指标 | 目标 |
|---|---|
| 纯检索 P95 | ≤ 300 ms |
| 端到端对话 P95（含生成） | ≤ 3 s |
| 起步 QPS | 300–500，架构支持扩至 2000+ |
| 数据规模 | 100 万+ 文档 / 1000 万+ chunk |

## 运行压测（k6）

```bash
# 安装：https://k6.sh
# 检索/对话压测
k6 run -e BASE=http://localhost:8000 -e TENANT=default loadtest/k6_chat.js

# 数据接入压测（观察 ingest_worker 扩缩 / KEDA）
k6 run -e BASE=http://localhost:8000 -e TENANT=default loadtest/k6_ingest.js
```

关注输出：`http_req_duration p(95)`、`http_reqs/s`、`vus`、失败率。结合 Grafana「Enterprise RAG 概览」看板的 **检索延迟 P95 / 端到端延迟 P95 / 索引写入速率 / 降级事件**。

## 可调旋钮（按瓶颈定位）

| 瓶颈 | 旋钮 | 位置 |
|---|---|---|
| 向量召回延迟/召回率 | HNSW `M` / `efConstruction` / `ef` | `.env`：`HNSW_M` / `HNSW_EF_CONSTRUCTION` / `HNSW_EF_SEARCH` |
| 大租户隔离/分片 | 每租户独立 collection | `.env`：`COLLECTION_PER_TENANT=true` |
| 关键词召回（生产必须） | OpenSearch 分片/副本 | `docker-compose.yml` opensearch |
| 数据处理积压 | ingest_worker 副本 / KEDA lag 阈值 | `deploy/k8s/ingest-worker-scaledobject.yaml` |
| 在线 QPS | backend HPA / 副本 | `deploy/k8s/backend-hpa.yaml` |
| 热点 embedding/查询 | 缓存开关与 TTL | `.env`：`EMBEDDING_CACHE_*` / `QUERY_CACHE_*` |

## 数据灌库（百万级）

- 批量上传走 `loadtest/k6_ingest.js`（调高 stages target）或自写脚本走 `/documents/upload-url` → `/upload`。
- 灌库期间观察 `rag_ingest_total`、`rag_chunks_indexed_total`、Kafka lag、Milvus/OpenSearch 资源。
- 灌完后跑 `loadtest/k6_chat.js` 验证检索 P95 与 QPS 上限，记录到 `docs/loadtest.md`（作为基线）。

## 冷热分层（后续）

低频历史文档索引可降级至低成本存储层、按需加载（设计书 §4.3）；本次未内置 tier 字段，列为后续迭代。
