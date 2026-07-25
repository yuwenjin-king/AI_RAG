import { api, BASE, authToken } from './client';
import type { AuthProfile } from '../stores/auth';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  tenant_id: string;
  role: string;
  memberships: Record<string, string>;
}

/** 用户名密码登录 → JWT + profile。 */
export async function login(username: string, password: string): Promise<LoginResponse> {
  return api<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

/**
 * 探测当前登录态（启动守卫调用）：
 * - 200 authenticated=true  → 已登录
 * - 200 authenticated=false → 认证未开启（匿名）
 * - 401                     → 认证开启但未登录
 * 用原始 fetch：401 不触发 api() 的登出副作用。
 */
export async function fetchMe(): Promise<AuthProfile> {
  const headers: Record<string, string> = {};
  const token = authToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}/api/v1/auth/me`, { headers });
  if (!resp.ok) throw new Error(`${resp.status}`);
  return resp.json();
}
