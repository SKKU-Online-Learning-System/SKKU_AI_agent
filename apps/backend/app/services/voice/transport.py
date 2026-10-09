"""Provider-neutral contract for live speech-to-speech sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

CALLER_RATE = 16000
AGENT_RATE = 24000


@dataclass(frozen=True)
class SessionReady:
    pass


@dataclass(frozen=True)
class UserStartedSpeaking:
    pass


@dataclass(frozen=True)
class UserStoppedSpeaking:
    pass


@dataclass(frozen=True)
class AgentAudio:
    pcm: bytes
    rate: int = AGENT_RATE
    # Audio of a progress notice rather than of the answer. The agent is audibly
    # speaking either way, but only the answer is what the student is waiting for,
    # so latency is measured against the answer.
    filler: bool = False


@dataclass(frozen=True)
class AgentTextDelta:
    text: str


@dataclass(frozen=True)
class AgentFiller:
    text: str
    # True for a fixed progress notice that the answer replaces on screen. False
    # for a filler the provider generated itself, which is a real turn and stays
    # in the transcript.
    transient: bool = False


@dataclass(frozen=True)
class AgentTextBoundary:
    """The streamed pre-tool filler ended; the next text is a new bubble."""

    pass


@dataclass(frozen=True)
class AgentTurnDone:
    pass


@dataclass(frozen=True)
class Transcript:
    who: str
    text: str
    item_id: str = ""
    replace: bool = False


@dataclass(frozen=True)
class ToolCalled:
    name: str
    args: dict = field(default_factory=dict)
    result: object = None


@dataclass(frozen=True)
class Failed:
    message: str
    fatal: bool = True


Event = (
    SessionReady
    | UserStartedSpeaking
    | UserStoppedSpeaking
    | AgentAudio
    | AgentTextDelta
    | AgentFiller
    | AgentTextBoundary
    | AgentTurnDone
    | Transcript
    | ToolCalled
    | Failed
)


class Transport(ABC):
    name = "transport"
    # True when the transport already writes the turn into the shared
    # ``VoiceContext``; the route then relays transcripts without writing a
    # second, independently trimmed copy of the same conversation.
    owns_history = False

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def send_audio(self, pcm: bytes) -> None:
        pass

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Submit a typed turn through the same live session."""

        pass

    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
