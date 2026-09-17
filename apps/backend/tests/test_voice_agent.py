"""COURSE AGENT unit tests, ported from the standalone voice-agent repo."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from unittest.mock import AsyncMock, Mock, patch

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


def test_visualization_normalizes_delimiters_and_rejects_placeholder_latex() -> None:
    rendered = json.loads(
        brain.show_visualization(
            kind="formula",
            title="소프트맥스",
            caption="점수를 확률로 바꿉니다.",
            latex=r"$\operatorname{softmax}(x_i)=\frac{e^{x_i}}{\sum_j e^{x_j}}$",
        )
    )
    assert rendered["latex"].startswith(r"\operatorname")

    with pytest.raises(ValueError, match="meaningful latex"):
        brain.show_visualization(
            kind="formula", title="소프트맥스", caption="깨진 수식", latex="$"
        )


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

def test_speech_text_leaves_no_latin_for_the_voice() -> None:
    """The voice runs in Korean mode, so Latin reaching it is mispronounced and
    can come out as a tonal artefact. Only the spoken copy is converted; what the
    student reads keeps its original spelling."""
    # An identifier is said part by part rather than mangled as one word.
    assert brain.for_speech("MyCPU 변수") == "마이씨피유 변수"
    assert brain.for_speech("CPUs 두 개") == "씨피유스 두 개"
    # Lower-case English prose is converted too; it used to be left to the model.
    assert brain.for_speech("softmax 함수") == "소프트맥스 함수"
    assert brain.for_speech("가상 메모리는 큽니다.") == "가상 메모리는 큽니다."
    spoken = brain.for_speech("gradient descent에서 learning rate가 크면 diverge합니다.")
    assert not re.search(r"[A-Za-z]", spoken), spoken

def test_speech_text_drops_a_term_written_twice() -> None:
    """'소프트맥스 (softmax)' is one term written twice.

    Once the English is converted the voice says it twice in a row, which is what
    makes it sound odd. The prompt asks for Korean only; this is the net, and it
    matches on what the bracket *reads as*, not on it being bracketed Latin.
    """
    assert brain.for_speech("소프트맥스 (softmax) 는 값을 바꿔요.") == "소프트맥스 는 값을 바꿔요."
    assert brain.for_speech("어텐션(attention)의 핵심이에요.") == "어텐션의 핵심이에요."
    # Bracketed Latin that is not a repeat is content: options, not a gloss.
    assert brain.for_speech("보기 (A)와 (B) 중 무엇일까요?") == "보기 (에이)와 (비) 중 무엇일까요?"
    assert brain.for_speech("가중치 (가장 큰 값) 를 보세요.") == "가중치 (가장 큰 값) 를 보세요."
    assert brain.for_speech("두 확률 (2, 3) 을 비교해요.") == "두 확률 (2, 3) 을 비교해요."


def test_speech_text_drops_math_notation() -> None:
    """Notation cannot be read aloud, so it is dropped rather than spelled out."""
    assert brain.for_speech("지수함수 $e^x$ 를 적용해요.") == "지수함수 를 적용해요."
    assert brain.for_speech("지수함수 ($e^x$) 를 적용해요.") == "지수함수 를 적용해요."
    assert brain.for_speech("\\frac{a}{b} 형태예요.") == "형태예요."
    # No stray brackets are left where the notation used to be.
    assert "(" not in brain.for_speech("값 ($x_1$) 을 보세요.")


def test_speech_text_says_bare_superscripts_instead_of_dropping_them() -> None:
    """'e^2' is part of the sentence, unlike a display formula, so it is read.

    The reading ends in a consonant where the notation did not, so the Korean
    particle after it has to come along: 'e^2와' is '이의 2제곱과', not '...제곱와'.
    """
    assert brain.for_speech("e^2와 e^3을 더해요.") == "이의 2제곱과 이의 3제곱을 더해요."
    assert brain.for_speech("2^10은 1024예요.") == "2의 10제곱은 1024예요."
    assert brain.for_speech("점수 z_1, z_2를 비교해요.") == "점수 제트 1, 제트 2를 비교해요."
    # Ordinary Korean ending in those syllables is not a particle to rewrite.
    assert brain.for_speech("사과와 효과를 비교해요.") == "사과와 효과를 비교해요."


def test_answer_policy_asks_for_korean_without_notation() -> None:
    """Both surfaces read the reply aloud, so the policy the voice path sees --
    only the first paragraph -- has to carry these rules."""
    voice_policy = brain.answer_instructions(make_context(), {}, voice=True)
    assert "every term in Korean" in voice_policy
    assert "LaTeX" in voice_policy


def test_the_typed_reply_may_explain_at_length_while_speech_stays_short() -> None:
    """The brevity rules exist for a spoken 220-character utterance; a reply read
    on a screen may explain a hint properly, and the model is asked to think briefly."""
    text_policy = brain.answer_instructions(make_context(), {})
    voice_policy = brain.answer_instructions(make_context(), {}, voice=True)
    assert "# 글로 답하는 방식" in text_policy and "2~5문장" in text_policy
    assert "3단계 전에는" in text_policy  # the ladder still holds on screen
    assert "Think in Korean and briefly" in text_policy
    assert "# 글로 답하는 방식" not in voice_policy
    assert "Think in Korean" not in voice_policy
    # The text-mode note comes after the shared policy and before the stage, so the
    # override is read with the rule it overrides.
    assert text_policy.index("SOCRATIC" if False else "한국어 존댓말로 짧게") < text_policy.index("# 글로 답하는 방식") < text_policy.index("# 이번 턴의 지도 단계")


def test_history_is_bounded_per_session() -> None:
    context = make_context()
    for index in range(brain.MAX_HISTORY_MESSAGES + 5):
        context.append_history({"role": "user", "content": str(index)})

    assert len(context.history) == brain.MAX_HISTORY_MESSAGES
    assert context.history[-1]["content"] == str(brain.MAX_HISTORY_MESSAGES + 4)


@pytest.mark.parametrize("answer", ["응", "모르겠어", "0.8", "큰 쪽이요", "저 식은 왜 그래?"])
def test_followup_retrieval_keeps_the_tutors_question(answer) -> None:
    context = make_context()
    context.history = [
        {"role": "user", "content": "소프트맥스가 뭐야?"},
        {"role": "assistant", "content": "어텐션 가중치가 0.8과 0.2라면 어느 쪽이 더 클까요?"},
        {"role": "user", "content": answer},
    ]
    query = brain.retrieval_query(context, answer)
    assert "어텐션 가중치" in query
    assert query.endswith(answer)
    assert brain.retrieval_query(context, "새로운 주제인 경사하강법을 설명해줘").endswith(
        "새로운 주제인 경사하강법을 설명해줘"
    )


def test_recent_visual_is_in_next_prompt_and_cleared_on_reset() -> None:
    context = make_context()
    context.last_visualizations = [{"kind": "formula", "latex": "a/(a+b)"}]
    prompt = brain.answer_instructions(context, {})
    assert "a/(a+b)" in prompt
    assert brain.SOCRATIC_PROMPT in prompt
    context.reset()
    assert context.last_visualizations == []

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

def test_turn_detector_debounces_prefix_and_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(turn_detector, "SILENCE_MS", 900)
    monkeypatch.setattr(turn_detector, "PREFIX_MS", 300)
    monkeypatch.setattr(turn_detector, "MIN_SPEECH_MS", 250)
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


class _ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self.turns = iter(ToolTurn(text=text, model_name="scripted", tool_calls=[]) for text in replies)
        self.calls: list[dict] = []

    async def stream_tool_turn(self, **kwargs) -> ToolTurn:
        self.calls.append(kwargs)
        return next(self.turns)


def _text_turn(context, transcript: str, replies: list[str]):
    llm = _ScriptedLLM(replies)
    with (
        patch.object(brain, "LLMService", return_value=llm),
        patch.object(brain, "prefetch_context", new=AsyncMock(return_value={})),
        patch("app.services.voice.session_store.external_brain_for", return_value=Mock()),
    ):
        reply, *_ = asyncio.run(brain.think(context, transcript, brain.StageTimer()))
    return reply, llm


def test_the_text_path_climbs_the_ladder_on_stuck_and_regenerates_a_repeated_question() -> None:
    """answer-text has no finish_turn, so its ladder never moved and the probe came back verbatim."""
    probe = "이름부터 볼게요. 두 벡터의 내적은 차원이 커지면 값이 어떻게 될 것 같나요?"
    context = make_context()
    context.history = [
        {"role": "user", "content": "스케일드 닷 프로덕트 어텐션이 뭔지 모르겠어."},
        {"role": "assistant", "content": probe},
    ]
    smaller = "괜찮아요. 2차원과 100차원 중 어느 쪽 내적이 더 클까요?"

    reply, llm = _text_turn(context, "몰라", [probe, smaller])

    assert reply == smaller
    assert len(llm.calls) == 2
    assert "두 벡터의 내적은" in llm.calls[1]["system"]
    assert "되묻지 말고" in llm.calls[1]["system"] or "같은 질문" in llm.calls[1]["system"]
    assert context.hint_level == 1

    # A second stuck turn climbs again; a second repeat is spoken rather than failed.
    reply, llm = _text_turn(context, "그것도 모르겠어요", [smaller, smaller])
    assert reply == smaller
    assert len(llm.calls) == 2
    assert context.hint_level == 2

    # A new question of its own is left to the model and moves the ladder nowhere.
    reply, llm = _text_turn(context, "소프트맥스는 왜 써요?", ["좋은 질문이에요. 점수가 여러 개 있으면 무엇으로 바꾸고 싶을까요?"])
    assert len(llm.calls) == 1
    assert context.hint_level == 2


def test_preloaded_memory_is_course_scoped_and_topic_first() -> None:
    """The turn's own words pull the matching concept ahead of merely recent ones."""
    memory = AsyncMock()
    memory.all_memories.return_value = [
        {"id": "other", "course": "소프트웨어공학", "concept": "응집도 - 결합도와의 차이",
         "difficulty_note": "결합도와 혼동함", "last_seen_at": 40},
        {"id": "newest", "course": "인공지능개론", "concept": "역전파 - 연쇄법칙 적용",
         "difficulty_note": "연쇄법칙 적용을 어려워함", "last_seen_at": 30},
        {"id": "newer", "course": "인공지능개론", "concept": "학습률 - 너무 크면 발산하는 이유",
         "difficulty_note": "학습률과 발산을 혼동함", "last_seen_at": 20},
        {"id": "relevant", "course": "인공지능개론", "concept": "소프트맥스 - 합이 1인 확률로 바꾸는 계산",
         "original_question": "소프트맥스가 뭔지 모르겠어", "difficulty_note": "정의를 설명하지 못함",
         "last_seen_at": 10},
        {"id": "oldest", "course": "인공지능개론", "concept": "과적합 - 정규화로 완화",
         "difficulty_note": "", "last_seen_at": 5},
    ]
    context = make_context(memory)

    recalled = asyncio.run(
        brain.recent_weak_concepts(context, topic="소프트맥스 다시 설명해 주세요")
    )
    assert [item["concept"].split(" - ")[0] for item in recalled["memories"]] == [
        "소프트맥스", "역전파", "학습률",
    ]
    assert all(item["course"] == "인공지능개론" for item in recalled["memories"])

    recent = asyncio.run(brain.recent_weak_concepts(context))
    assert [item["concept"].split(" - ")[0] for item in recent["memories"]] == [
        "역전파", "학습률", "소프트맥스",
    ]
