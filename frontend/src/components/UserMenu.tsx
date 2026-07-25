import { Avatar, Dropdown, Space, Tag, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../stores/auth';

const roleColor: Record<string, string> = { admin: 'red', editor: 'blue', viewer: 'default' };

/** 顶栏用户菜单：显示用户名 + 角色标签；下拉登出。仅认证开启且已登录时渲染。 */
export default function UserMenu() {
  const profile = useAuth((s) => s.profile);
  const clear = useAuth((s) => s.clear);
  const nav = useNavigate();
  if (!profile) return null;
  return (
    <Space>
      <Tag color={roleColor[profile.role] || 'default'}>{profile.role}</Tag>
      <Dropdown
        menu={{
          items: [
            {
              key: 'logout',
              label: '登出',
              onClick: () => {
                clear();
                nav('/login', { replace: true });
              },
            },
          ],
        }}
      >
        <Space style={{ cursor: 'pointer' }}>
          <Avatar size="small" style={{ backgroundColor: '#1677ff' }}>
            {(profile.username[0] || '?').toUpperCase()}
          </Avatar>
          <Typography.Text>{profile.username}</Typography.Text>
        </Space>
      </Dropdown>
    </Space>
  );
}
