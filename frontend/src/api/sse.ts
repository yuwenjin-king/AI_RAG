import { BASE, tenantId, authToken } from './client';
import { useAuth } from '../stores/auth';

/** SSE 单事件。data 已按 JSON 解析（失败则返回原始字符串）。 */
export interface SSEEvent {
  event: string;
  data: any;
}

export function parseBlock(raw: string): SSEEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  // SSE 规范允许 CRLF 行尾（sse-starlette 等实现即如此），按 \r?\n 切行
  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue; // 空行/注释(keepalive)
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
  }
  if (dataLines.length === 0) return null;
  const joined = dataLines.join('\n');
  try {
    return { event, data: JSON.parse(joined) };
  } catch {
    return { event, data: joined };
  }
}

/**
 * 流式问答：POST /api/v1/chat，逐块解析 SSE。
 * 事件：meta(含 conversation_id) / citations / token / done
 */
export async function* chatStream(body: any): AsyncGenerator<SSEEvent> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    'X-Tenant-Id': tenantId(),
  };
  const token = authToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}/api/v1/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) {
    if (resp.status === 401) {
      // token 失效 → 登出，App 守卫随即切到登录页
      useAuth.getState().clear();
    }
    throw new Error(`chat failed: ${resp.status} ${resp.statusText}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // 事件分隔符兼容 LF / CRLF（\n\n 或 \r\n\r\n），跨 chunk 的半截分隔符留在 buffer
    for (;;) {
      const m = /\r?\n\r?\n/.exec(buffer);
      if (!m) break;
      const block = buffer.slice(0, m.index);
      buffer = buffer.slice(m.index + m[0].length);
      const evt = parseBlock(block);
      if (evt) yield evt;
    }
  }
  // flush 残留
  if (buffer.trim()) {
    const evt = parseBlock(buffer);
    if (evt) yield evt;
  }
}
