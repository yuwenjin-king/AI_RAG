import { useEffect, useRef, useState } from 'react';
import { Button, Select, Space, Spin, Typography, App as AntdApp } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { chatStream } from '../api/sse';
import { KBApi } from '../api/resources';
import type { ChatMessage, Citation, KnowledgeBase } from '../api/types';
import CitationCard from '../components/CitationCard';

const { Text, Paragraph } = Typography;

export default function ChatPage() {
  const { message } = AntdApp.useApp();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [kbId, setKbId] = useState<number | undefined>();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    KBApi.list()
      .then((p) => setKbs(p.items || []))
      .catch(() => setKbs([]));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  async function send() {
    const query = input.trim();
    if (!query || loading) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', content: query }]);
    setLoading(true);

    // 占位一条 assistant 消息，流式追加
    const placeholderIdx = messages.length + 1;
    setMessages((m) => [
      ...m,
      { role: 'assistant', content: '', citations: [], degraded: [] },
    ]);

    try {
      let acc = '';
      let citations: Citation[] = [];
      let degraded: string[] = [];
      for await (const evt of chatStream({
        query,
        conversation_id: conversationId,
        knowledge_base_id: kbId,
      })) {
        if (evt.event === 'meta') {
          setConversationId(evt.data?.conversation_id);
        } else if (evt.event === 'citations') {
          citations = evt.data || [];
        } else if (evt.event === 'token') {
          acc += evt.data?.text || '';
          setMessages((m) => {
            const copy = [...m];
            copy[placeholderIdx] = { ...copy[placeholderIdx], content: acc };
            return copy;
          });
        } else if (evt.event === 'done') {
          acc = evt.data?.answer ?? acc;
          degraded = evt.data?.degraded || [];
          setMessages((m) => {
            const copy = [...m];
            copy[placeholderIdx] = {
              ...copy[placeholderIdx],
              content: acc || '（空）',
              citations,
              degraded,
            };
            return copy;
          });
        }
      }
    } catch (e: any) {
      setMessages((m) => {
        const copy = [...m];
        copy[placeholderIdx] = {
          ...copy[placeholderIdx],
          content: `请求失败：${e?.message || e}`,
          degraded: ['llm.stream_failed'],
        };
        return copy;
      });
      message.error(`请求失败：${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)' }}>
      <Space style={{ marginBottom: 12 }}>
        <Text type="secondary">知识库：</Text>
        <Select
          allowClear
          placeholder="全部知识库"
          style={{ width: 220 }}
          value={kbId}
          onChange={setKbId}
          options={kbs.map((k) => ({ value: k.id, label: k.name }))}
        />
      </Space>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          background: '#fff',
          padding: 16,
          borderRadius: 8,
        }}
      >
        {messages.length === 0 && (
          <Text type="secondary">
            提一个问题开始对话。答案会带区域级引用，点击引用可定位原文页 + 高亮区域。
          </Text>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              marginBottom: 16,
              textAlign: m.role === 'user' ? 'right' : 'left',
            }}
          >
            <div
              style={{
                display: 'inline-block',
                maxWidth: '80%',
                textAlign: 'left',
                background: m.role === 'user' ? '#e6f4ff' : '#f6ffed',
                padding: '8px 12px',
                borderRadius: 8,
                whiteSpace: 'pre-wrap',
              }}
            >
              {m.content}
              {loading && i === messages.length - 1 && m.role === 'assistant' && (
                <Spin size="small" style={{ marginLeft: 6 }} />
              )}
            </div>
            {m.role === 'assistant' && m.citations && m.citations.length > 0 && (
              <div style={{ marginTop: 8, textAlign: 'left' }}>
                <Text type="secondary">引用来源：</Text>
                {m.citations.map((c, ci) => (
                  <CitationCard key={ci} c={c} index={ci} />
                ))}
              </div>
            )}
            {m.role === 'assistant' && m.degraded && m.degraded.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  降级：{m.degraded.join(', ')}
                </Text>
              </div>
            )}
          </div>
        ))}
      </div>

      <Space.Compact style={{ marginTop: 12 }}>
        <input
          style={{
            flex: 1,
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #d9d9d9',
          }}
          placeholder="输入问题，回车发送"
          value={input}
          disabled={loading}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={send}>
          发送
        </Button>
      </Space.Compact>
    </div>
  );
}
