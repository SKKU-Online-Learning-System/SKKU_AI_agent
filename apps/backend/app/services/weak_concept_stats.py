"""Course-level weak-concept statistics for professors and administrators.

The course agent's External Brain captures weak concepts per student and keeps
them in the weak-concept file (see ``moss_memory``). This module turns those
records into the teaching-side view: which concepts trip up how many students,
how far along each is, who is due for a review, and what was captured lately.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

STATUSES = ("new", "practicing", "mastered")
TOP_CONCEPTS = 30
TOP_TOPICS = 15
RECENT_CAPTURES = 10
SAMPLE_NOTES = 3
WEAKEST_PER_STUDENT = 3

LabelFor = Callable[[str], str]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str | None:
    seconds = _number(value)
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _mastery(memory: dict) -> int:
    return round(min(max(_number(memory.get("confidence")), 0.0), 1.0) * 100)


def _status(memory: dict) -> str:
    status = str(memory.get("status") or "new")
    return status if status in STATUSES else "new"


def _concept(memory: dict) -> str:
    return str(memory.get("concept") or "").strip()


def _student(memory: dict) -> str:
    return str(memory.get("student_id") or "")


def _status_counts(memories: Iterable[dict]) -> dict[str, int]:
    counts = Counter(_status(memory) for memory in memories)
    return {status: counts.get(status, 0) for status in STATUSES}


def _average_mastery(memories: list[dict]) -> int:
    if not memories:
        return 0
    return round(sum(_mastery(memory) for memory in memories) / len(memories))


def _last_seen(memories: Iterable[dict]) -> float:
    return max((_number(memory.get("last_seen_at")) for memory in memories), default=0.0)


def _due_count(memories: Iterable[dict], now: float) -> int:
    return sum(
        1
        for memory in memories
        if _status(memory) != "mastered" and _number(memory.get("next_review_at")) <= now
    )


def split_concept(label: str) -> tuple[str, str]:
    """Split a "주제 - 구체 설명" label into its topic and the specific point."""
    topic, separator, detail = str(label).partition(" - ")
    return (topic.strip() or str(label).strip(), detail.strip() if separator else "")


def _course_key(name: Any) -> str:
    # Course names reach the memory file from the database and from macOS clients,
    # so the same Korean word can arrive composed (NFC) or decomposed (NFD).
    return unicodedata.normalize("NFC", str(name or "")).strip()


def course_memories(memories: Iterable[dict], course_name: str) -> list[dict]:
    """Records captured for one course; memories store the course by name."""
    wanted = _course_key(course_name)
    return [
        memory
        for memory in memories
        if isinstance(memory, dict)
        and _course_key(memory.get("course")) == wanted
        and _concept(memory)
    ]


def summarize_course(memories: list[dict], *, now: float) -> dict[str, Any]:
    """The counts one course row on the dashboard shows."""
    return {
        "recordCount": len(memories),
        "conceptCount": len({_concept(memory) for memory in memories}),
        "studentCount": len({_student(memory) for memory in memories if _student(memory)}),
        "statusCounts": _status_counts(memories),
        "averageMastery": _average_mastery(memories),
        "dueReviewCount": _due_count(memories, now),
        "lastActivityAt": _iso(_last_seen(memories)),
    }


def summarize_totals(
    course_summaries: list[dict], memories: list[dict], *, now: float
) -> dict[str, Any]:
    """Totals across the listed courses; ``courseCount`` counts courses with any record."""
    totals = summarize_course(memories, now=now)
    totals["courseCount"] = sum(1 for summary in course_summaries if summary["recordCount"])
    return totals


def _concept_rows(memories: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for memory in memories:
        grouped[_concept(memory)].append(memory)
    rows = []
    for concept, items in grouped.items():
        topic, detail = split_concept(concept)
        notes: list[str] = []
        for item in sorted(items, key=lambda m: _number(m.get("last_seen_at")), reverse=True):
            note = str(item.get("difficulty_note") or "").strip()
            if note and note not in notes:
                notes.append(note)
            if len(notes) >= SAMPLE_NOTES:
                break
        rows.append(
            {
                "concept": concept,
                "topic": topic,
                "detail": detail,
                "studentCount": len({_student(item) for item in items}),
                "failureCount": sum(int(_number(item.get("failure_count"))) for item in items),
                "successCount": sum(int(_number(item.get("success_count"))) for item in items),
                "statusCounts": _status_counts(items),
                "averageMastery": _average_mastery(items),
                "lastSeenAt": _iso(_last_seen(items)),
                "sampleNotes": notes,
            }
        )
    rows.sort(
        key=lambda row: (row["studentCount"], row["failureCount"], row["lastSeenAt"] or ""),
        reverse=True,
    )
    return rows[:TOP_CONCEPTS]


def _topic_rows(memories: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for memory in memories:
        grouped[split_concept(_concept(memory))[0]].append(memory)
    rows = [
        {
            "topic": topic,
            "conceptCount": len({_concept(item) for item in items}),
            "studentCount": len({_student(item) for item in items}),
            "failureCount": sum(int(_number(item.get("failure_count"))) for item in items),
            "averageMastery": _average_mastery(items),
        }
        for topic, items in grouped.items()
    ]
    rows.sort(key=lambda row: (row["studentCount"], row["failureCount"]), reverse=True)
    return rows[:TOP_TOPICS]


def _student_rows(memories: list[dict], label_for: LabelFor, *, now: float) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for memory in memories:
        if _student(memory):
            grouped[_student(memory)].append(memory)
    rows = []
    for student_id, items in grouped.items():
        weakest = sorted(
            items, key=lambda m: (_mastery(m), -int(_number(m.get("failure_count"))))
        )
        rows.append(
            {
                "studentId": student_id,
                "label": label_for(student_id),
                "conceptCount": len(items),
                "statusCounts": _status_counts(items),
                "averageMastery": _average_mastery(items),
                "dueReviewCount": _due_count(items, now),
                "lastSeenAt": _iso(_last_seen(items)),
                "weakestConcepts": [_concept(m) for m in weakest[:WEAKEST_PER_STUDENT]],
            }
        )
    # Most concepts first, then the lowest understanding, then the latest activity.
    rows.sort(
        key=lambda row: (row["conceptCount"], -row["averageMastery"], row["lastSeenAt"] or ""),
        reverse=True,
    )
    return rows


def _saved_by_date(memories: list[dict]) -> list[dict]:
    counts = Counter(
        datetime.fromtimestamp(_number(memory.get("saved_at")), tz=timezone.utc).date().isoformat()
        for memory in memories
        if _number(memory.get("saved_at")) > 0
    )
    return [{"date": date, "count": count} for date, count in sorted(counts.items())]


def _recent_captures(memories: list[dict], label_for: LabelFor) -> list[dict]:
    recent = sorted(memories, key=lambda m: _number(m.get("last_seen_at")), reverse=True)
    return [
        {
            "concept": _concept(memory),
            "status": _status(memory),
            "difficultyNote": str(memory.get("difficulty_note") or ""),
            "studentLabel": label_for(_student(memory)),
            "masteryPercent": _mastery(memory),
            "lastSeenAt": _iso(memory.get("last_seen_at")),
        }
        for memory in recent[:RECENT_CAPTURES]
    ]


def course_detail(memories: list[dict], *, label_for: LabelFor, now: float) -> dict[str, Any]:
    """Everything the per-course statistics view shows."""
    return {
        **summarize_course(memories, now=now),
        "concepts": _concept_rows(memories),
        "topics": _topic_rows(memories),
        "students": _student_rows(memories, label_for, now=now),
        "savedByDate": _saved_by_date(memories),
        "recentCaptures": _recent_captures(memories, label_for),
    }
