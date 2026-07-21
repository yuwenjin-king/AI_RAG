import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface TenantState {
  tenantId: string;
  setTenantId: (t: string) => void;
}

/** 当前租户（X-Tenant-Id），持久化到 localStorage。 */
export const useTenant = create<TenantState>()(
  persist(
    (set) => ({
      tenantId: 'default',
      setTenantId: (tenantId) => set({ tenantId }),
    }),
    { name: 'rag-tenant' },
  ),
);
