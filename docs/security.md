# 安全与合规（设计书 §8）

本平台的安全控制分层落地。应用层（PII 脱敏、RBAC、审计、限流）已在代码内；传输/静态加密/密钥管理在部署层，本文给出清单与接入方式。

## 1. 传输安全（TLS）

- **前端 ↔ BFF**：全链路 HTTPS。K8s 经 ingress + cert-manager 自动签发（见 `deploy/k8s/ingress.yaml` 的 `tls:` + `cert-manager.io/cluster-issuer`），并 `force-ssl-redirect`。
- **BFF ↔ 检索/生成内部服务**：集群内走 Service Mesh（Istio/Linkerd）开启 **mTLS**（自动双向证书），或服务间内部 token。
- **SSE 流式**：ingress 已 `proxy-buffering: off` + 长超时，TLS 不影响流式。

## 2. 静态加密（Encryption at Rest）

| 存储 | 加密方式 |
|---|---|
| PostgreSQL | 云托管磁盘加密 + 列级敏感字段加密；自建则 `pgcrypto`/TDE |
| Milvus | 对象存储（MinIO/S3）服务端加密；Milvus 元数据 etcd 磁盘加密 |
| OpenSearch | 节点磁盘加密 +（可选）字段级加密 |
| MinIO/S3 | SSE-S3 / SSE-KMS（KMS 托管主密钥） |
| Redis | `requirepass` + 云托管静态加密；不存明文敏感数据 |

> 原始 PDF 同样加密存储（对象存储 SSE），仅在 `/locate` 预签名短时效 URL 临时下发。

## 3. 密钥管理

- **不在 compose / 镜像里硬编码密钥**。`.env` 与 `deploy/k8s/secret.yaml` 已 `.gitignore`。
- 生产用 **Vault / 云 KMS** 注入；K8s 经 External Secrets Operator 从 Vault 拉取成 Secret，Pod 以 envFrom 挂载（见 `deploy/k8s/backend.yaml`）。
- 轮换：KMS 主密钥定期轮换；API key 通过 `model_configs.api_key_ref` 引用环境变量名，便于无代码轮换。

## 4. 访问控制（RBAC）— 应用层已落地

- 多租户：`X-Tenant-Id` → 仓储前置过滤 + 每租户 collection/index（详见 `docs/architecture.md`）。
- 细粒度：`governance/authz.py` 的 `PermissionFilter` 作为检索**前置过滤**注入（`allowed_kb_ids/allowed_doc_ids/denied_doc_ids`），按场景/角色（`X-Role`）解析，防越权。
- 限流：per-tenant `/chat` 限流（Redis 计数 + 本地兜底），超限 429。

## 5. PII 脱敏 — 应用层已落地

- `services/ingestion/pii.py`：接入阶段（解析后、入库前）按规则掩码手机/邮箱/身份证/银行卡，PII 不进入 chunk / 索引。
- 开关：`PII_MASKING_ENABLED` + `PII_RULES`；可按租户/合规要求扩展规则或接入 presidio。

## 6. 审计 — 应用层已落地

- `governance/audit.py` 落 `operation_logs`：文档创建/上传/原文溯源、场景配置变更等关键操作。
- 查询：`GET /api/v1/admin/audit?action=&limit=`（设计书 §8 审计追溯）。
- 记录：查询日志、检索命中来源、原文访问日志，满足合规审计需求。

## 7. 合规清单（部署前确认）

- [ ] ingress TLS + 强制 HTTPS（cert-manager）
- [ ] 服务间 mTLS（Mesh）或内部 token
- [ ] 全部存储静态加密（PG/Milvus/OS/MinIO/Redis）
- [ ] 密钥经 Vault/KMS，无明文入库/镜像
- [ ] RBAC 规则按最小权限配置
- [ ] PII 脱敏按业务合规开关
- [ ] 审计日志保留期满足合规要求（建议 ≥ 180 天）
- [ ] 按部署地区/行业评估云厂商合规资质（等保/GDPR/HIPAA 等）
