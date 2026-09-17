"""Agentic visual/no-visual decision gate for realtime teaching turns."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.llm_service import LLMService

log = logging.getLogger("voice.visual-router")

VISUAL_DECISION_PROMPT = """
Decide whether the current teaching step materially benefits from a visual. Consider
the recent conversation so short follow-ups inherit the active concept. Return one JSON
object with: needed, kind, title, caption, latex, labels, file, page. kind must be one of
none, formula, flow, pdf. Use formula for an equation or variable relationship, flow
for a process or structure, and pdf only when an exact filename and page already appear
in context. Keep the caption as a clue, not a final answer. Never invent a PDF location.
Write every user-visible title, caption and label in natural Korean.
When no visual helps, return needed=false, kind=none, empty strings, labels=[], page=0.
""".strip()


@dataclass(frozen=True)
class VisualDecision:
    needed: bool
    kind: str = "none"
    args: dict | None = None


def parse_decision(payload: dict) -> VisualDecision:
    needed = bool(payload.get("needed"))
    kind = str(payload.get("kind", "none"))
    if not needed or kind not in {"formula", "flow", "pdf"}:
        return VisualDecision(False)
    common = {
        "kind": kind,
        "title": str(payload.get("title", "")).strip(),
        "caption": str(payload.get("caption", "")).strip(),
    }
    if not common["title"] or not common["caption"]:
        return VisualDecision(False)
    if kind == "formula":
        latex = str(payload.get("latex", "")).strip()
        if not latex:
            return VisualDecision(False)
        common["latex"] = latex
    elif kind == "flow":
        raw_labels = payload.get("labels", [])
        if isinstance(raw_labels, str):
            raw_labels = re.split(r"\s*(?:→|->|=>|\||,|\n)\s*", raw_labels)
        labels = [str(value).strip() for value in raw_labels if str(value).strip()]
        if len(labels) < 2:
            return VisualDecision(False)
        common["labels"] = labels[:8]
    else:
        file = str(payload.get("file", "")).strip()
        page = int(payload.get("page", 0) or 0)
        if not file or page < 1:
            return VisualDecision(False)
        common.update({"file": file, "page": page})
    return VisualDecision(True, kind, common)


async def decide_visualization(
    current_user: str,
    recent_conversation: list[dict],
) -> VisualDecision:
    """Make a bounded structured decision without delaying realtime indefinitely."""
    current_user = current_user.strip()
    if not current_user:
        return VisualDecision(False)
    settings = get_settings()
    fallback = _fallback_visualization(current_user, recent_conversation)
    if settings.use_mock_llm:
        log.info(
            "visual decision using local fallback needed=%s kind=%s", fallback.needed, fallback.kind
        )
        return fallback
    try:
        payload = await asyncio.wait_for(
            LLMService(settings, profile="voice").generate_json(
                system=VISUAL_DECISION_PROMPT,
                payload={
                    "task": "visual_decision",
                    "recent_conversation": recent_conversation[-6:],
                    "current_user": current_user,
                },
                max_tokens=192,
            ),
            settings.visual_router_timeout_seconds,
        )
        decision = parse_decision(payload)
        log.info("visual decision needed=%s kind=%s", decision.needed, decision.kind)
        return decision
    except TimeoutError:
        log.warning("visual decision timed out")
    except Exception:
        log.exception("visual decision failed")
    return fallback


def _fallback_visualization(
    current_user: str,
    recent_conversation: list[dict],
) -> VisualDecision:
    """Keep core course visuals available when the decision model is offline or mocked."""
    context = " ".join(
        [str(item.get("content", "")) for item in recent_conversation[-4:]] + [current_user]
    ).casefold()
    if "transformer" in context or "트랜스포머" in context:
        args = {
            "kind": "flow",
            "title": "트랜스포머의 기본 구조",
            "caption": "각 블록은 문맥을 모으고 표현을 정제하는 역할을 반복합니다.",
            "labels": [
                "입력 임베딩",
                "Multi-Head Self-Attention",
                "Add & Norm",
                "Feed Forward",
                "Add & Norm",
                "출력",
            ],
        }
        return VisualDecision(True, "flow", args)
    if any(term in context for term in ("self-attention", "self attention", "셀프 어텐션")):
        args = {
            "kind": "formula",
            "title": "Scaled Dot-Product Attention",
            "caption": "Query와 Key의 유사도로 Value를 얼마나 모을지 정합니다.",
            "latex": r"\operatorname{Attention}(Q,K,V)=\operatorname{softmax}"
            r"\left(\frac{QK^{\mathsf T}}{\sqrt{d_k}}\right)V",
        }
        return VisualDecision(True, "formula", args)
    return VisualDecision(False)
