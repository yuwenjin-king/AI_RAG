import { describe, it, expect, beforeEach } from 'vitest';
import { useAuth } from './auth';

describe('auth store', () => {
  beforeEach(() => {
    useAuth.getState().clear();
    localStorage.clear();
  });

  it('clear 切到 needs-login 且清空 token/profile', () => {
    const s = useAuth.getState();
    expect(s.status).toBe('needs-login');
    expect(s.token).toBeNull();
    expect(s.profile).toBeNull();
  });

  it('setAuth 设置 token/profile 并切到 authed，持久化 token', () => {
    useAuth.getState().setAuth('tok-123', {
      user_id: 1,
      username: 'alice',
      tenant_id: 'acme',
      role: 'admin',
      memberships: { acme: 'admin' },
      authenticated: true,
    });
    const s = useAuth.getState();
    expect(s.token).toBe('tok-123');
    expect(s.status).toBe('authed');
    expect(s.profile?.username).toBe('alice');
    expect(localStorage.getItem('rag-auth')).toContain('tok-123');
  });

  it('clear 回到 needs-login 并清空', () => {
    useAuth.getState().setAuth('tok', {
      user_id: 1, username: 'u', tenant_id: 'a', role: 'admin',
      memberships: {}, authenticated: true,
    });
    useAuth.getState().clear();
    const s = useAuth.getState();
    expect(s.token).toBeNull();
    expect(s.profile).toBeNull();
    expect(s.status).toBe('needs-login');
  });

  it('status 不持久化（仅 token/profile 入 localStorage）', () => {
    useAuth.getState().setAuth('t', {
      user_id: 1, username: 'u', tenant_id: 'a', role: 'admin',
      memberships: {}, authenticated: true,
    });
    const raw = JSON.parse(localStorage.getItem('rag-auth') || '{}');
    expect(raw.state.token).toBe('t');
    expect(raw.state.profile).toBeDefined();
    expect(raw.state.status).toBeUndefined(); // 关键：status 每次启动重探测
  });

  it('setProfile / setStatus 独立更新', () => {
    useAuth.getState().setStatus('guest');
    expect(useAuth.getState().status).toBe('guest');
    useAuth.getState().setProfile({
      user_id: 2, username: 'b', tenant_id: 'beta', role: 'viewer',
      memberships: { beta: 'viewer' }, authenticated: true,
    });
    expect(useAuth.getState().profile?.role).toBe('viewer');
  });
});
