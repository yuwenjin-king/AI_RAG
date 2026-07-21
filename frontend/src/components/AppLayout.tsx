import { Layout, Menu, Space, Typography } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import TenantSwitcher from './TenantSwitcher';

const { Header, Sider, Content } = Layout;
const { Title } = Typography;

const items = [
  { key: '/chat', label: '对话问答' },
  { key: '/knowledge-bases', label: '知识库' },
  { key: '/documents', label: '文档管理' },
  { key: '/admin', label: '场景配置' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = '/' + (location.pathname.split('/')[1] || 'chat');
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider breakpoint="lg" collapsedWidth={0} theme="light">
        <div style={{ padding: '16px 20px' }}>
          <Title level={4} style={{ margin: 0 }}>
            Enterprise RAG
          </Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 16px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <Space>
            <TenantSwitcher />
          </Space>
        </Header>
        <Content style={{ padding: 24, background: '#f5f5f5' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
