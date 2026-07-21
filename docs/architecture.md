# 实现说明（architecture）

本仓库当前实现版本相对于 [`enterprise-rag-design.md`](./enterprise-rag-design.md)（v2.0 设计书）的落地状态、降级策略与可插拔点。

> 状态：**首轮 — 完整结构 + 后端可运行核心链路**。前端、k8s、Grafana 见 plan_one §路线。

---

## 1. 已实现（核心链路端到端可跑）

| 设计书模块 | 实现位置 | 说明 |
|---|---|---|
| 应用网关层 (BFF) | `backend/app/api/` | FastAPI async，鉴权骨架（租户头）、请求编排、SSE 流式转发 |
| 数据接入层 §4.1 | `backend/app/services/ingestion/` | 文件连接器（真实）、parser、增量同步接口（hash/timestamp）；DB/Wiki/API 连接器为接口 + stub |
| 知识处理层 §4.2 | `backend/app/services/knowledge/` | PDF 文本层抽取（PyMuPDF）含 bbox；分级版面检测/OCR 为 hook + 文本兜底；固定/结构/版面区域分块；embedding 可插拔 |
| 存储与索引层 §4.3 | `backend/app/infra/` + `backend/app/db/` | PG 元数据（Alembic）、Milvus 每租户 collection（HNSW）、OpenSearch 每租户 index（BM25）、Redis、MinIO、Kafka |
| 检索编排层 §4.4 | `backend/app/services/retrieval/` | 四段流水线：查询理解（**LLM 改写/扩展，多子查询多路召回**）→ vector+keyword → RRF 融合 + MMR → Cross-Encoder rerank（可插拔）；**父子 Small-to-Big 上下文回溯** |
| 生成与应用层 §4.5 | `backend/app/services/generation/` | LLM 网关（OpenAI 兼容，多模型路由/降级/SSE 流式 + 非流式 complete）、Prompt 模板（用父块上下文）、引用标注（page+bbox） |
| 知识处理·增强 | `backend/app/services/knowledge/` | 父子分块（chunker）+ 可插拔 embedding（OpenAI 兼容 / 本地 sentence-transformers / mock）；**版面检测抽象（pymupdf 基线 + YOLO hook）+ OCR（PaddleOCR hook）** |
| 视觉解析异步化 | `backend/app/services/vision.py` + `workers/layout_worker.py` | 扫描件/复杂件入队 `rag.layout` → 版面检测+区域级 OCR → 重新分块索引；Kafka 不可用轮询 `layout_pending` |
| 平台治理层 §6/§8 | `backend/app/governance/` | RBAC 接口 + 前置过滤、审计日志、场景配置中心（四要素） |
| 多租户隔离 §6 | `backend/app/core/tenant.py` + repositories | `X-Tenant-Id` → 仓储前置过滤 + Milvus/OpenSearch 每租户库 |

## 2. 接口 + 降级实现（首版不内置重型实现）

| 能力 | 当前形态 | 接入方式 |
|---|---|---|
| YOLO 版面检测 | `knowledge/layout_detector.py::DocLayoutYoloDetector`（ultralytics，已实现推理流程，懒加载）+ pymupdf 基线已生效 | 设 `PDF_LAYOUT_DETECTOR=yolo` + `YOLO_MODEL_PATH` + 装 ultralytics（建议 GPU） |
| PaddleOCR | `knowledge/ocr.py::PaddleOCREngine`（已实现区域级识别） | 设 `OCR_ENGINE=paddle` + 装 paddleocr；`vision.py` 自动逐页 OCR |
| GraphRAG | 未内置图存储；检索层预留结构化/图召回扩展位 | 后续接 Neo4j + 实体关系召回路 |
| 细粒度 RBAC | `governance/authz.py` 接口 + 文档级前置过滤 | 扩展权限规则引擎 |
| 评估标注 / A/B | `governance/` + `feedback` API 留数据落点 | 后续建评估集与实验框架 |
| CDC 连接器 | `ingestion/sync.py` 接口（hash/timestamp 已实现） | 接 Debezium 等 CDC 源 |

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
- **PDF 高亮**：后端已产出 `page_no + bbox`；前端 PDF.js 渲染在下一轮交付
