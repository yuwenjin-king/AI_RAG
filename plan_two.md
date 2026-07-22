# plan_two：后续迭代计划（重型能力落地 + 平台化深化）

> 本文件接续 [`plan_one.md`](./plan_one.md)。plan_one 已交付：后端核心链路、React 前端、可观测性（Prometheus+Grafana）、K8s 部署。
> 本计划目标：把设计书里"**接口 + 降级实现**"的重型能力真正落地，并完成平台化/规模化/安全合规深化。
> 规格：[`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)；实现现状：[`docs/architecture.md`](./docs/architecture.md)。
>
> **进度**：✅ P0（① PDF 视觉解析架构+基线+可插拔 YOLO/Paddle hook + layout_worker；② 父子 Small-to-Big 回溯 + 查询改写/扩展多路召回 + 本地 ST embedding）已落地并测试。
> ✅ P1 部分（③ RBAC 前置过滤；⑤ 成本管控 embedding/查询缓存+限流+token 指标；⑥ KEDA ScaledObject；⑨ CI/CD；④ 评估指标+runner+CLI+A/B 分桶+反馈聚合）。⏳ P1 剩余（⑦ 规模化压测、⑧ 安全合规）+ P2（GraphRAG/CDC）待做。

---

## 0. 优先级总览

| # | 工作流 | 优先级 | 设计书 | 现状 | 工作量 | 依赖 |
|---|---|---|---|---|---|---|
| 1 | PDF 视觉解析（YOLO 版面检测 + PaddleOCR） | **P0 ✅** | §4.2.2 | 架构+基线已落地，YOLO/Paddle 可插拔(懒加载) | 中大 | GPU 池 |
| 2 | 检索质量增强（语义 embedding + 查询改写/扩展 + 父子分块回溯） | **P0 ✅** | §4.2.3/§4.4.1 | 父子回溯/改写扩展/本地ST 已落地 | 中 | LLM |
| 3 | 细粒度 RBAC（文档级/字段级 + 前置过滤注入） | **P1 ✅** | §6/§8 | PermissionFilter 前置注入 vector/keyword/bm25 | 中 | — |
| 4 | 评估与 A/B 测试框架 | **P1 ✅** | §9 | 离线指标+runner+CLI+A/B 分桶+反馈聚合 | 中 | 离线评估集 |
| 5 | 成本管控（模型分级路由 + 配额限流 + 缓存复用） | **P1 ✅** | §4.5/§2.2 | embedding/查询缓存 + 限流 + token 指标 | 中 | Redis |
| 6 | KEDA：基于 Kafka lag 扩缩 ingest-worker | **P1 ✅** | §7/§11 | ScaledObject 已就绪 | 小 | K8s |
| 7 | 规模化与性能（百万级压测 + 索引分片/冷热分层 + 向量调优） | P1 | §4.3/§12 | 单分片 | 中大 | 压测环境 |
| 8 | 安全合规加固（TLS/mTLS + PII 脱敏 + 审计 + 静态加密） | P1 | §8 | 部分占位 | 中 | — |
| 9 | CI/CD 流水线 | **P1 ✅** | §11 | GitHub Actions(lint+test+build) | 小 | CI |
| 10 | GraphRAG（知识图谱召回路） | P2 | §4.3/§4.4 | 未内置 | 大 | Neo4j |
| 11 | CDC 连接器（DB 类数据源增量） | P2 | §4.1 | 接口占位 | 中 | Debezium |

---

## 1. PDF 视觉解析：YOLO 版面检测 + PaddleOCR【P0】

**为什么**：设计书核心卖点是"区域级精确溯源"。当前 `knowledge/pdf_layout.py::extract_blocks` 对原生文本型 PDF 已能取 bbox，但**扫描件/复杂多栏排版**会标 `needs_vision=True` 后无视觉兜底（`detect_layout` 返回 None）→ 这类文档退化为无 bbox 或无文本，溯源体验断裂。

**现状 hook**：
- `backend/app/services/knowledge/pdf_layout.py::detect_layout(data) -> Optional[List[Block]]`（返回 None）
- `backend/app/services/knowledge/ocr.py::OCREngine` / `NoOpOCR`
- `backend/app/workers/layout_worker.py`（idle，仅日志）
- `services/ingest.py` 解析阶段已产出 `needs_vision` 标记

**实现要点**：
1. **选型评测**（先做）：用一批真实复杂/扫描件 PDF，对比 DocLayout-YOLO、PP-Structure、Table Transformer 的（精度/速度/GPU 成本），写评测报告 `docs/eval-pdf-layout.md`。设计书 §4.2.2(3) 分级策略保留：原生文本型仍走文本层（零视觉成本）。
2. **实现 `detect_layout`**：PDF 页面 → 图片 → YOLO 输出区域块（标题/正文/表格/图片/页眉页脚 + bbox）→ 表格区接专用表格结构识别 → 正文区走文本抽取或 OCR → 输出 `Block(text, page_no, bbox 归一化)`。坐标系统一归一化（复用 `_norm_bbox`）。
3. **实现 `PaddleOCREngine(OCREngine)`**：区域级 OCR，返回带 bbox 的 `Block`。
4. **独立 GPU Worker**：`layout_worker` 消费 layout 任务队列（Kafka 新 topic `rag.layout`）：`ingest_worker` 遇 `needs_vision` 时入队，`layout_worker` 在 GPU nodepool 处理 → 回写 chunk 的 `page_no/bbox` + 补全文本。k8s 用 `nodeSelector`/tolerations 调度 GPU。
5. **成本控制**：分级触发（仅复杂/扫描件），`docker-compose` 加可选 GPU 服务；按 Spot 实例降本。

**验收**：
- 扫描件 PDF 上传后能产出带 `page_no + bbox` 的 chunk；前端 `/preview` 高亮命中正确区域
- 新增指标 `rag_layout_processed_total`（by 状态）、`rag_ocr_chars_total`、版面检测 P95 延迟
- 溯源准确率（设计书 §9 专项指标）抽样 ≥ 目标值

**工作量**：2–3 周（含选型评测）。

---

## 2. 检索质量增强【P0】

**为什么**：当前 `embedding.py` 在无 key 时用 `HashedBagEmbedding`（仅 demo 级语义）；`query.py` 改写/扩展为透传；父子分块字段 `parent_chunk_id` 已留但未回溯。这是召回率与答案质量的最大杠杆。

**现状 hook**：
- `knowledge/embedding.py::get_provider()`（key 有则 OpenAI 兼容，无则 mock）
- `retrieval/query.py::rewrite/expand/plan`（透传）
- `retrieval/orchestrator.py` 上下文构建（用 chunk 本体，未回溯父块）
- `db/models.py::Chunk.parent_chunk_id`（已建字段，未用）

**实现要点**：
1. **真实语义 embedding**：默认接 OpenAI 兼容（生产配 key）；本地可选 `sentence-transformers`（多语言/bge 系）作为离线/私有化 provider，补 `embedding.py` 一个 `LocalSentenceTransformerEmbedding`。
2. **查询改写（多轮）**：`query.rewrite` 接轻量 LLM，结合 `history` 做指代消解/省略补全；缓存改写结果到 Redis（`infra/redis_store`）。
3. **查询扩展**：`query.expand` 用同义词表/领域术语 + LLM 生成子查询；多子查询召回后统一进 RRF（`fusion.rrf_fuse` 已支持多路）。
4. **父子分块（Small-to-Big）**：`chunker` 产出小 chunk + 父块（`parent_chunk_id`）；`orchestrator` 检索用小 chunk 命中，上下文构建时回溯父块扩展（`chunker` + orchestrator 改 `build context`）；`fetch_enriched` 增父块查询。
5. **语义分块**：`chunker` 增 `semantic_chunk`（基于句向量相似度动态切分）。

**验收**：
- 离线评估集 Recall@K、MRR、NDCG 较基线提升（写进 `docs/eval-retrieval.md`）
- 多轮对话指代消解生效；父子回溯后生成上下文更完整
- 检索延迟 P95 仍 ≤ 300ms（embedding/改写加缓存）

**工作量**：2–3 周。

---

## 3. 细粒度 RBAC【P1】

**现状 hook**：`governance/authz.py::PermissionResolver.resolve()` 宽放（返回全可见）；`orchestrator` 未注入过滤。

**实现要点**：
1. 权限模型：用户 → 角色 → 文档/知识库/标签可见范围（`scene_configs.permission_rules` 已有字段）。
2. `PermissionResolver` 读取用户身份（JWT/请求头）→ 返回 `PermissionFilter(knowledge_base_ids, doc_ids, tags)`。
3. **前置过滤注入**：`orchestrator.retrieve` 接收 `PermissionFilter`，作为 Milvus 标量过滤、OpenSearch term 过滤、本地 BM25 过滤的**前置条件**（设计书 §6：前置而非后置，防越权 + 提效）。
4. 审计：`governance/audit.py` 落每次越权拦截与检索可见范围。

**验收**：越权用户检索不到非授权文档（单测覆盖）；性能不退化。

**工作量**：1–1.5 周。

---

## 4. 评估与 A/B 测试框架【P1】

**现状 hook**：`feedback` 表 + `/api/v1/feedback` 已有数据落点；`model_configs`/`scene_configs` 可作为实验变量。

**实现要点**：
1. **离线评估集**：`backend/app/eval/` 新模块，按场景存 Query–标准答案/标准引用（PG 新表 `eval_cases`）；跑批量检索+生成，算 Recall@K / MRR / NDCG / Faithfulness / 引用准确率 / **bbox 溯源准确率**。CLI：`python -m app.eval.run --scene xxx`。
2. **在线 A/B**：`scene_configs` 增 `variants` + 流量分配；`/chat` 按用户 hash 分桶选 variant；结果落 `messages` + variant 标记。
3. **反馈闭环**：点赞/点踩 → 聚合到 variant 效果对比看板（Grafana 新面板或独立页）。
4. **回归门禁**：CI 跑核心评估集，指标回归则阻断（接 §9 CI/CD）。

**验收**：能产出按场景的评估报告；A/B 能分流并统计显著差异。

**工作量**：2 周。

---

## 5. 成本管控【P1】

**现状 hook**：`llm_gateway` 多模型路由骨架在；`redis_store` 缓存未真正用于查询/embedding 复用；无限流/配额。

**实现要点**：
1. **查询结果缓存**：`orchestrator.retrieve` 命中相同 query+tenant+kb 时走 Redis（语义近邻可加，首版精确 key）。
2. **embedding 缓存**：`embedding.py` 对同文本走 Redis 缓存（chunk 写入与查询复用）。
3. **模型分级路由**：`llm_gateway` 按场景/难度/成本路由到不同档模型（简单走 flash，复杂走 pro）。
4. **配额限流**：按租户/场景的 QPS 与 token 配额（Redis 令牌桶）；超限返回 429。
5. **成本指标**：`metrics.py` 加 `rag_llm_tokens_total{model,direction}`、`rag_llm_cost_estimated`；Grafana 看板加成本面板。

**验收**：重复 query 命中缓存（延迟下降）；超配额被限流；成本可观测。

**工作量**：1.5 周。

---

## 6. KEDA：基于 Kafka lag 扩缩 ingest-worker【P1】

**现状**：`deploy/k8s/ingest-worker.yaml` 固定 2 副本。

**实现要点**：新增 `deploy/k8s/ingest-worker-scaledobject.yaml`（KEDA ScaledObject），触发器 = Kafka `rag.ingest` consumer group lag，min 1 / max N。文档补充 KEDA 安装。设计书 §7：按队列积压扩缩数据处理 Worker，与在线服务资源池分离。

**验收**：灌入大量文档时 worker 自动扩容，lag 清空后缩容；不影响 backend。

**工作量**：2–3 天。

---

## 7. 规模化与性能【P1】

**现状**：单 collection/index；本地 BM25 兜底全量扫描（仅 dev）；HNSW 用默认参数。

**实现要点**：
1. **索引分片**：大租户独立 collection（`settings.collection_per_tenant` 开关已在）；Milvus/OpenSearch 按租户/KB 分片；设计书 §4.3。
2. **冷热分层**：低频历史文档索引降级低成本存储层，按需加载（对象存储 + 元数据标记）。
3. **向量调优**：HNSW `M/efConstruction/ef` 按 recall/latency 权衡调参；IVF 备选。
4. **压测**：百万文档 / 千万 chunk 灌库 + 并发检索/问答压测（locust/k6），产出 P95 延迟、QPS 上限、扩缩行为报告 `docs/loadtest.md`。本地 BM25 兜底改为仅 OpenSearch 不可用时的最后兜底（生产必须 OpenSearch）。
5. **PDF 渲染图缓存**：MinIO 缓存页面渲染图，前端预览复用。

**验收**：百万文档下检索 P95 ≤ 300ms、问答 P95 ≤ 3s；扩缩容符合预期。

**工作量**：2–3 周（含压测环境）。

---

## 8. 安全合规加固【P1】

**现状**：CORS 有；无 TLS/mTLS；无 PII 脱敏；审计仅落点。

**实现要点**：
1. **传输**：全链路 TLS（ingress cert-manager）；服务间 mTLS（服务网格或内部 token）。
2. **静态加密**：PG/Milvus/OpenSearch/MinIO 启用加密；原始 PDF 加密存储。
3. **PII 脱敏**：`ingestion` 接入阶段识别并脱敏（接入 presidio 或规则引擎），开关由租户配置。
4. **审计落库**：`governance/audit.py` 全面接入关键操作（查询/检索命中来源/原文访问），`operation_logs` 已有表。
5. **密钥管理**：Secret 走 Vault/云 KMS，不落 compose。

**验收**：安全清单全绿；审计可追溯；脱敏可配置。

**工作量**：1.5–2 周。

---

## 9. CI/CD 流水线【P1】

**实现要点**：`.github/workflows/`（或 GitLab）：
- 后端：lint（ruff）→ pytest（含离线评估集回归）→ 构建 backend 镜像
- 前端：tsc → vite build → 构建前端镜像
- 镜像推送 → k8s 滚动/金丝雀（Argo CD 或 helm）
- 评估集回归作为发布门禁（接 §4）

**验收**：PR 合并自动跑通；版本可灰度发布。

**工作量**：3–5 天。

---

## 10. GraphRAG【P2】

**现状**：未内置图存储；检索层预留结构化/图召回扩展位。

**实现要点**：
1. 接入 Neo4j（或云图数据库）；`infra/` 加 `graph_store.py`。
2. 实体/关系抽取：ingest 阶段从 chunk 抽实体关系入图。
3. 检索：`retrieval/` 加 `graph.py` 召回路（实体邻域/多跳），并入 RRF 融合。
4. `orchestrator` 把 graph 召回作为第三路（vector + keyword + graph）。

**验收**：实体关系类问题（"X 和 Y 的关系"）召回优于纯向量。

**工作量**：3–4 周。

---

## 11. CDC 连接器【P2】

**现状**：`services/ingestion/sync.py::CDCSource` 接口占位；`HashTimestampDetector` 已实现。

**实现要点**：接 Debezium → Kafka（`rag.cdc.<source>`）→ `connectors/db.py` 消费变更 → 走 ingest 管线增量更新索引。新连接器实现 `Connector` 接口（`connectors/base.py`）。

**验收**：源库变更后索引在可配置延迟内更新（设计书 §2.2：增量 ≤ 5 分钟）。

**工作量**：2 周。

---

## 建议执行序列（依赖与并行）

```
P0 并行：① PDF 视觉解析 ─┐
        ② 检索质量增强 ──┤
                          ├──→ ④ 评估/A/B（依赖①②产出指标）
P1 并行：③ RBAC ─────────┤    ⑦ 规模化压测（依赖②调优）
        ⑤ 成本管控 ──────┤    ⑧ 安全合规（可并行）
        ⑥ KEDA ──────────┤    ⑨ CI/CD（先建，承接④回归）
P2 后置：⑩ GraphRAG、⑪ CDC
```

- 先建 **⑨ CI/CD** + **④ 评估框架**（基础设施性质，后续都能用）。
- **①②** 是质量与核心体验，最先做。
- **⑦ 规模化** 放质量优化之后，避免过早优化。

---

## 验收总览（贯穿）

- **离线评估集回归**：每个 P0/P1 工作流都附评估报告（`docs/eval-*.md`），指标不回归。
- **在线指标**：监控看板（`monitoring/grafana/dashboards/`）持续观察检索延迟、召回量、LLM 失败率、降级率、成本。
- **每步可独立合并**：保持 plan_one 的"每步可验证、可中断续做"节奏。

---

## 风险与说明

| 风险 | 应对 |
|---|---|
| 视觉解析 GPU 成本 | 分级触发 + Spot 实例 + 独立池；先选型评测再定方案 |
| LLM 改写/扩展增加延迟与成本 | 结果缓存 + 轻量模型 + 可关闭开关 |
| 规模化后索引性能退化 | 提前规划分片/冷热分层，压测验证（§7） |
| RBAC 前置过滤影响召回 | 评估集回归 + 性能基准对比 |
| GraphRAG/CDC 工作量大 | 列为 P2，按业务优先级择期推进 |

> 本计划可按工作流拆成独立分支逐个交付；建议每个工作流一个 PR，CI（§9）门禁 + 评估集回归（§4）把关。
