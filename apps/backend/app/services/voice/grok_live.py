"""xAI realtime transport with KINGO turn synchronization and visual gating."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncIterator, Awaitable, Callable

import websockets

from app.core.config import get_settings
from app.services.voice.brain import MAX_HISTORY_MESSAGES, require_api_key
from app.services.voice.transport import (
    AGENT_RATE,
    CALLER_RATE,
    AgentAudio,
    AgentFiller,
    AgentTextBoundary,
    AgentTextDelta,
    AgentTurnDone,
    Event,
    Failed,
    SessionReady,
    ToolCalled,
    Transcript,
    Transport,
    UserStartedSpeaking,
    UserStoppedSpeaking,
)
from app.services.voice.visual_router import VisualDecision, decide_visualization

log = logging.getLogger("voice.grok-live")

READY_TIMEOUT_S = 10
TOOL_TIMEOUT_S = 10
VISUAL_ALREADY_SHOWN_INSTRUCTION = (
    "A relevant visual has already been shown for this turn. Do not repeat its raw "
    "formula, labels, or visual data in speech. Use it as a teaching clue and continue "
    "the selected teaching mode."
)


class GrokConnectionError(RuntimeError):
    """The external realtime voice service could not be reached."""


class GrokTransport(Transport):
    name = "grok"

    def __init__(
        self,
        instructions: str,
        tools: list[dict],
        run_tool: Callable[[str, dict], Awaitable[object]],
        *,
        refresh_instructions: Callable[[], Awaitable[str]] | None = None,
        schedule_assessment: Callable[[list[dict]], object] | None = None,
        visual_decider: Callable[[str, list[dict]], Awaitable[VisualDecision]] | None = None,
    ) -> None:
        self.instructions = instructions
        self.tools = tools
        self.run_tool = run_tool
        self.refresh_instructions = refresh_instructions
        self.schedule_assessment = schedule_assessment
        self.visual_decider = visual_decider or decide_visualization
        self._ws = None
        self._connected = asyncio.Event()
        self._ready = asyncio.Event()
        self._closed = False
        self._tools_this_turn = 0
        self._response_transcript = ""
        self._response_transcript_emitted = False
        self._response_done = False
        self._last_user_transcript = ""
        self._response_active = False
        self._discard_response_output = False
        self._conversation: list[dict[str, str]] = []
        self._assessment_scheduled = False
        self._memory_task: asyncio.Task[None] | None = None
        self._local_events: asyncio.Queue[Event] = asyncio.Queue()
        self._input_transcripts: dict[str, str] = {}
        self._emitted_input_transcripts: dict[str, str] = {}
        self._speech_sequence = 0
        self._filler_emitted = False

        # server_vad starts a response automatically. The first response is
        # cancelled so the final transcript can pass through the visual gate.
        self._visual_gate_pending = False
        self._visual_gate_auto_response_seen = False
        self._visual_gate_auto_response_done = False
        self._visual_gate_decision_ready = False
        self._visual_gate_response_requested = False
        self._visual_gate_instruction: str | None = None

    async def start(self) -> None:
        settings = get_settings()
        key = require_api_key()
        last_error: TimeoutError | OSError | None = None
        for attempt in range(1, settings.xai_connect_attempts + 1):
            try:
                self._ws = await websockets.connect(
                    f"{settings.xai_realtime_url}?model={settings.grok_voice_model}",
                    additional_headers={"Authorization": f"Bearer {key}"},
                    max_size=None,
                    open_timeout=settings.xai_connect_timeout_seconds,
                    ping_interval=20,
                )
                break
            except (TimeoutError, OSError) as exc:
                last_error = exc
                log.warning(
                    "xAI connection attempt %d/%d failed: %s",
                    attempt,
                    settings.xai_connect_attempts,
                    type(exc).__name__,
                )
                if attempt < settings.xai_connect_attempts:
                    await asyncio.sleep(settings.xai_connect_retry_delay_seconds)

        if self._ws is None:
            if isinstance(last_error, TimeoutError):
                message = "xAI 음성 서버 연결 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
            else:
                message = "xAI 음성 서버에 연결할 수 없습니다. 네트워크를 확인해 주세요."
            raise GrokConnectionError(message) from last_error

        self._connected.set()
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "instructions": self.instructions,
                    "voice": settings.grok_voice,
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": CALLER_RATE},
                            "transcription": {
                                "model": "grok-transcribe",
                                "language_hint": "ko",
                            },
                        },
                        "output": {"format": {"type": "audio/pcm", "rate": AGENT_RATE}},
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": settings.vad_threshold,
                        "prefix_padding_ms": settings.prefix_ms,
                        "silence_duration_ms": settings.silence_ms,
                    },
                    "tools": self.tools,
                },
            }
        )
        try:
            await asyncio.wait_for(self._ready.wait(), READY_TIMEOUT_S)
        except TimeoutError as exc:
            raise RuntimeError("xAI realtime session configuration timed out") from exc

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is not None and not self._closed:
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm).decode(),
                }
            )

    async def send_text(self, text: str) -> None:
        if self._ws is None or self._closed:
            return
        text = text.strip()
        if not text:
            return
        self._begin_user_turn(text)
        await self._local_events.put(Transcript("user", text))
        await self._refresh_session_instructions()
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        visual_event, instruction = await self._prepare_visual(text)
        if visual_event is not None:
            await self._local_events.put(visual_event)
        await self._create_response(instruction)

    async def events(self) -> AsyncIterator[Event]:
        await self._connected.wait()
        assert self._ws is not None
        try:
            async for raw in self._ws:
                while not self._local_events.empty():
                    yield self._local_events.get_nowait()
                event = json.loads(raw)
                kind = event.get("type", "")

                if kind == "session.updated":
                    self._ready.set()
                    yield SessionReady()
                elif kind == "response.created":
                    self._response_transcript = ""
                    self._response_transcript_emitted = False
                    self._response_done = False
                    self._response_active = True
                    if (
                        self._visual_gate_pending
                        and not self._visual_gate_response_requested
                        and not self._visual_gate_auto_response_seen
                    ):
                        self._visual_gate_auto_response_seen = True
                        self._discard_response_output = True
                        await self._send({"type": "response.cancel"})
                    else:
                        self._discard_response_output = False
                elif kind == "input_audio_buffer.speech_started":
                    yield UserStartedSpeaking()
                    self._reset_for_new_speech()
                    self._start_visual_gate()
                    self._schedule_memory_refresh()
                    if self._response_active:
                        self._response_active = False
                        self._discard_response_output = True
                        await self._send({"type": "response.cancel"})
                elif kind == "input_audio_buffer.speech_stopped":
                    yield UserStoppedSpeaking()
                elif kind == "response.output_audio.delta":
                    if not self._discard_response_output:
                        yield AgentAudio(base64.b64decode(event["delta"]))
                elif kind == "response.output_audio_transcript.delta":
                    if self._discard_response_output:
                        continue
                    delta = str(event.get("delta", ""))
                    self._response_transcript += delta
                    if delta:
                        yield AgentTextDelta(delta)
                elif kind == "response.function_call_arguments.done":
                    async for output in self._handle_tool_call(event):
                        yield output
                elif kind == "response.done":
                    async for output in self._handle_response_done(event):
                        yield output
                elif "input_audio_transcription" in kind and kind.endswith(
                    (".updated", ".completed")
                ):
                    async for output in self._handle_user_transcript(
                        event,
                        completed=kind.endswith(".completed"),
                    ):
                        yield output
                elif kind.endswith("output_audio_transcript.done"):
                    self._response_transcript = str(
                        event.get("transcript") or self._response_transcript
                    )
                    if (
                        self._response_done
                        and self._response_transcript
                        and not self._response_transcript_emitted
                    ):
                        self._response_transcript_emitted = True
                        yield Transcript("agent", self._response_transcript)
                        self._schedule_completed_turn()
                elif kind == "error":
                    message = str(event.get("error", {}).get("message", json.dumps(event)))
                    if _is_stale_cancel_error(message):
                        self._response_active = False
                        log.info("ignoring stale realtime cancellation: %s", message)
                        continue
                    yield Failed(message)

            while not self._local_events.empty():
                yield self._local_events.get_nowait()
        except websockets.ConnectionClosed as exc:
            yield Failed(f"model connection closed: {exc}")
        finally:
            self._cancel_memory_task()
            self._closed = True

    async def _handle_tool_call(self, event: dict) -> AsyncIterator[Event]:
        name = str(event.get("name", ""))
        call_id = str(event.get("call_id", ""))
        filler = self._response_transcript.strip()
        if filler and not self._filler_emitted:
            self._filler_emitted = True
            yield AgentFiller(filler)
        try:
            args = json.loads(event.get("arguments") or "{}")
            result = await asyncio.wait_for(self.run_tool(name, args), TOOL_TIMEOUT_S)
        except TimeoutError:
            args, result = {}, {"error": f"{name} timed out"}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            args, result = {}, {"error": str(exc)}
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            }
        )
        self._tools_this_turn += 1
        yield ToolCalled(name, args, result)

    async def _handle_response_done(self, event: dict) -> AsyncIterator[Event]:
        self._response_active = False
        if self._discard_response_output:
            if (
                self._visual_gate_pending
                and self._visual_gate_auto_response_seen
                and not self._visual_gate_response_requested
            ):
                self._visual_gate_auto_response_done = True
                self._discard_response_output = False
                self._response_transcript = ""
                self._response_transcript_emitted = False
                self._response_done = False
                await self._maybe_start_gated_response()
            else:
                self._reset_discarded_response()
                yield AgentTurnDone()
            return
        if self._tools_this_turn:
            self._tools_this_turn = 0
            had_interim_text = bool(self._response_transcript)
            self._response_transcript = ""
            self._response_transcript_emitted = False
            self._response_done = False
            await self._create_response()
            if had_interim_text:
                yield AgentTextBoundary()
            return

        self._response_done = True
        self._response_transcript = self._response_transcript or _transcript_from_response(event)
        if self._response_transcript and not self._response_transcript_emitted:
            self._response_transcript_emitted = True
            yield Transcript("agent", self._response_transcript)
        self._schedule_completed_turn()
        self._finish_visual_gate()
        yield AgentTurnDone()

    async def _handle_user_transcript(
        self,
        event: dict,
        *,
        completed: bool,
    ) -> AsyncIterator[Event]:
        item_id = str(event.get("item_id", "")).strip() or f"speech-{self._speech_sequence}"
        previous = self._input_transcripts.get(item_id, "")
        transcript = str(event.get("transcript") or event.get("text") or "").strip()
        delta = str(event.get("delta") or "")
        if transcript:
            # Updated events normally contain the full current hypothesis. Keep
            # the longer value when providers briefly send an older hypothesis.
            current = transcript if len(transcript) >= len(previous) else previous
        elif delta:
            current = f"{previous}{delta}".strip()
        else:
            current = previous
        if current:
            self._input_transcripts[item_id] = current
        if not completed or not current:
            return

        current_normalized = _normalized_transcript(current)
        canonical_item_id = item_id
        for emitted_item_id, emitted_text in self._emitted_input_transcripts.items():
            emitted_normalized = _normalized_transcript(emitted_text)
            if current_normalized == emitted_normalized:
                return
            if current_normalized.startswith(emitted_normalized):
                canonical_item_id = emitted_item_id
                break
            if emitted_normalized.startswith(current_normalized):
                return

        emitted = self._emitted_input_transcripts.get(canonical_item_id, "")
        replace = bool(emitted)
        self._emitted_input_transcripts[canonical_item_id] = current
        yield Transcript("user", current, item_id=canonical_item_id, replace=replace)
        self._begin_user_turn(current, keep_memory_task=True)
        if self._visual_gate_pending and not replace:
            visual_event, instruction = await self._prepare_visual(current)
            if visual_event is not None:
                yield visual_event
            self._visual_gate_instruction = instruction
            self._visual_gate_decision_ready = True
            await self._maybe_start_gated_response()
        if self._response_done:
            self._schedule_completed_turn()

    async def close(self) -> None:
        self._closed = True
        self._cancel_memory_task()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def _create_response(self, instruction: str | None = None) -> None:
        payload: dict = {"type": "response.create"}
        if instruction:
            payload["response"] = {"instructions": instruction}
        await self._send(payload)

    async def _prepare_visual(self, transcript: str) -> tuple[ToolCalled | None, str | None]:
        decision = await self.visual_decider(transcript, self._conversation)
        if not decision.needed or not decision.args:
            return None, None
        try:
            result = await asyncio.wait_for(
                self.run_tool("show_visualization", decision.args),
                TOOL_TIMEOUT_S,
            )
        except TimeoutError:
            log.warning("visual gate render timed out")
            return None, None
        except Exception:
            log.exception("visual gate render failed")
            return None, None
        if not isinstance(result, dict) or "error" in result:
            return None, None
        return (
            ToolCalled("show_visualization", decision.args, result),
            VISUAL_ALREADY_SHOWN_INSTRUCTION,
        )

    def _start_visual_gate(self) -> None:
        self._visual_gate_pending = True
        self._visual_gate_auto_response_seen = False
        self._visual_gate_auto_response_done = False
        self._visual_gate_decision_ready = False
        self._visual_gate_response_requested = False
        self._visual_gate_instruction = None

    async def _maybe_start_gated_response(self) -> None:
        if (
            self._visual_gate_pending
            and self._visual_gate_auto_response_done
            and self._visual_gate_decision_ready
            and not self._visual_gate_response_requested
        ):
            self._visual_gate_response_requested = True
            await self._create_response(self._visual_gate_instruction)

    def _finish_visual_gate(self) -> None:
        self._visual_gate_pending = False
        self._visual_gate_auto_response_seen = False
        self._visual_gate_auto_response_done = False
        self._visual_gate_decision_ready = False
        self._visual_gate_response_requested = False
        self._visual_gate_instruction = None

    def _begin_user_turn(self, transcript: str, *, keep_memory_task: bool = False) -> None:
        transcript = transcript.strip()
        if not transcript:
            return
        self._last_user_transcript = transcript
        self._assessment_scheduled = False
        self._filler_emitted = False
        if not keep_memory_task:
            self._cancel_memory_task()

    def _reset_for_new_speech(self) -> None:
        self._cancel_memory_task()
        self._last_user_transcript = ""
        self._assessment_scheduled = False
        self._input_transcripts.clear()
        self._emitted_input_transcripts.clear()
        self._speech_sequence += 1
        self._filler_emitted = False

    def _reset_discarded_response(self) -> None:
        self._tools_this_turn = 0
        self._discard_response_output = False
        self._response_transcript = ""
        self._response_transcript_emitted = False
        self._response_done = False

    def _schedule_memory_refresh(self) -> None:
        self._cancel_memory_task()
        if self.refresh_instructions is not None:
            self._memory_task = asyncio.create_task(self._refresh_session_instructions())

    async def _refresh_session_instructions(self) -> None:
        if self.refresh_instructions is None:
            return
        try:
            instructions = await self.refresh_instructions()
            if instructions and instructions != self.instructions:
                self.instructions = instructions
                if self._ws is not None and not self._closed:
                    await self._send(
                        {
                            "type": "session.update",
                            "session": {"instructions": instructions},
                        }
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("realtime learner-memory refresh failed")
        finally:
            if self._memory_task is asyncio.current_task():
                self._memory_task = None

    def _cancel_memory_task(self) -> None:
        if self._memory_task is not None and not self._memory_task.done():
            self._memory_task.cancel()
        self._memory_task = None

    def _schedule_completed_turn(self) -> None:
        if self._assessment_scheduled:
            return
        user = self._last_user_transcript.strip()
        assistant = self._response_transcript.strip()
        if not user or not assistant:
            return
        self._conversation.extend(
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        )
        if len(self._conversation) > MAX_HISTORY_MESSAGES:
            del self._conversation[:-MAX_HISTORY_MESSAGES]
        if self.schedule_assessment is not None:
            self.schedule_assessment(self._conversation)
        self._assessment_scheduled = True
        self._last_user_transcript = ""


def _transcript_from_response(event: dict) -> str:
    for item in event.get("response", {}).get("output", []):
        for content in item.get("content", []):
            transcript = content.get("transcript") or content.get("text")
            if transcript:
                return str(transcript)
    return ""


def _is_stale_cancel_error(message: str) -> bool:
    normalized = message.casefold()
    return "cancellation failed" in normalized and "no active response found" in normalized


def _normalized_transcript(value: str) -> str:
    return " ".join(value.casefold().split())
