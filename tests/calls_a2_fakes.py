# tests/calls_a2_fakes.py - R18 A2: fakes for every port the call engine and hub use (a plain
# module, not conftest, so test files import it). No network, no audio device, no real calls.
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from jarvis.calls.brain import RULES, TRANSLATE_SYSTEM, CallBrain, FixedLines, Line
from jarvis.calls.captions import SYSTEM as CAPTION_SYSTEM
from jarvis.calls.captions import Captioner
from jarvis.calls.engine import CallSession
from jarvis.calls.engine_ports import BookedSlot, EngineDeps, Kind, Timing
from jarvis.calls.models import (
    Booking,
    CallCard,
    CallRecord,
    CallSettings,
    Direction,
    Heard,
    SpeechMode,
    TimeWindow,
)
from jarvis.calls.protocol import (
    FRAME_BYTES,
    CallStateEvent,
    CloudToDesk,
    DeskState,
    PhoneCommand,
)
from jarvis.calls.store import MemoryCallStore
from jarvis.calls.summary import SYSTEM as SUMMARY_SYSTEM
from jarvis.calls.summary import CallSummary, Summarizer
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMTransientError,
    ToolSpec,
    Usage,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier
from jarvis.tools.audit import AuditLog

UID = "u_owner"
NUMBER = "+919000000001"
NOW = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)  # 11:30 IST


def frames(n: int = 10, value: int = 100) -> bytes:
    return (value.to_bytes(2, "little", signed=True) * (FRAME_BYTES // 2)) * n


# ---- the brain, captions, summary and fixed lines: one provider routed by its system prompt ----
@dataclass
class RoutedProvider:
    """Each caller's own script: the call brain, captions, the summary, line translations."""

    name: str = "anthropic"
    brain: deque[str] = field(default_factory=deque)
    captions: deque[str] = field(default_factory=deque)
    summary: deque[str] = field(default_factory=deque)
    lines: deque[str] = field(default_factory=deque)
    seen: list[tuple[str, str, str]] = field(default_factory=list)  # (route, dynamic, user)
    fail_brain: int = 0
    gate: asyncio.Event | None = None  # set: the brain answers (None: at once)
    cost_usd: float = 0.0001

    def say(self, say: str, english: str = "", action: str = "none", **extra: Any) -> None:
        self.brain.append(
            json.dumps({"say": say, "say_english": english or say, "action": action, **extra})
        )

    def _route(self, system: str) -> str:
        if system.startswith(RULES[:60]):
            return "brain"
        if system == CAPTION_SYSTEM:
            return "captions"
        if system == SUMMARY_SYSTEM:
            return "summary"
        if system == TRANSLATE_SYSTEM:
            return "lines"
        return "other"

    async def complete(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> Completion:
        route = self._route(system)
        self.seen.append((route, system_dynamic or "", messages[-1].text()))
        if route == "brain":
            if self.gate is not None:
                await self.gate.wait()
            if self.fail_brain > 0:
                self.fail_brain -= 1
                raise LLMTransientError("mock: brain busy")
        queue: deque[str] = getattr(self, route) if route != "other" else deque()
        if route == "summary" and not queue:
            text = json.dumps(
                {"summary": "A call happened.", "agreed": [], "next_steps": [], "needs_you": []}
            )
        elif route == "captions" and not queue:
            text = "(english)"
        else:
            text = queue.popleft() if queue else '{"say": "", "action": "none"}'
        return Completion(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=100, output_tokens=20),
            latency_ms=0,
            cost_usd=self.cost_usd,
        )

    def stream(self, **kw: Any) -> Any:  # never used by calls
        raise NotImplementedError

    def routes(self) -> list[str]:
        return [r for r, _, _ in self.seen]


def registry(provider: RoutedProvider) -> BrainRegistry:
    spec = BrainSpec(
        id="anthropic",
        label="Claude",
        provider=provider,
        tiers={t: f"mock-{t.value}" for t in ModelTier},
    )
    return BrainRegistry([spec], default_id="anthropic")


# ---- the desk and the phone ---------------------------------------------------------------------
class FakeDesk:
    def __init__(
        self, *, ready: bool = True, bt: bool = False, answer_prepare: bool = True
    ) -> None:
        self.sent: list[CloudToDesk] = []
        self.audio: list[bytes] = []
        self.ready = ready
        self.bt = bt
        self.answer_prepare = answer_prepare
        self.session: CallSession | None = None
        self.fail = False

    def types(self) -> list[str]:
        return [m.type for m in self.sent]

    async def send(self, msg: CloudToDesk) -> None:
        if self.fail:
            raise ConnectionError("desk gone")
        self.sent.append(msg)
        if msg.type == "prepare" and self.answer_prepare and self.session is not None:
            self.session.on_mic(False)
        if msg.type == "dtmf" and self.session is not None:
            self.session.on_dtmf_done(msg.digit)

    async def send_audio(self, pcm: bytes) -> None:
        if self.fail:
            raise ConnectionError("desk gone")
        self.audio.append(pcm)

    def is_ready(self) -> bool:
        return self.ready

    def state(self) -> DeskState | None:
        return DeskState(ready=self.ready, bt_headset=self.bt, cable=True, phone_link=True)


class FakePhone:
    def __init__(self) -> None:
        self.sent: list[PhoneCommand] = []
        self.last: CallStateEvent | None = None

    def types(self) -> list[str]:
        return [c.type for c in self.sent]

    async def send(self, command: PhoneCommand) -> None:
        self.sent.append(command)

    def last_state(self) -> CallStateEvent | None:
        return self.last


def phone_event(state: str, call_id: str | None = None, **kw: Any) -> CallStateEvent:
    return CallStateEvent(call_id=call_id, state=state, at=NOW, **kw)  # type: ignore[arg-type]


# ---- speech ------------------------------------------------------------------------------------
class FakeHearing:
    def __init__(self, name: str = "google") -> None:
        self.name = name
        self.script: deque[tuple[str, str]] = deque()  # (lang, text)
        self.asked: list[Sequence[str]] = []
        self.fail = 0

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        self.asked.append(tuple(languages))
        if self.fail:
            self.fail -= 1
            raise RuntimeError("hearing down")
        lang, text = self.script.popleft() if self.script else (languages[0], "")
        return Heard(lang=lang, text=text, confidence=0.95, seconds=len(pcm16k) / 32_000)


class FakeVoice:
    def __init__(self, name: str = "google") -> None:
        self.name = name
        self.spoken: list[tuple[str, str]] = []
        self.gate: asyncio.Event | None = None
        self.fail_langs: set[str] = set()

    async def speak(self, text: str, lang: str) -> bytes:
        if lang in self.fail_langs:
            raise RuntimeError("voice down")
        if self.gate is not None:
            await self.gate.wait()
        self.spoken.append((lang, text))
        return frames(12)


class FakeDetector:
    def __init__(self) -> None:
        self.script: deque[tuple[str, float]] = deque()

    async def detect(self, pcm16k: bytes, candidates: Sequence[str]) -> tuple[str, float]:
        return self.script.popleft() if self.script else (candidates[0], 0.4)


class FakeSpeech:
    def __init__(self, *, detector: bool = False) -> None:
        self.hear = FakeHearing()
        self.voice_ = FakeVoice()
        self.det = FakeDetector() if detector else None
        self.balanced: set[str] = set()
        self.voiceless: set[str] = set()

    def hearing(self, lang: str) -> FakeHearing:
        return self.hear

    def voice(self, lang: str) -> FakeVoice:
        if lang in self.voiceless:
            raise LookupError("no voice for this language")
        return self.voice_

    def detector(self) -> FakeDetector | None:
        return self.det

    def needs_balanced(self, lang: str) -> bool:
        return lang in self.balanced


# ---- A1's seams --------------------------------------------------------------------------------
class FakeRecords:
    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.chunks: list[bytes] = []
        self.objections: list[str] = []
        self.finished: list[tuple[CallRecord, CallSummary, BookedSlot | None]] = []

    async def line(self, uid: str, call_id: str, line: Line) -> None:
        self.lines.append(line)

    async def audio(self, uid: str, call_id: str, pcm: bytes) -> None:
        self.chunks.append(pcm)

    async def objection(self, uid: str, call_id: str) -> None:
        self.objections.append(call_id)
        self.chunks.clear()

    async def finish(
        self,
        uid: str,
        record: CallRecord,
        *,
        card: CallCard | None,
        summary: CallSummary,
        lines: Sequence[Line],
        booked: BookedSlot | None,
    ) -> CallRecord:
        self.finished.append((record, summary, booked))
        return record.model_copy(update={"summary_ref": "vault:summary"})


class FakeSpend:
    def __init__(self, *, model_inr: float = 0.05, hear_inr: float = 0.0, voice_inr: float = 0.0):
        self.model_inr, self.hear_inr, self.voice_inr = model_inr, hear_inr, voice_inr
        self.calls: list[tuple[str, str, float]] = []
        self.ok = True

    async def model(self, uid: str, brain_id: str, completion: Completion) -> float:
        self.calls.append(("model", brain_id, completion.cost_usd))
        return self.model_inr

    async def speech(self, uid: str, option: str, kind: Kind, units: float) -> float:
        self.calls.append((kind, option, units))
        return self.hear_inr if kind == "hear" else self.voice_inr

    async def allowed(self, uid: str) -> bool:
        return self.ok


class FakeSlots:
    def within(self, booking: Booking, day: date, start: time, end: time | None) -> bool:
        for w in booking.windows:
            if w.day == day and w.start <= start and (end or start) <= w.end and start < w.end:
                return True
        return False


class FakeNotice:
    def __init__(self) -> None:
        self.notes: list[str] = []

    async def notice(self, uid: str, call_id: str, text: str) -> None:
        self.notes.append(text)


class FakeGate:
    def __init__(self, refusal: str | None = None) -> None:
        self.refusal = refusal
        self.asked: list[tuple[str, str]] = []

    async def before_dial(self, uid: str, card: CallCard, approval_id: str) -> str | None:
        self.asked.append((card.digest(), approval_id))
        return self.refusal


class Clock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at = self.at + timedelta(seconds=seconds)


FAST = Timing(
    prepare_s=0.2,
    ring_s=0.5,
    answer_s=0.5,
    silence_s=12.0,
    laptop_say_s=0.3,
    desk_grace_s=0.05,
    ask_owner_s=0.2,
    dtmf_s=0.2,
    cap_grace_s=10.0,
    tick_s=0,
    lead_s=0.0,
    pace=False,
)


@dataclass
class Rig:
    """One engine with fakes for every port."""

    provider: RoutedProvider
    desk: FakeDesk
    phone: FakePhone
    speech: FakeSpeech
    records: FakeRecords
    spend: FakeSpend
    notice: FakeNotice
    gate: FakeGate
    store: MemoryCallStore
    audit: AuditLog
    clock: Clock
    deps: EngineDeps
    settings: CallSettings

    def session(
        self,
        card: CallCard | None,
        *,
        mode: SpeechMode = SpeechMode.CLOUD,
        settings: CallSettings | None = None,
    ) -> CallSession:
        direction = Direction.OUTGOING if card is not None else Direction.INCOMING
        record = CallRecord(
            card_id=card.id if card else None,
            direction=direction,
            number_e164=card.number_e164 if card else NUMBER,
            speech_mode=mode,
            started_at=self.clock(),
        )
        s = CallSession(
            self.deps, uid=UID, record=record, card=card, settings=settings or self.settings
        )
        self.desk.session = s
        return s


def rig(
    *,
    detector: bool = False,
    gate: str | None = None,
    settings: CallSettings | None = None,
    timing: Timing = FAST,
    desk: FakeDesk | None = None,
) -> Rig:
    provider = RoutedProvider()
    brains = registry(provider)
    r = Rig(
        provider=provider,
        desk=desk or FakeDesk(),
        phone=FakePhone(),
        speech=FakeSpeech(detector=detector),
        records=FakeRecords(),
        spend=FakeSpend(),
        notice=FakeNotice(),
        gate=FakeGate(gate),
        store=MemoryCallStore(),
        audit=AuditLog(),
        clock=Clock(),
        deps=None,  # type: ignore[arg-type]
        settings=settings or CallSettings(owner_first_name="Asha"),
    )
    r.deps = EngineDeps(
        desk=r.desk,
        phone=r.phone,
        speech=r.speech,
        brain=CallBrain(brains),
        captions=Captioner(brains),
        summarizer=Summarizer(brains),
        lines=FixedLines(brains),
        store=r.store,
        records=r.records,
        spend=r.spend,
        slots=FakeSlots(),
        notice=r.notice,
        audit=r.audit,
        gate=r.gate,
        clock=r.clock,
        timing=timing,
    )
    return r


def card(
    *,
    languages: tuple[str, ...] = ("en-IN",),
    booking: bool = False,
    max_minutes: int = 6,
    max_inr: int = 20,
) -> CallCard:
    book = None
    if booking:
        book = Booking(
            windows=(TimeWindow(day=date(2026, 11, 28), start=time(10, 0), end=time(12, 0)),),
            give_name="Asha",
            give_number=NUMBER,
            reason="Laundry pickup",
        )
    return CallCard(
        number_e164=NUMBER,
        purpose="Book a laundry pickup",
        may_say=("The pickup address is on file with the laundry",),
        languages=languages,
        booking=book,
        limits={"max_minutes": max_minutes, "max_inr": max_inr},  # type: ignore[arg-type]
    )


async def connect(r: Rig, s: CallSession, approval: str = "appr_12345678") -> asyncio.Task[None]:
    """Start an outgoing call and answer it on the phone."""
    task = asyncio.create_task(s.start_outgoing(approval))
    for _ in range(200):
        await asyncio.sleep(0)
        if "call.dial" in r.phone.types():
            break
    await s.on_phone_state(phone_event("active", s.call_id))
    for _ in range(200):
        await asyncio.sleep(0)
        if task.done():
            break
    return task


async def them(r: Rig, s: CallSession, text: str, lang: str = "en-IN") -> None:
    """The other person says `text` (cloud mode: VAD on, audio, VAD off, then hearing)."""
    r.speech.hear.script.append((lang, text))
    s.on_vad(True)
    s.on_audio(frames(25))
    s.on_vad(False)
    await settle(s)


async def settle(s: CallSession, rounds: int = 3) -> None:
    for _ in range(rounds):
        await s.settle()
        await asyncio.sleep(0)


def spoken(r: Rig) -> list[str]:
    return [t for _, t in r.speech.voice_.spoken]


Watcher = Callable[[], bool]
