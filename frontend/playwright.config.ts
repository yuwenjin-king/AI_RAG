import { defineConfig } from '@playwright/test';

// E2E 前置：make up（完整栈在线）+ make migrate && make seed-admin（admin/changeme）
// 前端 nginx 同时反代 /api → backend，浏览器全程只访问 localhost:5173。
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  // 串行：用例间有状态依赖（登录 → 建库 → 上传 → 问答 → 预览）
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'only-on-failure',
    locale: 'zh-CN',
  },
});
