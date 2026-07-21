import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发期把 /api 代理到后端 FastAPI（避免 CORS，SSE 流也能透传）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  // pdfjs-dist worker 走 ?url 导入
  optimizeDeps: { include: ['pdfjs-dist/build/pdf.worker.min.mjs'] },
});
