import { Button, Card, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import type { Citation } from '../api/types';

const { Text, Paragraph } = Typography;

/** 引用卡片：文档名 + 页码 + 片段，点击"查看原文"跳转区域级高亮预览。 */
export default function CitationCard({ c, index }: { c: Citation; index: number }) {
  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space>
          <Tag color="blue">[{index + 1}]</Tag>
          <Text strong>{c.title || `文档 #${c.doc_id}`}</Text>
          {c.page_no != null && <Tag>第 {c.page_no} 页</Tag>}
        </Space>
        <Paragraph style={{ margin: 0, color: '#555' }} ellipsis={{ rows: 3 }}>
          {c.snippet}
        </Paragraph>
        {c.chunk_id != null && c.doc_id != null && (
          <Link to={`/preview/${c.doc_id}/${c.chunk_id}`}>
            <Button type="link" size="small" style={{ padding: 0 }}>
              查看原文（页面 + 区域高亮）→
            </Button>
          </Link>
        )}
      </Space>
    </Card>
  );
}
