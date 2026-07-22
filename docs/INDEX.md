# 文档导航

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) | 项目总览 + 一键启动 |
| [enterprise-rag-design.md](./enterprise-rag-design.md) | v2.0 设计规格（分层架构 / 模块 / 部署 / 路线） |
| [architecture.md](./architecture.md) | 本仓库实现现状、可插拔点、与设计书差异、降级链路 |
| [RUNBOOK.md](./RUNBOOK.md) | 运维：启动 / 降级开关 / Worker / 监控 / 排障 |
| [security.md](./security.md) | 安全合规：TLS / 静态加密 / 密钥管理 / RBAC / PII / 审计 |
| [loadtest.md](./loadtest.md) | 规模化与性能：目标 / k6 脚本 / 旋钮 / 灌库 |
| [plan_one.md](../plan_one.md) | 首轮落地计划（后端核心 / 前端 / 监控 / 部署）— 已完成 |
| [plan_two.md](../plan_two.md) | 后续迭代计划（P0 检索/视觉 → P1 平台化 → P2 GraphRAG/CDC）— 已完成 |

## 状态总览

- **plan_one**：✅ 后端核心链路 + React 前端 + 可观测性（Prometheus/Grafana）+ K8s 部署
- **plan_two**：✅ 全部 11 项（① PDF 视觉解析 ② 检索增强 ③ RBAC ④ 评估/A-B ⑤ 成本管控 ⑥ KEDA ⑦ 规模化 ⑧ 安全合规 ⑨ CI/CD ⑩ GraphRAG ⑪ CDC）
- 测试：57+（单元 + 集成），离线可跑（sqlite + 自研 BM25 + 内存图）
