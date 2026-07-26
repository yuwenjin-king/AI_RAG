# 备份恢复 / DR Runbook（plan_three §6）

> 目标：在数据丢失/损坏时，把平台恢复到一个一致的点。**PG 元数据是权威源**——丢了它，向量/倒排/原文都失去意义（向量引用的 doc/chunk id 无法还原）；其余 store 都可从 PG + 原文重建。

---

## 1. 备份范围

| Store | 是否备份 | 方式 | 备注 |
|---|---|---|---|
| **PostgreSQL**（元数据） | ✅ 始终 | 便携 JSON（`pg_meta.py`，asyncpg/sqlite 通用）+ 生产推荐 `pg_dump` | 13 张表，FK 拓扑序，显式主键保真 |
| **Milvus**（向量） | ✅ best-effort | `export_collection`（含 embedding，offset 分页）→ tar | 不可用→恢复时按 chunk 重新 embed（耗费 API） |
| **MinIO**（原文档） | ✅ best-effort | `list_object_keys` + `get_bytes` → tar；bucket 已启用**版本化** | 不可用→原文需重传 |
| **OpenSearch**（倒排） | ⚙️ 可选 | scroll 导出 → tar | 完全可由 chunks 重建；`BACKUP_INCLUDE_OPENSEARCH=false` 关闭以减体积 |
| **Redis**（缓存） | ❌ 不备份 | — | 仅查询/嵌入缓存 + 限流计数，全部可重建 |

备份产物（单份）：

```
<BACKUP_DIR>/<backup_id>/
  manifest.json        # 目录页 + sha256 完整性凭证
  postgres.json        # 元数据（权威）
  milvus.tar           # 每集合一个 .jsonl
  minio.tar            # 每对象以其 key 为成员
  opensearch.tar       # 每索引一个 .jsonl（可选）
```

---

## 2. RPO / RTO 目标

| 指标 | 目标 | 实现手段 |
|---|---|---|
| **RPO**（可容忍丢失时长） | 默认 24h（`BACKUP_RPO_TARGET_SECONDS=86400`） | 定时全量备份（cron / K8s CronJob）；生产走 `pg_dump` + WAL 归档做 PITR（分钟级 RPO） |
| **RTO**（恢复用时） | 开发规模分钟级 | 恢复顺序：MinIO → PG → Milvus → OpenSearch；PG 行级回灌 + 向量/倒排批量 upsert |

> 上述目标写入 `manifest.json`（`rpo_target_seconds`）便于审计。实际 RPO/RTO 取决于数据量与备份频率，**需按租户体量各自验证**（见 §6 演练）。

---

## 3. 配置（`.env`）

```bash
BACKUP_DIR=./backups               # 备份根目录（容器内相对 /app；生产用持久卷）
BACKUP_RETENTION=7                 # 保留最近 N 份，超出自动清理
BACKUP_INCLUDE_OPENSEARCH=true     # false→跳过 OS（可由 chunks 重建）
BACKUP_RPO_TARGET_SECONDS=86400    # 仅写入 manifest 元数据
MINIO_BUCKET_VERSIONING=true       # MinIO bucket 版本化（对象级历史/误删保护）
```

---

## 4. 备份

### 4.1 便携式备份（默认，跨方言，无 pg 客户端依赖）

```bash
make backup                      # 一次性
# 或指定输出目录 / 自定义 id
make backup BACKUP_DIR=/backups
```

等价 CLI：`docker compose exec backend python -m app.scripts.dr backup`

输出 JSON 摘要：`backup_id` / `status`（complete|partial）/ `stores` / `notes`（降级原因）。
- `status=partial`：PG 成功但 Milvus/MinIO 之一不可用——**仍可用于恢复**（向量重 embed、原文重传），只是恢复后需补步。

### 4.2 定时备份

```bash
# 主机 crontab（每日 02:17 错峰）
17 2 * * *   cd /path/to/AI_RAG && make backup >> /var/log/rag-backup.log 2>&1
```

K8s：用 CronJob 跑 `python -m app.scripts.dr backup`，把 `BACKUP_DIR` 指向持久卷，再用 sidecar/工具把卷同步到对象存储（异地副本）。

### 4.3 生产推荐：pg_dump + WAL 归档（PITR）

便携 JSON 兜底无 pg 客户端 / 跨方言（含 sqlite 测试），但**生产强烈推荐** `pg_dump` + WAL 归档，类型/约束/序列完全保真且支持时间点恢复：

```bash
# 全量逻辑备份（可与便携备份并存，互不干扰）
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > /backups/pg-$(date -u +%Y%m%dT%H%M%SZ).sql.gz

# PITR：开启 WAL 归档（postgres.conf 或启动参数）
#   archive_mode=on
#   archive_command='test ! -f /backups/wal/%f && cp %p /backups/wal/%f'
# 基准备份：pg_basebackup -h postgres -U rag -D /backups/base -Fp -Xs -P
# 恢复到时间点：还原 base → create recovery.signal + restore_command + recovery_target_time → 启动
```

便携备份的 `postgres.json` 与 `pg_dump` 产物**互补**：前者便于跨环境/测试快速回放，后者是生产权威。

---

## 5. 恢复

> ⚠️ **破坏性**：恢复会清空并重写目标存储（PG 按"子→父删、父→子插"使目标 == 备份）。务必先在演练环境验证。

```bash
# 1) 校验备份完整性（sha256 + 权威源）—— 恢复前必做
make backup-verify PATH=/backups/<backup_id>

# 2) 恢复（须显式确认）
make restore PATH=/backups/<backup_id> RESTORE_YES=1
```

等价 CLI：`python -m app.scripts.dr restore <dir> --yes`（不加 `--yes` 则交互确认）。

恢复顺序与理由：
1. **MinIO**（原文）——无强依赖，先放便于后续校验。
2. **PG**（元数据，权威）——重建 doc/chunk 行与编号。
3. **Milvus**（向量）——引用 PG 的 doc/chunk id，故在 PG 之后。
4. **OpenSearch**（倒排）——同上；可由 chunks 重建，缺失不阻断。

恢复后自检：
- PG：`SELECT count(*) FROM chunks;` 与 manifest `postgres.detail.chunks` 一致。
- Milvus：向量数与备份 `milvus` artifact `count` 一致；不一致则对 `embedding_status != indexed` 的 chunk 重跑 ingest worker 重新 embed。
- OpenSearch：文档数与备份一致；不一致则重建索引（重跑 ingest worker 的索引阶段）。

恢复时若某 store 不可用（infra 下线），该 store 记 `skipped` 不阻断——待 infra 恢复后按上面自检补齐。

---

## 6. 恢复演练（定期执行）

> DR 没演练过 = 没有 DR。建议每月一次，并记录实际 RTO。

```bash
# 0) 在演练环境准备一份近期生产备份（含 manifest）
# 1) 起一套干净的 infra
make up && make migrate
# 2) 恢复并计时
time make restore PATH=/backups/<backup_id> RESTORE_YES=1
# 3) 冒烟：登录 → 选租户 → 提一个已知问题 → 核对引用 page/bbox 溯源
# 4) 记录 RTO；若超目标，排查瓶颈（常见：向量重 embed、大对象传输）
```

---

## 7. 设计与边界

- **便携 dump 不保真 PG 专有类型/约束/序列**：用类型自描述标签（`{"__iso__":...}`/`__dec__`/`__uuid__`/`__bytes__`）覆盖 datetime/Decimal/UUID/bytes/JSONB，主键显式插入保 FK 一致；但 CHECK 约束、触发器、序列当前值不在内。**生产以 `pg_dump` 为准**，便携 dump 为跨环境兜底与离线测试路径。
- **Milvus 导出 offset 分页**：大数据量 offset 会变慢；超大规模租户建议改用 milvus-backup 工具（块级快照），本脚本面向开发/中小规模。
- **MinIO 版本化**：`init_object_storage` best-effort 启用（旧 MinIO 或 `MINIO_BUCKET_VERSIONING=false` 时跳过，不阻断启动）。版本化提供对象级历史与误删保护，与定期 tar 备份互补。
- **离线测试**：`tests/test_dr.py` 用 sqlite 验证 PG 往返 + manifest 纯逻辑 + 编排（monkeypatched stores）；真实 Milvus/OS/MinIO 的导出导入需在 `make up` 环境演练（见 §6）。
