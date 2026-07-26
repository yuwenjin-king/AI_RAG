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
    role_header: str = "X-Role"
    # RBAC（设计书 §6/§8）。policy 为 JSON 字符串；场景/角色规则可在运行时覆盖
    rbac_enabled: bool = True
    rbac_policy: str = ""

    # 认证授权（plan_three §1）。auth_enabled=false 时退回 X-Tenant-Id/X-Role 旧行为
    # （本地开发与离线测试无密码即可跑）；true 时强制 JWT，租户取自令牌而非可伪造头。
    auth_enabled: bool = False
    jwt_secret: str = "dev-secret-change-me"        # 生产务必经环境变量覆盖
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    # 首次 seed 管理员（仅 seed 脚本读取；生产务必经环境变量覆盖）
    seed_admin_username: str = "admin"
    seed_admin_password: str = "changeme"

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
    # HNSW 索引参数（设计书 §4.3 召回率/延迟权衡）
    hnsw_m: int = 16
    hnsw_ef_construction: int = 256
    hnsw_ef_search: int = 128

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

    # GraphRAG（设计书 §4.3/§4.4，P2）
    graph_enabled: bool = False                  # 图召回总开关
    graph_extraction: str = "auto"               # auto | llm | heuristic
    neo4j_url: str = ""                          # 为空 → 用内存图兜底
    neo4j_user: str = ""
    neo4j_password: str = ""
    graph_recall_topk: int = 30

    # CDC（设计书 §4.1，P2）
    kafka_cdc_topic: str = "rag.cdc"
    kafka_cdc_group: str = "rag-cdc-worker"

    # 检索参数
    retrieval_vector_topk: int = 50
    retrieval_keyword_topk: int = 50
    retrieval_final_topk: int = 8
    rrf_k: int = 60

    # 成本管控（缓存 / 限流）
    embedding_cache_enabled: bool = True
    embedding_cache_ttl: int = 86400
    query_cache_enabled: bool = True
    query_cache_ttl: int = 60
    rate_limit_chat_per_min: int = 60     # 0 = 不限流

    # 安全合规（设计书 §8）
    pii_masking_enabled: bool = False                 # 接入阶段 PII 脱敏
    pii_rules: str = "phone,email,idcard,bank"        # 启用的规则（逗号分隔）

    # 分块（父子 Small-to-Big / 查询理解）
    chunk_parent_child: bool = True
    chunk_parent_size: int = 1500
    chunk_child_size: int = 400
    chunk_overlap: int = 80
    query_rewrite_enabled: bool = True     # 多轮指代消解（需 LLM）
    query_expansion_enabled: bool = True   # 查询扩展（子查询多路召回）
    query_rewrite_cache_ttl: int = 3600

    # Agentic RAG（plan_three §2）：检索充分性评估 + 迭代召回 + 答案自检
    agentic_enabled: bool = False            # 总开关：关闭则走单次 retrieve→generate
    agentic_max_iterations: int = 2          # 迭代轮数上限（含首次检索）
    agentic_sufficient_topk: int = 3         # 启发式充分性：达此 chunk 数视为证据充分
    agentic_selfcheck_enabled: bool = True   # 生成后答案 faithfulness 自检

    # OpenTelemetry 分布式追踪（plan_three §3）。未装 opentelemetry → 自动降级为 no-op
    otel_enabled: bool = False
    otel_exporter: str = "console"        # console | otlp
    otel_endpoint: str = "http://localhost:4318/v1/traces"  # OTLP/HTTP（otlp 模式）
    otel_service_name: str = "enterprise-rag"

    # 韧性（plan_three §5）：外部调用重试 + 熔断 + DB 连接池
    retry_attempts: int = 3               # 外部调用（LLM/embedding）瞬时错误重试次数
    retry_multiplier: float = 0.5         # 指数退避基数
    retry_max_wait: float = 4.0           # 单次重试最大等待
    circuit_failure_threshold: int = 5    # 连续失败 N 次开路
    circuit_cooldown: float = 30.0        # 开路后冷却秒数（过后半开试探）
    circuit_success_threshold: int = 1    # 半开态连续成功 N 次恢复闭合
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    db_pool_timeout: float = 30.0
    db_slow_query_seconds: float = 5.0    # 慢查询阈值（0=关闭日志）

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
