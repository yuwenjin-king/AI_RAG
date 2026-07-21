"""对话 / 检索 / 生成 schema，含 SSE 事件形状。"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """区域级引用：文档 + 页码 + bbox + 片段。"""

    chunk_id: Optional[int] = None
    doc_id: int
    title: str = ""
    page_no: Optional[int] = None
    bbox: Optional[List[float]] = None
    snippet: str = ""


class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
    scene_id: Optional[str] = None
    top_k: Optional[int] = None
    history: Optional[List[dict]] = None  # [{role, content}]
    stream: bool = True


class RetrieveRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    scene_id: Optional[str] = None
    top_k: int = 8


class RetrievedChunk(BaseModel):
    chunk_id: Optional[int] = None
    doc_id: int
    title: str = ""
    content: str = ""
    page_no: Optional[int] = None
    bbox: Optional[List[float]] = None
    score: float = 0.0
    source: str = ""  # vector | bm25 | fused


class RetrieveResponse(BaseModel):
    query: str
    chunks: List[RetrievedChunk]
    degraded: List[str] = Field(default_factory=list)


class ChatResult(BaseModel):
    """非流式问答结果（流式时拆成 SSE 事件）。"""

    conversation_id: int
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    degraded: List[str] = Field(default_factory=list)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: List[dict] = Field(default_factory=list)
    degraded: List[str] = Field(default_factory=list)


class ConversationOut(BaseModel):
    id: int
    title: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    messages: List[MessageOut] = Field(default_factory=list)
