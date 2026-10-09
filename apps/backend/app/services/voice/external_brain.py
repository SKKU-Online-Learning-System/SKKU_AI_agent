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
"concept" must be a label in the form "주제 - 구체 설명": the technical concept name,
then " - ", then the specific point the student struggled with (for example
"소프트맥스 - 점수를 합이 1인 확률로 바꾸는 계산", "트랜스포머 - MHSA 레이어와 순서 정보 추가").
Never copy the tutor's greeting, question, or sentence as the concept. Take the
concept name from what the student said they do not understand or from the concept the
tutor was explaining, never from the tutor's wording of the question itself.
"difficulty_note" describes the observed misunderstanding in one Korean sentence.
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
            await self._apply(decision, memories, uncertainty)
        log.info(
            "external brain completed source=%s elapsed_ms=%s",
            source,
            round((time.perf_counter() - started_at) * 1000),
        )

    async def _apply(
        self,
        decision: dict,
        memories: list[dict],
        evidence: list[dict[str, str]] | None = None,
    ) -> None:
        save = decision.get("save")
        if isinstance(save, dict):
            concept = str(save.get("concept", "")).strip()
            question = str(save.get("original_question", "")).strip()
            note = str(save.get("difficulty_note", "")).strip()
            if _looks_like_tutor_utterance(concept):
                # The model echoed the tutor's question instead of naming the
                # concept; fall back to the "주제 - 구체 설명" label built from
                # the evidence, or skip the save when nothing names a concept.
                replacement = _concept_from_evidence(evidence[-1]) if evidence else None
                log.info(
                    "external brain concept looked like a tutor utterance; replaced %r with %r",
                    concept,
                    replacement,
                )
                concept = replacement or ""
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
    concept = _concept_from_evidence(latest)
    if concept is None:
        # Neither the student nor the tutor named a concept (for example a bare
        # "모르겠어" after a greeting); there is nothing worth remembering.
        return {"save": None, "reviews": []}
    topic = concept.split(" - ", 1)[0]
    return {
        "save": {
            "concept": concept,
            "original_question": f"{tutor_prompt} / 학생 응답: {student_response}",
            "difficulty_note": (
                f"학생이 '{student_response}'라고 명시적으로 표현해 "
                f"'{topic}' 이해에 어려움을 보임"
            ),
        },
        "reviews": [],
    }


# --------------------------------------------------------------------------
# "주제 - 구체 설명" label construction without a model.
# --------------------------------------------------------------------------

TOPIC_MAX_LENGTH = 60
DETAIL_MAX_LENGTH = 70
GENERIC_DEFINITION_DETAIL = "정의와 기본 개념"
GENERIC_DETAIL = "개념 이해"

# Words a student or tutor sentence can start with that never name a concept.
_NON_TOPIC_WORDS = frozenset(
    {
        "그냥", "이거", "그거", "저거", "이게", "그게", "저게", "이것", "그것", "저것",
        "이건", "그건", "저건", "나", "저", "난", "전", "나는", "저는", "우리", "우리는",
        "음", "어", "아", "네", "응", "다", "전부", "전체", "아직", "솔직히", "그", "이",
        "여기", "거기", "오늘", "지금", "이번", "이 부분", "그 부분", "이 문제", "그 문제",
        "뭐", "무엇", "뭔지", "그게 뭔지", "설명", "질문", "답", "내용",
    }
)
_GREETING_MARKERS = ("안녕", "환영", "궁금하신", "궁금한 점", "도와드릴", "반가")

# Trailing part of a student's confusion ("...이 뭔지 잘 모르겠어") removed to
# leave the concept the student named.
_STUDENT_CONFUSION_TAIL = re.compile(
    r"(?:\s*(?:이라는\s*(?:게|건|것은)|라는\s*(?:게|건|것은)|이란|란|이|가|은|는|을|를|도))?"
    r"\s*(?P<question>뭔지|무엇인지|뭐인지|어떤\s*건지|어떤\s*것인지|왜\s*\S+|어떻게\s*\S+|어디에\s*\S+)?"
    r"\s*(?:정확히|하나도|전혀|완전히|좀|약간|아직|잘|아예|진짜|너무|아직도)?\s*"
    r"(?:모르겠|모르|기억\s*안|기억이\s*안|감이\s*안|이해\s*안|이해가\s*안|이해가\s*잘\s*안"
    r"|설명\s*못|설명을\s*못|헷갈|어렵|어려).*$",
    re.DOTALL,
)
_DEFINITION_MARKERS = re.compile(r"뭔지|무엇인지|뭐인지|뭐야|뭐예요|뭐에요|무엇인가요|뭔가요|뭘까요|무엇일까요|정의")
_LEADING_FILLER = re.compile(r"^(?:음+|어+|아+|그+|저기|근데|그런데|사실|솔직히|그니까|그러니까)[,\s]+")

# "소프트맥스는 점수를 확률로 바꾸는 함수예요." -> topic / detail.
_DEFINITION_SENTENCE = re.compile(
    r"^(?P<topic>.{1,40}?)\s*(?:이라는\s*(?:건|것은|것이|게)|라는\s*(?:건|것은|것이|게)|이란|란|은|는)\s+"
    r"(?P<detail>.+?)"
    r"(?:이에요|예요|에요|입니다|이다|이야|야|죠|이죠|이지요|지요|인데요|이거든요|거든요|입니다만|이랍니다|랍니다)"
    r"\s*[.!]?$"
)
# "Query와 Key의 역할을 말해 볼까요?" -> "Query와 Key의 역할".
_QUESTION_TAIL = re.compile(
    r"(?:을|를|이|가|은|는)?\s*"
    r"(?:설명해|말해|생각해|찾아|풀어|구해|계산해|적어|써|골라|비교해|정리해|떠올려"
    r"|뭘까요|무엇일까요|무엇인가요|뭔가요|무엇이라고|어떻게\s*될까요|어떻게\s*되나요"
    r"|얼마일까요|얼마가\s*될까요|왜일까요|왜\s*그럴까요|어떤\s*걸까요|어떤\s*것일까요"
    r"|아시나요|아세요|알고\s*있나요|기억나세요|기억하시나요).*$"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_UTTERANCE_ENDING = re.compile(
    r"(?:까요|나요|세요|볼까|입니다|합니다|예요|에요|해요|어요|아요|네요|군요|죠|지요)\s*[.!?]*$"
)


def _clean_phrase(value: str, limit: int) -> str:
    compact = " ".join(value.split()).strip(" ,.!?\"'“”‘’()[]")
    compact = _LEADING_FILLER.sub("", compact).strip(" ,.!?\"'")
    return compact[:limit].strip()


def _is_topic(value: str) -> bool:
    if len(value) < 2 or value.casefold() in _NON_TOPIC_WORDS:
        return False
    if any(marker in value for marker in _GREETING_MARKERS):
        return False
    if re.search(r"[.!?]", value):
        return False
    return bool(re.search(r"[가-힣A-Za-z]", value))


def _topic_from_student_response(response: str) -> tuple[str, str]:
    """Return the concept a student names while saying they do not understand it.

    The second value is the specific question the student attached to it
    ("왜 필요한지"), empty when they only asked what the concept is.
    """
    compact = _clean_phrase(response, 400)
    match = _STUDENT_CONFUSION_TAIL.search(compact)
    if match is None:
        return "", ""
    # Only the phrase before the confusion counts as the topic.
    topic = _clean_phrase(compact[: match.start()], TOPIC_MAX_LENGTH)
    if not _is_topic(topic):
        return "", ""
    question = _clean_phrase(match.group("question") or "", DETAIL_MAX_LENGTH)
    if _DEFINITION_MARKERS.search(question):
        question = ""
    return topic, question


def _topic_and_detail_from_tutor_prompt(prompt: str) -> tuple[str, str]:
    """Split the tutor's last turn into the concept it explained and the specific point."""
    compact = " ".join(prompt.split()).strip()
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(compact) if part.strip()]
    # Prefer a sentence that defines something: "X는 ...예요."
    for sentence in sentences:
        if any(marker in sentence for marker in _GREETING_MARKERS):
            continue
        match = _DEFINITION_SENTENCE.match(sentence)
        if not match:
            continue
        topic = _clean_phrase(match.group("topic"), TOPIC_MAX_LENGTH)
        detail = _clean_phrase(match.group("detail"), DETAIL_MAX_LENGTH)
        if _is_topic(topic):
            return topic, detail
    # Otherwise use the question itself: "Query와 Key의 역할을 말해 볼까요?"
    for sentence in reversed(sentences):
        if any(marker in sentence for marker in _GREETING_MARKERS):
            continue
        phrase = _clean_phrase(_QUESTION_TAIL.sub("", sentence), 120)
        if phrase == _clean_phrase(sentence, 120) or not phrase:
            continue
        if len(phrase) > TOPIC_MAX_LENGTH or not _is_topic(phrase):
            continue
        # "경사하강법에서 학습률이 크면" / "Query와 Key의 역할" -> topic, point.
        for separator in ("에서 ", "의 "):
            head, found, tail = phrase.partition(separator)
            if found and _is_topic(head) and tail:
                return head, tail
        return phrase, ""
    return "", ""


def _concept_from_evidence(evidence: dict[str, str]) -> str | None:
    """Build a "주제 - 구체 설명" label from one confusion exchange, or None."""
    tutor_prompt = evidence.get("preceding_tutor_prompt", "")
    student_response = evidence.get("student_response", "")
    student_topic, student_question = _topic_from_student_response(student_response)
    tutor_topic, tutor_detail = _topic_and_detail_from_tutor_prompt(tutor_prompt)
    topic = student_topic or tutor_topic
    if not topic:
        return None
    detail = student_question
    if not detail and tutor_detail and (
        not student_topic or _same_topic(student_topic, tutor_topic)
    ):
        detail = tutor_detail
    if not detail:
        asks_definition = _DEFINITION_MARKERS.search(student_response) or (
            not student_topic and _DEFINITION_MARKERS.search(tutor_prompt)
        )
        detail = GENERIC_DEFINITION_DETAIL if asks_definition else GENERIC_DETAIL
    return f"{topic} - {detail}"


def _same_topic(first: str, second: str) -> bool:
    left = re.sub(r"\s+", "", first).casefold()
    right = re.sub(r"\s+", "", second).casefold()
    return bool(left and right) and (left in right or right in left)


def _looks_like_tutor_utterance(concept: str) -> bool:
    """True when a concept label is really a sentence the tutor said."""
    if not concept:
        return False
    if "?" in concept or len(concept) > 80:
        return True
    if any(marker in concept for marker in _GREETING_MARKERS):
        return True
    return bool(_UTTERANCE_ENDING.search(concept))
