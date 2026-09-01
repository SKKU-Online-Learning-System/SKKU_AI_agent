from app.core.config import Settings


def test_local_voice_is_configured_without_xai_key() -> None:
    settings = Settings(
        _env_file=None,
        voice_provider="local_cascade",
        xai_api_key=None,
        voice_llm_base_url="http://model:8002/v1",
        voice_llm_model="Qwen/Qwen3.5-9B",
        speech_base_url="http://model:8010",
    )
    assert settings.is_voice_configured is True


def test_legacy_grok_requires_xai_key() -> None:
    missing = Settings(_env_file=None, voice_provider="grok", xai_api_key=None)
    configured = Settings(_env_file=None, voice_provider="grok", xai_api_key="test-key")
    assert missing.is_voice_configured is False
    assert configured.is_voice_configured is True


def test_mock_llm_override_remains_available_for_ci() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="local_qwen",
        use_mock_llm=True,
    )
    assert settings.effective_llm_provider == "mock"


def test_voice_trace_content_defaults_off_and_accepts_env(monkeypatch) -> None:
    assert Settings(_env_file=None).voice_trace_content is False
    monkeypatch.setenv("VOICE_TRACE_CONTENT", "true")
    assert Settings(_env_file=None).voice_trace_content is True
