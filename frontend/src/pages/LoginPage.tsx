import { useState } from 'react';
import { App as AntdApp, Button, Card, Form, Input, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/auth';
import { useAuth } from '../stores/auth';
import { useTenant } from '../stores/tenant';

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();
  const setAuth = useAuth((s) => s.setAuth);
  const setTenantId = useTenant((s) => s.setTenantId);
  const { message } = AntdApp.useApp();

  const onFinish = async (v: { username: string; password: string }) => {
    setLoading(true);
    try {
      const r = await login(v.username, v.password);
      setAuth(
        r.access_token,
        {
          // login 响应不含 user_id（非关键字段，后续 /auth/me 可补全）
          user_id: 0,
          username: r.username,
          tenant_id: r.tenant_id,
          role: r.role,
          memberships: r.memberships,
          authenticated: true,
        },
      );
      setTenantId(r.tenant_id); // 默认活动租户 = 归属租户
      nav('/chat', { replace: true });
    } catch (e) {
      message.error((e as Error).message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f5f5',
      }}
    >
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          Enterprise RAG 登录
        </Typography.Title>
        <Form layout="vertical" onFinish={onFinish} initialValues={{ username: 'admin' }}>
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, fontSize: 12, marginBottom: 0 }}>
          首次使用请后端执行 <code>make seed-admin</code>（默认 admin / changeme，生产务必覆盖）。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
