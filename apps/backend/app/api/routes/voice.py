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

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
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
from app.services.voice import agent_spec, voice_log
from app.services.voice.brain import StageTimer, VoiceContext, prefetch_memory_context, think
from app.services.voice.factory import create_voice_transport, get_voice_availability
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
TEXT_FILLER_MESSAGE = "질문을 살펴보고 있어요. 잠시만 기다려 주세요."
VOICE_UNAVAILABLE_MESSAGE = "음성 모델 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."

VALID_MODES = {"explain", "socratic"}


class VoiceQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    mode: str = "socratic"
    chat_session_id: Optional[str] = None


class TrustedSitePayload(BaseModel):
    url: str = Field(min_length=1, max_length=500)


def _normalized_mode(mode: Optional[str]) -> str:
    return mode if mode in VALID_MODES else "socratic"


def _session_context(user: User, course: Course) -> VoiceContext:
    return get_context(user.id, course.id, course.name)


def _resume(
    db: Session,
    context: VoiceContext,
    user: User,
    course: Course,
    chat_session_id: Optional[str],
) -> None:
    """Reload a conversation reopened from 대화 이력, if it is not already loaded."""
    if not chat_session_id or context.chat_session_id == chat_session_id:
        return
    if not voice_log.restore_history(db, context, user, course, chat_session_id):
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
) -> dict:
    """Run SAFE guardrails then the agent, returning the wire payload."""
    transcript = question.text.strip()
    mode = _normalized_mode(question.mode)
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
        }

    reply, tools_used, sources, visualizations = await think(
        context, transcript, timer, mode, on_token=on_token
    )
    return {
        "transcript": transcript,
        "reply": reply,
        "tools": tools_used,
        "sources": sources,
        "visualizations": visualizations,
        "timings": timer.timings_ms,
        "safety": safety,
    }


def _persist(
    db: Session,
    user: User,
    course: Course,
    payload: dict,
    context: VoiceContext,
    mode: str,
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
        mode=mode,
        model_name=None if blocked else llm.model_name,
        response_time_ms=elapsed_ms,
        safety=payload["safety"],
        provider_name=None if blocked else llm.provider,
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
        **persisted,
    }


@router.post("/courses/{course_id}/answer-text")
async def answer_text(
    course_id: str,
    question: VoiceQuestion,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Answer one typed question with the same brain the voice path uses."""
    course = authorize_course_access(session, current_user, course_id)
    if not question.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")

    context = _session_context(current_user, course)
    _resume(session, context, current_user, course, question.chat_session_id)
    timer = StageTimer()
    started = time.perf_counter()
    try:
        with timer.stage("total"):
            payload = await _answer(context, question, timer)
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
        _normalized_mode(question.mode),
        question.chat_session_id,
        elapsed_ms,
    )
    return _wire(payload, context, persisted)


@router.post("/courses/{course_id}/answer-text/stream")
async def answer_text_stream(
    course_id: str,
    question: VoiceQuestion,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Stream answer tokens as NDJSON, then one final ``done`` event."""
    course = authorize_course_access(session, current_user, course_id)
    if not question.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")

    context = _session_context(current_user, course)
    _resume(session, context, current_user, course, question.chat_session_id)
    user_id = current_user.id
    course_id_value = course.id
    mode = _normalized_mode(question.mode)

    async def events():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        timer = StageTimer()
        started = time.perf_counter()

        async def on_token(token: str) -> None:
            await queue.put({"type": "token", "text": token})

        async def generate() -> None:
            try:
                with timer.stage("total"):
                    payload = await _answer(context, question, timer, on_token=on_token)
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
                        mode,
                        question.chat_session_id,
                        elapsed_ms,
                    )
                await queue.put({"type": "done", **_wire(payload, context, persisted)})
            except Exception:
                log.exception("streaming voice answer failed")
                await queue.put(
                    {"type": "error", "message": "답변 생성 서비스를 사용할 수 없습니다."}
                )

        await queue.put({"type": "status", "text": TEXT_FILLER_MESSAGE})
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

    return StreamingResponse(events(), media_type="application/x-ndjson")


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

    mode = _normalized_mode(websocket.query_params.get("mode"))
    context = get_context(user.id, course.id, course.name)
    try:
        memory_context = await asyncio.wait_for(prefetch_memory_context(context), timeout=3)
    except Exception:
        memory_context = {"found": False}

    async def refresh_instructions() -> str:
        memory = await prefetch_memory_context(context)
        return agent_spec.persona(course.name, mode, memory)

    external_brain = external_brain_for(user.id, course.id, course.name)
    transport = create_voice_transport(
        context=context,
        mode=mode,
        instructions=agent_spec.persona(course.name, mode, memory_context),
        tools=agent_spec.json_schemas(),
        run_tool=agent_spec.tool_runner(context),
        refresh_instructions=refresh_instructions,
        schedule_assessment=lambda conversation: external_brain.schedule(
            conversation,
            source="realtime",
        ),
        settings=settings,
    )
    reader: asyncio.Task[None] | None = None
    try:
        await transport.start()
        reader = asyncio.create_task(
            _pump_provider_events(websocket, transport, context, user, course, mode)
        )
        await websocket.send_json({"type": "ready", "provider": transport.name})
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
    mode: str,
) -> None:
    """Translate provider-neutral realtime events for the browser."""
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
                case AgentAudio(pcm=pcm, rate=rate):
                    if not speaking:
                        speaking = True
                        await websocket.send_json({"type": "state", "value": "speaking"})
                        if turn_ended_at is not None:
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
                case AgentFiller(text=text) if text:
                    await websocket.send_json({"type": "filler", "text": text})
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
                            _replace_latest_history(context, "user", text)
                        elif replace and item_id and item_id == completed_question_id:
                            _replace_latest_history(context, "user", text)
                            if completed_log_id:
                                _update_logged_question(completed_log_id, text)
                        else:
                            context.append_history({"role": "user", "content": text})
                            pending_question = text
                            pending_question_id = item_id
                            turn_safety = SafetyGuardService().check_question(text)
                            if not pending_answer:
                                turn_started_at = time.perf_counter()
                                turn_tools = []
                                turn_web_sources = []
                        if pending_answer:
                            context.append_history({"role": "assistant", "content": pending_answer})
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
                                mode,
                                round((time.perf_counter() - turn_started_at) * 1000),
                            )
                            completed_question_id = pending_question_id
                            pending_question = ""
                            pending_question_id = ""
                            pending_answer = ""
                    elif pending_question:
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
                            mode,
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
    mode: str,
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
                mode=mode,
                model_name=model_name,
                response_time_ms=elapsed_ms,
                safety=safety,
                provider_name=provider_name,
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
