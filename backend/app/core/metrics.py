"""Prometheus 业务指标（设计书 §9 监控告警）。

HTTP 指标由中间件记录；这里聚焦 RAG 业务：检索延迟 / LLM 调用 / ingest / 降级 / 索引写入。
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

# HTTP（由中间件记录）
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP 请求总数", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

# 对话请求
RAG_REQUESTS = Counter(
    "rag_requests_total", "对话问答请求总数", ["tenant"]
)

# 检索延迟（核心 P95 ≤ 300ms 目标）
RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_seconds",
    "纯检索耗时（不含生成）",
    ["tenant"],
    buckets=(0.05, 0.1, 0.15, 0.25, 0.3, 0.5, 1, 2.5, 5, 10),
)

# 端到端对话延迟（含生成，目标 P95 ≤ 3s）
CHAT_LATENCY = Histogram(
    "rag_chat_latency_seconds",
    "端到端对话耗时（含生成）",
    ["tenant"],
    buckets=(0.5, 1, 2, 3, 5, 8, 15, 30, 60),
)

# ingest 处理结果
INGEST_TOTAL = Counter(
    "rag_ingest_total", "文档处理结果", ["tenant", "status"]  # status: indexed | failed
)
CHUNKS_INDEXED = Counter(
    "rag_chunks_indexed_total", "写入索引的 chunk 数", ["tenant"]
)

# LLM 调用
LLM_CALLS = Counter(
    "rag_llm_calls_total", "LLM 调用次数", ["model", "status"]  # status: ok | failed | mock
)

# 降级事件（设计书 §7 降级可观测）
DEGRADED = Counter(
    "rag_degraded_total", "降级事件", ["kind"]
)

# 检索召回量
RECALL_CHUNKS = Histogram(
    "rag_recall_chunks",
    "单次检索返回的 chunk 数",
    buckets=(0, 1, 2, 4, 6, 8, 12, 20, 50),
)

# 视觉解析（版面检测/OCR）
LAYOUT_PROCESSED = Counter(
    "rag_layout_processed_total", "视觉版面/OCR 处理结果", ["tenant", "status"]
)
OCR_CHARS = Counter(
    "rag_ocr_chars_total", "OCR 识别字符数", ["tenant"]
)

# 成本管控（缓存 / 限流 / LLM token）
EMBEDDING_CACHE = Counter("rag_embedding_cache_total", "embedding 缓存命中", ["result"])
QUERY_CACHE = Counter("rag_query_cache_total", "检索结果缓存命中", ["result"])
RATE_LIMITED = Counter("rag_rate_limited_total", "被限流次数", ["tenant", "endpoint"])
LLM_TOKENS = Counter("rag_llm_tokens_total", "LLM token 估算", ["model", "direction"])

# GraphRAG（P2）
GRAPH_UPSERTS = Counter("rag_graph_entities_total", "入图实体数", ["tenant"])
GRAPH_RECALL = Counter("rag_graph_recall_total", "图召回结果", ["result"])
