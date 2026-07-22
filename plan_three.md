# plan_three：平台化深化（认证授权 / Agentic RAG / 可观测性 / 多模态 / 韧性 / DR）

> 接续 [`plan_one.md`](./plan_one.md)、[`plan_two.md`](./plan_two.md)。两者已 100% 交付：后端核心链路、React 前端、可观测性(metrics)、K8s 部署、plan_two 全部 11 项（视觉解析架构/检索增强/RBAC/评估/成本/KEDA/规模化/安全/CI-CD/GraphRAG/CDC）。
>
> 本计划目标：把"**接口 + 降级实现**"里最后几处**关键空心**填实，让平台真正达到"企业级可用"而非"架构完整"。
> 规格：[`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)；实现现状：[`docs/architecture.md`](./docs/architecture.md)。
>
> **核心判断**：当前最大短板是 **① 无真实身份认证**（`X-Tenant-Id` 头任何人可伪造，RBAC `PermissionResolver` 宽放）与 **② 检索是单次 retrieve→generate**（无充分性评估/迭代/自纠正）。这两项分别决定"安全可信"与"答案质量"。

---

## 0. 优先级总览

| # | 工作流 | 优先级 | 现状 | 工作量 | 可离线测试 |
|---|---|---|---|---|---|
| 1 | 真实认证与授权（JWT + 用户/角色模型，RBAC 真正生效） | **P0** | X-Tenant-Id 无校验、RBAC 宽放 | 中大 | ✅ |
| 2 | Agentic RAG（检索充分性评估 + 迭代召回 + 工具调用） | **P0** | 单次 retrieve→generate | 中大 | ✅(mock LLM) |
| 3 | 分布式追踪（OpenTelemetry） | **P1** | 仅 Prometheus metrics | 中 | ✅(内存 exporter) |
| 4 | 多模态：表格/图片抽取入索引 | **P1** | PDF 仅文本层 | 中 | ⚠️(需样本) |
| 5 | 韧性与稳定性（连接池/重试/熔断/优雅关停/readiness） | **P1** | 部分有降级，无系统化韧性 | 中 | ✅ |
| 6 | 备份恢复 / DR（PG/Milvus/MinIO 备份 + 恢复演练） | **P2** | 无 | 中 | ⚠️(需环境) |

---

## 1. 真实认证与授权【P0】

**为什么**：当前鉴权仅靠 `X-Tenant-Id` 请求头——**任何人改个头就能访问/越权任意租户**。`governance/authz.py::PermissionResolver.resolve()` 宽放（返回全可见），plan_two 落地的 RBAC 前置过滤因此**没有真实主体**，形同虚设。这是"企业级"最致命的空心。

**现状**：
- `app/core/tenant.py`：仅从 `X-Tenant-Id` 头取租户，无身份校验
- `governance/authz.py`：`PermissionResolver` 接口在，但 `resolve()` 宽放
- `db/models.py`：无 users / user_roles / user_tenant_memberships 表
- 前端 `stores/tenant.ts`：仅存 tenantId，无登录态/token

**实现要点**：
1. **数据模型**：新增 `users`、`roles`、`user_roles`、`user_tenant_memberships`（用户↔租户↔角色，多租户归属）。Alembic 迁移。
2. **认证**：JWT（HS256，dev secret 走 env `JWT_SECRET`；生产对接 OIDC 可扩展）。中间件解析 `Authorization: Bearer <jwt>` → 注入 `CurrentUser{id, tenant_id, role, permissions}`。**保留 `X-Tenant-Id` 作为用户归属租户的显式选择**（多租户用户切换上下文），但必须校验该用户确属此租户。
3. **授权**：`PermissionResolver.resolve(current_user)` 依据角色→返回真实 `PermissionFilter(kb_ids/doc_ids/tags)`，替换宽放。RBAC 前置过滤（已落地）由此真正生效。
4. **API**：`/api/v1/auth/login`（用户名密码→JWT）、`/api/v1/auth/me`；种子管理员脚本。
5. **前端**：登录页 → 存 JWT → 请求拦截器带 `Authorization`；租户切换走用户可访问租户列表。
6. **降级**：`AUTH_ENABLED=false` 时退回旧行为（X-Tenant-Id），保证本地/测试无密码可跑（关键：不破坏现有 `make test` 与离线测试策略）。

**验收**：
- 伪造 `X-Tenant-Id` 无 JWT → 401；越权租户 → 403
- 不同角色检索可见范围不同（单测覆盖）
- `AUTH_ENABLED=false` 时旧行为不回归（现有测试全绿）

**工作量**：1.5–2 周。

---

## 2. Agentic RAG：多步检索 + 自纠正【P0】

**为什么**：当前 `retrieval/orchestrator.py` 是**单次** recall→fuse→rerank→generate。复杂问题（多跳、需证据补全、答案自相矛盾）召回不足时无补救；生成也无"证据是否充分"的判断。这是答案质量的最大剩余杠杆。

**现状**：
- `orchestrator.retrieve`：四段流水线，一次召回
- `generation/llm_gateway`：单轮生成，SSE 流式
- plan_two 已有查询改写/扩展多路召回（单轮内的多查询），但**无跨轮迭代**

**实现要点**：
1. **充分性评估**：召回后用轻量 LLM/启发式判断"证据是否足以回答"（score + 缺失维度）。
2. **迭代召回**：不充分则生成 follow-up 子查询 → 再召回 → 与已有证据去重合并（上限 N 轮，防发散）。
3. **答案自检**：生成后校验引用是否被证据支撑（faithfulness），不通过则重试/降级声明。
4. **工具调用（可选）**：把"检索"/"精确查找"作为工具，LLM 自主决定调用（ReAct 风格骨架）。
5. **开关 + 成本护栏**：`AGENTIC_ENABLED` 开关；迭代轮数/token 上限由 `scene_configs` 控制；命中查询缓存则跳过。
6. **指标**：`rag_agentic_iterations`、`rag_sufficiency_score`、`rag_selfcheck_fail_total`。

**验收**：
- 多跳/复合问题答案较单次召回改善（评估集 faithfulness/引用准确率提升，写 `docs/eval-agentic.md`）
- 迭代有上限、可关闭、可观测
- 单次简单问题不被拖慢（缓存 + 早退）

**工作量**：2–3 周。

---

## 3. 分布式追踪（OpenTelemetry）【P1】

**为什么**：当前只有 Prometheus metrics（计数/延迟聚合），**无分布式 trace**。检索链路四段+多路召回+生成，出问题时无法定位是哪一段慢/失败。

**实现要点**：
1. `opentelemetry-sdk` + auto-instrumentation（FastAPI/SQLAlchemy/httpx）。
2. 关键业务 span：`retrieve.{vector,keyword,graph}`、`fusion`、`rerank`、`generate`、`agentic.iteration`。
3. 导出：开发用内存/控制台 exporter；生产 OTLP → Tempo/Jaeger（compose 可选加 Jaeger all-in-one）。
4. trace ↔ metrics 关联（exemplars）。

**验收**：一次 `/chat` 能看到完整 span 树，定位慢段；离线测试用内存 exporter 断言 span 生成。

**工作量**：1 周。

---

## 4. 多模态：表格/图片抽取【P1】

**为什么**：PDF 表格信息当前被拍平成文本（行列关系丢失），图表无 caption。表格类问题（"Q3 营收"）召回与溯源质量差。

**实现要点**：
1. `knowledge/` 增表格抽取 hook：`pdf_layout` 标记表格区 → `camelot`/`pdfplumber` 抽结构 → 序列化为 Markdown/HTML 表（保留行列）→ 作为 chunk 入索引（结构化字段）。
2. 图片区：接 VLM 生成 caption（视觉解析 worker 复用，无 VLM 则跳过）。
3. 表格 chunk 溯源：page_no + bbox 不变，前端表格高亮。
4. 评估：表格类 query 召回/答案准确率。

**工作量**：1.5–2 周（含样本评测）。

---

## 5. 韧性与稳定性【P1】

**为什么**：降级已有，但缺系统化韧性：DB 连接池未调优、LLM/embedding 调用无重试/熔断、无优雅关停、readiness 探针粗。

**实现要点**：
1. DB：连接池参数 config 化（pool_size/max_overflow/pool_recycle）、慢查询告警。
2. LLM/embedding：`tenacity` 指数退避重试 + 熔断（连续失败短路一段时间走降级）。
3. 优雅关停：lifespan 收到 SIGTERM 先停止接新请求→排空→关连接。
4. 探针：`/healthz`(liveness) 与 `/readyz`(readiness，检查 infra 连通) 分离。
5. 背压：Kafka 消费限速/并发上限。

**工作量**：1 周。

---

## 6. 备份恢复 / DR【P2】

**实现要点**：PG `pg_dump`/PITR、Milvus snapshot、MinIO 版本化/复制；备份脚本 + 恢复演练 runbook；RPO/RTO 目标。

**工作量**：1–1.5 周（含演练）。

---

## 建议执行序列

```
① 认证授权 ──┐               ③ 追踪（可并行，纯增量）
              ├──→ ⑤ 韧性（认证后整体加固）
② Agentic ──┘               ④ 多模态（依赖①②稳定后）
P2：⑥ DR（最后，需稳定环境）
```

- **①② 是 P0**：① 决定"可信"，② 决定"好用"。建议**先 ① 再 ②**（认证是安全地基，Agentic 在其上迭代更可控）。
- ③④ 可与 ①② 并行（独立模块）。
- ⑤ 在 ①② 后做整体加固。

---

## 风险与说明

| 风险 | 应对 |
|---|---|
| 认证改造影响面大（前后端+测试） | `AUTH_ENABLED` 开关保留旧行为；先补测试再改 |
| Agentic 增加延迟/成本 | 充分性早退 + 轮数上限 + 缓存 + 可关闭 |
| 追踪采样开销 | 采样率 config 化，开发全量/生产按比例 |
| 多模态样本不足 | 先用公开表格 PDF 建小评估集 |
| DR 演练需环境 | 列 P2，按需推进 |

> 每个工作流独立分支 + CI 门禁 + 评估回归，保持 plan_one/two 的"可验证、可中断续做"节奏。
