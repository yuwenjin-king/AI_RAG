"""通用 schema：分页、时间戳、标准响应。"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int = 1
    page_size: int = 20


class Timestamps(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LocateOut(BaseModel):
    """区域级溯源定位：chunk -> 页码 + bbox + 文档预览地址。"""

    chunk_id: int
    doc_id: int
    title: str
    page_no: Optional[int] = None
    bbox: Optional[List[float]] = None
    preview_url: Optional[str] = None
