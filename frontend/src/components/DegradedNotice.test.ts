import { describe, expect, it } from 'vitest';
import { degradedHint } from './DegradedNotice';

describe('degradedHint', () => {
  it('把已知码映射为友好文案 + 级别', () => {
    expect(degradedHint('embedding.mock').level).toBe('warn');
    expect(degradedHint('embedding.mock').text).toContain('Embedding');
    expect(degradedHint('llm.mock').level).toBe('warn');
    expect(degradedHint('vector.unavailable').text).toContain('关键词召回');
  });

  it('增强/缓存类码为 info（非质量受损）', () => {
    expect(degradedHint('query.rewritten').level).toBe('info');
    expect(degradedHint('query.expanded').level).toBe('info');
    expect(degradedHint('query.cache_hit').level).toBe('info');
  });

  it('未知码原样返回，级别 info（防御新增码不崩）', () => {
    const h = degradedHint('something.new.unmapped');
    expect(h.text).toBe('something.new.unmapped');
    expect(h.level).toBe('info');
  });
});
