"""Turn trace: what the agent is doing, shown to the student while it works.

Every label and detail here is composed by the server from tool arguments and
results, never by the model, so nothing unreviewed reaches the screen before the
answer.
"""

from __future__ import annotations

import re
import time
from typing import Awaitable, Callable, Literal


TurnEventSink = Callable[[dict], Awaitable[None]]
StepState = Literal["running", "done", "failed"]

TOOL_RUNNING_LABELS = {
    "search_trusted_web": "신뢰할 수 있는 웹을 검색하는 중",
    "show_visualization": "시각 자료를 그리는 중",
    "search_course_materials": "강의자료를 검색하는 중",
    "recall_weak_concepts": "이전에 어려워했던 개념을 떠올리는 중",
    "save_weak_concept": "취약 개념을 기록하는 중",
    "review_weak_concept": "복습 결과를 기록하는 중",
}


async def emit_step(
    on_event: TurnEventSink | None,
    key: str,
    state: StepState,
    label: str,
    *,
    detail: str = "",
    stage: str = "",
    started_at: float | None = None,
) -> None:
    """Send one trace step to the UI, if anyone is listening.

    A step is addressed by ``key``: the first event with a key adds the line,
    later ones with the same key update it, so "searching…" becomes "found 3"
    in place. ``label`` is the sentence the student reads; ``detail`` is the
    smaller line under it (a query, filenames). Both are composed here, never by
    the model, so nothing unreviewed reaches the screen before the answer.
    """
    if on_event is None:
        return
    event: dict = {
        "type": "step",
        "key": key,
        "stage": stage or key,
        "state": state,
        "label": label,
    }
    if detail:
        event["detail"] = detail[:200]
    if started_at is not None:
        event["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000)
    await on_event(event)


NO_QUERY_ERROR = "a focused course-material search query is required"


async def emit_rewind(on_event: TurnEventSink | None) -> None:
    """Tell the UI that the answer text streamed so far is not the answer.

    Sent when a draft is discarded -- a regenerated repeat, or a turn retried
    with thinking off after truncation -- so the next tokens replace it instead
    of being appended to it.
    """
    if on_event is not None:
        await on_event({"type": "rewind"})


def tool_step_labels(name: str, args: dict, result: dict) -> tuple[str, str, StepState]:
    """(label, detail, state) for a finished tool call, from its result alone.

    A failure's ``error`` is written for the model (which gets the tool result
    verbatim), not for the student: it can be a Python exception message or an
    HTTP error. Only the few server-composed cases get a Korean detail; anything
    else leaves the detail empty, so exception text never reaches the screen.
    """
    if "error" in result:
        error = str(result.get("error", ""))
        failed = {
            "search_trusted_web": "웹 검색에서 근거를 찾지 못했어요",
            "show_visualization": "시각 자료를 표시하지 못했어요",
        }.get(name, "도구 실행에 실패했어요")
        if "no citable sources" in error:
            detail = "인용할 수 있는 출처가 없었어요"
        elif error.startswith("invalid ") or error.endswith("is required"):
            detail = "도구 인자가 올바르지 않았어요"
        else:
            detail = ""
        return failed, detail, "failed"
    if name == "search_trusted_web":
        sources = result.get("sources") or []
        hosts = []
        for url in sources[:3]:
            host = re.sub(r"^https?://(www\.)?", "", str(url)).split("/", 1)[0]
            if host and host not in hosts:
                hosts.append(host)
        return f"웹 출처 {len(sources)}개를 찾았어요", ", ".join(hosts), "done"
    if name == "show_visualization":
        # Object particle included: 수식을, but 흐름도를.
        kind = {
            "formula": "수식을", "flow": "흐름도를", "plot": "그래프를", "pdf": "자료 페이지를",
        }.get(str(result.get("kind")), "시각 자료를")
        return f"{kind} 준비했어요", str(result.get("title", ""))[:80], "done"
    if name == "search_course_materials":
        results = result.get("results") or []
        return (
            f"강의자료 {len(results)}곳을 찾았어요" if results else "관련 강의자료를 찾지 못했어요",
            ", ".join(str(item.get("source", "")) for item in results[:3]),
            "done",
        )
    if name == "recall_weak_concepts":
        memories = result.get("memories") or []
        return (
            f"취약 개념 {len(memories)}개를 참고해요" if memories else "참고할 취약 개념이 없어요",
            ", ".join(_short(str(item.get("concept", "")), 24) for item in memories[:3]),
            "done",
        )
    return f"{name} 완료", "", "done"


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def timing_detail(started_at: float, first_token_at: float | None, ended_at: float) -> str:
    """"생각 4.1초 · 작성 2.1초": how the round's time split between reasoning and writing."""
    if first_token_at is None:
        return ""
    thought = first_token_at - started_at
    wrote = ended_at - first_token_at
    if thought < 0.05:
        return ""
    return f"생각 {thought:.1f}초 · 작성 {wrote:.1f}초"


def tool_running_detail(name: str, args: dict) -> str:
    for key in ("query", "title", "topic", "concept"):
        value = args.get(key) if isinstance(args, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
