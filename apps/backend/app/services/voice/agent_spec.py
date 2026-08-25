"""Provider-neutral realtime KINGO persona and three-tool adapter."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import CourseMaterial, CourseMaterialStatus, DocumentChunk
from app.services.voice.brain import MODE_PROMPTS, TOOLS, StageTimer, VoiceContext
from app.services.voice.brain import run_tool as run_brain_tool

log = logging.getLogger("voice.agent-spec")

VOICE_SYSTEM_PROMPT = """
# Role
You are KINGO, a Socratic voice TA. Speak brief, natural Korean in polite style.

# Memory
Use up to three preloaded weak concepts only when relevant; never invent.

# Tools
Only immediately before calling search_course_materials, search_trusted_web, or
show_visualization, say one short topic-specific Korean filler. Never guess search
results or reveal formula/visual data in the filler. Follow tool-result instructions.
Use trusted web only when course evidence is insufficient.

# Visualization
Visualization is part of teaching, not decoration. Prefer show_visualization for a
helpful formula, process, structure, or exact PDF page. In Socratic mode use it as a
clue, not the final answer. Speak only its meaning; never read raw visual data aloud.
All user-visible visualization text must be Korean except formulas and standard terms.

# Output
Keep each turn short and conversational. Never read raw JSON aloud.
""".strip()

VOICE_SOCRATIC_VISUAL_RULE = """
# Socratic visual priority
A visual clue is not a spoken explanation. When the current reasoning step has a useful
formula, process, or structure, call show_visualization before the one Socratic
question. Keep the visual a clue and never use it to reveal the final answer.
""".strip()

VOICE_COURSE_TOOL = {
    "type": "function",
    "name": "search_course_materials",
    "description": (
        "Search uploaded course materials. Say one short topic-specific Korean filler "
        "immediately before this call and follow returned teaching instructions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Focused terms from the student's question.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

VOICE_VISUALIZATION_TOOL = {
    "type": "function",
    "name": "show_visualization",
    "description": (
        "Show a visual when a formula, process, structure, or exact course PDF page "
        "helps the student reason. Treat it as a clue in Socratic mode."
    ),
    "parameters": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "formula"},
                    "title": {"type": "string"},
                    "caption": {"type": "string"},
                    "latex": {"type": "string"},
                },
                "required": ["kind", "title", "caption", "latex"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "flow"},
                    "title": {"type": "string"},
                    "caption": {"type": "string"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 8,
                    },
                },
                "required": ["kind", "title", "caption", "labels"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "const": "pdf"},
                    "title": {"type": "string"},
                    "caption": {"type": "string"},
                    "file": {"type": "string"},
                    "page": {"type": "integer", "minimum": 1},
                    "material_id": {"type": "string"},
                },
                "required": ["kind", "title", "caption", "file", "page"],
                "additionalProperties": False,
            },
        ]
    },
}


def persona(course_name: str, mode: str, memory_context: dict | None = None) -> str:
    """Return the compact realtime policy and recent learner memory."""
    mode_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["socratic"])
    if mode == "socratic":
        mode_prompt = f"{mode_prompt}\n\n{VOICE_SOCRATIC_VISUAL_RULE}"
    memory_json = json.dumps(memory_context or {"found": False}, ensure_ascii=False)
    return "\n\n".join(
        (
            VOICE_SYSTEM_PROMPT,
            f"# Course\nCourse: '{course_name}'. Search is limited to this course.",
            mode_prompt,
            f"# Recent weak concepts\n{memory_json}",
        )
    )


def json_schemas() -> list[dict]:
    """Expose exactly the three conversational tools used by current KINGO."""
    trusted_web = next(
        {"type": "function", **tool["function"]}
        for tool in TOOLS
        if tool["function"]["name"] == "search_trusted_web"
    )
    return [VOICE_COURSE_TOOL, trusted_web, VOICE_VISUALIZATION_TOOL]


def tool_runner(context: VoiceContext) -> Callable[[str, dict], Awaitable[object]]:
    """Bind shared course-scoped tools to one realtime session."""

    async def run(name: str, args: dict) -> object:
        result = json.loads(await run_brain_tool(context, name, args, StageTimer()))
        if name == "search_course_materials" and result.get("found"):
            result["instruction"] = {
                "grounding": "Teach from this evidence and cite filename/page.",
                "teaching": "Keep the mode; in Socratic mode ask one next step.",
                "visualization": (
                    "Prefer show_visualization for a useful formula, flow, or PDF page. "
                    "Use it as a clue, not the final answer."
                ),
            }
        elif name == "search_trusted_web" and result.get("found"):
            result["instruction"] = {
                "grounding": "Use web evidence only for course-material gaps.",
                "teaching": "Keep the selected teaching mode.",
                "visualization": "Prefer a useful visual when it clarifies the concept.",
                "sources": "Do not read raw URLs aloud.",
            }
        elif name == "show_visualization" and result.get("kind") == "pdf":
            with SessionLocal() as session:
                materials = list(
                    session.scalars(
                        select(CourseMaterial)
                        .where(
                            CourseMaterial.course_id == context.course_id,
                            func.lower(CourseMaterial.file_type) == "pdf",
                        )
                        .order_by(CourseMaterial.updated_at.desc(), CourseMaterial.id)
                    )
                )
                material = _resolve_pdf_material(context, result, materials)
                if material is None:
                    failure = {
                        "error": "requested PDF did not match a processed course material",
                        "available_files": sorted(
                            {item.original_file_name for item in materials if _is_processed(item)}
                        )[:12],
                    }
                    log.warning(
                        "visualization rejected course_id=%s args=%s result=%s",
                        context.course_id,
                        args,
                        failure,
                    )
                    return failure
                max_page = session.scalar(
                    select(func.max(DocumentChunk.page_number)).where(
                        DocumentChunk.material_id == material.id
                    )
                )
                if max_page and int(result.get("page", 0)) > max_page:
                    failure = {
                        "error": "requested PDF page does not exist",
                        "file": material.original_file_name,
                        "max_page": int(max_page),
                    }
                    log.warning(
                        "visualization rejected course_id=%s args=%s result=%s",
                        context.course_id,
                        args,
                        failure,
                    )
                    return failure
                result["material_id"] = material.id
                result["file"] = material.original_file_name
        if name == "show_visualization" and "error" in result:
            log.warning(
                "visualization rejected course_id=%s args=%s result=%s",
                context.course_id,
                args,
                result,
            )
        return result

    return run


def _is_processed(material: CourseMaterial) -> bool:
    return material.processing_status == CourseMaterialStatus.completed


def _file_key(value: object) -> str:
    name = Path(str(value or "")).name
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _file_terms(value: object) -> set[str]:
    name = Path(str(value or "")).stem
    return {
        term
        for term in re.findall(r"[0-9a-zA-Z가-힣]+", unicodedata.normalize("NFKC", name).casefold())
        if len(term) > 1 and term not in {"pdf", "lecture"}
    }


def _resolve_pdf_material(
    context: VoiceContext,
    visualization: dict,
    materials: list[CourseMaterial],
) -> CourseMaterial | None:
    """Resolve model-friendly PDF references back to one authorized material."""
    processed = [material for material in materials if _is_processed(material)]
    if not processed:
        return None

    requested_id = str(visualization.get("material_id", "")).strip()
    if requested_id:
        match = next((material for material in processed if material.id == requested_id), None)
        if match is not None:
            return match

    recent_ids = [
        str(source.get("material_id", ""))
        for source in context.last_material_sources
        if isinstance(source, dict) and source.get("material_id")
    ]
    requested_key = _file_key(visualization.get("file"))
    exact = [
        material
        for material in processed
        if _file_key(material.original_file_name) == requested_key
    ]
    if exact:
        return next(
            (material for material in exact if material.id in recent_ids),
            exact[0],
        )

    requested_terms = _file_terms(visualization.get("file"))
    scored = sorted(
        (
            (
                len(requested_terms & _file_terms(material.original_file_name)),
                material.id in recent_ids,
                material,
            )
            for material in processed
        ),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    if scored and scored[0][0] > 0:
        return scored[0][2]

    recent = [material for material in processed if material.id in recent_ids]
    return recent[0] if len(recent) == 1 else None
