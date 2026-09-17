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

    # Model weights live exclusively on the external model server.
    embedding_provider: Literal["qwen", "mock"] = "qwen"
    embedding_base_url: str = "http://localhost:8003/v1"
    embedding_model: str = "Qwen/Qwen3-VL-Embedding-2B"
    embedding_dimension: int = Field(default=2048, ge=64, le=2048)
    embedding_timeout_seconds: float = Field(default=120, gt=0)
    vision_llm_base_url: str = "http://localhost:8002/v1"
    vision_llm_model: str = "Qwen/Qwen3.5-9B"
    document_max_pages: int = Field(default=300, gt=0)
    document_render_max_side: int = Field(default=1600, ge=512, le=4096)
    document_conversion_timeout_seconds: float = Field(default=120, gt=0)
    mock_embedding_dim: int = Field(default=512, gt=0)
    embedding_max_chars: int = Field(default=8000, gt=0)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    min_chunk_chars: int = Field(default=40, ge=0)
    vector_search_mode: Literal["local", "pgvector"] = "local"
    rag_visual_max_pages: int = Field(default=2, ge=1, le=5)
    rag_top_k: int = Field(default=5, gt=0)
    rag_max_top_k: int = Field(default=20, gt=0)
    # Cosine cutoff is deployment/calibration dependent; not a confidence probability.
    rag_text_score_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    rag_score_threshold: float = Field(default=0.22, ge=0.0, le=1.0)

    # Provider-neutral answer generation. USE_MOCK_LLM is retained as a
    # backwards-compatible override for the deterministic test/development mode.
    llm_provider: Literal["mock", "anthropic", "local_qwen"] = "local_qwen"
    use_mock_llm: bool = False
    text_llm_base_url: str = "http://localhost:8001/v1"
    text_llm_model: str = "Qwen/Qwen3.8-27B"
    voice_llm_base_url: str = "http://localhost:8002/v1"
    voice_llm_model: str = "Qwen/Qwen3.5-9B"
    # A finish_turn call carries up to 220 Korean characters plus its JSON
    # envelope; 320 truncated often enough to burn the single retry.
    voice_llm_max_tokens: int = Field(default=512, ge=128, le=1024)
    model_server_api_key: Optional[str] = None
    model_request_timeout_seconds: float = Field(default=60.0, gt=0)
    model_health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    # Legacy Anthropic provider. It remains available for regression comparison
    # but is no longer required in local_qwen mode.
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-5"

    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=1024, gt=0)
    # Completion budget for the text profile, which runs with thinking on: the
    # reasoning tokens count against max_tokens, and the 27B thinks for hundreds
    # to a few thousand of them before it writes a 200-500 token answer. 1024
    # truncated 11 of 14 measured turns. The text model's window is 16k, and
    # the prompt stays under ~9k even with attachments, so 4096 fits.
    text_llm_max_tokens: int = Field(default=4096, ge=256, le=8192)
    # The text model (Qwen3.8-27B) is a vision-language model. When the model
    # server keeps its vision encoder loaded (TEXT_LANGUAGE_MODEL_ONLY=false
    # there), a student's photo or a scanned page goes straight into the
    # message instead of being transcribed by the 9B first. If the server turns
    # out to be text-only, the turn falls back to the transcript on its own.
    text_llm_vision: bool = False
    # Images handed to the text model per request (about 1k tokens per megapixel
    # each); the previous turn's images ride along once so a follow-up still sees them.
    attachment_direct_images_max: int = Field(default=3, ge=1, le=8)
    # Headlines for the text model's reasoning while it streams, the way Codex
    # shows "what I am doing now": every so many characters and seconds, the
    # fast voice-profile model (thinking off) writes one Korean line. They run
    # beside the turn, never gate it, and are skipped when that model is down.
    text_thought_summaries: bool = True
    thought_summary_min_chars: int = Field(default=320, ge=40)
    thought_summary_interval_seconds: float = Field(default=4.0, ge=0.5)
    max_question_length: int = Field(default=2000, gt=0)
    max_context_chars: int = Field(default=12000, gt=0)
    seed_password: Optional[str] = None

    # Files a student attaches to a typed COURSE AGENT question (images and
    # PDFs). They are read once, on the turn that carries them, and the text
    # travels in the student's message; nothing is indexed. The text budgets
    # are in characters and bound what one turn adds to the model's context.
    attachment_max_count: int = Field(default=4, ge=1, le=8)
    attachment_max_size_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    attachment_max_pages: int = Field(default=600, ge=1, le=2000)
    # A PDF up to this many pages is read whole into the turn; a longer one (a
    # textbook) is indexed once after upload and each question pulls only the
    # pages that match it -- the model's window holds a few pages, not a book.
    attachment_inline_max_pages: int = Field(default=8, ge=1, le=50)
    attachment_index_top_k: int = Field(default=6, ge=1, le=20)
    # Pages or images the vision model reads per turn. Native PDF text is free;
    # a scanned page or a photo costs one vision call each.
    attachment_max_vision_pages: int = Field(default=3, ge=0, le=10)
    attachment_max_chars: int = Field(default=6000, ge=500)
    # What of an attachment stays in the bounded conversation history after its
    # own turn, so a follow-up still knows what the file said without the whole
    # window filling with one PDF -- and in how many of the newest user turns
    # (counting the current one) that text is shown to the model in full. Older
    # turns keep only the file names. The text model's window is 16k tokens and
    # Korean runs ~0.56 tokens per character, so 6000 + 2000 chars of file text
    # plus the prompt stays well inside it; six turns of it would not.
    attachment_history_chars: int = Field(default=2000, ge=200)
    attachment_history_turns: int = Field(default=2, ge=1, le=6)
    # Per-learner storage bounds; the oldest file is evicted to make room. A
    # file that was already asked about is dead weight -- its text is in the log.
    attachment_max_stored_files: int = Field(default=20, ge=1)
    attachment_max_stored_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    # How long one turn waits for its files to be read before answering without them.
    attachment_read_timeout_seconds: float = Field(default=60.0, gt=0)

    # COURSE AGENT voice orchestration. local_cascade is the default path;
    # Grok stays available only as a legacy regression provider.
    voice_provider: Literal["grok", "local_cascade"] = "local_cascade"
    voice_trace_content: bool = False
    speech_base_url: str = "http://localhost:8010"
    tts_base_url: Optional[str] = None
    asr_timeout_seconds: float = Field(default=30.0, gt=0)
    tts_timeout_seconds: float = Field(default=30.0, gt=0)
    tts_speaker: str = "Sohee"
    tts_language: str = "Korean"
    # Bound each synthesis request so the first playable audio arrives before
    # the complete response waveform has been generated. Sentence boundaries
    # are preferred; this limit only splits unusually long sentences further.
    tts_chunk_max_chars: int = Field(default=80, ge=20, le=300)
    # Knobs for the first request of a turn. Both were measured against
    # the current streaming backend and are neutral by default: first-audio latency
    # is gated by how fast the LLM completes its first sentence, not by chunk
    # size, and a smaller decoder hop trades more throughput than it saves
    # (token2wav costs ~600ms almost regardless of token count). Kept tunable
    # because a faster TTS backend shifts that balance.
    tts_first_chunk_max_chars: int = Field(default=80, ge=10, le=300)
    # 0 keeps the TTS server's own hop length.
    tts_first_chunk_hop_len: int = Field(default=0, ge=0, le=100)
    # Floor for the first request, which merges a too-short opening sentence
    # ("네!", "안녕하세요!") into the one after it.
    #
    # The brain now releases a finished, validated reply, so this no longer
    # decides whether a fragment is spoken before the round is known to be an
    # answer round -- nothing is spoken early any more. It only protects the
    # playback buffer and the delivery of the opening.
    #
    # Do not lower this much: TTS pacing degrades sharply on very short input.
    # Over 8 runs per size, the spoken duration of the same fragment had a
    # coefficient of variation of 0.23 at 12 characters versus 0.07 at 20+, which
    # is audible as uneven delivery, and a short fragment also leaves the playback
    # buffer too thin to absorb the packet after it.
    tts_first_chunk_min_chars: int = Field(default=24, ge=0, le=200)
    # Each TTS request is generated independently, so concatenating two of them
    # loses most of the pause a speaker leaves at the boundary and the seam is
    # heard as one sentence running into the next.
    #
    # Sized from the voice itself rather than from a rule of thumb. Measured over
    # 5 replies synthesized as a single request, this speaker pauses a median of
    # 523ms at a sentence end and 256ms at a comma. The TTS server already keeps
    # `QWEN_TTS_SILENCE_KEEP_MS` of its own trailing silence and trims the next
    # request's leading silence to a pre-roll, which left the seam at 352ms; these
    # values top that back up to the speaker's natural pause. A seam that pauses
    # for less than a real sentence boundary while the delivery changes across it
    # is what reads as abrupt, so under-shooting here is worse than over-shooting.
    tts_sentence_gap_ms: int = Field(default=350, ge=0, le=1000)
    tts_clause_gap_ms: int = Field(default=90, ge=0, le=1000)

    xai_api_key: Optional[str] = None
    xai_realtime_url: str = "wss://api.x.ai/v1/realtime"
    xai_connect_timeout_seconds: float = Field(default=20.0, gt=0)
    xai_connect_attempts: int = Field(default=2, ge=1, le=5)
    xai_connect_retry_delay_seconds: float = Field(default=0.75, ge=0, le=10)
    visual_router_timeout_seconds: float = Field(default=5.0, gt=0, le=15)
    # Speak the progress notice while the model is still working, so a slow turn
    # is not dead air. Synthesis races the model: if the reply is ready first the
    # notice is dropped unheard, because a spoken filler always delays the answer
    # it precedes and is only worth it when there was silence to buy back.
    voice_spoken_filler: bool = True

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
            and (self.tts_base_url or self.speech_base_url).strip()
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
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def resolved_vector_db_url(self) -> str:
        return self.vector_db_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
