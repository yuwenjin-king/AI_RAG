import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** 后端 /auth/me 返回的用户信息（auth_enabled=false 时为匿名 admin）。 */
export interface AuthProfile {
  user_id: number;
  username: string;
  tenant_id: string; // 归属/默认租户
  role: string; // admin | editor | viewer
  memberships: Record<string, string>; // {tenant_id: role}
  authenticated: boolean; // false = 匿名（认证未开启）
}

/**
 * status 语义：
 * - 'unknown'      启动未探测（显示 loading，调 /auth/me）
 * - 'needs-login'  认证开启且未登录（显示登录页）
 * - 'guest'        认证未开启（匿名 admin，直进主应用）
 * - 'authed'       已登录
 * 注意：status 不持久化（每次启动都重新探测），仅持久化 token+profile。
 */
type Status = 'unknown' | 'needs-login' | 'guest' | 'authed';

interface AuthState {
  token: string | null;
  profile: AuthProfile | null;
  status: Status;
  setAuth: (token: string, profile: AuthProfile) => void;
  setProfile: (profile: AuthProfile) => void;
  setStatus: (s: Status) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      profile: null,
      status: 'unknown',
      setAuth: (token, profile) => set({ token, profile, status: 'authed' }),
      setProfile: (profile) => set({ profile }),
      setStatus: (status) => set({ status }),
      clear: () => set({ token: null, profile: null, status: 'needs-login' }),
    }),
    {
      name: 'rag-auth',
      // 仅持久化 token + profile；status 每次启动重探测
      partialize: (s) => ({ token: s.token, profile: s.profile }),
    },
  ),
);
