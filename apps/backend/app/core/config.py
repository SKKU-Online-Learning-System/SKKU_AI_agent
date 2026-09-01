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

    # Document processing and retrieval. This migration intentionally keeps the
    # embedding/RAG provider unchanged.
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

    # Provider-neutral answer generation. USE_MOCK_LLM is retained as a
    # backwards-compatible override for the deterministic test/development mode.
    llm_provider: Literal["mock", "anthropic", "local_qwen"] = "local_qwen"
    use_mock_llm: bool = False
    text_llm_base_url: str = "http://localhost:8001/v1"
    text_llm_model: str = "Qwen/Qwen3.8-27B"
    voice_llm_base_url: str = "http://localhost:8002/v1"
    voice_llm_model: str = "Qwen/Qwen3.5-9B"
    model_server_api_key: Optional[str] = None
    model_request_timeout_seconds: float = Field(default=60.0, gt=0)
    model_health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    # Legacy Anthropic provider. It remains available for regression comparison
    # but is no longer required in local_qwen mode.
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-5"

    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=1024, gt=0)
    max_question_length: int = Field(default=2000, gt=0)
    max_context_chars: int = Field(default=12000, gt=0)
    seed_password: Optional[str] = None

    # COURSE AGENT voice orchestration. local_cascade is the default path;
    # Grok stays available only as a legacy regression provider.
    voice_provider: Literal["grok", "local_cascade"] = "local_cascade"
    voice_trace_content: bool = False
    speech_base_url: str = "http://localhost:8010"
    asr_timeout_seconds: float = Field(default=30.0, gt=0)
    tts_timeout_seconds: float = Field(default=30.0, gt=0)
    tts_speaker: str = "Sohee"
    tts_language: str = "Korean"

    xai_api_key: Optional[str] = None
    xai_realtime_url: str = "wss://api.x.ai/v1/realtime"
    xai_connect_timeout_seconds: float = Field(default=20.0, gt=0)
    xai_connect_attempts: int = Field(default=2, ge=1, le=5)
    xai_connect_retry_delay_seconds: float = Field(default=0.75, ge=0, le=10)
    visual_router_timeout_seconds: float = Field(default=3.0, gt=0, le=15)
    grok_voice_model: str = "grok-voice-latest"
    grok_voice: str = "eve"

    # Application-side VAD / endpointing. The local cascade uses Silero VAD on
    # CPU; the legacy Grok provider continues to use the equivalent server-VAD
    # settings when selected.
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    silence_ms: int = Field(default=900, gt=0)
    prefix_ms: int = Field(default=300, gt=0)
    min_speech_ms: int = Field(default=250, gt=0)
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)  # legacy WebRTC tests/config

    # Self-hosted trusted-web search. The professor-managed allowlist is always
    # re-applied by the application after SearXNG returns results.
    searxng_url: str = "http://localhost:8080"
    searxng_timeout_seconds: float = Field(default=10.0, gt=0)
    searxng_max_results: int = Field(default=5, ge=1, le=20)

    # Weak-concept memory. Optional: falls back to a local JSON file.
    moss_project_id: Optional[str] = None
    moss_project_key: Optional[str] = None
    moss_memory_index: str = "course-agent-weak-concepts"
    moss_memory_model: str = "moss-minilm"
    moss_sync_debounce_seconds: float = Field(default=0.75, ge=0.0)
    moss_local_fallback_file: Optional[str] = None

    @property
    def effective_llm_provider(self) -> Literal["mock", "anthropic", "local_qwen"]:
        """Resolve the old mock flag without making local_qwen depend on Claude."""
        return "mock" if self.use_mock_llm else self.llm_provider

    @property
    def is_voice_configured(self) -> bool:
        if self.voice_provider == "grok":
            return bool((self.xai_api_key or "").strip())
        return bool(
            self.voice_llm_base_url.strip()
            and self.voice_llm_model.strip()
            and self.speech_base_url.strip()
        )

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
