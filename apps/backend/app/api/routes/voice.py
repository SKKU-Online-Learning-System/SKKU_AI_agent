"""COURSE AGENT endpoints: text answers, hands-free voice, and settings.

Every route is course-scoped and reuses the project's RBAC, SAFE guardrails and
chat-log persistence. The realtime WebSocket authenticates with the same JWT,
passed as a query parameter because browsers cannot set WebSocket headers.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    authorize_course_access,
    authorize_course_manage_permission,
    get_current_user,
)
from app.core.config import Settings, get_settings
from app.core.security import InvalidAccessTokenError, JWTService
from app.db.session import SessionLocal, get_db
from app.models import Course, User
from app.services.llm_service import LLMService
from app.services.rag_service import RagService
from app.services.safety_service import NORMAL_RESULT, SafetyGuardService, SafetyResult
from app.services.voice import agent_spec, attachment_index, voice_log
from app.services.voice import attachments as attachments_module
from app.services.voice.attachments import (
    Attachment,
    AttachmentContent,
    AttachmentValidationError,
)
from app.services.voice.brain import (
    StageTimer,
    VoiceContext,
    attachment_query,
    emit_step,
    last_assistant_turn,
    prefetch_memory_context,
    think,
)
from app.services.voice.factory import (
    create_voice_transport,
    get_voice_availability,
    uses_grok,
)
from app.services.voice.filler import pick_filler
from app.services.voice.session_store import external_brain_for, get_context, reset_context
from app.services.voice.turn_detector import FRAME_BYTES
from app.services.voice.transport import (
    AgentAudio,
    AgentFiller,
    AgentTextBoundary,
    AgentTextDelta,
    AgentTurnDone,
    Failed,
    SessionReady,
    ToolCalled,
    Transcript,
    Transport,
    UserStartedSpeaking,
    UserStoppedSpeaking,
)
from app.services.voice.trusted_sites import (
    add_trusted_domain,
    get_trusted_domains,
    remove_trusted_domain,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])
VOICE_UNAVAILABLE_MESSAGE = "음성 모델 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
# Teaching is always Socratic. Kept as a constant because it is written into the
# ChatLog payload, not because anything can select another mode.
TEACHING_MODE = "socratic"

class VoiceQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    mode: str = "socratic"
    chat_session_id: Optional[str] = None
    # Files the student attached to this question, uploaded first through
    # ``POST .../attachments``. Only the typed path takes them: a voice turn is
    # spoken and heard, and a photo cannot be.
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)


class TrustedSitePayload(BaseModel):
    url: str = Field(min_length=1, max_length=500)


def _session_context(user: User, course: Course) -> VoiceContext:
    return get_context(user.id, course.id, course.name)


def _resume(
    db: Session,
    context: VoiceContext,
    user: User,
    course: Course,
    chat_session_id: Optional[str],
    settings: Optional[Settings] = None,
) -> None:
    """Reload a conversation reopened from 대화 이력, if it is not already loaded."""
    if not chat_session_id or context.chat_session_id == chat_session_id:
        return
    if not voice_log.restore_history(
        db, context, user, course, chat_session_id, settings=settings
    ):
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")


# --------------------------------------------------------------------------
# Configuration and settings
# --------------------------------------------------------------------------


@router.get("/courses/{course_id}/config")
def read_voice_config(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Return what the voice TA screen needs before the first question."""
    course = authorize_course_access(session, current_user, course_id)
    status_ = RagService(session, settings).course_status(course.id)
    can_manage = current_user.role.value in {"professor", "admin"}
    availability = get_voice_availability(settings)
    return {
        "course_id": course.id,
        "course_name": course.name,
        "term": course.semester,
        "voice_enabled": availability.enabled,
        "voice_provider": availability.provider,
        "voice_status": availability.as_dict(),
        "material_count": status_.material_count,
        "is_search_ready": status_.is_search_ready,
        "can_manage": can_manage,
        "trusted_sites": get_trusted_domains(course.id) if can_manage else [],
    }


@router.get("/courses/{course_id}/trusted-sites")
def list_trusted_sites(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """List the professor-managed web-search allowlist for one course."""
    course = authorize_course_manage_permission(session, current_user, course_id)
    return {"sites": get_trusted_domains(course.id)}


@router.post("/courses/{course_id}/trusted-sites")
def create_trusted_site(
    course_id: str,
    payload: TrustedSitePayload,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Add one trusted web-search domain."""
    course = authorize_course_manage_permission(session, current_user, course_id)
    try:
        return {"sites": add_trusted_domain(course.id, payload.url)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/courses/{course_id}/trusted-sites")
def delete_trusted_site(
    course_id: str,
    payload: TrustedSitePayload,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Remove one trusted web-search domain."""
    course = authorize_course_manage_permission(session, current_user, course_id)
    try:
        return {"sites": remove_trusted_domain(course.id, payload.url)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Conversation lifecycle
# --------------------------------------------------------------------------


@router.post("/courses/{course_id}/reset")
def reset_voice_conversation(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Clear the in-memory conversation; stored weak concepts survive."""
    course = authorize_course_access(session, current_user, course_id)
    reset_context(current_user.id, course.id)
    return {"ok": True}


@router.get("/courses/{course_id}/review")
async def read_next_review(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Return the next due weak concept for this learner."""
    from app.services.voice.brain import next_review_prompt

    course = authorize_course_access(session, current_user, course_id)
    return await next_review_prompt(_session_context(current_user, course))


@router.get("/courses/{course_id}/weak-concepts")
async def read_weak_concepts(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """List the current learner's weak concepts for one authorized course."""
    from app.services.voice.brain import list_weak_concepts

    course = authorize_course_access(session, current_user, course_id)
    return {"concepts": await list_weak_concepts(_session_context(current_user, course))}


# --------------------------------------------------------------------------
# Text answers
# --------------------------------------------------------------------------


async def _answer(
    context: VoiceContext,
    question: VoiceQuestion,
    timer: StageTimer,
    on_token=None,
    on_event=None,
    attachments: list[Attachment] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Run SAFE guardrails then the agent, returning the wire payload."""
    transcript = question.text.strip()
    safety = SafetyGuardService().check_question(transcript)

    if safety.blocked:
        reply = safety.safe_answer or "요청하신 내용은 도와드릴 수 없습니다."
        if on_token:
            await on_token(reply)
        context.append_history({"role": "user", "content": transcript})
        context.append_history({"role": "assistant", "content": reply})
        context.last_material_sources = []
        return {
            "transcript": transcript,
            "reply": reply,
            "tools": [],
            "sources": [],
            "visualizations": [],
            "timings": timer.timings_ms,
            "safety": safety,
            "attachments": [],
        }

    contents = await _read_attachments(
        attachments or [], timer, on_event, settings, query=attachment_query(context, transcript)
    )
    reply, tools_used, sources, visualizations = await think(
        context, transcript, timer, on_token=on_token, on_event=on_event, attachments=contents
    )
    return {
        "transcript": transcript,
        "reply": reply,
        "tools": tools_used,
        "sources": sources,
        "visualizations": visualizations,
        "timings": timer.timings_ms,
        "safety": safety,
        "attachments": contents,
    }


async def _read_attachments(
    attachments: list[Attachment],
    timer: StageTimer,
    on_event,
    settings: Settings | None,
    *,
    query: str = "",
) -> list[AttachmentContent]:
    """Read the turn's files off the event loop, tracing the step for the UI.

    ``query`` is what an indexed (long) PDF is searched with for this turn.
    """
    if not attachments:
        return []
    started = time.perf_counter()
    label, detail = attachments_module.reading_label(attachments)
    await emit_step(on_event, "attachments", "running", label, detail=detail)
    settings = settings or get_settings()
    try:
        contents = await asyncio.wait_for(
            asyncio.to_thread(
                attachments_module.read_attachments,
                attachments,
                settings=settings,
                llm=LLMService(settings),
                query=query,
            ),
            timeout=settings.attachment_read_timeout_seconds,
        )
    except asyncio.TimeoutError:
        # The turn goes on without the files rather than hanging; the model is
        # told they could not be read. (The worker thread finishes on its own.)
        log.warning("attachment read timed out after %ss", settings.attachment_read_timeout_seconds)
        contents = [
            AttachmentContent(
                item.id, item.name, item.kind, item.pages, "",
                error="읽는 데 시간이 너무 오래 걸렸어요", size=item.size,
            )
            for item in attachments
        ]
    except Exception:
        await emit_step(
            on_event, "attachments", "failed", "첨부 파일을 읽지 못했어요", started_at=started
        )
        raise
    finally:
        timer.record("attach", started)
    label, detail = attachments_module.read_label(contents)
    state = "done" if any(content.has_content for content in contents) else "failed"
    await emit_step(on_event, "attachments", state, label, detail=detail, started_at=started)
    return contents


def _resolve_attachments(
    question: VoiceQuestion, user: User, course: Course, settings: Settings
) -> list[Attachment]:
    """Map the request's attachment ids to files this learner uploaded for this course."""
    ids = list(dict.fromkeys(item.strip() for item in question.attachment_ids if item.strip()))
    if not ids:
        return []
    if len(ids) > settings.attachment_max_count:
        raise HTTPException(
            status_code=422,
            detail=f"파일은 한 번에 {settings.attachment_max_count}개까지 첨부할 수 있어요.",
        )
    resolved: list[Attachment] = []
    for attachment_id in ids:
        attachment = attachments_module.load_attachment(
            attachment_id, user_id=user.id, course_id=course.id, settings=settings
        )
        if attachment is None:
            raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없어요.")
        if attachment_index.needs_index(attachment, settings):
            status_record = attachment_index.index_status(attachment) or {}
            if status_record.get("status") == "failed":
                raise HTTPException(
                    status_code=422,
                    detail=f"{attachment.name}: {status_record.get('message') or '색인에 실패했어요'}",
                )
            if status_record.get("status") != "ready":
                raise HTTPException(
                    status_code=409,
                    detail=f"{attachment.name}의 색인이 아직 진행 중이에요. 잠시 후 다시 보내 주세요.",
                )
        resolved.append(attachment)
    return resolved


def _persist(
    db: Session,
    user: User,
    course: Course,
    payload: dict,
    context: VoiceContext,
    chat_session_id: Optional[str],
    elapsed_ms: int,
) -> dict:
    chat_session = voice_log.resolve_session(
        db, user, course, chat_session_id or context.chat_session_id
    )
    context.chat_session_id = chat_session.id
    llm = LLMService(get_settings())
    blocked = payload["safety"].blocked
    log_id = voice_log.log_turn(
        db,
        chat_session=chat_session,
        user=user,
        course=course,
        question=payload["transcript"],
        answer=payload["reply"],
        material_sources=context.last_material_sources,
        web_sources=payload["sources"],
        tools_used=payload["tools"],
        mode=TEACHING_MODE,
        model_name=None if blocked else llm.model_name,
        response_time_ms=elapsed_ms,
        safety=payload["safety"],
        provider_name=None if blocked else llm.provider,
        visualizations=context.last_visualizations,
        attachments=attachments_module.logged_list(payload.get("attachments", [])),
    )
    return {"session_id": chat_session.id, "log_id": log_id}


def _wire(payload: dict, context: VoiceContext, persisted: dict) -> dict:
    safety = payload["safety"]
    return {
        "transcript": payload["transcript"],
        "reply": payload["reply"],
        "tools": payload["tools"],
        "sources": payload["sources"],
        "visualizations": payload["visualizations"],
        "timings": payload["timings"],
        "material_sources": context.last_material_sources,
        "safety": safety.as_dict(),
        "attachments": attachments_module.wire_list(payload.get("attachments", [])),
        **persisted,
    }


# --------------------------------------------------------------------------
# Attachments: images and PDFs a student asks about
# --------------------------------------------------------------------------


@router.post("/courses/{course_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    course_id: str,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> dict:
    """Store one file for the learner's next typed question.

    The file belongs to this learner within this course only. It is validated
    (type, size, page count) but not read yet: reading happens on the turn that
    carries it, where the student watches it happen in the trace. A PDF longer
    than ``attachment_inline_max_pages`` is indexed in the background first;
    the response says so (``index.status``) and the composer waits for it.
    """
    course = authorize_course_access(session, current_user, course_id)
    try:
        attachments_module.classify(file.filename or "")
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(attachments_module.READ_CHUNK_SIZE):
        size += len(chunk)
        if size > settings.attachment_max_size_bytes:
            limit_mb = settings.attachment_max_size_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=422, detail=f"파일은 {limit_mb}MB 이하만 첨부할 수 있어요."
            )
        chunks.append(chunk)
    try:
        attachment = await asyncio.to_thread(
            attachments_module.store_attachment,
            b"".join(chunks),
            filename=file.filename or "",
            user_id=current_user.id,
            course_id=course.id,
            settings=settings,
        )
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if attachment_index.needs_index(attachment, settings):
        attachment_index.mark_indexing(attachment)
        background_tasks.add_task(attachment_index.build_index, attachment, settings)
    return attachment.wire_with_index(settings)


@router.get("/courses/{course_id}/attachments/{attachment_id}")
def read_attachment_status(
    course_id: str,
    attachment_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """How far an uploaded file is: the composer polls this while a long PDF is indexed."""
    course = authorize_course_access(session, current_user, course_id)
    attachment = attachments_module.load_attachment(
        attachment_id, user_id=current_user.id, course_id=course.id, settings=settings
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없어요.")
    return attachment.wire_with_index(settings)


@router.delete(
    "/courses/{course_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attachment(
    course_id: str,
    attachment_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Drop a file the learner removed before sending; another learner's id is unknown."""
    course = authorize_course_access(session, current_user, course_id)
    attachment = attachments_module.load_attachment(
        attachment_id, user_id=current_user.id, course_id=course.id, settings=settings
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없어요.")
    attachments_module.delete_attachment(attachment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/courses/{course_id}/answer-text")
async def answer_text(
    course_id: str,
    question: VoiceQuestion,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Answer one typed question with the same brain the voice path uses."""
    course = authorize_course_access(session, current_user, course_id)
    if not question.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")

    context = _session_context(current_user, course)
    _resume(session, context, current_user, course, question.chat_session_id, settings)
    attachments = _resolve_attachments(question, current_user, course, settings)
    timer = StageTimer()
    started = time.perf_counter()
    try:
        with timer.stage("total"):
            payload = await _answer(
                context, question, timer, attachments=attachments, settings=settings
            )
    except Exception as exc:
        log.exception("voice text answer failed")
        raise HTTPException(
            status_code=503,
            detail="답변 생성 서비스를 사용할 수 없습니다.",
        ) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    persisted = _persist(
        session,
        current_user,
        course,
        payload,
        context,
        question.chat_session_id,
        elapsed_ms,
    )
    return _wire(payload, context, persisted)


@router.post("/courses/{course_id}/answer-text/stream")
async def answer_text_stream(
    course_id: str,
    question: VoiceQuestion,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Stream the turn as NDJSON: trace steps, reasoning, answer tokens, then ``done``.

    Event types, one JSON object per line:

    * ``status`` -- the progress notice composed from the question (``filler``).
    * ``step`` -- one line of the agent's work, addressed by ``key`` so a later
      event with the same key updates it in place: ``state`` is ``running``,
      ``done`` or ``failed``; ``label``/``detail`` are the Korean text to show.
    * ``thinking`` -- a delta of the model's own reasoning, for the collapsible
      "생각 과정" panel. Never part of the answer.
    * ``token`` -- a delta of the answer text.
    * ``done`` -- the same payload ``answer-text`` returns; ``error`` -- failure.
    """
    course = authorize_course_access(session, current_user, course_id)
    if not question.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")

    context = _session_context(current_user, course)
    _resume(session, context, current_user, course, question.chat_session_id, settings)
    attachments = _resolve_attachments(question, current_user, course, settings)
    user_id = current_user.id
    course_id_value = course.id

    async def events():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        timer = StageTimer()
        started = time.perf_counter()

        async def on_token(token: str) -> None:
            await queue.put({"type": "token", "text": token})

        async def on_event(event: dict) -> None:
            # Trace lines ("step") and the model's reasoning ("thinking"), shown
            # while the answer is still being worked out.
            await queue.put(event)

        async def generate() -> None:
            try:
                with timer.stage("total"):
                    payload = await _answer(
                        context,
                        question,
                        timer,
                        on_token=on_token,
                        on_event=on_event,
                        attachments=attachments,
                        settings=settings,
                    )
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                # The request session is already closed when the generator runs.
                with SessionLocal() as db:
                    user = db.get(User, user_id)
                    course_row = db.get(Course, course_id_value)
                    persisted = _persist(
                        db,
                        user,
                        course_row,
                        payload,
                        context,
                        question.chat_session_id,
                        elapsed_ms,
                    )
                await queue.put({"type": "done", **_wire(payload, context, persisted)})
            except Exception:
                log.exception("streaming voice answer failed")
                await queue.put(
                    {"type": "error", "message": "답변 생성 서비스를 사용할 수 없습니다."}
                )

        notice = pick_filler(
            question.text,
            history_length=len(context.history),
            previous=context.last_filler,
            previous_turn=last_assistant_turn(context),
        )
        if notice:
            context.last_filler = notice
            await queue.put({"type": "status", "text": notice})
        task = asyncio.create_task(generate())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in {"done", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # A proxy that compresses or buffers the body (the Next.js dev server's
    # rewrite, nginx) would hold every line until the end, and the stream would
    # arrive as one block after the whole wait. no-transform forbids compression,
    # X-Accel-Buffering the buffering, and the trailing header is for browsers.
    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --------------------------------------------------------------------------
# Hands-free realtime voice
# --------------------------------------------------------------------------


def _authenticate_socket(token: str, course_id: str) -> tuple[User, Course]:
    """Resolve the JWT and course access for a WebSocket connection."""
    settings = get_settings()
    jwt_service = JWTService(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_in=settings.jwt_expires_in,
    )
    user_id = jwt_service.decode_access_token(token)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise InvalidAccessTokenError("unknown user")
        course = authorize_course_access(db, user, course_id)
        db.expunge(user)
        db.expunge(course)
    return user, course


@router.websocket("/courses/{course_id}/stream")
async def voice_stream(websocket: WebSocket, course_id: str) -> None:
    """Relay 20 ms PCM frames through the configured provider-neutral transport."""
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    try:
        user, course = _authenticate_socket(token, course_id)
    except InvalidAccessTokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return
    except HTTPException as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc.detail))
        return

    settings = get_settings()
    availability = await asyncio.to_thread(get_voice_availability, settings)
    if not availability.enabled:
        log.warning(
            "voice provider unavailable provider=%s detail=%s",
            availability.provider,
            availability.detail,
        )
        await _try_send(websocket, {"type": "error", "message": VOICE_UNAVAILABLE_MESSAGE})
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    context = get_context(user.id, course.id, course.name)
    try:
        with SessionLocal() as db:
            _resume(
                db, context, user, course, websocket.query_params.get("chat_session_id"), settings
            )
            chat_session = voice_log.resolve_session(db, user, course, context.chat_session_id)
            context.chat_session_id = chat_session.id
    except HTTPException as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc.detail))
        return
    provider_wiring: dict = {}
    if uses_grok(settings):
        # Only the legacy provider is driven by a persona, a tool schema and a
        # dispatcher handed to it; building them costs a learner-memory fetch, so
        # the default cascade -- which runs the brain itself -- must not pay it.
        try:
            memory_context = await asyncio.wait_for(prefetch_memory_context(context), timeout=3)
        except Exception:
            memory_context = {"found": False}

        async def refresh_instructions() -> str:
            return agent_spec.persona(
                course.name, TEACHING_MODE, await prefetch_memory_context(context)
            )

        external_brain = external_brain_for(user.id, course.id, course.name)
        provider_wiring = {
            "instructions": agent_spec.persona(course.name, TEACHING_MODE, memory_context),
            "tools": agent_spec.json_schemas(),
            "run_tool": agent_spec.tool_runner(context),
            "refresh_instructions": refresh_instructions,
            "schedule_assessment": lambda conversation: external_brain.schedule(
                conversation,
                source="realtime",
            ),
        }
    transport = create_voice_transport(context=context, settings=settings, **provider_wiring)
    reader: asyncio.Task[None] | None = None
    try:
        await transport.start()
        reader = asyncio.create_task(
            _pump_provider_events(websocket, transport, context, user, course)
        )
        await websocket.send_json(
            {"type": "ready", "provider": transport.name, "session_id": context.chat_session_id}
        )
        await _pump_caller_audio(websocket, transport)
    except WebSocketDisconnect:
        log.info("voice stream closed")
    except Exception:
        log.exception("realtime voice failed provider=%s", transport.name)
        await _try_send(websocket, {"type": "error", "message": VOICE_UNAVAILABLE_MESSAGE})
    finally:
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await transport.close()


async def _pump_caller_audio(websocket: WebSocket, transport: Transport) -> None:
    """Relay PCM or typed turns through the same live session."""
    while True:
        message = await websocket.receive_json()
        if not isinstance(message, dict):
            continue
        if message.get("type") == "text":
            text = str(message.get("text", "")).strip()
            if text:
                await transport.send_text(text[:4000])
            continue
        if message.get("type") != "audio":
            continue
        try:
            frame = base64.b64decode(message.get("data", ""), validate=True)
        except (binascii.Error, TypeError, ValueError):
            continue
        if len(frame) == FRAME_BYTES:
            await transport.send_audio(frame)


async def _pump_provider_events(
    websocket: WebSocket,
    transport: Transport,
    context: VoiceContext,
    user: User,
    course: Course,
) -> None:
    """Translate provider-neutral realtime events for the browser."""
    # A transport that runs the brain against the session context already owns the
    # conversation; writing it again here would keep a second, independently
    # trimmed copy that drifts from the one the model actually sees.
    writes_history = not transport.owns_history
    speaking = False
    turn_ended_at: Optional[float] = None
    pending_question = ""
    pending_question_id = ""
    pending_answer = ""
    completed_question_id = ""
    completed_log_id: Optional[str] = None
    turn_started_at = time.perf_counter()
    turn_tools: list[str] = []
    turn_web_sources: list[str] = []
    turn_safety: SafetyResult = NORMAL_RESULT
    try:
        async for event in transport.events():
            match event:
                case SessionReady():
                    log.info("realtime session configured provider=%s", transport.name)
                case UserStartedSpeaking():
                    await websocket.send_json({"type": "state", "value": "hearing"})
                    speaking = False
                    # Interruption starts a new generation. Do not attach any
                    # unfinished previous response to the next user transcript.
                    pending_question = ""
                    pending_question_id = ""
                    pending_answer = ""
                    turn_tools = []
                    turn_web_sources = []
                    turn_safety = NORMAL_RESULT
                    await websocket.send_json({"type": "flush"})
                case UserStoppedSpeaking():
                    turn_ended_at = time.perf_counter()
                    await websocket.send_json({"type": "state", "value": "thinking"})
                case AgentAudio(pcm=pcm, rate=rate, filler=filler):
                    if not speaking:
                        speaking = True
                        await websocket.send_json({"type": "state", "value": "speaking"})
                    # The badge is the wait for an ANSWER. A progress notice plays
                    # first when the model is slow, and timing that instead would
                    # report the notice's latency on exactly the turns that were
                    # slow enough to need one.
                    if not filler and turn_ended_at is not None:
                        await websocket.send_json(
                            {
                                "type": "latency",
                                "ms": round((time.perf_counter() - turn_ended_at) * 1000),
                            }
                        )
                        turn_ended_at = None
                    await websocket.send_json(
                        {
                            "type": "audio",
                            "data": base64.b64encode(pcm).decode(),
                            "rate": rate,
                        }
                    )
                case AgentTextDelta(text=text) if text:
                    await websocket.send_json({"type": "token", "text": text})
                case AgentFiller(text=text, transient=transient) if text:
                    await websocket.send_json(
                        {"type": "filler", "text": text, "transient": transient}
                    )
                case AgentTextBoundary():
                    await websocket.send_json({"type": "text_boundary"})
                case AgentTurnDone():
                    speaking = False
                    await websocket.send_json({"type": "state", "value": "listening"})
                    await websocket.send_json({"type": "turn_done"})
                case Transcript(
                    who=who,
                    text=text,
                    item_id=item_id,
                    replace=replace,
                ) if text:
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "who": who,
                            "text": text,
                            "item_id": item_id,
                            "replace": replace,
                        }
                    )
                    if who == "user":
                        if replace and item_id and item_id == pending_question_id:
                            pending_question = text
                            turn_safety = SafetyGuardService().check_question(text)
                            if writes_history:
                                _replace_latest_history(context, "user", text)
                        elif replace and item_id and item_id == completed_question_id:
                            if writes_history:
                                _replace_latest_history(context, "user", text)
                            if completed_log_id:
                                _update_logged_question(completed_log_id, text)
                        else:
                            if writes_history:
                                context.append_history({"role": "user", "content": text})
                            pending_question = text
                            pending_question_id = item_id
                            turn_safety = SafetyGuardService().check_question(text)
                            if not pending_answer:
                                turn_started_at = time.perf_counter()
                                turn_tools = []
                                turn_web_sources = []
                        if pending_answer:
                            if writes_history:
                                context.append_history(
                                    {"role": "assistant", "content": pending_answer}
                                )
                            completed_log_id = _log_voice_turn(
                                user,
                                course,
                                context,
                                pending_question,
                                pending_answer,
                                turn_tools,
                                turn_web_sources,
                                turn_safety,
                                transport,
                                round((time.perf_counter() - turn_started_at) * 1000),
                            )
                            completed_question_id = pending_question_id
                            pending_question = ""
                            pending_question_id = ""
                            pending_answer = ""
                    elif pending_question:
                        if writes_history:
                            context.append_history({"role": "assistant", "content": text})
                        completed_log_id = _log_voice_turn(
                            user,
                            course,
                            context,
                            pending_question,
                            text,
                            turn_tools,
                            turn_web_sources,
                            turn_safety,
                            transport,
                            round((time.perf_counter() - turn_started_at) * 1000),
                        )
                        completed_question_id = pending_question_id
                        pending_question = ""
                        pending_question_id = ""
                    else:
                        pending_answer = text
                case ToolCalled(name=name, result=result):
                    if name not in turn_tools:
                        turn_tools.append(name)
                    if name == "search_trusted_web" and isinstance(result, dict):
                        sources = result.get("sources")
                        if isinstance(sources, list):
                            turn_web_sources = [str(source) for source in sources[:3]]
                    await websocket.send_json({"type": "tool", "name": name})
                    if name == "show_visualization" and isinstance(result, dict):
                        if "error" in result:
                            await websocket.send_json(
                                {
                                    "type": "visualization_error",
                                    "message": "시각 자료를 표시하지 못했어요.",
                                }
                            )
                        else:
                            await websocket.send_json(
                                {
                                    "type": "visualization",
                                    "visualization": result,
                                }
                            )
                case Failed(message=message, fatal=fatal):
                    await websocket.send_json({"type": "error", "message": message})
                    if pending_question:
                        # The student did ask something. Losing the question because
                        # the answer never arrived would hide the outage from the
                        # professor and admin log screens entirely.
                        _log_voice_turn(
                            user,
                            course,
                            context,
                            pending_question,
                            message,
                            turn_tools,
                            turn_web_sources,
                            turn_safety,
                            transport,
                            round((time.perf_counter() - turn_started_at) * 1000),
                        )
                        pending_question = ""
                        pending_question_id = ""
                        pending_answer = ""
                    if fatal:
                        return
                    speaking = False
                    await websocket.send_json({"type": "state", "value": "listening"})
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("provider event pump failed")
        await _try_send(
            websocket,
            {"type": "error", "message": "음성 이벤트 처리 중 오류가 발생했습니다."},
        )


def _log_voice_turn(
    user: User,
    course: Course,
    context: VoiceContext,
    question: str,
    answer: str,
    tools_used: list[str],
    web_sources: list[str],
    safety: SafetyResult,
    transport: Transport,
    elapsed_ms: int,
) -> Optional[str]:
    """Persist one spoken turn; a logging failure must not drop the call."""
    try:
        with SessionLocal() as db:
            db_user = db.get(User, user.id)
            db_course = db.get(Course, course.id)
            chat_session = voice_log.resolve_session(
                db, db_user, db_course, context.chat_session_id
            )
            context.chat_session_id = chat_session.id
            model_name = str(getattr(transport, "model_name", transport.name) or transport.name)
            provider_name = str(
                getattr(transport, "provider_name", transport.name) or transport.name
            )
            provider_sources = getattr(transport, "last_web_sources", [])
            if not web_sources and isinstance(provider_sources, list):
                web_sources = [str(source) for source in provider_sources[:3]]
            provider_safety = getattr(transport, "last_safety", safety)
            if isinstance(provider_safety, SafetyResult):
                safety = provider_safety
            return voice_log.log_turn(
                db,
                chat_session=chat_session,
                user=db_user,
                course=db_course,
                question=question,
                answer=answer,
                material_sources=context.last_material_sources,
                web_sources=web_sources,
                tools_used=tools_used,
                mode=TEACHING_MODE,
                model_name=model_name,
                response_time_ms=elapsed_ms,
                safety=safety,
                provider_name=provider_name,
                visualizations=context.last_visualizations,
            )
    except Exception:
        log.exception("failed to persist a voice turn")
    return None


def _replace_latest_history(context: VoiceContext, role: str, text: str) -> None:
    for message in reversed(context.history):
        if message.get("role") == role:
            message["content"] = text
            return


def _update_logged_question(log_id: str, question: str) -> None:
    """Apply a late provider transcript correction to the persisted voice log."""
    try:
        from app.models import ChatLog

        with SessionLocal() as db:
            chat_log = db.get(ChatLog, log_id)
            if chat_log is not None:
                chat_log.question = question
                db.commit()
    except Exception:
        log.exception("failed to update corrected voice transcript")


async def _try_send(websocket: WebSocket, payload: dict) -> None:
    try:
        await websocket.send_json(payload)
    except Exception:
        pass
