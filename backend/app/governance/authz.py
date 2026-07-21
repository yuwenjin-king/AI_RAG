"""RBAC 与权限前置过滤（设计书 §2.1 F9 / §6）。

设计原则：权限作为前置过滤条件注入检索请求，而非检索后过滤，避免越权且提效。
首版为"宽放"实现（不做过滤），接口已预留；接入权限规则引擎时实现 resolve。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.tenant import TenantContext


@dataclass
class PermissionFilter:
    """检索前置过滤范围。None 表示不限制。"""

    knowledge_base_ids: Optional[set[int]] = None
    doc_ids: Optional[set[int]] = None


class PermissionResolver:
    """权限解析器：根据用户身份返回可见范围。首版宽放（全可见）。"""

    async def resolve(self, tenant: TenantContext, user: Optional[str] = None) -> PermissionFilter:
        return PermissionFilter(knowledge_base_ids=None, doc_ids=None)


_resolver: PermissionResolver | None = None


def get_resolver() -> PermissionResolver:
    global _resolver
    if _resolver is None:
        _resolver = PermissionResolver()
    return _resolver
