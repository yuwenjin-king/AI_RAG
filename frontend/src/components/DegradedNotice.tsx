import { Alert, Tag } from 'antd';

/**
 * 降级码 → 友好提示映射（plan_four §4）。
 * level: warn=检索/生成质量受损（mock/不可用/失败）；info=正常增强/缓存（非问题）。
 * 未命中的码原样显示（防御新增码）。
 */
const HINTS: Record<string, { text: string; level: 'warn' | 'info' }> = {
  'embedding.mock': { text: '未配置 Embedding，向量检索为占位（仅跑通链路）', level: 'warn' },
  'vector.unavailable': { text: '向量检索不可用，已降级为关键词召回', level: 'warn' },
  'keyword.unavailable': { text: '关键词检索不可用', level: 'warn' },
  'keyword.empty_fallback': { text: '关键词无命中，已用本地兜底召回', level: 'info' },
  'llm.mock': { text: '未配置 LLM，答案为占位模板', level: 'warn' },
  'llm.stream_failed': { text: '生成失败', level: 'warn' },
  'graph.unavailable': { text: '图召回不可用', level: 'info' },
  'agentic.selfcheck_failed': { text: '答案自检未通过', level: 'warn' },
  'query.rewritten': { text: '查询已改写', level: 'info' },
  'query.expanded': { text: '查询已扩展（多路召回）', level: 'info' },
  'query.cache_hit': { text: '命中查询缓存', level: 'info' },
};

export function degradedHint(code: string): { text: string; level: 'warn' | 'info' } {
  return HINTS[code] ?? { text: code, level: 'info' };
}

/** 把后端 degraded 码列表渲染成分级提示（含 warn→warning，纯 info→info）。 */
export default function DegradedNotice({ codes }: { codes: string[] }) {
  if (!codes || codes.length === 0) return null;
  const items = codes.map(degradedHint);
  const hasWarn = items.some((it) => it.level === 'warn');
  return (
    <Alert
      type={hasWarn ? 'warning' : 'info'}
      showIcon
      style={{ marginTop: 6, padding: '4px 12px', fontSize: 12 }}
      message={
        <span>
          {items.map((it, i) => (
            <Tag key={i} color={it.level === 'warn' ? 'orange' : 'blue'} style={{ marginBottom: 2 }}>
              {it.text}
            </Tag>
          ))}
        </span>
      }
    />
  );
}
