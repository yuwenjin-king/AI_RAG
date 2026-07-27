 主要问题

  1. 安全仍是上线前最大风险。 .env.example 默认 AUTH_ENABLED=false，表示信
     任 X-Tenant-Id/X-Role 头；生产必须开启 JWT 并替换默认 secret，
     见 .env.example:108。此外，require_roles() 已实现，但管理/写接口基本没
     接入，例如知识库创建/修改/删除在 backend/app/api/v1/
     knowledge_bases.py:20，场景配置在 backend/app/api/v1/admin/
     scenes.py:16，评估管理在 backend/app/api/v1/admin/eval.py:40。开启 JWT
     后也需要补接口级角色门禁。

  2. RBAC 默认宽放。 PermissionResolver 没有规则时返回全可见，见 backend/
     app/governance/authz.py:76。这适合开发兜底，但企业场景需要最小权限默认
     策略、角色规则、文档/知识库权限数据源。

  3. 真实 RAG 效果还没有被证明。 测试主要验证代码路径和降级逻辑，缺少真实语
     料评估集、召回率、引用准确率、答案 faithful 指标和回归门禁。项目有
     eval 框架，但还需要填真实 case。

  4. 多个高级能力仍是 hook / 降级 / 可选形态。 文档也明确提到 DB/Wiki/API
     connector、细粒度 RBAC、CDC、GraphRAG、视觉 OCR 等不少能力是接口或可选
     实现，见 docs/architecture.md:31。

  5. 文档存在漂移。 设计文档还提到旧栈 “Next.js + MySQL”和不存在的
     reade.md，见 docs/enterprise-rag-design.md:7。Runbook 迁移说明也还写
     0001/0002，但仓库已有 0003_auth_users.py，见 docs/RUNBOOK.md:70。

  建议后续路线

  P0：先补安全闭环。开启 AUTH_ENABLED=true 的完整验收；所有写接口/admin 接
  口接 require_roles("admin", "editor") 或更细策略；viewer 只读；补越权单
  测；生产 secret、默认账号、CORS、审计保留策略收紧。

  P0：建立真实效果评估集。选 20-50 篇代表性文档，覆盖普通文本、表格、PDF 页
  码/bbox、多轮追问、无答案问题；把 Recall@K、MRR、引用命中、bbox 命中、
  faithfulness 做成 CI 或 nightly 评估。

  P1：做一次端到端真实环境冒烟。用 Docker Compose 拉完整 infra，跑迁移、
  seed admin、上传 PDF/TXT、等待索引、执行 /retrieve 和 /chat，记录失败点和
  启动顺序问题。当前单测通过，但还没证明完整 infra 串起来稳定。

  P1：前端产品补齐。当前页面可用，但测试覆盖偏底层；需要补上传进度/失败重
  试、文档预览 E2E、登录/租户切换、引用点击定位、空状态与降级提示体验。构建
  bundle 偏大，PDF 相关模块建议懒加载。

  P1：整理文档和发布清单。把 README、architecture、Runbook、plan 文件里
  的“已实现/待实现/生产要求”重新对齐，避免后续按过期文档操作。

  P2：再推进高级能力。GraphRAG、CDC、OCR/YOLO、多模态表格图片、DR 演练、
  KEDA 扩缩等都值得做，但应排在安全和评估闭环之后。当前最有价值的顺序是：安
  全门禁 → 真实评估 → 端到端环境验证 → 前端/E2E → 高级检索增强。
