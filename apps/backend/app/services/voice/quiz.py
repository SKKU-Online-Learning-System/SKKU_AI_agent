"""O/X quizzes on one of the learner's weak concepts, grounded in the course materials.

The statements are written by the model from the same course-scoped retrieval the
tutor uses, so a quiz cannot test something the professor never taught, and every
answer carries the material it came from. The result of a finished quiz goes
through ``MossMemoryStore.review`` like any other review, so it moves the same
spaced-repetition schedule.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.config import Settings
from app.services.llm_service import LLMService
from app.services.voice.brain import search_course_materials

log = logging.getLogger("voice.quiz")

QUIZ_SIZE = 3
STATEMENT_MAX_CHARS = 200
EXPLANATION_MAX_CHARS = 300

SYSTEM_PROMPT = f"""
You write a short true/false (O/X) quiz in Korean for one university student.
Input: the weak concept the student struggled with, the note describing the
misunderstanding, and excerpts from the course materials.
Return JSON only: {{"items": [{{"statement": Korean sentence, "answer": true or false,
"explanation": one Korean sentence saying why, "source": index of the excerpt used or null}}]}}.
Write exactly {QUIZ_SIZE} items. Each statement is one clear claim that is either true or
false, never both, and never a question. Base every statement only on the excerpts; when
there are none, use only standard textbook facts about the concept. Include at least one
true and one false statement. Make at least one false statement target the recorded
misunderstanding, so answering it shows whether the student still holds it.
""".strip()


class QuizError(RuntimeError):
    """The model could not produce a usable quiz."""


async def make_quiz(memory: dict, *, course_id: str, settings: Settings) -> dict:
    concept = str(memory.get("concept", "")).strip()
    topic = concept.split(" - ", 1)[0].strip() or concept
    raw, _citations = await asyncio.to_thread(search_course_materials, course_id, concept)
    excerpts = [
        {"index": index, "source": item["source"], "excerpt": item["excerpt"][:1500]}
        for index, item in enumerate(json.loads(raw).get("results", []))
    ]
    data = await LLMService(settings, profile="voice").generate_json(
        system=SYSTEM_PROMPT,
        payload={
            "quiz_concept": concept,
            "difficulty_note": str(memory.get("difficulty_note", "")),
            "course_materials": excerpts,
        },
        max_tokens=1200,
    )
    items = _valid_items(data, [item["source"] for item in excerpts])
    if not items:
        log.warning("quiz generation returned no usable item: %.500r", data)
        raise QuizError("퀴즈를 만들지 못했어요. 잠시 후 다시 시도해 주세요.")
    return {"memory_id": memory.get("id", ""), "concept": concept, "topic": topic, "items": items}


def _valid_items(data: dict, sources: list[str]) -> list[dict]:
    """Keep only well-formed items: a claim, a boolean answer and a reason."""
    items = []
    for raw in (data.get("items") if isinstance(data, dict) else None) or []:
        if not isinstance(raw, dict) or type(raw.get("answer")) is not bool:
            continue
        statement = str(raw.get("statement", "")).strip()
        explanation = str(raw.get("explanation", "")).strip()
        if not statement or not explanation:
            continue
        index = raw.get("source")
        items.append(
            {
                "statement": statement[:STATEMENT_MAX_CHARS],
                "answer": raw["answer"],
                "explanation": explanation[:EXPLANATION_MAX_CHARS],
                # Sources are the server's own labels, never text the model wrote.
                "source": sources[index]
                if type(index) is int and 0 <= index < len(sources)
                else None,
            }
        )
    return items[:QUIZ_SIZE]


def passed(correct: int, total: int) -> bool:
    """Two out of three counts as a successful review."""
    return total > 0 and correct * 3 >= total * 2
