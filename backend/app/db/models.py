"""多租户数据模型（PostgreSQL）。

所有业务表带 tenant_id 并在复合唯一约束中包含它，实现租户隔离。
chunk 表冗余 tenant_id 以支持检索前置过滤。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.types import JSONB  # 可移植：PG=JSONB / sqlite=JSON


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- 枚举 ----
class DocumentStatus(str, PyEnum):
    PENDING = "pending"          # 已入库待处理
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"
    LAYOUT_PENDING = "layout_pending"  # 扫描件/无文本层，等待视觉(layout)处理


class Role(str, PyEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ---- 基类 mixin ----
class TimestampMixin:
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantModel(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts()


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, default="")
    # 场景四要素：检索策略 / Prompt 模板 id / 模型路由 / 权限规则
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    prompt_template_id: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_kb_tenant_name"),)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    object_key: Mapped[str] = mapped_column(String(512))  # MinIO key
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.PENDING.value, index=True)
    embedding_status: Mapped[str] = mapped_column(String(32), default="pending")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # 页数、来源、标签等
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)

    __table_args__ = (
        UniqueConstraint("tenant_id", "checksum", name="uq_doc_tenant_checksum"),
        Index("ix_doc_tenant_kb", "tenant_id", "knowledge_base_id"),
    )


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)  # 冗余，检索前置过滤
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parent_chunk_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, default=None)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)  # 文档内顺序
    content: Mapped[str] = mapped_column(Text)
    # 区域级溯源（归一化坐标，兼容不同渲染分辨率）
    page_no: Mapped[Optional[int]] = mapped_column(Integer, default=None, index=True)
    bbox: Mapped[Optional[list]] = mapped_column(JSONB, default=None)  # [x0, y0, x1, y1] 归一化
    # 父子分块：小 chunk 检索，生成时回溯父块
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    vector_id: Mapped[Optional[str]] = mapped_column(String(128), default=None)  # Milvus 主键

    __table_args__ = (Index("ix_chunk_tenant_doc", "tenant_id", "document_id"),)


class ModelConfig(Base, TimestampMixin):
    """可插拔模型配置（LLM / Embedding / Rerank）。"""

    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32))  # llm | embedding | rerank
    name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64), default="openai_compatible")
    model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    api_key_ref: Mapped[Optional[str]] = mapped_column(String(128), default=None)  # 引用环境变量名
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "name", name="uq_model_tenant_kind_name"),
    )


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)  # [{doc_id, page_no, bbox, snippet}]
    degraded: Mapped[list] = mapped_column(JSONB, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # A/B 变体、延迟等


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    rating: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 1 赞 / -1 踩
    comment: Mapped[Optional[str]] = mapped_column(Text, default=None)


class OperationLog(Base):
    """审计日志。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts()


class SceneConfig(Base, TimestampMixin):
    """场景四要素：知识库 + 检索策略 + Prompt 模板 + 权限规则。"""

    __tablename__ = "scene_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scene_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    knowledge_base_ids: Mapped[list] = mapped_column(JSONB, default=list)
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    prompt_template: Mapped[Optional[str]] = mapped_column(Text, default=None)
    model_route: Mapped[dict] = mapped_column(JSONB, default=dict)
    permission_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    variants: Mapped[list] = mapped_column(JSONB, default=list)  # A/B：[{name, retrieval_config, weight}]
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "scene_id", name="uq_scene_tenant_id"),)


class EvalCase(Base, TimestampMixin):
    """离线评估用例：Query + 标准答案/标准引用（设计书 §9）。"""

    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scene_id: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[Optional[str]] = mapped_column(Text, default=None)
    expected_doc_ids: Mapped[list] = mapped_column(JSONB, default=list)  # 相关文档
    expected_page: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    expected_bbox: Mapped[Optional[list]] = mapped_column(JSONB, default=None)  # 归一化 [x0,y0,x1,y1]
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_evalcase_tenant_scene", "tenant_id", "scene_id"),)

