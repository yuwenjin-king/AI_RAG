// 数据接入压测（k6）：批量上传小文档触发 ingest 管线，考察 worker 吞吐与扩缩（配合 KEDA）。
// 运行：k6 run -e BASE=http://localhost:8000 -e TENANT=default loadtest/k6_ingest.js
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://localhost:8000';
const TENANT = __ENV.TENANT || 'default';

export const options = {
  stages: [
    { duration: '1m', target: 20 },   // 每秒 20 个上传
    { duration: '2m', target: 20 },
    { duration: '30s', target: 0 },
  ],
};

export default function () {
  const headers = { 'X-Tenant-Id': TENANT };
  // 1) 申请上传
  const u = http.post(
    `${BASE}/api/v1/documents/upload-url`,
    JSON.stringify({ filename: `loadtest-${Date.now()}-${__VU}-${__ITER}.txt`, content_type: 'text/plain' }),
    { headers: { ...headers, 'Content-Type': 'application/json' } },
  );
  if (u.status !== 200) { sleep(0.2); return; }
  const docId = u.json('doc_id');
  const direct = u.json('direct_upload_url');

  // 2) 直传（小文本）
  const text = `压测文档 ${__ITER} `.repeat(200);
  const fd = { file: http.file(text, 'f.txt', 'text/plain') };
  if (direct) {
    const up = http.post(`${BASE}${direct}`, fd, { headers });
    check(up, { 'upload 200': (r) => r.status === 200 });
  }
  sleep(0.2);
}
