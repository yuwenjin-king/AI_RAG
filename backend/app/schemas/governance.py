"""模型配置 / 场景 / 反馈 schema。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMBase, Timestamps


class ModelConfigOut(ORMBase, Timestamps):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    tenant_id: str
    kind: str
    name: str
    provider: str
    model: str
    base_url: Optional[str] = None
    is_default: bool = False
    params: dict = Field(default_factory=dict)


class ModelConfigCreate(BaseModel):
    kind: str  # llm | embedding | rerank
    name: str
    provider: str = "openai_compatible"
    model: str
    base_url: Optional[str] = None
    api_key_ref: Optional[str] = None
    params: dict = Field(default_factory=dict)
    is_default: bool = False


class SceneConfigOut(ORMBase, Timestamps):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    tenant_id: str
    scene_id: str
    name: str
    knowledge_base_ids: List[int] = Field(default_factory=list)
    retrieval_config: dict = Field(default_factory=dict)
    prompt_template: Optional[str] = None
    model_route: dict = Field(default_factory=dict)
    permission_rules: dict = Field(default_factory=dict)
    is_active: bool = True


class SceneConfigCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scene_id: str
    name: str
    knowledge_base_ids: List[int] = Field(default_factory=list)
    retrieval_config: dict = Field(default_factory=dict)
    prompt_template: Optional[str] = None
    model_route: dict = Field(default_factory=dict)
    permission_rules: dict = Field(default_factory=dict)
    is_active: bool = True


class FeedbackCreate(BaseModel):
    message_id: Optional[int] = None
    rating: Optional[int] = None  # 1 / -1
    comment: Optional[str] = None


class FeedbackOut(ORMBase):
    id: int
    message_id: Optional[int] = None
    rating: Optional[int] = None
    comment: Optional[str] = None
