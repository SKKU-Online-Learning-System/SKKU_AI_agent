"""Background weak-concept assessment, ported from KINGO's External Brain."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from app.core.config import get_settings
from app.services.llm_service import LLMService
from app.services.voice.moss_memory import MossMemoryStore

log = logging.getLogger("voice.external-brain")

UNCERTAINTY_MARKERS = (
    "모르겠",
    "잘 모르",
    "기억 안",
    "감이 안",
    "이해 안",
    "설명 못",
    "헷갈",
)

SYSTEM_PROMPT = """
You are a background learning-diagnosis model separated from the speaking tutor.
Inspect only the supplied recent conversation, explicit uncertainty evidence, and
stored weak concepts. Return JSON:
{"save": null or {"concept": Korean string, "original_question": Korean string,
"difficulty_note": Korean string}, "reviews": [{"memory_id": string,
"correct": boolean}]}. Save only explicit confusion, a wrong answer, or an incomplete
explanation. Do not treat an ordinary first question as weakness. Review only known IDs.
Return JSON only.
""".strip()


class ExternalBrain:
    def __init__(self, memory: MossMemoryStore, course_name: str) -> None:
        self.memory = memory
        self.course_name = course_name
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    def schedule(self, conversation: list[dict], *, source: str) -> asyncio.Task[None] | None:
        if not conversation:
            return None
        task = asyncio.create_task(
            self.assess([dict(item) for item in conversation], source=source)
        )
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            log.exception("background weak-concept assessment failed")

    async def assess(self, conversation: list[dict], *, source: str) -> None:
        started_at = time.perf_counter()
        async with self._lock:
            memories = await self.memory.all_memories()
            recent = conversation[-12:]
            uncertainty = _explicit_uncertainty_evidence(recent)
            settings = get_settings()
            if getattr(settings, "voice_trace_content", False):
                log.info(
                    "external brain input source=%s conversation=%.8000r uncertainty=%.4000r memories=%.4000r",
                    source,
                    recent,
                    uncertainty,
                    memories,
                )
            try:
                decision = await LLMService(settings).generate_json(
                    system=SYSTEM_PROMPT,
                    payload={
                        "conversation": recent,
                        "explicit_uncertainty_evidence": uncertainty,
                        "stored_weak_concepts": [
                            {
                                "memory_id": item.get("id"),
                                "concept": item.get("concept"),
                                "difficulty_note": item.get("difficulty_note"),
                                "status": item.get("status"),
                            }
                            for item in memories
                        ],
                    },
                )
            except Exception:
                log.exception("external brain model failed; applying safe fallback")
                decision = _fallback_decision(uncertainty)
            else:
                # The deterministic mock intentionally performs no diagnosis.
                # Preserve useful local behavior for explicit learner confusion.
                if settings.use_mock_llm and decision.get("save") is None:
                    decision["save"] = _fallback_decision(uncertainty)["save"]
            if getattr(settings, "voice_trace_content", False):
                log.info(
                    "external brain decision source=%s decision=%.8000r",
                    source,
                    decision,
                )
            await self._apply(decision, memories)
        log.info(
            "external brain completed source=%s elapsed_ms=%s",
            source,
            round((time.perf_counter() - started_at) * 1000),
        )

    async def _apply(self, decision: dict, memories: list[dict]) -> None:
        save = decision.get("save")
        if isinstance(save, dict):
            concept = str(save.get("concept", "")).strip()
            question = str(save.get("original_question", "")).strip()
            note = str(save.get("difficulty_note", "")).strip()
            if concept and question and note and _contains_korean(concept + note):
                await self.memory.save(self.course_name, concept, question, note)

        known = {str(item.get("id")) for item in memories if item.get("id")}
        seen: set[str] = set()
        for review in decision.get("reviews", []):
            if not isinstance(review, dict):
                continue
            memory_id = str(review.get("memory_id", "")).strip()
            correct = review.get("correct")
            if memory_id in known and memory_id not in seen and type(correct) is bool:
                seen.add(memory_id)
                await self.memory.review(memory_id, correct)

    async def flush(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


def _explicit_uncertainty_evidence(conversation: list[dict]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    previous_assistant = ""
    for message in conversation:
        role = message.get("role")
        content = str(message.get("content", "")).strip()
        if role == "assistant":
            previous_assistant = content
        elif role == "user" and any(marker in content.casefold() for marker in UNCERTAINTY_MARKERS):
            evidence.append(
                {
                    "preceding_tutor_prompt": previous_assistant,
                    "student_response": content,
                }
            )
    return evidence


def _contains_korean(value: str) -> bool:
    return any("가" <= character <= "힣" for character in value)


def _fallback_decision(evidence: list[dict[str, str]]) -> dict:
    """Capture only explicit confusion when model diagnosis is unavailable."""
    if not evidence:
        return {"save": None, "reviews": []}
    latest = evidence[-1]
    tutor_prompt = latest.get("preceding_tutor_prompt", "").strip()
    student_response = latest.get("student_response", "").strip()
    if not tutor_prompt or not student_response:
        return {"save": None, "reviews": []}
    concept = _concept_from_tutor_prompt(tutor_prompt)
    return {
        "save": {
            "concept": concept,
            "original_question": f"{tutor_prompt} / 학생 응답: {student_response}",
            "difficulty_note": (
                f"학생이 '{student_response}'라고 명시적으로 표현해 "
                f"'{concept}' 이해에 어려움을 보임"
            ),
        },
        "reviews": [],
    }


def _concept_from_tutor_prompt(prompt: str) -> str:
    compact = " ".join(prompt.split()).strip(" ?.!\"'")
    concept = re.sub(
        r"(?:을|를|이|가|은|는)?\s*(?:설명해|말해|생각해|찾아|풀어|구해).*$",
        "",
        compact,
    ).strip(" ?.!\"'")
    return (concept or compact)[:100]
