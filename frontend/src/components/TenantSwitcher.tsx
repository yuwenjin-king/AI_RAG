import { Input, Space, Typography } from 'antd';
import { useTenant } from '../stores/tenant';

const { Text } = Typography;

/** 租户切换器：当前请求头 X-Tenant-Id 即此值，切换后所有数据按租户隔离。 */
export default function TenantSwitcher() {
  const tenantId = useTenant((s) => s.tenantId);
  const setTenantId = useTenant((s) => s.setTenantId);
  return (
    <Space>
      <Text type="secondary">租户：</Text>
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
