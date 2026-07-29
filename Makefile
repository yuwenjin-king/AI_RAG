.PHONY: help up up-vision down restart logs migrate dev-be dev-fe test test-be test-fe lint eval eval-seed fmt clean backup restore backup-verify

help:  ## 列出常用目标
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:  ## 拉起全套 infra + 应用
	docker compose up -d --build

up-vision:  ## 同时启用视觉解析 worker（扫描件 OCR/版面检测）
	docker compose up -d --build --profile vision

up-otel:  ## 同时启用追踪（Jaeger UI: localhost:16686）
	docker compose up -d --build --profile otel

down:  ## 停止全部
	docker compose down

restart:  ## 重建并重启应用服务
	docker compose up -d --build --force-recreate backend ingest-worker frontend

logs:  ## 跟随后端/worker 日志
	docker compose logs -f backend ingest-worker

migrate:  ## 执行数据库迁移
	docker compose exec backend alembic upgrade head

seed-admin:  ## 创建默认管理员（AUTH_ENABLED=true 前必须先 seed；经 SEED_ADMIN_USERNAME/PASSWORD 覆盖）
	docker compose exec backend python -m app.scripts.seed_admin

backup:  ## 创建一份备份（PG 元数据 + Milvus/MinIO/OpenSearch best-effort）。BACKUP_DIR 覆盖输出目录
	docker compose exec backend python -m app.scripts.dr backup $(if $(BACKUP_DIR),--out $(BACKUP_DIR))

backup-verify:  ## 校验某份备份完整性（sha256 + 权威源）。用法: make backup-verify PATH=<备份目录>
	@test -n "$(PATH)" || (echo "用法: make backup-verify PATH=<备份目录>" && false)
	docker compose exec backend python -m app.scripts.dr verify $(PATH)

restore:  ## 从备份恢复（破坏性：清空重写 PG/Milvus/MinIO/OpenSearch）。用法: make restore PATH=<备份目录> RESTORE_YES=1
	@test -n "$(PATH)" -a -n "$(RESTORE_YES)" || (echo "用法: make restore PATH=<备份目录> RESTORE_YES=1（须显式确认，破坏性）" && false)
	docker compose exec backend python -m app.scripts.dr restore $(PATH) --yes

dev-be:  ## 本地后端热重载（需 infra 已 up）
	cd backend && uvicorn app.main:app --reload --port 8000

dev-fe:  ## 本地前端热重载
	cd frontend && npm run dev

test: test-be test-fe  ## 跑全部测试

test-be:  ## 后端 pytest
	cd backend && python3 -m pytest -q

test-fe:  ## 前端 vitest
	cd frontend && npm run test

lint:  ## 后端 ruff（不阻断）
	cd backend && (ruff check app tests || true)

eval-seed:  ## 装载评估语料集（建 KB+场景+文档+chunk+用例）。用法: make eval-seed TENANT=default SCENE=eval [RESET=1]
	docker compose exec backend python -m app.eval.seed --tenant $(TENANT) --scene $(SCENE) $(if $(RESET),--reset)

eval:  ## 离线评估（检索层；加 GEN=1 跑生成层 faithfulness）。用法: make eval TENANT=default SCENE=eval [GEN=1]
	docker compose exec backend python -m app.eval --tenant $(TENANT) --scene $(SCENE) $(if $(GEN),--with-generation)

clean:  ## 清理构建产物
	find . -type d -name __pycache__ -prune -exec rm -rf {} + ; \
	rm -rf backend/.pytest_cache frontend/dist frontend/node_modules/.vite
