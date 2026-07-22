import { describe, it, expect, beforeEach } from 'vitest';
import { useTenant } from './tenant';

describe('tenant store', () => {
  beforeEach(() => {
    useTenant.getState().setTenantId('default');
  });

  it('默认租户为 default', () => {
    expect(useTenant.getState().tenantId).toBe('default');
  });

  it('切换租户并持久化', () => {
    useTenant.getState().setTenantId('acme');
    expect(useTenant.getState().tenantId).toBe('acme');
    // 持久化到 localStorage（zustand persist）
    expect(localStorage.getItem('rag-tenant')).toContain('acme');
  });
});
