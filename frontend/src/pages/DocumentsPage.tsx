import { useEffect, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { DocApi, KBApi } from '../api/resources';
import { BASE } from '../api/client';
import type { DocumentItem, KnowledgeBase } from '../api/types';

const { Title, Text } = Typography;
const { Dragger } = Upload;

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  parsing: 'blue',
  chunking: 'blue',
  embedding: 'blue',
  indexed: 'green',
  failed: 'red',
};

export default function DocumentsPage() {
  const { message } = AntdApp.useApp();
  const [rows, setRows] = useState<DocumentItem[]>([]);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [kbId, setKbId] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);

  async function reload() {
    setLoading(true);
    try {
      const [dp, kp] = await Promise.all([
        DocApi.list({ kbId }),
        KBApi.list(),
      ]);
      setRows(dp.items || []);
      setKbs(kp.items || []);
    } catch (e: any) {
      message.error(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    reload();
    // 轮询索引状态（pending/processing 文档会推进）
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [kbId]);

  // 上传：拿 upload-url → 预签名 PUT 直传或直传接口 → finalize/触发 ingest
  const uploadProps: UploadProps = {
    multiple: true,
    showUploadList: true,
    customRequest: async (opt) => {
      const file = opt.file as File;
      try {
        const u = await DocApi.uploadUrl(file.name, file.type || 'application/octet-stream', kbId);
        if (u.upload_url) {
          // 预签名 PUT 直传对象存储
          const put = await fetch(u.upload_url, { method: 'PUT', body: file });
          if (!put.ok) throw new Error(`对象存储上传失败 ${put.status}`);
          await DocApi.finalize(u.doc_id);
        } else if (u.direct_upload_url) {
          // 直传接口（MinIO 不可用走本地存储兜底）
          await DocApi.directUpload(u.doc_id, file);
        }
        message.success(`${file.name} 已上传，正在解析…`);
        opt.onSuccess?.({}, new XMLHttpRequest());
        reload();
      } catch (e: any) {
        message.error(`${file.name} 上传失败：${e?.message || e}`);
        opt.onError?.(e as any);
      }
    },
  };

  return (
    <Card>
      <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 12 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>
            文档管理
          </Title>
          <Text type="secondary">知识库：</Text>
          <Select
            allowClear
            placeholder="全部"
            style={{ width: 180 }}
            value={kbId}
            onChange={setKbId}
            options={kbs.map((k) => ({ value: k.id, label: k.name }))}
          />
        </Space>
        <Button icon={<ReloadOutlined />} onClick={reload}>
          刷新
        </Button>
      </Space>

      <Dragger {...uploadProps} style={{ marginBottom: 16 }}>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文件上传（支持 PDF / TXT / Markdown / 代码 等）</p>
        <p className="ant-upload-hint">
          上传后自动异步解析 → 分块 → 向量化 → 双写索引（{BASE || '/api'}）
        </p>
      </Dragger>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 80 },
          { title: '标题', dataIndex: 'title' },
          {
            title: '状态',
            dataIndex: 'status',
            width: 120,
            render: (s: string, r) => (
              <Space direction="vertical" size={0}>
                <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>
                {r.error && <Text type="danger" style={{ fontSize: 12 }}>{r.error}</Text>}
              </Space>
            ),
          },
          {
            title: '大小',
            dataIndex: 'size_bytes',
            width: 100,
            render: (n: number) => `${Math.max(1, Math.round(n / 1024))} KB`,
          },
          { title: '类型', dataIndex: 'content_type', width: 160 },
          {
            title: 'chunks',
            width: 80,
            render: (_: any, r) => r.meta?.chunks ?? '-',
          },
        ]}
      />
    </Card>
  );
}
