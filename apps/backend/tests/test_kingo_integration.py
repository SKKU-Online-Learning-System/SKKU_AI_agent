from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CourseMaterialStatus
from app.services.voice import agent_spec
from app.services.voice.external_brain import ExternalBrain, _explicit_uncertainty_evidence
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
    assert "exactly one question" in prompt


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
async def test_visual_router_uses_a_safe_attention_fallback_when_model_fails() -> None:
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
    assert concept == "Query와 Key의 역할"
    assert "잘 모르겠어요" in question
    assert "어려움" in note


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
