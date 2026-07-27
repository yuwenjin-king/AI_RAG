"""RBAC 与权限前置过滤（设计书 §2.1 F9 / §6 / §8）。

核心原则（设计书 §6）：权限作为**前置过滤条件**注入检索请求（Milvus 标量过滤、
OpenSearch term、本地 BM25 WHERE），而非检索后过滤——防越权 + 提效。

规则来源（后者覆盖前者）：
  全局策略 settings.rbac_policy(JSON) < 场景 scene.permission_rules < 角色 role 子规则
支持：allow_all / allowed_kb_ids / allowed_doc_ids / denied_doc_ids。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Set

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant import TenantContext

log = get_logger(__name__)


@dataclass
class PermissionFilter:
    """检索前置过滤范围。None 表示不限制。"""

    knowledge_base_ids: Optional[Set[int]] = None
    doc_ids: Optional[Set[int]] = None
    denied_doc_ids: Optional[Set[int]] = None

    @property
    def restricted(self) -> bool:
        return self.knowledge_base_ids is not None or self.doc_ids is not None

    def allows_doc(self, doc_id: int) -> bool:
        if self.denied_doc_ids and doc_id in self.denied_doc_ids:
            return False
        if self.doc_ids is not None and doc_id not in self.doc_ids:
            return False
        return True


def _base_policy() -> dict:
    if not settings.rbac_policy:
        return {}
    try:
        return json.loads(settings.rbac_policy) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("rbac.policy.parse_failed err=%s", e)
        return {}


class PermissionResolver:
    """规则解析器：根据 场景/角色 产出 PermissionFilter。"""

    async def resolve(
        self,
        tenant: TenantContext,
        *,
        user: Optional[str] = None,
        role: Optional[str] = None,
        scene=None,
    ) -> "PermissionFilter":
        if not settings.rbac_enabled:
            return PermissionFilter()

        rules: dict = dict(_base_policy())
        if scene is not None and getattr(scene, "permission_rules", None):
            rules.update(scene.permission_rules or {})
        if role and isinstance(rules.get("roles"), dict):
            rules.update(rules["roles"].get(role, {}) or {})

        kb = rules.get("allowed_kb_ids")
        docs = rules.get("allowed_doc_ids")
        denied = rules.get("denied_doc_ids")
        # 无任何白/黑名单规则时的默认策略（plan_four §1）：
        #   rbac_default_deny=True  → 最小权限：拒绝所有文档（生产推荐）
        #   rbac_default_deny=False → 全可见（旧行为，开发兜底）
        if not kb and not docs and not denied:
            if getattr(settings, "rbac_default_deny", False):
                return PermissionFilter(doc_ids=set())  # 空 doc 集 → allows_doc 恒 False
            return PermissionFilter()

        return PermissionFilter(
            knowledge_base_ids=set(kb) if kb else None,
            doc_ids=set(docs) if docs else None,
            denied_doc_ids=set(denied) if denied else None,
        )


_resolver: Optional[PermissionResolver] = None


def get_resolver() -> PermissionResolver:
    global _resolver
    if _resolver is None:
        _resolver = PermissionResolver()
    return _resolver
