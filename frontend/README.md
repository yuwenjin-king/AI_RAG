# Enterprise RAG — Frontend

React + TypeScript + Vite + Ant Design + Zustand。对话式问答 + 知识库/文档管理 + PDF 区域级溯源高亮 + 场景配置。

## 开发

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 （/api 经 vite 代理到后端 :8000）
```

> 需后端在 `http://localhost:8000` 运行（见仓库根 `docker compose up`）。
> 右上角切换「租户」，对应请求头 `X-Tenant-Id`，数据按租户隔离。

## 页面

| 路由 | 说明 |
|---|---|
| `/chat` | 对话问答：SSE 流式打字机输出 + 引用卡片（含页码），点引用跳转高亮预览 |
| `/knowledge-bases` | 知识库 CRUD |
| `/documents` | 文档上传（预签名 PUT 直传，MinIO 不可用时走直传兜底）+ 索引状态轮询 |
| `/preview/:docId/:chunkId` | **PDF.js 区域级溯源**：按 `page_no` 渲染页面 + 归一化 `bbox` 画高亮框 |
| `/admin` | 场景四要素配置（知识库 + 检索策略 + Prompt + 权限） |

## 生产构建

```bash
npm run build    # 产物 dist/
# 或：docker build -t enterprise-rag-frontend . （nginx 托管 + 反代 /api）
```
