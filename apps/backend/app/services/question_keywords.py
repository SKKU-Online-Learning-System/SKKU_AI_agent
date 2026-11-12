"""Publish course-week counts for approved teaching terms, never free text."""

from collections import Counter, defaultdict
from functools import lru_cache
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatLog, CourseMaterial, CourseMaterialStatus, User, UserRole
from app.schemas.domain import CamelModel

DEFAULT_TERMS = (
    "경사하강법", "학습률", "과적합", "정규화", "지도학습", "비지도학습",
    "교차검증", "손실함수", "회귀", "분류", "신경망", "트랜스포머", "소프트맥스",
    "시계열", "정상성", "자기상관", "이동평균", "차분", "계절성", "ARIMA",
    "푸리에 변환", "표본추출", "확률분포", "표준편차", "상관계수",
    "트랜잭션", "인덱스", "SQL", "형상관리", "요구사항 분석", "단위 테스트",
)

PARTICLE = r"(?:에서는|으로는|에서|으로|에게|부터|까지|은|는|이|가|을|를|의|에|와|과|도|로|만)?"


class KeywordCount(CamelModel):
    keyword: str
    question_count: int


class KeywordWeek(CamelModel):
    week: int
    keywords: list[KeywordCount]


class CourseKeywordCounts(CamelModel):
    course_id: str
    weeks: list[KeywordWeek]


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


@lru_cache(maxsize=64)
def _patterns(terms: tuple[str, ...]) -> tuple[tuple[str, re.Pattern], ...]:
    approved = {}
    for value in terms:
        label = value.strip()
        normalized = _normalize(label)
        if normalized and normalized not in approved:
            approved[normalized] = label
    return tuple(
        (label, re.compile(r"(?<!\w)" + re.escape(term) + PARTICLE + r"(?!\w)"))
        for term, label in approved.items()
    )


def _material_ids(retrieval: dict, sources: list[dict]) -> list[str]:
    # A learner's open slide takes precedence; every candidate is checked
    # against the course's own processed materials before assigning a week.
    focus = retrieval.get("focus_material_id")
    candidates = [focus] if isinstance(focus, str) else []
    candidates.extend(
        material_id
        for source in sources
        if isinstance(source, dict)
        and isinstance(material_id := source.get("material_id"), str)
    )
    return candidates


def course_keyword_counts(
    session: Session,
    course_id: str,
    terms: tuple[str, ...] = DEFAULT_TERMS,
    minimum_students: int = 5,
) -> CourseKeywordCounts:
    material_weeks = dict(session.execute(
        select(CourseMaterial.id, CourseMaterial.week).where(
            CourseMaterial.course_id == course_id,
            CourseMaterial.processing_status == CourseMaterialStatus.completed,
        )
    ).tuples().all())
    patterns = _patterns(terms)
    counts: Counter[tuple[int, str]] = Counter()
    students: dict[tuple[int, str], set[str]] = defaultdict(set)
    rows = session.execute(
        select(
            ChatLog.user_id, ChatLog.question, ChatLog.referenced_documents,
            ChatLog.retrieval_result, ChatLog.safety_result,
        )
        .join(User, ChatLog.user_id == User.id)
        .where(ChatLog.course_id == course_id, User.role == UserRole.student)
        .execution_options(yield_per=256)
    )
    for user_id, question, sources, retrieval, safety in rows:
        if (safety or {}).get("category", "normal") != "normal":
            continue
        week = next(
            (material_weeks[mid] for mid in _material_ids(retrieval or {}, sources or [])
             if mid in material_weeks),
            None,
        )
        if week is None:
            continue
        normalized = _normalize(question)
        for keyword, pattern in patterns:
            if pattern.search(normalized):
                key = (week, keyword)
                counts[key] += 1
                students[key].add(user_id)

    by_week: dict[int, list[KeywordCount]] = defaultdict(list)
    for (week, keyword), count in sorted(
        counts.items(), key=lambda item: (item[0][0], -item[1], item[0][1])
    ):
        if len(students[week, keyword]) >= max(5, minimum_students):
            by_week[week].append(KeywordCount(keyword=keyword, question_count=count))
    return CourseKeywordCounts(
        course_id=course_id,
        weeks=[KeywordWeek(week=week, keywords=keywords) for week, keywords in by_week.items()],
    )
