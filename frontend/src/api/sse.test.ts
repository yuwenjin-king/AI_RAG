import { describe, it, expect, vi, beforeEach } from 'vitest';
import { parseBlock, chatStream } from './sse';

describe('parseBlock', () => {
  it('解析 event + JSON data', () => {
    const e = parseBlock('event: token\ndata: {"text":"hi"}');
    expect(e?.event).toBe('token');
    expect(e?.data).toEqual({ text: 'hi' });
  });

  it('多行 data 拼接', () => {
    const e = parseBlock('event: done\ndata: {"a":1\ndata: ,"b":2}');
    expect(e?.data).toEqual({ a: 1, b: 2 });
  });

  it('keepalive 注释行跳过；无 data 返回 null', () => {
    expect(parseBlock(': ping')).toBeNull();
    expect(parseBlock('event: x')).toBeNull();
  });

  it('非 JSON data 原样字符串', () => {
    const e = parseBlock('event: raw\ndata: plain text');
    expect(e?.event).toBe('raw');
    expect(e?.data).toBe('plain text');
  });
});

describe('chatStream', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('逐块解析 SSE 事件序列', async () => {
    const enc = new TextEncoder();
    const chunks = [
      'event: meta\ndata: {"conversation_id": 1}\n\n',
      'event: token\ndata: {"text": "hel"}\n\n',
      'event: token\ndata: {"text": "lo"}\n\n',
      'event: done\ndata: {"answer": "hello"}\n\n',
    ];
    const body = new ReadableStream({
      start(c) {
        chunks.forEach((ck) => c.enqueue(enc.encode(ck)));
        c.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body }));

    const events = [];
    for await (const e of chatStream({ query: 'hi' })) events.push(e);
    expect(events.map((e) => e.event)).toEqual(['meta', 'token', 'token', 'done']);
    expect(events.at(-1)?.data.answer).toBe('hello');
  });

  it('HTTP 失败抛错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'err', body: null }));
    await expect(async () => {
      for await (const _ of chatStream({ query: 'x' })) {
        // drain
      }
    }).rejects.toThrow(/500/);
  });
});
