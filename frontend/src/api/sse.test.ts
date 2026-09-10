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

  it('CRLF 行尾（sse-starlette 等实现）', () => {
    const e = parseBlock('event: token\r\ndata: {"text":"hi"}');
    expect(e?.event).toBe('token');
    expect(e?.data).toEqual({ text: 'hi' });
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

  it('CRLF 事件流解析（含跨 chunk 半截分隔符）', async () => {
    const enc = new TextEncoder();
    // 服务端以 \r\n\r\n 分隔（SSE 规范允许），且一处分隔符被 chunk 边界劈开
    const chunks = [
      'event: meta\r\ndata: {"conversation_id": 1}\r\n\r',
      '\n',
      'event: citations\r\ndata: [{"chunk_id": 9}]\r\n\r\n',
      'event: done\r\ndata: {"answer": "ok"}\r\n\r\n',
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
    expect(events.map((e) => e.event)).toEqual(['meta', 'citations', 'done']);
    expect(events.at(-1)?.data.answer).toBe('ok');
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
