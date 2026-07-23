"""认证相关请求/响应模型。"""
from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    tenant_id: str
    role: str
    memberships: Dict[str, str] = Field(default_factory=dict)
