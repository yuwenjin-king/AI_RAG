# plan_four：上线就绪加固（安全闭环 / 真实评估 / 端到端 / 前端 / 文档对齐）

> 接续 [`plan_one.md`](./plan_one.md)、[`plan_two.md`](./plan_two.md)、[`plan_three.md`](./plan_three.md)。三者已 100% 交付：后端核心全链路、React 前端、可观测、K8s、plan_two 全 11 项、plan_three §1–§6（认证/Agentic/OTel/多模态/韧性/DR）。
>
> 本计划来源：[`advice.md`](./advice.md) gap review——plan_three 完成后对项目的上线前审查。核心判断：**架构已完整，但"安全闭环"和"真实效果"两道关口尚未真正闭合**——`require_roles` 写好了却零接入、RBAC 默认宽放、真实语料评估集缺失、文档与代码漂移。
>
> 规格：[`docs/enterprise-rag-design.md`](./docs/enterprise-rag-design.md)；实现现状：[`docs/architecture.md`](./docs/architecture.md)。
>
> **范围**：P0 + P1（advice 原列 P0/P1/P2 中的前两档）。P2 高级能力增量（DB/Wiki/API 连接器、细粒度 RBAC 数据模型）不纳入，避免计划过胖——其中 GraphRAG/CDC/多模态/DR 在 plan_two/plan_three 已实现，真正仍 stub 的只剩连接器框架与 RBAC 数据源。

---

## 0. 优先级总览

| # | 工作流 | 优先级 | 现状（已核实） | 工作量 | 可离线测试 |
|---|---|---|---|---|---|
| 1 | 安全闭环（写/admin 接口接 `require_roles` + RBAC 默认最小权限 + 越权单测 + 配置/审计收紧） | **P0** | `require_roles` 全仓 0 接入；15 个写接口无门禁；authz 默认宽放 | 中 | ✅ |
| 2 | 真实效果评估集（20–50 篇语料 + Recall@K/MRR/引用命中/bbox/faithfulness + 回归门禁） | **P0** | eval 框架在，无真实 case | 中大 | ✅(本地 BM25+mock LLM) |
| 3 | 端到端真实环境冒烟（compose 全套起、迁移、seed、上传、索引、/retrieve+/chat，记录启动顺序与失败点） | **P1** | 单测全绿但未证完整 infra 稳定 | 中 | ⚠️(需真实 infra，本机无) |
| 4 | 前端产品补齐（上传进度/重试、预览 E2E、登录/租户切换、引用点击定位、空状态/降级提示、PDF 模块懒加载） | **P1** | 页面可用，测试偏底层 | 中 | ✅(vitest) |
| 5 | 文档与发布清单对齐（README/architecture/Runbook/plan 已实现-待实现-生产要求重对齐） | **P1** | 设计书写 Next.js+MySQL、引 `reade.md`、Runbook 漏 0003 | 小 | ✅ |

> 实施顺序遵循 advice："安全门禁 → 真实评估 → 端到端环境验证 → 前端/E2E → 高级检索增强"。每项独立分支 → ff-only 合 main → push。

---

## 1. 安全闭环【P0】

**为什么**：plan_three §1 把 JWT + 用户/角色模型 + `require_roles` 都写好了，但**`require_roles` 被导入却零接入**——15 个写接口（KB×3 / documents×3 / eval×3 / chat×2 / model_configs / feedback / scenes / auth）任何登录用户（含 `viewer`）都能创建/修改/删除。`governance/authz.py::PermissionResolver` 在无规则时返回全可见（`authz.py:77`）。这是上线前最大风险。

**已核实**：
- `app/api/deps.py:4` 导入并 re-export `require_roles`，但 `grep -rn require_roles app/api/` 除 deps 外**无任何使用点**。
- `app/core/auth.py:114` `require_roles(*allowed)` 工厂实现正确（auth_enabled=False 放行；True 校验角色）。
- `app/governance/authz.py:76` 注释直写"默认宽放：无任何白名单/黑名单 → 全可见"。

**交付**：

### 1.1 写/admin 接口角色门禁
- **写操作（POST/PUT/DELETE/PATCH）** → `require_roles("admin", "editor")`：
  - `knowledge_bases.py`：create/update/delete
  - `documents.py`：upload（含 upload-url/delete）
  - `model_configs.py`：create/update/delete
  - `admin/scenes.py`：场景配置写
  - `admin/eval.py`：评估 case 写（create/update/delete）
- **读操作（GET）** → 不加门禁（viewer 可读，租户隔离已由 `get_tenant_ctx` 保证）。
- **`/chat`、`/retrieve`、`feedback`** → `require_roles("admin", "editor", "viewer")`（所有角色可问答/反馈，但需登录）。
- **`/auth/login`、`/healthz`、`/readyz`** → 无门禁。
- **匿名模式**（auth_enabled=False）：`require_roles` 内部已放行，不破坏本地/测试。

### 1.2 RBAC 默认最小权限（opt-in，不破坏开发）
- 新增 `settings.rbac_default_deny: bool = False`。
- `authz.py::PermissionResolver.resolve`：当 `rbac_enabled=True` 且 `rbac_default_deny=True` 且无匹配白/黑名单 → 返回 `PermissionFilter(doc_ids=set())`（拒绝所有文档）而非全可见。
- 默认 False 保留旧行为；生产显式置 True 即得最小权限。文档与 `.env.example` 标注。

### 1.3 越权 / 角色单测
- `tests/test_authz_endpoints.py`（新增）：
  - viewer 调写接口 → 403（auth_enabled=True + viewer token）。
  - editor/admin 调写接口 → 通过。
  - 跨租户访问（X-Tenant-Id 指向非成员租户）→ 403。
  - auth_enabled=False 时全部放行（回归保护）。
  - `rbac_default_deny=True` + 无规则 → 检索返回空（最小权限生效）。
- 复用 §1 的 JWT 生成工具（`core/security.create_access_token`）造各角色 token。

### 1.4 配置与审计收紧（文档化 + 小改）
- `.env.example`：在 `AUTH_ENABLED` / `JWT_SECRET` / `SEED_ADMIN_PASSWORD` 处加**生产必改**注释；CORS `allowed_origins` 注明生产应收窄。
- 审计保留：`governance/audit.py` 加 `settings.audit_retention_days`（默认 90），查询接口支持按时间过滤（落点已存在）。

**验证**：`pytest backend/tests` 全绿 + 新增越权测试；`grep -rn require_roles app/api/` 出现 ≥15 处接入点。

---

## 2. 真实效果评估集【P0】

**为什么**：当前 137 个测试验证的是**代码路径与降级逻辑**，从未证明"检索真的能把对的东西召回来、答案真的引用对了页"。eval 框架（plan_two §4：metrics/runner/ab）已就绪但 case 为空。

**交付**：
- 语料：20–50 篇代表性文档（普通文本 / 表格 / 多页 PDF / 含 bbox 图），置于 `backend/tests/fixtures/eval_corpus/`。
- 评估集：`eval_cases.jsonl`，每条 `{query, expected_doc_ids, expected_pages, gold_answer}`，覆盖：文本召回、表格召回、多轮追问、无答案问题。
- 指标接入既有 `eval/metrics.py`：Recall@K、MRR、引用命中（page）、bbox 命中（IoU）、faithfulness（LLM judge 或规则）。
- 回归门禁：`make eval` 跑全集，输出报告；CI 可选（nightly）。
- 降级兼容：无 LLM key 时 faithfulness 用规则近似（不阻塞）。

**验证**：`python -m app.eval --cases eval_cases.jsonl` 产出报告，指标非零；回归基线入库。

---

## 3. 端到端真实环境冒烟【P1】

**为什么**：单测全绿，但"完整 infra 串起来稳定"尚未证明。本机无 Milvus/PG/MinIO，此项**需用户侧执行**，我远程配合调试。

**交付**：
- 冒烟脚本 `make smoke`（或文档化步骤）：`make up && make migrate && make seed-admin` → 上传 PDF/TXT → 等待 indexed → `/retrieve` + `/chat`（SSE）→ 记录失败点。
- 启动顺序核对（MinIO 健康检查、Milvus ready、PG migrate 等）。
- 逐项开 `AUTH_ENABLED` / `AGENTIC_ENABLED` / `OTEL_ENABLED` / `TABLE_EXTRACTION_ENABLED` 实跑，记录问题并修。
- DR 演练：`make backup` → `make backup-verify` → `make restore ... RESTORE_YES=1`。

**验证**：一份冒烟报告（成功步骤 + 发现的问题 + 修复 commit）。

---

## 4. 前端产品补齐【P1】

**交付**：
- 上传：进度条 / 失败重试 / 批量。
- 预览：PDF.js E2E（bbox 高亮渲染验证）。
- 登录/租户切换：E2E（vitest 已有单测，补交互流）。
- 引用点击 → 定位高亮。
- 空状态 / 降级提示 UX（对齐后端 `degraded` 字段）。
- 构建：PDF 相关模块懒加载（降 bundle 体积）。

**验证**：`pnpm test` + `pnpm build` 通过；bundle 体积下降。

---

## 5. 文档与发布清单对齐【P1】

**已核实漂移**（已逐条核对）：
- `docs/enterprise-rag-design.md:8` 写 "FastAPI + Next.js + MySQL"（实为 FastAPI + React + PostgreSQL）。
- `docs/enterprise-rag-design.md:9` 引用不存在的 `reade.md`（应为 `README.md`）。
- `docs/RUNBOOK.md:10/68/72` 迁移只写 0001/0002（已有 `0003_auth_users.py`）。

**交付**：
- 设计书前言栈名修正 + `reade.md` → `README.md`。
- Runbook 迁移说明补 0003（auth_users），改为"以 `alembic upgrade head` 为准，版本号仅示例"。
- `architecture.md`：把 plan_three §1–§6 落地项从"接口/降级"移到"已实现"。
- README：补 plan_three/plan_four 进度 + 上线 checklist（AUTH/CORS/secret/审计）。

**验证**：`grep -rniE "next.?js|mysql|reade.md" docs/` 无残留；Runbook 列出全部迁移。

---

## 6. 不在本计划（P2，留 plan_five）

- DB/Wiki/API 真实连接器（当前接口 + stub）。
- 细粒度 RBAC 数据源（文档/知识库级权限落库 + 规则引擎）。
- 真实 OCR/YOLO GPU 验证、camelot 表格真实抽取验证。
- KEDA 扩缩实战、GraphRAG Neo4j 实跑。

> 这些依赖真实 GPU/infra 或大设计投入，排在安全与评估闭环之后。
