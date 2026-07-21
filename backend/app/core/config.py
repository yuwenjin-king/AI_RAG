"""集中配置：所有 infra URL / 开关 / 模型参数，从环境变量读取。"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # 应用
    app_name: str = "enterprise-rag"
    env: str = "dev"
    log_level: str = "INFO"
    default_tenant_id: str = "default"
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])
    tenant_header: str = "X-Tenant-Id"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: str = "ragpass"
    postgres_db: str = "rag"
    database_url: str = ""

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_enabled: bool = True
    embedding_dim: int = 1024
    # 大租户独立 collection（否则共享 + tenant_id 过滤）
    collection_per_tenant: bool = False

    # OpenSearch
    opensearch_url: str = "http://localhost:9200"
    opensearch_user: str = ""
    opensearch_password: str = ""
    opensearch_enabled: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    # Kafka
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_ingest_topic: str = "rag.ingest"
    kafka_layout_topic: str = "rag.layout"
    kafka_consumer_group: str = "rag-ingest-worker"
    kafka_layout_group: str = "rag-layout-worker"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-documents"
    minio_secure: bool = False
    # MinIO 不可用时的本地存储兜底（开发/测试空跑）
    local_store_dir: str = "/tmp/rag_uploads"
    # Kafka 不可用时，上传 API 同步触发 ingest（保证最小可跑通）
    sync_ingest_fallback: bool = True

    # LLM（生成）
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    llm_timeout: int = 60

    # Embedding（向量化）
    embedding_api_key: str = ""
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_model: str = "embedding-3"
    # provider: auto(有 key→openai兼容, 无→mock) | openai_compatible | sentence_transformers | mock
    embedding_provider: str = "auto"
    embedding_local_model: str = "BAAI/bge-small-zh-v1.5"  # sentence_transformers 模型名

    # Rerank（可选）
    rerank_api_key: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""

    # PDF 视觉解析（设计书 §4.2.2）
    vision_enabled: bool = False                 # 总开关：关闭则扫描件/复杂件纯文本兜底
    pdf_layout_detector: str = "auto"            # auto | pymupdf | yolo
    yolo_model_path: str = ""                    # DocLayout-YOLO 权重路径（yolo 模式必填）
    ocr_engine: str = "none"                     # none | paddle

    # 检索参数
    retrieval_vector_topk: int = 50
    retrieval_keyword_topk: int = 50
    retrieval_final_topk: int = 8
    rrf_k: int = 60

    # 分块（父子 Small-to-Big / 查询理解）
    chunk_parent_child: bool = True
    chunk_parent_size: int = 1500
    chunk_child_size: int = 400
    chunk_overlap: int = 80
    query_rewrite_enabled: bool = True     # 多轮指代消解（需 LLM）
    query_expansion_enabled: bool = True   # 查询扩展（子查询多路召回）
    query_rewrite_cache_ttl: int = 3600

    @field_validator("database_url", mode="before")
    @classmethod
    def _build_db_url(cls, v, info):
        if v:
            return v
        d = info.data
        return (
            f"postgresql+asyncpg://{d.get('postgres_user', 'rag')}:"
            f"{d.get('postgres_password', 'ragpass')}@{d.get('postgres_host', 'localhost')}:"
            f"{d.get('postgres_port', 5432)}/{d.get('postgres_db', 'rag')}"
        )

    @property
    def collection_name(self) -> str:
        """共享 collection 名（collection_per_tenant=False 时使用）。"""
        return "rag_chunks"

    def tenant_collection(self, tenant_id: str) -> str:
        return f"rag_chunks__{_safe(tenant_id)}"

    def tenant_index(self, tenant_id: str) -> str:
        return f"rag-chunks-{_safe(tenant_id)}"


def _safe(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "default"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
