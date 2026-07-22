# 运维 Runbook

日常启动、降级开关、Worker、监控与常见排障。前置：[`README.md`](../README.md)、[`architecture.md`](./architecture.md)。

## 1. 启动

```bash
cp .env.example .env            # 按需填 LLM/Embedding key（不填也能跑，自动降级）
docker compose up -d --build
docker compose exec backend alembic upgrade head   # 建表（含 0001/0002 迁移）
```

访问：前端 `http://localhost:5173` ｜ API `http://localhost:8000/docs` ｜ Grafana `:3000`(admin/admin) ｜ Prometheus `:9090` ｜ MinIO 控制台 `:9001`。

健康：`GET /api/v1/healthz`、`GET /api/v1/status`（各 infra 在线状态）。

## 2. 降级 / 功能开关（.env）

| 开关 | 默认 | 关闭/缺省时的行为 |
|---|---|---|
| `LLM_API_KEY` | 空 | 生成降级 mock（直引检索结果）；查询改写/扩展透传 |
| `EMBEDDING_PROVIDER` / `EMBEDDING_API_KEY` | auto | 无 key → 哈希占位向量（仅跑通链路） |
| `MILVUS_ENABLED` / `OPENSEARCH_ENABLED` / `REDIS_ENABLED` | true | 关 → 检索仅 BM25 本地兜底 / 缓存失效 |
| `VISION_ENABLED` | false | 扫描件走纯文本层（可能无文本） |
| `GRAPH_ENABLED` | false | 图召回第三路关闭；neo4j 未配 → 内存图 |
| `RBAC_ENABLED` | true | 关 → 权限宽放 |
| `PII_MASKING_ENABLED` | false | 关 → 原文不脱敏入库 |
| `QUERY_CACHE_ENABLED` / `EMBEDDING_CACHE_ENABLED` | true | 关 → 不缓存 |
| `RATE_LIMIT_CHAT_PER_MIN` | 60 | 0 = 不限流 |
| `SYNC_INGEST_FALLBACK` | true | Kafka 不可用时上传同步触发 ingest |

> 设计原则：每个 infra / 重型能力独立降级，单个不可用不阻断主链路；降级经响应 `degraded` 字段与指标 `rag_degraded_total` 透出。

## 3. Worker

| Worker | 触发 | 作用 | 不可用时 |
|---|---|---|---|
| `ingest_worker` | Kafka `rag.ingest` | 解析→分块→embedding→双写（+抽实体入图） | 轮询 `pending/failed` 兜底 |
| `layout_worker`（`--profile vision`） | Kafka `rag.layout` | 扫描件/复杂件 版面检测+OCR | `vision_enabled=false` 时退出 |
| `cdc_worker` | Kafka `rag.cdc` | 数据源变更→增量 ingest/delete | CDC 需 Kafka，不可用阻塞重连 |

```bash
docker compose up -d --profile vision     # 启用视觉 worker
docker compose logs -f ingest-worker
```

## 4. 监控

Grafana「Enterprise RAG 概览」看板（自动配置）：检索/端到端延迟 P95、LLM 调用与失败率、ingest 速率、降级事件、缓存命中、token 成本。告警阈值参考设计书 §2.2（检索 P95≤300ms、端到端≤3s）。

## 5. 评估与压测

```bash
docker compose exec backend python -m app.eval --tenant default --scene <scene_id>   # 离线评估
k6 run -e BASE=http://localhost:8000 loadtest/k6_chat.js                              # 检索/对话压测
```

## 6. 常见排障

| 现象 | 排查 |
|---|---|
| 对话返回 mock 提示 | 未配 `LLM_API_KEY`；配后真实生成 |
| Milvus upsert 报维度不符 | `EMBEDDING_DIM` 与所选 Embedding 模型不一致（如 GLM embedding-3=2048） |
| 扫描件 `status=failed` 无文本 | 未启用 `VISION_ENABLED`+OCR；启用 `--profile vision` |
| `/chat` 429 | 触发 per-tenant 限流，调高 `RATE_LIMIT_CHAT_PER_MIN` |
| 文档一直 `pending` | ingest_worker 未起或 Kafka 异常；`SYNC_INGEST_FALLBACK=true` 兜底 |
| 检索只有 BM25 | Milvus 未就绪（`/api/v1/status` 查看）；属降级，非故障 |
| `alembic upgrade` 报错 | 0002 幂等；确认 PG 可达、`DATABASE_URL` 正确 |

## 7. 数据库迁移

迁移 `0001`（建表，metadata.create_all）+ `0002`（幂等：eval_cases / scene.variants / message.meta）。后续结构变更用 `alembic revision --autogenerate` 生成增量迁移，保持幂等。

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```
