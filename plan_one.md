# 企业级 RAG 平台：全新仓库重写（greenfield，全套技术栈）

> 本文件是落地计划（spec 见 [`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)）。
> 仓库根：`/Users/ywj/dev_code/AI_RAG/`（已确认原地构建，作为 enterprise-rag monorepo 根目录）。

---

## Context（为什么）

按 `docs/enterprise-rag-design.md`（v2.0 设计书）从零搭一个全新 monorepo。全新独立仓库 + 设计书全套技术栈（FastAPI + React + PG + Milvus + OpenSearch + Redis + Kafka + MinIO + K8s）。

本计划交付一个全新的、结构干净的 monorepo，严格按设计书 §3 的分层架构组织，全套基础设施一次性在 `docker-compose` 中就位，所有层都有真实代码骨架。多租户、SSE 流式、混合检索、区域级溯源等设计书核心能力从第一天就内建，而非事后嫁接。

---

## 关于"一次到位"的诚实边界

全套技术栈一次性接线就位（compose 全起、各层客户端初始化、所有 API/页面骨架存在），核心链路端到端可跑（上传 → 异步分块 → embedding → Milvus+OpenSearch 混合检索 → RRF → rerank → LLM 生成 → SSE 对话+引用溯源 → 多租户隔离）。

重型 / 长尾能力（YOLO 版面检测、PaddleOCR、GraphRAG、细粒度 RBAC、评估标注、A/B、CDC 连接器）留**真实接口 + 降级实现**，后续迭代填充。**这是多 session 工程，本计划 = 完整结构 + 第一份可运行核心。**

---

## 仓库位置与命名

- **路径**：`/Users/ywj/dev_code/AI_RAG/`（原地构建，已确认；作为 enterprise-rag monorepo 根目录）。
- 设计书位于 `docs/enterprise-rag-design.md`（由原 `README.md` 移入）。
- 新写项目级 `README.md`（总览 + 一键启动）。

---

## 目录结构（按设计书 §3 分层）

```
AI_RAG/
├── README.md                      # 项目总览 + 一键启动
├── docs/
│   ├── enterprise-rag-design.md   # v2.0 设计书（规格）
│   └── architecture.md            # 本仓库实现说明
├── docker-compose.yml             # 全套基础设施
├── docker-compose.dev.yml         # 热重载覆盖
├── .env.example
│
├── backend/                       # FastAPI BFF + 服务层（Python 3.11, async）
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                # FastAPI app + lifespan(初始化 infra) + 路由注册
│   │   ├── core/
│   │   │   ├── config.py          # pydantic-settings：所有 infra URL/开关
│   │   │   ├── tenant.py          # X-Tenant-Id 解析 → TenantContext
│   │   │   ├── exceptions.py      # AppError 体系（含 404 子类）
│   │   │   └── logging.py         # 结构化日志（OTel-ready）
│   │   ├── api/                   # 应用网关层（BFF）
│   │   │   ├── deps.py            # DI：tenant / stores / services
│   │   │   └── v1/
│   │   │       ├── chat.py        # POST /chat（SSE token+引用流式）
│   │   │       ├── documents.py   # /upload-url 预签名、list、/locate?page+bbox
│   │   │       ├── knowledge_bases.py
│   │   │       ├── conversations.py
│   │   │       ├── model_configs.py
│   │   │       ├── feedback.py
│   │   │       ├── tenants.py
│   │   │       └── admin/scenes.py
│   │   ├── db/                    # 存储与索引层·元数据（PostgreSQL）
│   │   │   ├── database.py        # async engine + Session
│   │   │   ├── models.py          # 多租户 schema
│   │   │   └── migrations/        # Alembic
│   │   ├── repositories/          # 仓储（全部 tenant_id 前置过滤）
│   │   ├── schemas/               # Pydantic 请求/响应/领域
│   │   ├── infra/                 # 有状态存储客户端
│   │   │   ├── milvus.py          # 每租户 collection + HNSW
│   │   │   ├── opensearch.py      # 每租户 index（BM25 + 结构化过滤）
│   │   │   ├── redis.py           # 查询/嵌入缓存、会话
│   │   │   ├── kafka.py           # 异步数据处理 producer/consumer
│   │   │   └── object_storage.py  # MinIO/S3 原文档+渲染图
│   │   ├── services/
│   │   │   ├── ingestion/         # 数据接入层 §4.1
│   │   │   │   ├── connectors/    # file/s3(真实) · db/wiki/api(接口+stub)
│   │   │   │   ├── parser.py      # 多格式解析→标准中间表示
│   │   │   │   └── sync.py        # 增量同步（hash/timestamp；CDC 接口）
│   │   │   ├── knowledge/         # 知识处理层 §4.2
│   │   │   │   ├── pdf_layout.py  # 分级：文本层取 bbox → 复杂/扫描件触发版面检测（YOLO hook）
│   │   │   │   ├── ocr.py         # PaddleOCR hook（区域级）
│   │   │   │   ├── chunker.py     # 固定/语义/结构/父子/版面区域
│   │   │   │   └── embedding.py   # 可插拔（按 model_config），批量异步
│   │   │   ├── retrieval/         # 检索编排层 §4.4（四段流水线）
│   │   │   │   ├── query.py       # 查询理解：改写/扩展/路由
│   │   │   │   ├── vector.py      # Milvus 向量召回
│   │   │   │   ├── keyword.py     # OpenSearch BM25 召回
│   │   │   │   ├── fusion.py      # RRF 融合 + MMR 多样性
│   │   │   │   ├── reranker.py    # Cross-Encoder 精排（可插拔）
│   │   │   │   └── orchestrator.py
│   │   │   ├── generation/        # 生成与应用层 §4.5
│   │   │   │   ├── llm_gateway.py # 多模型路由/降级/限流配额
│   │   │   │   ├── prompts.py     # Prompt 模板中心（版本/灰度）
│   │   │   │   └── citation.py    # 后处理：引用标注 page+bbox
│   │   │   └── rag.py             # 端到端编排（检索×生成 + 降级）
│   │   ├── workers/               # 异步数据处理消费者（与在线链路解耦）
│   │   │   ├── ingest_worker.py   # 解析→分块→embedding→写索引
│   │   │   └── layout_worker.py   # GPU 版面检测/OCR 独立池
│   │   └── governance/            # 平台治理层 §6/§8
│   │       ├── authz.py           # RBAC（首版接口+前置过滤）
│   │       ├── audit.py
│   │       └── config_center.py   # 场景配置（KB+检索策略+Prompt+权限）
│   └── tests/                     # pytest：隔离/检索/ingestion/API
│
├── frontend/                      # React + TS + Vite + Ant Design + Zustand（下一轮）
│   └── ...
│
├── deploy/                        # Dockerfile + k8s + HPA（下一轮）
└── monitoring/                    # Prometheus + Grafana（下一轮）
```

---

## docker-compose.yml（全套基础设施，一条命令起）

| 服务 | 镜像 | 用途（设计书 §4.3/§10） |
|---|---|---|
| postgres | postgres:16 | 元数据、租户、权限、Chunk 溯源坐标 |
| milvus (+ etcd + minio-for-milvus) | milvusdb/milvus | 向量 ANN（每租户 collection） |
| opensearch | opensearchproject/opensearch | BM25 倒排 + 结构化过滤（每租户 index） |
| redis | redis:7 | 查询/embedding 缓存、会话、渲染图缓存 |
| kafka (KRaft 单节点) | confluentinc/cp-kafka | 异步数据处理管道 |
| minio | minio/minio | 原始文档 + 页面渲染图 |
| backend / ingest-worker | 本仓库构建 | 应用服务 |

> 单 `docker compose up` 即可拉起整个平台。dev 覆盖文件为 backend 提供热重载。

---

## 数据模型（PostgreSQL，多租户内建）

所有业务表带 `tenant_id` + 复合唯一约束（隔离模式）：

`tenants` · `knowledge_bases` · `documents`(status/embedding_status) · `chunks`(含 `page_no` + `bbox` 归一化坐标，冗余 `tenant_id` 供检索前置过滤) · `model_configs`(llm/embedding/rerank 可插拔) · `conversations` · `messages`(多轮) · `feedback`(点赞/标注) · `operation_logs`(审计) · `scene_configs`(场景四要素)。

Alembic 管理迁移。

---

## 关键实现要点（对齐设计书原则 §3.1）

- **检索与生成解耦**：`/retrieve` 与 `/chat` 分离，检索服务可独立复用。
- **多路召回 + 统一精排**：vector + keyword 并行 → RRF 融合 → Cross-Encoder rerank（无 rerank 配置时降级跳过）。
- **异步化**：上传只入队，`ingest_worker` 消费做 解析→分块→embedding→双写 Milvus/OpenSearch；GPU 版面/OCR 走独立 `layout_worker`。
- **溯源全链路透传**：解析阶段产出 `{doc_id, page_no, bbox}` → 存 chunk → 检索结果透传 → 生成引用 → `/locate` 返回 → 前端 PDF.js 高亮。
- **多租户隔离**：`X-Tenant-Id` → 仓储前置过滤 + Milvus/OpenSearch 每租户 collection/index；无 header 回退 default。
- **降级**：向量超时→仅 BM25；视觉解析超时→纯文本抽取兜底；主 LLM 不可用→备用/mock。

---

## 第一步执行顺序（本计划落地）

1. 建仓库 + README + 设计书就位 + `.env.example` + `docker-compose.yml`（全套 infra）。
2. backend：core(config/tenant/exceptions) + PG(models + Alembic) + infra 客户端(Milvus/OpenSearch/Redis/Kafka/MinIO 初始化 + 每租户建库)。
3. services：ingestion(parser/chunker) → knowledge(embedding 可插拔) → retrieval(vector+keyword+RRF+rerank) → generation(llm_gateway/prompts/citation) → rag 编排。
4. workers：ingest_worker（Kafka 消费全链路）；layout_worker 接口 + 文本兜底。
5. api：chat(SSE)、documents(upload-url/list/locate)、KB、conversations、model_configs、tenants、feedback、admin/scenes；多租户依赖注入。
6. frontend：Vite+React+TS+AntD+Zustand；api/SSE/tenant；Chat / KnowledgeBases / DocumentPreview(PDF.js bbox) / Admin。
7. deploy（Dockerfile + k8s + HPA）+ monitoring（Prometheus/Grafana）。
8. 冒烟测试 + README 启动说明。

> 每步可独立验证；结构先全铺好再逐层填实现。

---

## 验证（端到端）

1. `docker compose up` 拉起全套 infra；`alembic upgrade head` 建表。
2. 冒烟：上传 1 个 PDF/TXT → `ingest_worker` 日志显示 解析→分块→embedding→双写 → Milvus/OpenSearch 出现向量/文档。
3. `POST /chat`（SSE）：收到流式 token + 引用列表（含 page_no+bbox）；切租户后互不可见。
4. 前端：`npm run dev` → 对话打字机 + 点引用卡片 → PDF.js 渲染对应页 + bbox 高亮。
5. `pytest backend/tests`：多租户隔离、混合检索 RRF、ingestion 解析分块、API。
6. 降级手测：关掉 Milvus → 查询自动降级仅 BM25 仍返回结果。

---

## 风险与说明

- **体量**：这是多 session 工程。本计划交付完整结构 + 可运行核心链路；YOLO/OCR/GraphRAG/RBAC/评估等为接口+降级实现，后续迭代。每步可验证、可中断续做。
- **embedding/LLM 默认**：可插拔，默认走 OpenAI 兼容接口（可指向 anthropic/openai/百炼），通过 `model_configs` 配置；无 key 时降级到本地占位以便空跑。
- **GPU 依赖**：layout/OCR worker 首版用文本层兜底，不强制 GPU；接入 YOLO 服务时按需启用。
