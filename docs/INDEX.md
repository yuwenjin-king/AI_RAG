# 文档导航

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) | 项目总览 + 一键启动 |
| [enterprise-rag-design.md](./enterprise-rag-design.md) | v2.0 设计规格（分层架构 / 模块 / 部署 / 路线） |
| [architecture.md](./architecture.md) | 本仓库实现现状、可插拔点、与设计书差异、降级链路 |
| [RUNBOOK.md](./RUNBOOK.md) | 运维：启动 / 降级开关 / Worker / 监控 / 排障 |
| [dr-runbook.md](./dr-runbook.md) | 备份恢复 / DR：范围 / RPO-RTO / 备份-恢复-演练 / pg_dump+PITR |
| [security.md](./security.md) | 安全合规：TLS / 静态加密 / 密钥管理 / RBAC / PII / 审计 |
| [eval.md](./eval.md) | 评估：组件 / 指标 / 离线回归门禁 / 真实环境评估用法 |
| [loadtest.md](./loadtest.md) | 规模化与性能：目标 / k6 脚本 / 旋钮 / 灌库 |
| [plan_one.md](../plan_one.md) | 首轮落地计划（后端核心 / 前端 / 监控 / 部署）— 已完成 |
| [plan_two.md](../plan_two.md) | 后续迭代计划（P0 检索/视觉 → P1 平台化 → P2 GraphRAG/CDC）— 已完成 |
| [plan_three.md](../plan_three.md) | 平台化深化（认证授权 / Agentic / OTel / 多模态 / 韧性 / DR）— 已完成 |
| [plan_four.md](../plan_four.md) | 上线就绪加固（安全闭环 / 真实评估 / 端到端 / 前端 / 文档对齐） |
| [advice.md](../advice.md) | plan_three 完成后的上线前差距审查（plan_four 输入） |

## 状态总览

- **plan_one**：✅ 后端核心链路 + React 前端 + 可观测性（Prometheus/Grafana）+ K8s 部署
- **plan_two**：✅ 全部 11 项（① PDF 视觉解析 ② 检索增强 ③ RBAC ④ 评估/A-B ⑤ 成本管控 ⑥ KEDA ⑦ 规模化 ⑧ 安全合规 ⑨ CI/CD ⑩ GraphRAG ⑪ CDC）
- **plan_three**：✅ 全部 6 项（§1 认证授权 §2 Agentic §3 OTel §4 多模态 §5 韧性 §6 DR）
- **plan_four**：✅ §1 安全闭环 §2 真实评估集 §4 前端补齐 §5 文档对齐；⏳ §3 端到端真实环境冒烟
- 测试：后端 161（+2 skipped 无 OTel）+ 前端 16，全绿；离线可跑（sqlite + 自研 BM25 + 内存图）
