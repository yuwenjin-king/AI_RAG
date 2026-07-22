"""A/B 变体分配（设计书 §9）。

按 权重 + 确定性哈希 分桶：同一 用户×场景 永远落到同一变体，保证对照可比。
变体定义在 scene.variants：[{name, retrieval_config, weight}]。
"""
from __future__ import annotations

import hashlib
from typing import Optional


def variant_key(tenant_id: str, scene_id: str, user: Optional[str]) -> str:
    return f"{tenant_id}:{scene_id or 'default'}:{user or 'anon'}"


def pick_variant(scene, key: str) -> Optional[dict]:
    """返回选中的变体 dict（含 name/retrieval_config/weight）；无变体返回 None。"""
    variants = [v for v in (getattr(scene, "variants", None) or []) if isinstance(v, dict) and v.get("name")]
    if not variants:
        return None
    weights = [max(0, int(v.get("weight", 1))) for v in variants]
    total = sum(weights) or 1
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % total
    acc = 0
    for v, w in zip(variants, weights):
        acc += w
        if bucket < acc:
            return v
    return variants[-1]
