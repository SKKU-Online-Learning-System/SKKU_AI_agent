from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional


@dataclass(frozen=True)
class RagConfig:
    qwen_api_key: Optional[str] = None
    qwen_model: str = "qwen3.8-27b"
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_enable_thinking: bool = False
    use_mock_llm: bool = True
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    embedding_dim: int = 1536
    top_k: int = 5
    max_context_chars: int = 12000

    def __post_init__(self) -> None:
        if not 0 <= self.llm_temperature <= 1:
            raise ValueError("llm_temperature must be between 0 and 1")
        if self.llm_max_tokens <= 0:
            raise ValueError("llm_max_tokens must be positive")
        if not 1 <= self.top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")

    @classmethod
    def from_env(cls) -> "RagConfig":
        return cls(
            qwen_api_key=os.getenv("QWEN_API_KEY") or None,
            qwen_model=os.getenv("QWEN_MODEL", "qwen3.8-27b"),
            qwen_base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            ),
            qwen_enable_thinking=os.getenv("QWEN_ENABLE_THINKING", "false").lower() == "true",
            use_mock_llm=os.getenv("USE_MOCK_LLM", "true").lower() == "true",
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        )
