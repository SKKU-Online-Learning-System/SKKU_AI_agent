from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_SECRETS = frozenset(
    {
        "local-dev-change-me",
        "replace-with-a-long-random-secret",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    database_url: str = "postgresql+psycopg://course_agent:course_agent@localhost:5432/course_agent"
    qwen_api_key: Optional[str] = None
    jwt_secret: str = "local-dev-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_in: int = Field(default=3600, gt=0)

    vector_db_provider: Literal["pgvector", "local"] = "pgvector"
    vector_db_url: Optional[str] = None
    vector_db_collection: str = "course_document_chunks"
    vector_db_embedding_dim: int = 1536

    backend_cors_origins: str = Field(default="http://localhost:3000")
    upload_dir: str = "uploads"
    max_upload_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_upload_request_size_bytes: int = Field(default=21 * 1024 * 1024, gt=0)

    # Document processing and retrieval.
    mock_embedding_dim: int = Field(default=512, gt=0)
    embedding_max_chars: int = Field(default=8000, gt=0)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    min_chunk_chars: int = Field(default=40, ge=0)
    vector_search_mode: Literal["local", "pgvector"] = "local"
    rag_top_k: int = Field(default=5, gt=0)
    rag_max_top_k: int = Field(default=20, gt=0)
    # Tuned for the mock embedding provider; raise it (around 0.3) for real models.
    rag_score_threshold: float = Field(default=0.1, ge=0.0, le=1.0)

    # Answer generation.
    qwen_model: str = "qwen3.8-27b"
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_enable_thinking: bool = False
    # Kept separately configurable for deployments that route search traffic,
    # but defaults to the same Qwen3.8 model as all other text-agent calls.
    qwen_web_search_model: str = "qwen3.8-27b"
    qwen_dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/api/v1"
    use_mock_llm: bool = True
    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=1024, gt=0)
    max_question_length: int = Field(default=2000, gt=0)
    max_context_chars: int = Field(default=12000, gt=0)
    seed_password: Optional[str] = None

    # COURSE AGENT. Text answers use qwen_model/use_mock_llm above; only the
    # realtime speech-to-speech leg needs xAI, and without xai_api_key the voice
    # button renders in "not configured" mode while text chat keeps working.
    xai_api_key: Optional[str] = None
    xai_realtime_url: str = "wss://api.x.ai/v1/realtime"
    xai_connect_timeout_seconds: float = Field(default=20.0, gt=0)
    xai_connect_attempts: int = Field(default=2, ge=1, le=5)
    xai_connect_retry_delay_seconds: float = Field(default=0.75, ge=0, le=10)
    visual_router_timeout_seconds: float = Field(default=3.0, gt=0, le=15)
    grok_voice_model: str = "grok-voice-latest"
    grok_voice: str = "eve"
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    silence_ms: int = Field(default=900, gt=0)
    prefix_ms: int = Field(default=300, gt=0)
    min_speech_ms: int = Field(default=250, gt=0)
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)

    # Weak-concept memory. Optional: falls back to a local JSON file.
    moss_project_id: Optional[str] = None
    moss_project_key: Optional[str] = None
    moss_memory_index: str = "course-agent-weak-concepts"
    moss_memory_model: str = "moss-minilm"
    moss_sync_debounce_seconds: float = Field(default=0.75, ge=0.0)
    moss_local_fallback_file: Optional[str] = None

    @property
    def is_voice_configured(self) -> bool:
        return bool((self.xai_api_key or "").strip())

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @model_validator(mode="after")
    def validate_top_k_bounds(self) -> "Settings":
        if self.rag_top_k > self.rag_max_top_k:
            raise ValueError("RAG_TOP_K must not exceed RAG_MAX_TOP_K")
        return self

    @model_validator(mode="after")
    def validate_nonlocal_jwt_secret(self) -> "Settings":
        if self.app_env != "local" and (
            self.jwt_secret in INSECURE_JWT_SECRETS or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "JWT_SECRET must be a unique secret of at least 32 characters "
                "when APP_ENV is not local"
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.backend_cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def resolved_vector_db_url(self) -> str:
        return self.vector_db_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
