"""内置轻量 BM25（本地兜底用，避免对外部 rank_bm25 的硬依赖）。

仅用于 OpenSearch 不可用时的开发/兜底语料；生产请使用 OpenSearch BM25。
算法：标准 BM25（k1=1.5, b=0.75），输入为已分词的文档/查询。
"""
from __future__ import annotations

import math
from collections import Counter
from typing import List, Sequence


class BM25:
    def __init__(self, corpus: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = list(corpus)
        self.n = len(self.corpus)
        self.doc_len = [len(d) for d in self.corpus]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf: List[Counter] = [Counter(d) for d in self.corpus]
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.idf = {
            t: math.log((self.n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()
        }

    def get_scores(self, query: Sequence[str]) -> List[float]:
        if self.n == 0:
            return []
        q = set(query)
        scores = [0.0] * self.n
        for t in q:
            idf = self.idf.get(t, 0.0)
            if idf == 0.0:
                continue
            for i, c in enumerate(self.tf):
                f = c.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * (self.doc_len[i] / (self.avgdl or 1.0)))
                scores[i] += idf * (f * (self.k1 + 1)) / denom
        return scores
