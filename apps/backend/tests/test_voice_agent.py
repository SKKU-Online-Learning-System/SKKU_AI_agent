"""COURSE AGENT unit tests, ported from the standalone voice-agent repo."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.llm_service import ToolCallRequest, ToolTurn
from app.services.voice import brain, trusted_sites, turn_detector
from app.services.voice.moss_memory import MossMemoryStore

# --------------------------------------------------------------------------
# Tool dispatcher
# --------------------------------------------------------------------------

def call(call_id: str, name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=name, arguments=args)

class FakeLLM:
    """Two scripted turns: optional action tools, then the final answer."""

    def __init__(self) -> None:
        self.turns = iter(
            [
                ToolTurn(
                    text="",
                    model_name="claude-test",
                    tool_calls=[
                        call(
                            "web",
                            "search_trusted_web",
                            {"query": "attention paper", "reason": "강의자료 설명이 불충분함"},
                        ),
                        call(
                            "visual",
                            "show_visualization",
                            {
                                "title": "Attention 가중치",
                                "kind": "formula",
                                "caption": "유사도 점수를 비율로 바꿔요.",
                                "latex": r"\alpha_i=\frac{e^{s_i}}{\sum_j e^{s_j}}",
                                "labels": [],
                                "points": [],
                                "x_label": "",
                                "y_label": "",
                            },
                        ),
                    ],
                ),
                ToolTurn(
                    text="근거를 바탕으로 설명할게요. https://arxiv.org/abs/1706.03762",
                    model_name="claude-test",
                    tool_calls=[],
                ),
            ]
        )
        self.calls: list[dict] = []

    async def stream_tool_turn(self, **kwargs) -> ToolTurn:
        self.calls.append(kwargs)
        return next(self.turns)

def make_context(memory=None) -> brain.VoiceContext:
    return brain.VoiceContext(
        course_id="course-1",
        course_name="인공지능개론",
        user_id="student-1",
        memory=memory or AsyncMock(),
    )

def test_tool_schema_names_are_the_six_agent_tools() -> None:
    assert {tool["function"]["name"] for tool in brain.TOOLS} == {
        "recall_weak_concepts",
        "search_course_materials",
        "search_trusted_web",
        "save_weak_concept",
        "review_weak_concept",
        "show_visualization",
    }

def test_weak_concept_list_is_course_scoped_and_sorted_by_recent_activity() -> None:
    memory = AsyncMock()
    memory.all_memories.return_value = [
        {
            "id": "older",
            "course": "인공지능개론",
            "concept": "경사하강법",
            "difficulty_note": "학습률을 혼동함",
            "confidence": 0.34,
            "last_seen_at": 10,
        },
        {
            "id": "other-course",
            "course": "소프트웨어공학",
            "concept": "응집도",
            "difficulty_note": "결합도와 혼동함",
            "confidence": 0.9,
            "last_seen_at": 30,
        },
        {
            "id": "newer",
            "course": "인공지능개론",
            "concept": "역전파",
            "difficulty_note": "연쇄법칙 적용을 어려워함",
            "confidence": 0.666,
            "last_seen_at": 20,
        },
    ]

    concepts = asyncio.run(brain.list_weak_concepts(make_context(memory)))

    assert [item["memory_id"] for item in concepts] == ["newer", "older"]
    assert [item["mastery_percent"] for item in concepts] == [67, 34]

def test_all_schemas_execute_through_dispatcher() -> None:
    fake_llm = FakeLLM()
    memory = AsyncMock()
    memory.recall.return_value = {"found": False, "memories": []}
    memory.all_memories.return_value = []
    memory.save.return_value = {"status": "saved"}
    memory.review.return_value = {"status": "practicing"}
    context = make_context(memory)

    with (
        patch.object(brain, "LLMService", return_value=fake_llm),
        patch.object(
            brain,
            "search_course_materials",
            return_value=(
                json.dumps({"found": True, "results": []}),
                [{"document_name": "w1.pdf"}],
            ),
        ) as material_search,
        patch.object(
            brain,
            "search_trusted_web",
            new=AsyncMock(
                return_value=json.dumps(
                    {"found": True, "sources": ["https://arxiv.org/abs/1706.03762"]}
                )
            ),
        ) as web_search,
    ):
        reply, tools, sources, visualizations = asyncio.run(
            brain.think(context, "Query와 Key를 왜 곱해?", brain.StageTimer())
        )

    assert set(tools) == {"search_trusted_web", "show_visualization"}
    # Memory and course evidence are prefetched; only action tools reach Claude.
    assert "force_tools" not in fake_llm.calls[0]
    assert {tool["name"] for tool in fake_llm.calls[0]["tools"]} == {
        "search_trusted_web",
        "show_visualization",
    }
    assert "input_schema" in fake_llm.calls[0]["tools"][0]

    # The tool results reach Claude as one user turn of tool_result blocks.
    last_messages = fake_llm.calls[1]["messages"]
    result_blocks = [
        block
        for message in last_messages
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(result_blocks) == 2

    memory.all_memories.assert_awaited_once()
    material_search.assert_called_once_with("course-1", "Query와 Key를 왜 곱해?")
    web_search.assert_awaited_once_with(
        "course-1",
        pdf_evidence_insufficient=True,
        query="attention paper",
        reason="강의자료 설명이 불충분함",
    )
    memory.save.assert_not_awaited()
    memory.review.assert_not_awaited()

    # Trusted URLs travel in `sources`, never inside the spoken answer.
    assert "https://arxiv.org/abs/1706.03762" not in reply
    assert sources == ["https://arxiv.org/abs/1706.03762"]
    assert visualizations[0]["kind"] == "formula"
    assert context.last_material_sources == [{"document_name": "w1.pdf"}]

def test_mock_llm_grounds_the_answer_without_any_api_key() -> None:
    """The voice TA must work on the project default (USE_MOCK_LLM=true)."""

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = make_context(memory)
    material_result = json.dumps(
        {
            "found": True,
            "results": [
                {"source": "week1.pdf p.3", "excerpt": "정상성은 평균과 분산이 일정한 성질입니다."}
            ],
        },
        ensure_ascii=False,
    )
    streamed: list[str] = []

    async def on_token(token: str) -> None:
        streamed.append(token)

    with (
        patch.object(
            brain, "get_settings", return_value=Settings(_env_file=None, use_mock_llm=True)
        ),
        patch.object(
            brain,
            "search_course_materials",
            return_value=(material_result, [{"document_name": "week1.pdf"}]),
        ),
    ):
        reply, tools, sources, visualizations = asyncio.run(
            brain.think(context, "정상성이 뭐야?", brain.StageTimer(), on_token=on_token)
        )

    assert tools == []
    assert "week1.pdf p.3" in reply
    assert "".join(streamed) == reply
    assert sources == []
    assert visualizations == []

def test_visualization_rejects_incomplete_shapes() -> None:
    with pytest.raises(ValueError):
        brain.show_visualization(
            title="빈 그래프",
            kind="plot",
            caption="점이 부족해요.",
            latex="",
            labels=[],
            points=[{"x": 0, "y": 0}],
            x_label="x",
            y_label="y",
        )

def test_visualization_normalizes_realtime_provider_aliases() -> None:
    rendered = json.loads(
        brain.show_visualization(
            type="flow",
            name="트랜스포머 구조",
            description="정보가 블록을 따라 흐릅니다.",
            steps="입력 → Self-Attention → Feed Forward → 출력",
        )
    )

    assert rendered["kind"] == "flow"
    assert rendered["title"] == "트랜스포머 구조"
    assert rendered["labels"] == ["입력", "Self-Attention", "Feed Forward", "출력"]

def test_tool_logs_include_args_status_timing_and_result() -> None:
    args = {
        "title": "소프트맥스",
        "kind": "formula",
        "caption": "확률로 변환해요.",
        "latex": r"\frac{e^{x_i}}{\sum_j e^{x_j}}",
        "labels": [],
        "points": [],
        "x_label": "",
        "y_label": "",
    }
    # Own handler: the assertion is about brain's log contract, not about
    # whatever root logging configuration the rest of the suite leaves behind.
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    previous_level = brain.log.level
    brain.log.addHandler(handler)
    brain.log.setLevel(logging.INFO)
    try:
        asyncio.run(brain.run_tool(make_context(), "show_visualization", args, brain.StageTimer()))
    finally:
        brain.log.removeHandler(handler)
        brain.log.setLevel(previous_level)

    output = "\n".join(record.getMessage() for record in records)
    assert 'tool call name=show_visualization args={"title":"소프트맥스"' in output
    assert "tool result name=show_visualization status=ok elapsed_ms=" in output
    assert 'result={"title":"소프트맥스"' in output

def test_speech_text_drops_urls() -> None:
    assert brain.for_speech("설명이에요. https://arxiv.org/abs/1706.03762") == "설명이에요."

def test_speech_text_spells_acronyms_in_hangul() -> None:
    """The TTS model mispronounces upper-case acronyms, and a Korean particle
    attaches straight to them, so the boundary cannot rely on \\b."""
    assert brain.for_speech("CPU 사용률이 높으면 GPU로 넘기세요.") == (
        "씨피유 사용률이 높으면 지피유로 넘기세요."
    )
    assert brain.for_speech("API를 호출하면 JSON이 반환됩니다.") == (
        "에이피아이를 호출하면 제이슨이 반환됩니다."
    )
    # Read as a word, not letter by letter.
    assert brain.for_speech("RAM 용량") == "램 용량"
    # Written with a slash, so the acronym pattern cannot reach it.
    assert brain.for_speech("I/O를 관리합니다.") == "아이오를 관리합니다."

def test_speech_text_uses_hangul_pronunciation_hints() -> None:
    assert brain.for_speech(
        "softmax(소프트맥스) 함수와 virtual memory(버추얼 메모리)를 비교해요."
    ) == "소프트맥스 함수와 버추얼 메모리를 비교해요."

def test_speech_text_leaves_non_acronyms_alone() -> None:
    # Mixed case is a name or identifier, and a trailing lower-case letter makes
    # the reading ambiguous; neither should be spelled out.
    assert brain.for_speech("MyCPU 변수") == "MyCPU 변수"
    assert brain.for_speech("CPUs 두 개") == "CPUs 두 개"
    # Lower-case English prose is left to the model.
    assert brain.for_speech("softmax 함수") == "softmax 함수"
    assert brain.for_speech("가상 메모리는 큽니다.") == "가상 메모리는 큽니다."

def test_history_is_bounded_per_session() -> None:
    context = make_context()
    for index in range(brain.MAX_HISTORY_MESSAGES + 5):
        context.append_history({"role": "user", "content": str(index)})

    assert len(context.history) == brain.MAX_HISTORY_MESSAGES
    assert context.history[-1]["content"] == str(brain.MAX_HISTORY_MESSAGES + 4)

# --------------------------------------------------------------------------
# Trusted-site allowlist
# --------------------------------------------------------------------------

@pytest.fixture
def voice_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(trusted_sites, "voice_storage_dir", lambda: tmp_path)
    return tmp_path

def test_trusted_sites_default_to_the_academic_allowlist(voice_storage) -> None:
    assert "skku.edu" in trusted_sites.get_trusted_domains("course-1")

def test_trusted_sites_are_scoped_per_course(voice_storage) -> None:
    trusted_sites.add_trusted_domain("course-1", "https://kosis.kr/statHtml")

    assert "kosis.kr" in trusted_sites.get_trusted_domains("course-1")
    assert "kosis.kr" not in trusted_sites.get_trusted_domains("course-2")

    trusted_sites.remove_trusted_domain("course-1", "kosis.kr")
    assert "kosis.kr" not in trusted_sites.get_trusted_domains("course-1")

def test_trusted_site_rejects_non_http_values(voice_storage) -> None:
    with pytest.raises(ValueError):
        trusted_sites.add_trusted_domain("course-1", "ftp://example")

# --------------------------------------------------------------------------
# Week-3 endpointing fallback
# --------------------------------------------------------------------------

class FakeVad:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = iter(decisions)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return next(self.decisions)

FRAME = bytes(turn_detector.FRAME_BYTES)

def test_turn_detector_debounces_prefix_and_endpoint() -> None:
    decisions = [False, False, True, True, True] + [True] * 10 + [False] * 45
    detector = turn_detector.TurnDetector(FakeVad(decisions))
    utterance = None
    for _ in decisions:
        utterance = detector.feed(FRAME) or utterance

    assert utterance is not None
    assert len(utterance) == len(decisions) * turn_detector.FRAME_BYTES
    assert detector.speaking is False

def test_turn_detector_requires_consecutive_silence(monkeypatch) -> None:
    decisions = [True, True, True, False, False, True, False, False, False]
    monkeypatch.setattr(turn_detector, "PREFIX_MS", 40)
    monkeypatch.setattr(turn_detector, "SILENCE_MS", 60)
    monkeypatch.setattr(turn_detector, "MIN_SPEECH_MS", 60)

    detector = turn_detector.TurnDetector(FakeVad(decisions))
    results = [detector.feed(FRAME) for _ in decisions]

    assert all(result is None for result in results[:-1])
    assert results[-1] is not None

def test_turn_detector_discards_short_noise(monkeypatch) -> None:
    decisions = [True, True, True, False, False]
    monkeypatch.setattr(turn_detector, "PREFIX_MS", 40)
    monkeypatch.setattr(turn_detector, "SILENCE_MS", 40)
    monkeypatch.setattr(turn_detector, "MIN_SPEECH_MS", 100)

    detector = turn_detector.TurnDetector(FakeVad(decisions))
    results = [detector.feed(FRAME) for _ in decisions]

    assert all(result is None for result in results)
    assert detector.speaking is False

def test_wav_contract() -> None:
    wav = turn_detector.wav_bytes(FRAME)
    assert wav[:4] == b"RIFF"
    assert b"WAVE" in wav[:16]

# --------------------------------------------------------------------------
# Weak-concept memory (local fallback)
# --------------------------------------------------------------------------

def test_local_memory_saves_recalls_and_reviews(tmp_path) -> None:
    store = MossMemoryStore(student_id="student-1", local_path=tmp_path / "weak.json")
    store._local_mode = True  # no Moss credentials in tests

    async def scenario():
        saved = await store.save(
            course="인공지능개론",
            concept="Self-Attention",
            original_question="Query와 Key를 왜 곱해?",
            difficulty_note="유사도 의미가 불명확함",
        )
        recalled = await store.recall("Self-Attention 유사도")
        reviewed = await store.review(saved["memory_id"], True)
        return saved, recalled, reviewed

    saved, recalled, reviewed = asyncio.run(scenario())

    assert saved["storage"] == "local"
    assert recalled["found"] is True
    assert recalled["memories"][0]["concept"] == "Self-Attention"
    assert reviewed["status"] == "practicing"

def test_local_memory_is_isolated_per_student(tmp_path) -> None:
    shared = tmp_path / "weak.json"
    first = MossMemoryStore(student_id="student-1", local_path=shared)
    second = MossMemoryStore(student_id="student-2", local_path=shared)
    first._local_mode = True
    second._local_mode = True

    async def scenario():
        await first.save(
            course="인공지능개론",
            concept="Self-Attention",
            original_question="왜 곱해?",
            difficulty_note="유사도 의미가 불명확함",
        )
        return await second.recall("Self-Attention")

    assert asyncio.run(scenario())["found"] is False
