import { useTenant } from '../stores/tenant';
import { useAuth } from '../stores/auth';

/** API 基址。开发期 vite 代理 /api → 后端，故默认空（相对路径）。 */
export const BASE = import.meta.env.VITE_API_BASE || '';

export function tenantId(): string {
  return useTenant.getState().tenantId;
}

/** 当前用户 token（未登录/认证未开启时为 null）。 */
export function authToken(): string | null {
  return useAuth.getState().token;
}

function authHeaders(extra: HeadersInit = {}): Record<string, string> {
  const h: Record<string, string> = { 'X-Tenant-Id': tenantId(), ...(extra as Record<string, string>) };
  const token = authToken();
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

/** JSON 请求封装。401（非登录接口）自动登出，App 守卫随即切到登录页。 */
export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = authHeaders(opts.headers as HeadersInit);
  if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const resp = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (!resp.ok) {
    // 401（登录接口自身除外）→ 清除登录态
    if (resp.status === 401 && !path.startsWith('/api/v1/auth/login')) {
      useAuth.getState().clear();
    }
    let msg = `${resp.status} ${resp.statusText}`;
    try {
      const j = await resp.json();
      // AppError→{message}，HTTPException→{detail}
      msg = j.message || j.detail || msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as unknown as T;
  const ct = resp.headers.get('content-type') || '';
  return (ct.includes('application/json') ? await resp.json() : await resp.text()) as T;
}

/** multipart 上传（文件直传）。不要设 Content-Type，让浏览器带 boundary。 */
export async function uploadFile(path: string, file: File): Promise<any> {
  const fd = new FormData();
  fd.append('file', file);
  const headers: Record<string, string> = { 'X-Tenant-Id': tenantId() };
  const token = authToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: fd });
  if (!resp.ok) {
    if (resp.status === 401) useAuth.getState().clear();
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

/**
 * 带进度的上传（XHR）。用于预签名 PUT 直传对象存储（plan_four §4）。
 * onProgress(percent 0~100) 由调用方透传给 AntD Upload 的 onProgress → 列表显示进度条。
 * 失败 reject → 调用方 onError → AntD 列表标记 error 并提供重试。
 */
export function putWithProgress(
  url: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)));
      }
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`对象存储上传失败 ${xhr.status}`));
    xhr.onerror = () => reject(new Error('上传网络错误'));
    xhr.send(file);
  });
}
