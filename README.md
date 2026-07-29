# Enterprise RAG Platform

企业级 / 工业级多租户 RAG 检索平台。FastAPI（BFF + 服务层）+ React 前端 + 全套基础设施（PostgreSQL / Milvus / OpenSearch / Redis / Kafka / MinIO），一套 `docker compose up` 拉起。

> 📐 设计规格：[`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)（v2.0）
> 🏗️ 实现说明：[`docs/architecture.md`](./docs/architecture.md)
> 📚 文档导航：[`docs/INDEX.md`](./docs/INDEX.md)
> 🛠️ 运维手册：[`docs/RUNBOOK.md`](./docs/RUNBOOK.md) ｜ 安全：[`docs/security.md`](./docs/security.md) ｜ 压测：[`docs/loadtest.md`](./docs/loadtest.md)
> 📋 落地计划：[`plan_one.md`](./plan_one.md)（首轮）｜ [`plan_two.md`](./plan_two.md)（迭代，已完成）｜ [`plan_three.md`](./plan_three.md)（平台化深化，已完成）｜ [`plan_four.md`](./plan_four.md)（上线就绪加固）｜ 审查：[`advice.md`](./advice.md)

---

## 能力

- **多租户隔离**：`X-Tenant-Id` → 仓储前置过滤 + Milvus/OpenSearch 每租户库；无 header 回退 `default`
- **认证授权**：JWT + 用户/租户/角色；写/admin 接口 `require_roles` 角色门禁（viewer 只读）；`AUTH_ENABLED=true` 后租户取自令牌不可伪造（plan_three §1 / plan_four §1）
- **异步数据管道**：上传只入队（Kafka），`ingest_worker` 消费做 解析 → 分块 → embedding → 双写索引
- **混合检索 + 精排**：向量（Milvus）+ 关键词（OpenSearch BM25）+ 图召回（GraphRAG）并行 → RRF 融合 → Cross-Encoder rerank（可插拔，无配置跳过）；父子 Small-to-Big 上下文回溯
- **Agentic RAG**：检索充分性评估 + 迭代召回 + 答案 faithfulness 自检（`AGENTIC_ENABLED`，默认关）
- **多模态**：PDF 表格抽取（pdfplumber/camelot → 结构化 chunk）+ 图片 VLM caption（plan_three §4）
- **区域级溯源**：PDF 文本层抽取 `page_no + bbox` → chunk 元数据 → 检索透传 → 生成引用 → `/locate` 返回 → 前端 PDF.js 高亮
- **SSE 流式问答**：`POST /chat` 逐 token 推送 + citations 事件
- **降级链路**：向量超时→仅 BM25；视觉解析超时→纯文本；主 LLM 不可用→备用/mock；降级码经 `degraded` 字段前端友好提示
- **可观测**：Prometheus 指标 + Grafana 看板 + OpenTelemetry 分布式追踪（jaeger）
- **韧性**：外部调用熔断 + 重试；存活/就绪探针分离（`/healthz`·`/readyz`）+ 优雅关停
- **备份恢复 / DR**：PG 权威源 + Milvus/MinIO best-effort；`make backup`·`make restore` + 演练（`docs/dr-runbook.md`）
- **真实评估集**：确定性语料 + Recall@K/MRR/引用/bbox/faithfulness 回归门禁（`make eval-seed`·`make eval`，`docs/eval.md`）
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

### 4b. 访问前端

`docker compose up` 已包含前端服务，访问 **`http://localhost:5173`**：
- 右上角切换「租户」（对应 `X-Tenant-Id`，数据按租户隔离）
- `/chat` 对话问答（流式输出 + 引用卡片）；点引用 → `/preview` 渲染原 PDF 页面 + bbox 高亮
- `/documents` 上传文档并查看索引状态；`/knowledge-bases` 管理知识库；`/admin` 场景配置

前端纯前端开发（热重载）：
```bash
cd frontend && npm install && npm run dev   # 需后端在 :8000 运行（/api 经 vite 代理）
```

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
| 前端 | React + TS + Vite + Ant Design + Zustand（路由级懒加载；Chat SSE / 知识库 / 文档上传（进度+重试）/ PDF.js bbox 高亮 / 场景配置 / 登录） |

---

## 项目结构

见 [`plan_one.md`](./plan_one.md) §目录结构。分层：**数据接入层 → 知识处理层 → 存储与索引层 → 检索编排层 → 生成与应用层 → 应用网关层(BFF) → 平台治理层**。

---

## 路线（多 session）

- ✅ **plan_one**：完整结构 + 后端可运行核心链路 + docker-compose 全套 infra + React 前端 + Prometheus/Grafana + K8s
- ✅ **plan_two**（11 项）：PDF 视觉解析架构 / 检索增强（父子+改写+扩展）/ RBAC 前置过滤 / 评估+A-B / 成本管控 / KEDA / 规模化 / 安全合规 / CI-CD / GraphRAG / CDC
- ✅ **plan_three**（6 项）：真实认证授权 / Agentic RAG / OTel 追踪 / 多模态表格图片 / 韧性（熔断+重试+探针+优雅关停）/ 备份恢复 DR
- 🔨 **plan_four**（来源 `advice.md` 审查）：✅ §1 安全闭环（接口角色门禁 + RBAC 最小权限）· ✅ §2 真实评估集 + 回归门禁 · ✅ §4 前端补齐（懒加载/上传进度/降级提示）· ⏳ §3 端到端真实环境冒烟 · ⏳ §5 文档对齐
- ⏳ **后续（P2）**：YOLO/PaddleOCR/camelot 真实 GPU 验证、DB/Wiki/API 连接器、细粒度 RBAC 规则引擎、KEDA 实战

### 上线 checklist（生产必做）

- [ ] `AUTH_ENABLED=true` + `JWT_SECRET` 覆盖为强随机串（≥32 字节）+ `SEED_ADMIN_PASSWORD` 改默认
- [ ] `CORS_ORIGINS` 收窄为前端实际域名
- [ ] `RBAC_DEFAULT_DENY=true`（最小权限，需显式配置 `RBAC_POLICY` 授权）
- [ ] `LLM_API_KEY` / `EMBEDDING_API_KEY` 配齐（否则降级 mock）
- [ ] `make migrate && make seed-admin`；备份策略就绪（`make backup`，见 `docs/dr-runbook.md`）
- [ ] 传输 TLS（ingress cert-manager）、审计保留策略
