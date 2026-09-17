from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import Settings
from app.services.model_server import speech_client
from app.services.model_server.speech_client import SpeechClient, SpeechError
from app.services.trusted_web_search import TrustedWebSearchService


class FakeResponse:
    def __init__(
        self,
        *,
        payload: dict | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://service/test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class FakeSpeechHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs) -> FakeResponse:
        self.calls.append({"path": path, **kwargs})
        if path == "v1/audio/transcriptions":
            return FakeResponse(
                payload={
                    "text": "가상 메모리가 뭐야?",
                    "language": "Korean",
                    "audio_duration_ms": 1000,
                    "inference_ms": 120,
                }
            )
        return FakeResponse(
            content=b"\x01\x02" * 100,
            headers={
                "X-Audio-Sample-Rate": "24000",
                "X-Inference-Ms": "90",
                "X-Audio-Duration-Ms": "400",
            },
        )


class FakeSearchHttpClient:
    async def get(self, path: str, **kwargs) -> FakeResponse:
        assert path == "search"
        return FakeResponse(
            payload={
                "results": [
                    {
                        "title": "Allowed root",
                        "url": "https://cs.skku.edu/page",
                        "content": "trusted root snippet",
                    },
                    {
                        "title": "Allowed subdomain",
                        "url": "https://docs.cs.skku.edu/reference",
                        "content": "trusted subdomain snippet",
                    },
                    {
                        "title": "Attacker",
                        "url": "https://cs.skku.edu.evil.example/phish",
                        "content": "must be removed",
                    },
                    {
                        "title": "Wrong scheme",
                        "url": "javascript:alert(1)",
                        "content": "must be removed",
                    },
                ]
            }
        )


def settings(**overrides) -> Settings:
    values = {
        "speech_base_url": "http://speech:8010",
        "tts_base_url": "http://tts:8011",
        "searxng_url": "http://search:8080",
        "tts_speaker": "ryan",
        "tts_language": "Korean",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_speech_client_asr_and_tts_contract(monkeypatch) -> None:
    fake = FakeSpeechHttpClient()
    base_urls = []
    monkeypatch.setattr(
        speech_client,
        "async_client",
        lambda base_url, *args: base_urls.append(base_url) or fake,
    )
    client = SpeechClient(settings())

    transcription = await client.transcribe(b"\x00\x00" * 16000, sample_rate=16000)
    synthesized = await client.synthesize("안녕하세요.")

    assert transcription.text == "가상 메모리가 뭐야?"
    assert base_urls == ["http://speech:8010", "http://tts:8011"]
    asr_call = fake.calls[0]
    assert asr_call["path"] == "v1/audio/transcriptions"
    assert asr_call["data"] == {}
    assert asr_call["files"]["file"][2] == "audio/wav"
    assert asr_call["files"]["file"][1][:4] == b"RIFF"

    tts_call = fake.calls[1]
    assert tts_call["path"] == "v1/audio/speech"
    assert tts_call["json"] == {
        "input": "안녕하세요.",
        "voice": "ryan",
        "language": "Korean",
        "response_format": "pcm",
    }
    assert synthesized.sample_rate == 24000
    assert synthesized.inference_ms == 90


@pytest.mark.asyncio
async def test_speech_client_rejects_wrong_tts_sample_rate(monkeypatch) -> None:
    class WrongRate(FakeSpeechHttpClient):
        async def post(self, path: str, **kwargs) -> FakeResponse:
            return FakeResponse(content=b"x", headers={"X-Audio-Sample-Rate": "16000"})

    monkeypatch.setattr(speech_client, "async_client", lambda *args: WrongRate())

    with pytest.raises(SpeechError, match="sample rate"):
        await SpeechClient(settings()).synthesize("테스트")


@pytest.mark.asyncio
async def test_searxng_results_are_revalidated_against_allowlist() -> None:
    service = TrustedWebSearchService(settings())
    service.client = FakeSearchHttpClient()

    results = await service.search("가상 메모리", ["cs.skku.edu"])

    assert [result.url for result in results] == [
        "https://cs.skku.edu/page",
        "https://docs.cs.skku.edu/reference",
    ]
    assert all("evil.example" not in result.url for result in results)


@pytest.mark.asyncio
async def test_tts_stream_never_hands_out_half_a_sample(monkeypatch) -> None:
    """PCM16 split at an odd byte desyncs every sample after it.

    ``aiter_bytes`` splits the body wherever the transport did, not between
    samples, and a consumer given half a sample either drops it -- shifting the
    rest of the stream by one byte, which is audible as white noise -- or refuses
    the buffer. The stream must only ever emit whole samples.
    """
    body = bytes(range(200))
    # Deliberately odd-sized pieces, the way a real socket would deliver them.
    pieces = [body[0:7], body[7:8], body[8:55], body[55:120], body[120:199], body[199:200]]

    class StreamedResponse:
        status_code = 200
        headers = {"X-Audio-Sample-Rate": "24000"}

        async def aiter_bytes(self):
            for piece in pieces:
                yield piece

        async def aread(self):
            return b""

        async def aclose(self):
            return None

    client = SpeechClient(Settings(_env_file=None))
    monkeypatch.setattr(client.tts_client, "build_request", lambda *a, **k: object())
    monkeypatch.setattr(
        client.tts_client, "send", AsyncMock(return_value=StreamedResponse())
    )

    chunks = [chunk async for chunk, _ in client.synthesize_stream("안녕하세요")]

    assert all(len(chunk) % 2 == 0 for chunk in chunks), [len(c) for c in chunks]
    # Nothing is dropped or reordered: the stream is the body, whole samples only.
    assert b"".join(chunks) == body[: len(body) // 2 * 2]
