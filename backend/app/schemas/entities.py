"""租户 / 知识库 / 文档 schema。"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase, Timestamps


# ---- 租户 ----
class TenantOut(ORMBase):
    id: int
    tenant_id: str
    name: str
    settings: dict = Field(default_factory=dict)


class TenantUpsert(BaseModel):
    tenant_id: str
    name: str
    settings: dict = Field(default_factory=dict)


# ---- 知识库 ----
class KnowledgeBaseOut(ORMBase, Timestamps):
    id: int
    tenant_id: str
    name: str
    description: Optional[str] = ""
    retrieval_config: dict = Field(default_factory=dict)
    prompt_template_id: Optional[str] = None
    is_active: bool = True


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = ""
    retrieval_config: dict = Field(default_factory=dict)
    prompt_template_id: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    retrieval_config: Optional[dict] = None
    prompt_template_id: Optional[str] = None
    is_active: Optional[bool] = None


# ---- 文档 ----
class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    knowledge_base_id: Optional[int] = None


class UploadUrlResponse(BaseModel):
    doc_id: int
    object_key: str
    upload_url: Optional[str] = None
    # 当对象存储不可用时，提供直接上传入口
    direct_upload_url: Optional[str] = None


class DocumentOut(ORMBase, Timestamps):
    id: int
    tenant_id: str
    knowledge_base_id: Optional[int] = None
    title: str
    content_type: str
    size_bytes: int
    status: str
    embedding_status: str
    error: Optional[str] = None
    meta: dict = Field(default_factory=dict)


class DocumentListFilter(BaseModel):
    knowledge_base_id: Optional[int] = None
    status: Optional[str] = None
    page: int = 1
    page_size: int = 20
