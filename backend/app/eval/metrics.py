"""检索/引用评估指标（设计书 §9）。

纯函数，便于离线评估集回归与单测。
- 检索层：Recall@K、MRR、NDCG（二值相关性）
- 引用层：引用准确率（cited ∩ relevant / cited）
- 溯源层：bbox IoU + 命中率（专项指标，评估区域级定位质量）
- 生成层：faithfulness（答案被检索上下文支撑的比例，规则化）+ token_overlap（答案-金标重叠）
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence


def _to_set(ids: Iterable) -> set:
    return {i for i in ids if i is not None}


def recall_at_k(retrieved: Sequence, relevant: Iterable, k: int) -> float:
    rel = _to_set(relevant)
    if not rel or k <= 0:
        return 0.0
    topk = [i for i in retrieved[:k] if i is not None]
    if not topk:
        return 0.0
    hit = len(set(topk) & rel)
    return hit / len(rel)


def mrr(retrieved: Sequence, relevant: Iterable) -> float:
    rel = _to_set(relevant)
    for rank, rid in enumerate(retrieved, start=1):
        if rid in rel:
            return 1.0 / rank
    return 0.0


def ndcg(retrieved: Sequence, relevant: Iterable, k: int) -> float:
    rel = _to_set(relevant)
    if not rel or k <= 0:
        return 0.0
    topk = [i for i in retrieved[:k] if i is not None]

    def dcg(items: Sequence) -> float:
        return sum((1.0 if items[i] in rel else 0.0) / math.log2(i + 2) for i in range(len(items)))

    idcg_n = min(len(rel), len(topk))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(idcg_n))
    if idcg == 0:
        return 0.0
    return dcg(topk) / idcg


def citation_accuracy(cited: Iterable, relevant: Iterable) -> float:
    """被引用文档中，命中相关文档的比例（引用精确率）。"""
    cited_set = _to_set(cited)
    rel = _to_set(relevant)
    if not cited_set:
        return 0.0
    return len(cited_set & rel) / len(cited_set)


def bbox_iou(a: Optional[Sequence[float]], b: Optional[Sequence[float]]) -> float:
    """两个归一化 bbox [x0,y0,x1,y1] 的交并比；缺任一返回 0。"""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = a[:4]
    bx0, by0, bx1, by1 = b[:4]
    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)
    iw = max(0.0, inter_x1 - inter_x0)
    ih = max(0.0, inter_y1 - inter_y0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def bbox_accuracy(pred: Optional[Sequence[float]], gt: Optional[Sequence[float]], *, threshold: float = 0.5) -> float:
    """bbox 命中：IoU ≥ threshold 记 1，否则 0；缺预测/真值返回 0。"""
    return 1.0 if bbox_iou(pred, gt) >= threshold else 0.0


def aggregate(per_case: List[dict], keys: Iterable[str]) -> dict:
    """对每例指标字典按 key 取均值。"""
    out = {}
    keys = list(keys)
    for key in keys:
        vals = [c.get(key) for c in per_case if isinstance(c.get(key), (int, float))]
        out[key] = (sum(vals) / len(vals)) if vals else 0.0
    out["n_cases"] = len(per_case)
    return out


# ===== 生成层（设计书 §9，plan_four §2） =====

def _ngrams(text: str, n: int = 1) -> List[str]:
    """空白分词后取 n-gram（小写）。与离线 BM25 的 split() 分词一致。"""
    toks = (text or "").lower().split()
    if n <= 1 or len(toks) < n:
        return toks
    return [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def token_overlap(answer: str, gold: str) -> float:
    """答案-金标重叠率：答案 unigram 中（含重复）出现在金标里的比例（0~1）。

    用于无 LLM judge 时近似答案相关性；完全跑题→0，命中关键词→高。
    """
    ans = _ngrams(answer, 1)
    if not ans:
        return 0.0
    g = set(_ngrams(gold, 1))
    if not g:
        return 0.0
    return sum(1 for t in ans if t in g) / len(ans)


def faithfulness(answer: str, contexts: Iterable[str], n: int = 1) -> float:
    """规则化忠实度：答案 n-gram 中（含重复）被检索上下文并集覆盖的比例（0~1）。

    高→答案有据（低幻觉）；低→答案引入了上下文之外的内容。
    n=1 即词级覆盖；n=2 对短语更严格。离线无 LLM judge 时的近似指标，
    真实评估可叠加 LLM judge（plan_four §3 真实环境）。
    """
    ans = _ngrams(answer, n)
    if not ans:
        return 0.0
    ctx: set = set()
    for c in contexts:
        ctx.update(_ngrams(c, n))
    if not ctx:
        return 0.0
    return sum(1 for t in ans if t in ctx) / len(ans)
