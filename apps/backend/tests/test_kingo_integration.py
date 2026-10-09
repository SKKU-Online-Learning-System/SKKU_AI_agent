import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CourseMaterialStatus
from app.services.voice import agent_spec
from app.services.voice.external_brain import (
    ExternalBrain,
    _concept_from_evidence,
    _explicit_uncertainty_evidence,
)
from app.services.voice.visual_router import VisualDecision, decide_visualization, parse_decision


def test_realtime_exposes_exactly_the_three_kingo_tools() -> None:
    assert [tool["name"] for tool in agent_spec.json_schemas()] == [
        "search_course_materials",
        "search_trusted_web",
        "show_visualization",
    ]


def test_socratic_persona_keeps_memory_and_visual_priority() -> None:
    prompt = agent_spec.persona(
        "인공지능개론",
        "socratic",
        {"found": True, "memories": [{"concept": "Self-Attention"}]},
    )
    assert "Self-Attention" in prompt
    assert "show_visualization" in prompt
    assert agent_spec.SOCRATIC_PROMPT in prompt


def test_visual_decision_accepts_only_renderable_payloads() -> None:
    assert parse_decision({"needed": False, "kind": "none"}) == VisualDecision(False)
    decision = parse_decision(
        {
            "needed": True,
            "kind": "flow",
            "title": "어텐션 흐름",
            "caption": "정보가 가중 결합돼요.",
            "labels": ["Query-Key 비교", "가중치", "Value 결합"],
        }
    )
    assert decision.needed is True
    assert decision.args and decision.args["labels"][-1] == "Value 결합"

    string_labels = parse_decision(
        {
            "needed": True,
            "kind": "flow",
            "title": "트랜스포머 구조",
            "caption": "정보 흐름",
            "labels": "입력 → Self-Attention → 출력",
        }
    )
    assert string_labels.args and string_labels.args["labels"] == [
        "입력",
        "Self-Attention",
        "출력",
    ]


@pytest.mark.asyncio
async def test_visual_router_shows_no_visual_when_the_model_fails() -> None:
    """A visual is an optional aid, so an unavailable router degrades to silence.

    Standing in a canned diagram would put a clue no model chose in front of a
    student, and into the ChatLog, indistinguishable from a real decision.
    """
    with (
        patch(
            "app.services.voice.visual_router.LLMService.generate_json",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ),
        patch(
            "app.services.voice.visual_router.get_settings",
            return_value=SimpleNamespace(use_mock_llm=False, visual_router_timeout_seconds=1),
        ),
    ):
        decision = await decide_visualization("Self-Attention을 설명해 줘", [])
    assert decision.needed is False
    assert decision.args is None


@pytest.mark.asyncio
async def test_visual_router_keeps_a_demo_stub_for_the_mock_provider() -> None:
    """USE_MOCK_LLM runs the whole product with no model server, visuals included."""
    with patch(
        "app.services.voice.visual_router.get_settings",
        return_value=SimpleNamespace(use_mock_llm=True, visual_router_timeout_seconds=1),
    ):
        decision = await decide_visualization("Self-Attention을 설명해 줘", [])
    assert decision.needed is True
    assert decision.kind == "formula"


def test_pdf_visualization_resolves_natural_filename_and_recent_duplicate() -> None:
    older = SimpleNamespace(
        id="old",
        original_file_name="lecture06_Transformer_Part1.pdf",
        processing_status=CourseMaterialStatus.completed,
    )
    recent = SimpleNamespace(
        id="recent",
        original_file_name="lecture06_Transformer_Part1.pdf",
        processing_status=CourseMaterialStatus.completed,
    )
    context = SimpleNamespace(last_material_sources=[{"material_id": "recent"}])

    resolved = agent_spec._resolve_pdf_material(
        context,
        {"file": "Transformer Part 1", "page": 3},
        [older, recent],
    )

    assert resolved is recent


def test_external_brain_pairs_explicit_uncertainty_with_tutor_prompt() -> None:
    evidence = _explicit_uncertainty_evidence(
        [
            {"role": "assistant", "content": "Query와 Key의 역할을 말해 볼까요?"},
            {"role": "user", "content": "잘 모르겠어요."},
        ]
    )
    assert evidence == [
        {
            "preceding_tutor_prompt": "Query와 Key의 역할을 말해 볼까요?",
            "student_response": "잘 모르겠어요.",
        }
    ]


@pytest.mark.asyncio
async def test_external_brain_applies_only_known_reviews_and_valid_korean_save() -> None:
    memory = AsyncMock()
    worker = ExternalBrain(memory, "인공지능개론")
    await worker._apply(
        {
            "save": {
                "concept": "어텐션 가중치",
                "original_question": "왜 Query와 Key를 곱하나요?",
                "difficulty_note": "유사도와 가중치의 관계를 혼동함",
            },
            "reviews": [
                {"memory_id": "known", "correct": True},
                {"memory_id": "invented", "correct": False},
            ],
        },
        [{"id": "known"}],
    )
    memory.save.assert_awaited_once()
    memory.review.assert_awaited_once_with("known", True)


@pytest.mark.asyncio
async def test_external_brain_saves_explicit_confusion_in_mock_mode() -> None:
    memory = AsyncMock()
    memory.all_memories.return_value = []
    worker = ExternalBrain(memory, "인공지능개론")
    conversation = [
        {"role": "assistant", "content": "Query와 Key의 역할을 말해 볼까요?"},
        {"role": "user", "content": "잘 모르겠어요."},
    ]
    with patch(
        "app.services.voice.external_brain.get_settings",
        return_value=SimpleNamespace(use_mock_llm=True),
    ):
        await worker.assess(conversation, source="test")

    memory.save.assert_awaited_once()
    course, concept, question, note = memory.save.await_args.args
    assert course == "인공지능개론"
    assert concept == "Query와 Key - 역할"
    assert "잘 모르겠어요" in question
    assert "어려움" in note


@pytest.mark.parametrize(
    ("tutor_prompt", "student_response", "expected"),
    [
        # The student names the concept; the tutor's greeting must not leak in.
        (
            "안녕하세요! 인공지능 개론 수업에 오신 것을 환영합니다. 오늘 어떤 부분이 궁금하신가요",
            "스케일드닷 프로덕터 텐션이 뭔지 모르겠어.",
            "스케일드닷 프로덕터 텐션 - 정의와 기본 개념",
        ),
        # A bare "모르겠어" after an explanation takes the explained concept.
        (
            "소프트맥스는 점수들을 확률처럼 합이 1이 되도록 변환하는 함수예요. "
            "예를 들어 점수 2와 3을 softmax에 넣으면 어떻게 될까요",
            "모르겠어.",
            "소프트맥스 - 점수들을 확률처럼 합이 1이 되도록 변환하는 함수",
        ),
        (
            "트랜스포머는 단어의 순서와 관계없이 문맥을 이해할 수 있도록 설계된 신경망 "
            "아키텍처예요. 이 모델의 핵심 아이디어는 무엇이라고 생각하나요?",
            "모르겠네",
            "트랜스포머 - 단어의 순서와 관계없이 문맥을 이해할 수 있도록 설계된 신경망 아키텍처",
        ),
        # The student's own sub-question becomes the specific point.
        (
            "역전파는 오차를 뒤로 전달해 가중치를 갱신하는 방법이에요.",
            "연쇄법칙이 왜 필요한지 이해가 안 돼",
            "연쇄법칙 - 왜 필요한지",
        ),
        ("경사하강법에서 학습률이 크면 어떻게 될까요?", "그냥 모르겠어", "경사하강법 - 학습률이 크면"),
        # Nothing names a concept, so nothing is worth saving.
        ("안녕하세요! 오늘 어떤 부분이 궁금하신가요?", "모르겠어", None),
    ],
)
def test_external_brain_fallback_builds_topic_detail_labels(
    tutor_prompt: str, student_response: str, expected: str | None
) -> None:
    concept = _concept_from_evidence(
        {"preceding_tutor_prompt": tutor_prompt, "student_response": student_response}
    )
    assert concept == expected


@pytest.mark.asyncio
async def test_external_brain_replaces_model_concept_that_echoes_the_tutor() -> None:
    memory = AsyncMock()
    worker = ExternalBrain(memory, "인공지능개론")
    tutor_prompt = "소프트맥스는 점수들을 확률처럼 합이 1이 되도록 변환하는 함수예요. 2와 3을 넣으면 어떻게 될까요"
    await worker._apply(
        {
            "save": {
                "concept": tutor_prompt,
                "original_question": "모르겠어",
                "difficulty_note": "학생이 명시적으로 혼란을 표현함",
            },
            "reviews": [],
        },
        [],
        [{"preceding_tutor_prompt": tutor_prompt, "student_response": "모르겠어"}],
    )
    memory.save.assert_awaited_once()
    assert memory.save.await_args.args[1] == "소프트맥스 - 점수들을 확률처럼 합이 1이 되도록 변환하는 함수"


@pytest.mark.asyncio
async def test_external_brain_drops_echoed_concept_without_evidence() -> None:
    memory = AsyncMock()
    worker = ExternalBrain(memory, "인공지능개론")
    await worker._apply(
        {
            "save": {
                "concept": "안녕하세요! 인공지능 개론 수업에 오신 것을 환영합니다",
                "original_question": "모르겠어",
                "difficulty_note": "학생이 명시적으로 혼란을 표현함",
            },
            "reviews": [],
        },
        [],
    )
    memory.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_brain_does_not_save_an_ordinary_first_question() -> None:
    memory = AsyncMock()
    memory.all_memories.return_value = []
    worker = ExternalBrain(memory, "인공지능개론")
    with patch(
        "app.services.voice.external_brain.get_settings",
        return_value=SimpleNamespace(use_mock_llm=True),
    ):
        await worker.assess(
            [{"role": "user", "content": "트랜스포머가 무엇인가요?"}],
            source="test",
        )

    memory.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_brain_trace_logs_input_and_decision(caplog) -> None:
    memory = AsyncMock()
    memory.all_memories.return_value = []
    worker = ExternalBrain(memory, "인공지능개론")
    decision = {"save": None, "reviews": []}
    with (
        patch(
            "app.services.voice.external_brain.get_settings",
            return_value=SimpleNamespace(use_mock_llm=False, voice_trace_content=True),
        ),
        patch(
            "app.services.voice.external_brain.LLMService.generate_json",
            new=AsyncMock(return_value=decision),
        ),
        caplog.at_level(logging.INFO, logger="voice.external-brain"),
    ):
        await worker.assess(
            [{"role": "user", "content": "어텐션이 헷갈려요."}],
            source="test",
        )

    output = caplog.text
    assert "external brain input source=test" in output
    assert "어텐션이 헷갈려요." in output
    assert "external brain decision source=test" in output
