"""LLM 网关（设计书 §4.5）：多模型路由 / 降级 / 限流 / SSE 流式。

- 有 LLM_API_KEY：OpenAI 兼容接口（GLM/Qwen/DeepSeek/OpenAI/Anthropic 兼容网关）
- 无 key：MockLLM —— 基于检索结果生成模板化答案（确定性，不调用外部）
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.chat import RetrievedChunk

log = get_logger(__name__)


class LLMGateway(ABC):
    is_mock: bool = False

    @abstractmethod
    async def stream(self, messages: List[dict]) -> AsyncIterator[str]:
        ...

    async def complete(self, messages: List[dict]) -> str:
        """非流式补全（查询改写/扩展等短任务用）。默认实现：聚合 stream。"""
        parts: List[str] = []
        async for tok in self.stream(messages):
            parts.append(tok)
        return "".join(parts)


class OpenAICompatibleLLM(LLMGateway):
    is_mock = False

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def stream(self, messages: List[dict]) -> AsyncIterator[str]:
        from app.core.resilience import get_breaker

        breaker = get_breaker("llm")
        await breaker.check()  # 开路则快速失败（rag 已 try/except 降级）
        payload = {"model": self.model, "messages": messages, "stream": True, "temperature": 0.3}
        timeout = httpx.Timeout(self.timeout, connect=10)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = obj.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {}).get("content")
                            if delta:
                                yield delta
            await breaker.record_success()
        except Exception:
            await breaker.record_failure()
            raise

    async def complete(self, messages: List[dict]) -> str:
        """非流式补全（查询改写/扩展等短任务用）；熔断 + 重试保护。"""
        from app.core.resilience import get_breaker, retry_external

        @retry_external
        async def _call() -> str:
            payload = {"model": self.model, "messages": messages, "temperature": 0.0, "max_tokens": 512}
            timeout = httpx.Timeout(self.timeout, connect=10)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {}) or {}
                from app.core.metrics import LLM_TOKENS

                LLM_TOKENS.labels(model=self.model, direction="prompt").inc(usage.get("prompt_tokens", 0))
                LLM_TOKENS.labels(model=self.model, direction="completion").inc(usage.get("completion_tokens", 0))
                choices = data.get("choices", [])
                return choices[0]["message"]["content"].strip() if choices else ""

        return await get_breaker("llm").call(_call)


class MockLLM(LLMGateway):
    """基于检索结果的模板化答案（无 key 时降级）。"""

    is_mock = True

    def __init__(self, chunks: Optional[List[RetrievedChunk]] = None):
        self.chunks = chunks or []

    async def stream(self, messages: List[dict]) -> AsyncIterator[str]:
        answer = self._compose()
        # 模拟逐 token 输出（按字符），便于前端打字机效果
        for ch in answer:
            await asyncio.sleep(0.005)
            yield ch

    def _compose(self) -> str:
        if not self.chunks:
            return "（未检索到相关信息：当前为降级 mock 模式，未配置 LLM_API_KEY。请在 .env 配置后获得真实回答。）"
        lines = ["根据检索到的资料："]
        for i, c in enumerate(self.chunks[:5], start=1):
            loc = f"，第{c.page_no}页" if c.page_no else ""
            lines.append(f"[{i}] 《{c.title}》{loc}：{c.content[:120].strip()}…")
        lines.append("")
        lines.append("（注：当前为降级 mock 模式，未配置 LLM_API_KEY，以上为检索结果直引；配置后将由大模型生成综合回答。）")
        return "\n".join(lines)


_llm: Optional[LLMGateway] = None


def get_llm(chunks: Optional[List[RetrievedChunk]] = None) -> LLMGateway:
    """获取 LLM。真实模型为单例；Mock 每次带 chunks 构造（用于引用）。"""
    global _llm
    if settings.llm_api_key:
        if _llm is None or _llm.is_mock:
            _llm = OpenAICompatibleLLM(
                settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout
            )
        return _llm
    # 无 key → mock（不缓存，因 chunks 不同）
    return MockLLM(chunks=chunks)


def reset_llm() -> None:
    global _llm
    _llm = None
