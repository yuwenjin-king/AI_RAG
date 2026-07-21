"""融合与精排前处理：RRF（Reciprocal Rank Fusion）+ 可选 MMR 多样性（设计书 §4.4.3）。"""
from __future__ import annotations

from typing import Dict, List

from app.core.config import settings


def _key(h: dict) -> str:
    cid = h.get("chunk_id")
    return str(cid) if cid is not None else f"{h.get('doc_id')}:{h.get('content','')[:40]}"


def rrf_fuse(*hit_lists: List[dict], k: int | None = None) -> List[dict]:
    """多路召回 RRF 融合，按 chunk 去重。"""
    k = k or settings.rrf_k
    scores: Dict[str, float] = {}
    best: Dict[str, dict] = {}
    for hits in hit_lists:
        for rank, h in enumerate(hits):
            key = _key(h)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in best:
                best[key] = h
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out: List[dict] = []
    for key, sc in ordered:
        item = dict(best[key])
        item["rrf_score"] = sc
        item["source"] = "fused"
        out.append(item)
    return out


def mmr_select(candidates: List[dict], top_n: int, lambda_: float = 0.7) -> List[dict]:
    """MMR 多样性（基于 content 字符重叠的简化相似度）。首版可选，默认不启用。"""
    if len(candidates) <= top_n:
        return candidates
    selected: List[dict] = []
    pool = list(candidates)
    while pool and len(selected) < top_n:
        best, best_idx, best_score = None, -1, -1e9
        for i, c in enumerate(pool):
            rel = c.get("rrf_score", 0.0)
            div = max(
                (_overlap(c.get("content", ""), s.get("content", "")) for s in selected),
                default=0.0,
            )
            score = lambda_ * rel - (1 - lambda_) * div
            if score > best_score:
                best_score, best, best_idx = score, c, i
        if best is None:
            break
        selected.append(best)
        pool.pop(best_idx)
    return selected


def _overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
