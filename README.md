# Enterprise RAG Platform

企业级 / 工业级多租户 RAG 检索平台。FastAPI（BFF + 服务层）+ React 前端 + 全套基础设施（PostgreSQL / Milvus / OpenSearch / Redis / Kafka / MinIO），一套 `docker compose up` 拉起。

> 📐 设计规格：[`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)（v2.0）
> 🏗️ 实现说明：[`docs/architecture.md`](./docs/architecture.md)
> 📋 落地计划：[`plan_one.md`](./plan_one.md)

---

## 能力（首轮可运行核心）

- **多租户隔离**：`X-Tenant-Id` → 仓储前置过滤 + Milvus/OpenSearch 每租户库；无 header 回退 `default`
- **异步数据管道**：上传只入队（Kafka），`ingest_worker` 消费做 解析 → 分块 → embedding → 双写索引
- **混合检索 + 精排**：向量（Milvus）+ 关键词（OpenSearch BM25）并行召回 → RRF 融合 → Cross-Encoder rerank（可插拔，无配置跳过）
- **区域级溯源**：PDF 文本层抽取 `page_no + bbox` → chunk 元数据 → 检索透传 → 生成引用 → `/locate` 返回 → 前端 PDF.js 高亮
- **SSE 流式问答**：`POST /chat` 逐 token 推送 + citations 事件
- **降级链路**：向量超时→仅 BM25；视觉解析超时→纯文本；主 LLM 不可用→备用/mock
- **可插拔模型**：LLM / Embedding / Rerank 走 OpenAI 兼容接口，无 key 时自动降级到本地占位（空跑可用）

---

## 快速开始

### 1. 准备配置

```bash
cp .env.example .env
# 按需编辑：LLM_API_KEY / LLM_BASE_URL / EMBEDDING_API_KEY 等
# 不填也能跑（自动降级到 mock）
```

### 2. 拉起全套基础设施 + 服务

```bash
docker compose up -d --build
# 首次会拉取 postgres/milvus/opensearch/redis/kafka/minio 镜像，耐心等待
```

### 3. 建表

```bash
docker compose exec backend alembic upgrade head
```

### 4. 冒烟验证

```bash
# 健康检查
curl http://localhost:8000/healthz

# 上传一个文档（拿预签名 URL 直传，或用便捷上传接口）
curl -X POST http://localhost:8000/api/v1/documents/upload-url \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"filename":"sample.txt","content_type":"text/plain"}'

# SSE 流式问答
curl -N http://localhost:8000/api/v1/chat \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"query":"这份文档讲了什么？"}'
```

API 文档（Swagger UI）：`http://localhost:8000/docs`

### 5. 本地开发（免 Docker）

```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000   # 仍需 infra（postgres/milvus/opensearch/kafka/minio）在跑
# 跑 worker（另开终端）
python -m app.workers.ingest_worker
```

---

## 技术栈

| 层 | 选型 |
|---|---|
| BFF + 服务层 | Python 3.11 · FastAPI(async) · Pydantic v2 · SQLAlchemy 2(async) · Alembic |
| 元数据 | PostgreSQL |
| 向量库 | Milvus（每租户 collection + HNSW） |
| 全文检索 | OpenSearch（每租户 index，BM25 + 结构化过滤） |
| 缓存/会话 | Redis |
| 异步管道 | Kafka（KRaft 单节点） |
| 对象存储 | MinIO（原文档 + 渲染图） |
| PDF 解析 | PyMuPDF（文本层 + bbox，分级触发版面检测 hook） |
| 前端 | React + TS + Vite + Ant Design + Zustand（下一轮） |

---

## 项目结构

见 [`plan_one.md`](./plan_one.md) §目录结构。分层：**数据接入层 → 知识处理层 → 存储与索引层 → 检索编排层 → 生成与应用层 → 应用网关层(BFF) → 平台治理层**。

---

## 路线（多 session）

- ✅ 首轮：完整结构 + 后端可运行核心链路 + docker-compose 全套 infra
- ⏳ 下一轮：React 前端（Chat / 知识库管理 / PDF.js bbox 高亮 / Admin）、k8s + HPA、Grafana 看板
- ⏳ 后续迭代：YOLO 版面检测、PaddleOCR、GraphRAG、细粒度 RBAC、评估标注、A/B、CDC 连接器（当前均为接口 + 降级实现）
