import { useTenant } from '../stores/tenant';

/** API 基址。开发期 vite 代理 /api → 后端，故默认空（相对路径）。 */
export const BASE = import.meta.env.VITE_API_BASE || '';

export function tenantId(): string {
  return useTenant.getState().tenantId;
}

function authHeaders(extra: HeadersInit = {}): Record<string, string> {
  return { 'X-Tenant-Id': tenantId(), ...(extra as Record<string, string>) };
}

/** JSON 请求封装。 */
export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = authHeaders(opts.headers as HeadersInit);
  if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const resp = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (!resp.ok) {
    let msg = `${resp.status} ${resp.statusText}`;
    try {
      const j = await resp.json();
      msg = j.message || msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as unknown as T;
  const ct = resp.headers.get('content-type') || '';
  return (ct.includes('application/json') ? await resp.json() : await resp.text()) as T;
}

/** multipart 上传（文件直传）。 */
export async function uploadFile(path: string, file: File): Promise<any> {
  const fd = new FormData();
  fd.append('file', file);
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'X-Tenant-Id': tenantId() }, // 不要设 Content-Type，让浏览器带 boundary
    body: fd,
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}
