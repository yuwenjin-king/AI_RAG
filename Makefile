.PHONY: help up up-vision down restart logs migrate dev-be dev-fe test test-be test-fe lint eval fmt clean

help:  ## 列出常用目标
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:  ## 拉起全套 infra + 应用
	docker compose up -d --build

up-vision:  ## 同时启用视觉解析 worker（扫描件 OCR/版面检测）
	docker compose up -d --build --profile vision

down:  ## 停止全部
	docker compose down

restart:  ## 重建并重启应用服务
	docker compose up -d --build --force-recreate backend ingest-worker frontend

logs:  ## 跟随后端/worker 日志
	docker compose logs -f backend ingest-worker

migrate:  ## 执行数据库迁移
	docker compose exec backend alembic upgrade head

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

eval:  ## 离线评估：make eval SCENE=xxx TENANT=default
	cd backend && python -m app.eval --tenant $(TENANT) --scene $(SCENE)

clean:  ## 清理构建产物
	find . -type d -name __pycache__ -prune -exec rm -rf {} + ; \
	rm -rf backend/.pytest_cache frontend/dist frontend/node_modules/.vite
