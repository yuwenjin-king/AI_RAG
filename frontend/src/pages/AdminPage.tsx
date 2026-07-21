import { useEffect, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Form,
  Input,
  Select,
  Space,
  Typography,
} from 'antd';
import { KBApi, SceneApi } from '../api/resources';
import type { KnowledgeBase } from '../api/types';

const { Title, Text } = Typography;

export default function AdminPage() {
  const { message } = AntdApp.useApp();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    KBApi.list()
      .then((p) => setKbs(p.items || []))
      .catch(() => setKbs([]));
  }, []);

  async function load(sceneId: string) {
    try {
      const s = await SceneApi.get(sceneId);
      if (s) form.setFieldsValue(s);
      else message.info('场景不存在，将新建');
    } catch (e: any) {
      message.error(e?.message || String(e));
    }
  }

  async function submit() {
    const v = await form.validateFields();
    const parse = (s?: string) => {
      try {
        return s ? JSON.parse(s) : {};
      } catch {
        throw new Error('JSON 解析失败，请检查检索策略/权限规则');
      }
    };
    try {
      await SceneApi.upsert(v.scene_id, {
        scene_id: v.scene_id,
        name: v.name,
        knowledge_base_ids: v.knowledge_base_ids || [],
        retrieval_config: parse(v.retrieval_config),
        prompt_template: v.prompt_template || null,
        model_route: parse(v.model_route),
        permission_rules: parse(v.permission_rules),
        is_active: v.is_active ?? true,
      });
      message.success('已保存');
    } catch (e: any) {
      message.error(e?.message || String(e));
    }
  }

  return (
    <Card>
      <Title level={4}>场景配置（四要素）</Title>
      <Text type="secondary">
        知识库范围 + 检索策略 + Prompt 模板 + 权限规则，配置化接入新场景。
      </Text>

      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 16, maxWidth: 720 }}
        initialValues={{ is_active: true }}
      >
        <Space style={{ width: '100%' }} align="start">
          <Form.Item name="scene_id" label="场景 ID" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="如 product-manual" onBlur={(e) => load(e.target.value)} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input />
          </Form.Item>
        </Space>

        <Form.Item name="knowledge_base_ids" label="知识库范围">
          <Select
            mode="multiple"
            placeholder="选择该场景可见的知识库"
            options={kbs.map((k) => ({ value: k.id, label: k.name }))}
          />
        </Form.Item>

        <Form.Item
          name="retrieval_config"
          label="检索策略（JSON）"
          tooltip='如 {"final_topk":8,"use_rerank":true}'
        >
          <Input.TextArea rows={2} placeholder='{"final_topk": 8}' />
        </Form.Item>

        <Form.Item name="prompt_template" label="Prompt 模板">
          <Input.TextArea rows={4} placeholder="留空使用默认 RAG 模板" />
        </Form.Item>

        <Form.Item name="model_route" label="模型路由（JSON）">
          <Input.TextArea rows={2} placeholder='{"llm": "glm-4-flash"}' />
        </Form.Item>

        <Form.Item name="permission_rules" label="权限规则（JSON）">
          <Input.TextArea rows={2} placeholder='{}' />
        </Form.Item>

        <Button type="primary" onClick={submit}>
          保存配置
        </Button>
      </Form>
    </Card>
  );
}
