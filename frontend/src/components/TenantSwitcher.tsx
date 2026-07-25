import { Input, Select, Space, Typography } from 'antd';
import { useTenant } from '../stores/tenant';
import { useAuth } from '../stores/auth';

/**
 * 租户切换器：当前请求头 X-Tenant-Id 即此值，切换后所有数据按租户隔离。
 * - 已登录（authed）：只能在用户所属租户间切换（后端强制成员校验，非成员 403）。
 * - 匿名（认证未开启）：自由输入（旧行为）。
 */
export default function TenantSwitcher() {
  const tenantId = useTenant((s) => s.tenantId);
  const setTenantId = useTenant((s) => s.setTenantId);
  const profile = useAuth((s) => s.profile);
  const status = useAuth((s) => s.status);

  if (status === 'authed' && profile) {
    const tenants = Object.keys(profile.memberships || {});
    return (
      <Space>
        <Typography.Text type="secondary">租户：</Typography.Text>
        <Select
          size="small"
          style={{ width: 160 }}
          value={tenantId}
          onChange={setTenantId}
          options={tenants.map((t) => ({ value: t, label: t }))}
        />
      </Space>
    );
  }

  return (
    <Space>
      <Typography.Text type="secondary">租户：</Typography.Text>
      <Input
        size="small"
        style={{ width: 160 }}
        value={tenantId}
        onChange={(e) => setTenantId(e.target.value)}
        placeholder="如 default"
      />
    </Space>
  );
}
