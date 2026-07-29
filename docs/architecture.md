# 实现说明（architecture）

本仓库当前实现版本相对于 [`enterprise-rag-design.md`](./enterprise-rag-design.md)（v2.0 设计书）的落地状态、降级策略与可插拔点。

> 状态：**plan_one/two/three/four 已交付** — 后端核心全链路 + React 前端 + 可观测 + K8s + 认证授权 + Agentic RAG + OTel + 多模态 + 韧性 + DR + 真实评估集 + 安全闭环。进度见 [`README.md`](../README.md) §路线 与各 `plan_*.md`。

---

## 1. 已实现（核心链路端到端可跑）

| 设计书模块 | 实现位置 | 说明 |
|---|---|---|
| 应用网关层 (BFF) | `backend/app/api/` | FastAPI async，**真实认证授权（plan_three §1 + plan_four §1：JWT + 接口级 `require_roles` 角色门禁，viewer 只读）**、请求编排、SSE 流式转发 |
| 数据接入层 §4.1 | `backend/app/services/ingestion/` | 文件连接器（真实）、parser、增量同步接口（hash/timestamp）；DB/Wiki/API 连接器为接口 + stub |
| 知识处理层 §4.2 | `backend/app/services/knowledge/` | PDF 文本层抽取（PyMuPDF）含 bbox；分级版面检测/OCR 为 hook + 文本兜底；**多模态表格抽取（plan_three §4，pdfplumber/camelot→Markdown/HTML 结构化 chunk，行感知切分保行列，bbox 溯源）+ 图片 VLM caption hook**；固定/结构/版面区域/父子分块；embedding 可插拔 |
| 存储与索引层 §4.3 | `backend/app/infra/` + `backend/app/db/` | PG 元数据（Alembic）、Milvus 每租户 collection（HNSW）、OpenSearch 每租户 index（BM25）、Redis、MinIO、Kafka |
| 检索编排层 §4.4 | `backend/app/services/retrieval/` | 四段流水线：查询理解（**LLM 改写/扩展，多子查询多路召回**）→ vector+keyword → RRF 融合 + MMR → Cross-Encoder rerank（可插拔）；**父子 Small-to-Big 上下文回溯** |
| 生成与应用层 §4.5 | `backend/app/services/generation/` | LLM 网关（OpenAI 兼容，多模型路由/降级/SSE 流式 + 非流式 complete）、Prompt 模板（用父块上下文）、引用标注（page+bbox） |
| 知识处理·增强 | `backend/app/services/knowledge/` | 父子分块（chunker）+ 可插拔 embedding（OpenAI 兼容 / 本地 sentence-transformers / mock）；**版面检测抽象（pymupdf 基线 + YOLO hook）+ OCR（PaddleOCR hook）** |
| 视觉解析异步化 | `backend/app/services/vision.py` + `workers/layout_worker.py` | 扫描件/复杂件入队 `rag.layout` → 版面检测+区域级 OCR → 重新分块索引；Kafka 不可用轮询 `layout_pending` |
| 平台治理层 §6/§8 | `backend/app/governance/` | RBAC 接口 + 前置过滤、审计日志、场景配置中心（四要素）；**接口级角色门禁（plan_four §1）** |
| 多租户隔离 §6 | `backend/app/core/tenant.py` + repositories | `X-Tenant-Id` → 仓储前置过滤 + Milvus/OpenSearch 每租户库；**认证开启后租户取自 JWT（不可伪造）** |
| RBAC 前置过滤 §6/§8 | `backend/app/governance/authz.py` | `PermissionFilter` 注入 vector/keyword/bm25 作检索前置过滤（场景/角色规则）；**`rbac_default_deny` 最小权限默认（plan_four §1）**；防越权 |
| 成本管控 §4.5/§2.2 | `embedding.embed_texts` / `orchestrator` / `core/ratelimit.py` | embedding+查询结果 Redis 缓存；per-tenant 限流（Redis 计数+本地兜底）；LLM token 成本指标 |
| 评估与 A/B §9 | `app/eval/`（metrics/runner/ab/seed/corpus）+ `repositories/eval.py` + `api/v1/admin/eval.py` | 离线评估集 + Recall@K/MRR/NDCG/引用/bbox/faithfulness 指标（`python -m app.eval [--with-generation]`）；**确定性语料 + 回归门禁（plan_four §2，`make eval-seed`）**；A/B 按用户×场景确定性分桶、变体可覆盖 Top-K、反馈按变体聚合 |
| 安全合规 §8 | `ingestion/pii.py` + `governance/audit.py` + `api/v1/admin/audit.py` + `docs/security.md` | PII 脱敏（接入阶段，可配规则）；审计落库 + 查询；传输 TLS/静态加密/密钥管理 部署清单（ingress cert-manager） |
| 规模化 §4.3/§7 | `milvus_store` HNSW 参数 + `services/render.py` + `loadtest/` | HNSW M/efConstruction/ef 可配；每租户 collection 开关；PDF 页面渲染图缓存；k6 压测脚本 + 方法论文档 |
| GraphRAG §4.3/§4.4 | `infra/graph_store.py` + `knowledge/graph.py` + `retrieval/graph.py` | 图存储(内存兜底/Neo4j 懒加载)；实体抽取(LLM+启发式)；图召回作 vector/keyword 之外第三路入 RRF；gated by `GRAPH_ENABLED` |
| CDC §4.1 | `ingestion/connectors/cdc.py` + `workers/cdc_worker.py` + `connectors/db.py` | Debezium 风格事件 → upsert 触发 ingest / delete 清理；DB 轮询 + hash/timestamp 差量连接器 |
| 认证授权 plan_three §1 / plan_four §1 | `core/security.py` + `core/auth.py` + `repositories/users.py` + `api/v1/auth.py` | JWT（HS256，stdlib）+ 用户/租户/角色模型 + `/auth/login`·`/auth/me`·`make seed-admin`；**15 个写/admin 接口接 `require_roles`（viewer 只读）+ `rbac_default_deny` 最小权限**；默认 `AUTH_ENABLED=false` 兼容开发 |
| Agentic RAG plan_three §2 | `retrieval/agentic.py` + `generation/selfcheck.py` | 检索充分性评估 + 迭代召回（LLM judge + 启发式双实现）+ 答案 faithfulness 自检；`AGENTIC_ENABLED` 门控，默认关 |
| 可观测 plan_three §3 | `core/tracing.py` + `core/metrics.py` + compose jaeger | Prometheus 指标 + **OpenTelemetry 分布式追踪**（console/otlp，未装 otel 自动降级 no-op）；`make up-otel` |
| 韧性 plan_three §5 | `core/resilience.py` + `/healthz`·`/readyz` | 外部调用熔断器 + 重试（tenacity）；DB 池 config 化 + 慢查询日志；存活/就绪探针分离 + lifespan 优雅关停 drain |
| 备份恢复 / DR plan_three §6 | `scripts/dr/`（manifest/pg_meta/stores/backup/restore）+ `Makefile` | PG 权威源 + Milvus/MinIO best-effort + OpenSearch 可选；sha256 校验 + 恢复演练；`make backup`·`make restore`；`docs/dr-runbook.md` |

## 2. 接口 + 降级实现（首版不内置重型实现）

| 能力 | 当前形态 | 接入方式 |
|---|---|---|
| YOLO 版面检测 | `knowledge/layout_detector.py::DocLayoutYoloDetector`（ultralytics，已实现推理流程，懒加载）+ pymupdf 基线已生效 | 设 `PDF_LAYOUT_DETECTOR=yolo` + `YOLO_MODEL_PATH` + 装 ultralytics（建议 GPU） |
| PaddleOCR | `knowledge/ocr.py::PaddleOCREngine`（已实现区域级识别） | 设 `OCR_ENGINE=paddle` + 装 paddleocr；`vision.py` 自动逐页 OCR |
| camelot 表格抽取 | `knowledge/tables.py::CamelotExtractor`（lattice/stream，已实现，需 ghostscript） | 设 `TABLE_EXTRACTOR=camelot` + 装 camelot-py；pdfplumber 已在核心依赖 |
| DB/Wiki/API 连接器 | `ingestion/connectors/base.py` 接口 + 文件连接器（真实）；DB/Wiki/API 为接口 + stub | 实现接口接入新数据源 |
| 细粒度 RBAC 规则引擎 | 端点 `require_roles` 角色门禁 + 文档级 `PermissionResolver`（含 `rbac_default_deny`）已实现 | 扩展为规则数据源（文档/知识库级权限落库） |

## 3. 降级链路（设计书 §7）

```
向量检索超时/不可用 ─► 仅 BM25 关键词召回 ─► 正常返回（标注降级）
视觉解析超时/无模型 ─► 纯文本层抽取（bbox 由文本块坐标兜底）
主 LLM 不可用/无 key ─► 备用模型 ─► mock 模板答案（标注降级）
Rerank 未配置        ─► 跳过精排，直接用 RRF 排序结果
Embedding 无 key     ─► 哈希占位向量（仅跑通链路，无真实语义）
```

降级会在响应中通过 `degraded: [string]` 字段透出，前端据此提示。

## 4. 可插拔点

- **Embedding**：`knowledge/embedding.py` — `EmbeddingProvider` 接口；按 `model_configs` 选择 provider
- **LLM**：`generation/llm_gateway.py` — OpenAI 兼容 client + mock；多模型路由按场景配置
- **Rerank**：`retrieval/reranker.py` — `Reranker` 接口；无配置即 NoOp
- **解析器/分块器**：`ingestion/parser.py`、`knowledge/chunker.py` — 按文件类型与场景策略路由
- **连接器**：`ingestion/connectors/base.py` — 新数据源实现接口即可

## 5. 与设计书的差异（务实取舍）

- **Kafka**：首版用 KRaft 单节点（开发足够），生产再扩多副本
- **多租户索引隔离**：中小租户默认**共享 collection + tenant_id 过滤**（逻辑隔离，低成本）；高安全租户可配独立 collection（接口已预留 `collection_per_tenant` 开关）
- **父子分块**：数据模型已预留 `parent_chunk_id`；首版检索用 chunk 本体，生成上下文回溯父块作为 stretch
- **PDF 高亮**：后端产出 `page_no + bbox` → 前端 `DocumentPreviewPage` 用 PDF.js 渲染原页 + bbox 高亮层（已交付；`/preview/:docId/:chunkId`，pdfjs 路由级懒加载）
