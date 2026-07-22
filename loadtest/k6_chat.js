// 对话/检索压测（k6）。目标：纯检索 P95 ≤ 300ms；端到端 P95 ≤ 3s（设计书 §2.2）。
// 运行：k6 run -e BASE=http://localhost:8000 -e TENANT=default loadtest/k6_chat.js
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://localhost:8000';
const TENANT = __ENV.TENANT || 'default';
const KB = __ENV.KB || '';

export const options = {
  stages: [
    { duration: '30s', target: 50 },
    { duration: '1m', target: 100 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    // 纯检索 P95 应 ≤ 300ms
    http_req_duration: ['p(95)<300'],
  },
};

const queries = ['产品功能', '如何配置', '错误处理', '架构设计', '部署方式', '权限控制'];

export default function () {
  const q = queries[Math.floor(Math.random() * queries.length)];
  const params = { headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': TENANT } };
  const body = { query: q, top_k: 8 };
  if (KB) body.knowledge_base_id = Number(KB);

  // 纯检索（同步 JSON，便于稳定测检索延迟）
  const r = http.post(`${BASE}/api/v1/retrieve`, JSON.stringify(body), params, { tags: { op: 'retrieve' } });
  check(r, { 'retrieve 200': (r) => r.status === 200 });

  // 端到端对话（SSE，k6 读完整响应，测总时长；去掉注释启用）
  // const c = http.post(`${BASE}/api/v1/chat`, JSON.stringify(body), params, { tags: { op: 'chat' } });
  // check(c, { 'chat 200': (r) => r.status === 200 });
  sleep(0.1);
}
