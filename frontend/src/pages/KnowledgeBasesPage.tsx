import { useEffect, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { KBApi } from '../api/resources';
import type { KnowledgeBase } from '../api/types';

const { Title } = Typography;

export default function KnowledgeBasesPage() {
  const { message } = AntdApp.useApp();
  const [rows, setRows] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  async function reload() {
    setLoading(true);
    try {
      const p = await KBApi.list();
      setRows(p.items || []);
    } catch (e: any) {
      message.error(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    reload();
  }, []);

  async function submit() {
    const v = await form.validateFields();
    await KBApi.create({ name: v.name, description: v.description || '' });
    message.success('已创建');
    setOpen(false);
    form.resetFields();
    reload();
  }

  async function remove(id: number) {
    await KBApi.remove(id);
    message.success('已删除');
    reload();
  }

  return (
    <Card>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          知识库管理
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          新建知识库
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 80 },
          { title: '名称', dataIndex: 'name' },
          { title: '描述', dataIndex: 'description' },
          {
            title: '操作',
            render: (_, r) => (
              <Popconfirm title="确认删除？" onConfirm={() => remove(r.id)}>
                <Button danger size="small">
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]}
      />
      <Modal
        title="新建知识库"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如：产品手册库" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
