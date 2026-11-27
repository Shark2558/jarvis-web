# src/jarvis/calls/join.py
"""R18 I1: the adapters that join the calls parts (docs/plans/r18-integration/I1-NOTES.md). Each
part coded against its own Protocol; these turn one part's names into another's, nothing more.

    A1 `CallStarter`         EngineStarter     -> A2 `CallHub.start_outgoing`
    A2 `DialGate`            GrantGate         -> A1 `CallsService.take_for_dial`
    D  `ApprovalCheck`       PhoneApprovals    -> A1 `GrantBook.live_until` (spends nothing)
    A2 `SlotCheck`           BookingSlots      -> A1 `booking.booking_slot`
    A2 `RecordsSink`         VaultRecords      -> A1 `RecordKeeper` + `BookingCalendar`
    A2 `AnsweringPolicy`     HubAnswering      -> A1 `AnsweringPolicy`
    D  `AnsweringView`       AnsweringRules    -> I0 `CallStore.settings`
    D  `CardDesk`            PhoneCardDesk     -> A1 `CardsApi.approve` / `cancel`
    D  `PhoneEventSink`      HubPhoneSink      -> A2 `CallHub.phone_event`
    A2 `OwnerNotice`         PushNotice        -> Web Push (`app.state.push`), kind `call_notice`
    I0 `PhoneLink` (none)    NoPhone           every command refused (no phone part)

`status_view` is the Calls panel's ready check (`GET /v1/calls/status`). Nothing here logs a
number, a transcript or audio.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

from jarvis.calls.approvals import CallsService, GrantBook, GrantInvalid
from jarvis.calls.booking import BookingCalendar, booking_slot
from jarvis.calls.brain import Line
from jarvis.calls.cards import CardRefused
from jarvis.calls.engine_ports import BookedSlot, desk_problems
from jarvis.calls.hub import CallHub
from jarvis.calls.limits import IST, LimitRefused, ist_day, ist_month
from jarvis.calls.models import (
    CALLS_PER_DAY,
    Booking,
    CallCard,
    CallRecord,
    CallSettings,
    Speaker,
    is_language,
)
from jarvis.calls.ports import CallsRefused, CallStore
from jarvis.calls.protocol import FRAME_BYTES, CallStateEvent, PhoneCommand
from jarvis.calls.records import (
    MAX_AUDIO_BYTES,
    RecordKeeper,
    RecordRefused,
    Transcript,
    TranscriptLine,
)
from jarvis.calls.records import CallSummary as KeptSummary
from jarvis.calls.speech.audio import from_float, resample, to_float, wav_from_pcm
from jarvis.calls.summary import CallSummary
from jarvis.calls.templates import catalogue
from jarvis.logging import get_logger

log = get_logger(__name__)

MSG_UNREADABLE = "JARVIS can't check the call's approval just now, so nothing was dialled."
RECORD_RATE = 8_000  # the phone line is narrowband: the kept recording is 8 kHz WAV (I1)
RECORD_MAX_PCM = MAX_AUDIO_BYTES - 64  # the WAV header fits under A1's cap (≈ 17 minutes)
NOTICE_KIND = "call_notice"
FAILED_DIAL = frozenset({"refused", "no_permission", "expired", "no_phone"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---- A1 -> A2: start the approved call ---------------------------------------------------------
class Refresh(Protocol):
    """`SpeechChoices.refresh`: (owner, the call's languages, its length in minutes)."""

    async def __call__(
        self, uid: str, languages: Sequence[str] | None, minutes: int | None = None
    ) -> None: ...


class EngineStarter:
    """A1's `CallStarter`: the approved card's call runs in the hub (one per owner); `refresh`
    reads the language table first (free first, for the card's own length), so the call's
    speech is the one its card was estimated with."""

    def __init__(self, hub: CallHub, refresh: Refresh | None = None) -> None:
        self._hub, self._refresh = hub, refresh

    async def start(self, uid: str, card: CallCard, approval_id: str) -> str:
        if self._refresh is not None:
            await self._refresh(uid, card.languages, card.limits.max_minutes)
        record = await self._hub.start_outgoing(uid, card, approval_id)
        return record.id


# ---- A2 -> A1: the dial gate -------------------------------------------------------------------
class GrantGate:
    """A2's `DialGate`: spend the grant for THIS call, match the card, count the call."""

    def __init__(self, service: CallsService) -> None:
        self._service = service

    async def before_dial(
        self, uid: str, card: CallCard, approval_id: str, call_id: str
    ) -> str | None:
        try:
            used = await self._service.take_for_dial(uid, approval_id, call_id)
        except GrantInvalid as exc:
            return str(exc)
        except (CardRefused, LimitRefused) as exc:
            return exc.words
        except Exception as exc:  # noqa: BLE001 - fail closed: nothing is dialled
            log.error("dial gate failed", extra={"error": type(exc).__name__})
            return MSG_UNREADABLE
        if used.id != card.id or used.digest() != card.digest():
            return "The call card changed since it was approved, so nothing was dialled."
        return None


class PhoneApprovals:
    """D's `ApprovalCheck`: the dial's approval is the grant taken for this call (unix seconds)."""

    def __init__(self, grants: GrantBook) -> None:
        self._grants = grants

    async def live_until(
        self, uid: str, approval_id: str, call_id: str, number_e164: str
    ) -> float | None:
        until = await self._grants.live_until(uid, approval_id, call_id, number_e164)
        return None if until is None else until.timestamp()


# ---- A2 -> A1: a booking's slot ----------------------------------------------------------------
class BookingSlots:
    """A2's `SlotCheck` on A1's rule (inside one window, not in the past; IST)."""

    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock

    def within(self, booking: Booking, day: date, start: time, end: time | None) -> bool:
        begin = datetime.combine(day, start, tzinfo=IST)
        minutes: int | None = None
        if end is not None:
            span = datetime.combine(day, end, tzinfo=IST) - begin
            if span <= timedelta(0):
                return False
            minutes = int(span.total_seconds() // 60)
        return booking_slot(booking, begin, now=self._clock(), minutes=minutes).ok


# ---- A2 -> A1: records in the vault ------------------------------------------------------------
def _narrowband(pcm: bytes) -> bytes:
    usable = pcm[: len(pcm) - len(pcm) % 2]
    return from_float(resample(to_float(usable), 16_000, RECORD_RATE)) if usable else b""


def transcript_of(lines: Sequence[Line]) -> Transcript:
    kept = []
    for ln in lines[:2_000]:
        if not ln.text.strip() or not is_language(ln.lang):
            continue
        english = "" if ln.lang.startswith("en-") else ln.english
        kept.append(
            TranscriptLine(
                who=Speaker(ln.who), lang=ln.lang, text=ln.text[:4_000], english=english[:4_000]
            )
        )
    return Transcript(lines=tuple(kept))


def summary_of(s: CallSummary, record: CallRecord, booked: BookedSlot | None) -> KeptSummary:
    start = None if booked is None else datetime.combine(booked.day, booked.start, tzinfo=IST)
    return KeptSummary(
        english=(s.text.strip() or "The call ended.")[:4_000],
        agreed=tuple(s.agreed[:20]),
        next_steps=tuple(s.next_steps[:20]),
        needs_owner=tuple(s.needs_you[:20]),
        booked_start=start,
        cost_inr=max(0.0, record.cost_inr),
        cost_parts={k: max(0.0, v) for k, v in record.cost_parts.items()},
    )


class VaultRecords:
    """A2's `RecordsSink`. Audio is held in memory for the call (8 kHz, at most `RECORD_MAX_PCM`
    bytes) and sealed once at its end with the transcript and the summary; an objection drops
    what was held and keeps no more. `finish` never raises: each part that fails is logged and
    the record keeps the parts that were sealed."""

    def __init__(self, keeper: RecordKeeper, booking: BookingCalendar | None = None) -> None:
        self._keeper, self.booking = keeper, booking  # booking: set once the gateway exists
        self._audio: dict[str, bytearray] = {}
        self._objected: set[str] = set()

    async def line(self, uid: str, call_id: str, line: Line) -> None:
        return None  # the whole transcript comes with `finish`

    async def audio(self, uid: str, call_id: str, pcm: bytes) -> None:
        if call_id in self._objected or len(pcm) % FRAME_BYTES:
            return
        buf = self._audio.setdefault(call_id, bytearray())
        part = _narrowband(pcm)
        if len(buf) + len(part) > RECORD_MAX_PCM:
            log.warning("call recording reached its size cap: the rest is not kept")
            return
        buf += part

    async def objection(self, uid: str, call_id: str) -> None:
        self._objected.add(call_id)
        self._audio.pop(call_id, None)

    async def _step(self, what: str, run: Callable[[], Awaitable[CallRecord]]) -> CallRecord | None:
        try:
            return await run()
        except RecordRefused as exc:
            log.warning("call record part not kept", extra={"part": what, "code": exc.code})
        except Exception as exc:  # noqa: BLE001 - the other parts are still kept
            log.error("call record part failed", extra={"part": what, "error": type(exc).__name__})
        return None

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
        pcm = bytes(self._audio.pop(record.id, b""))
        objected = record.objected or record.id in self._objected
        self._objected.discard(record.id)
        keeper, rec = self._keeper, record
        try:
            await keeper.store.put_record(uid, rec)  # the keeper reads the record back
        except Exception as exc:  # noqa: BLE001 - the engine saves it again after this
            log.error("call record not saved", extra={"error": type(exc).__name__})
            return rec
        if pcm and rec.recorded and not objected:
            wav = wav_from_pcm(pcm, RECORD_RATE)
            rec = (
                await self._step(
                    "audio", lambda: keeper.save_audio(uid, record.id, wav, "audio/wav")
                )
                or rec
            )
        if lines and not objected:
            text = transcript_of(lines)
            rec = (
                await self._step("transcript", lambda: keeper.save_transcript(uid, record.id, text))
                or rec
            )
        kept = summary_of(summary, record, booked)
        rec = await self._step("summary", lambda: keeper.save_summary(uid, record.id, kept)) or rec
        if booked is not None and card is not None and self.booking is not None:
            rec = await self._book(uid, rec, card, booked)
        return rec

    async def _book(
        self, uid: str, rec: CallRecord, card: CallCard, booked: BookedSlot
    ) -> CallRecord:
        assert self.booking is not None
        start = datetime.combine(booked.day, booked.start, tzinfo=IST)
        try:
            out = await self.booking.add(uid, rec.id, card, start)
            log.info("booking after the call", extra={"status": out.status})
            return await self._keeper.record(uid, rec.id)
        except Exception as exc:  # noqa: BLE001 - the summary says what was agreed
            log.error("booking calendar add failed", extra={"error": type(exc).__name__})
            return rec


# ---- answering missed calls (row 104) ----------------------------------------------------------
class _Answering(Protocol):
    async def should_answer(self, uid: str, event: CallStateEvent) -> Any: ...


class HubAnswering:
    """A2's `AnsweringPolicy` on A1's (which decides on the phone's ringing event)."""

    def __init__(self, policy: _Answering, clock: Callable[[], datetime] = _utcnow) -> None:
        self._policy, self._clock = policy, clock

    async def should_answer(
        self, uid: str, number_e164: str, rings: int, settings: CallSettings
    ) -> bool:
        del settings  # A1 reads them itself, in the same decision
        event = CallStateEvent(
            state="ringing", number_e164=number_e164, rings=min(rings, 60), at=self._clock()
        )
        decision = await self._policy.should_answer(uid, event)
        return bool(getattr(decision, "answer", False))


class AnsweringRules:
    """D's `AnsweringView`: on, and the ring count (off when the settings can't be read)."""

    def __init__(self, store: CallStore) -> None:
        self._store = store

    async def rule(self, uid: str) -> Any:
        from jarvis.phone.calls import AnsweringRule  # the phone side's own shape

        s = await self._store.settings(uid)
        return AnsweringRule(on=s.answering_on, after_rings=s.answer_after_rings)


# ---- the phone (D) -----------------------------------------------------------------------------
class _Cards(Protocol):
    async def approve(self, uid: str, card_id: str, body: dict[str, Any]) -> dict[str, Any]: ...

    async def cancel(self, uid: str, card_id: str) -> dict[str, Any]: ...


_GONE = frozenset({"gone", "not_found", "not_waiting", "changed"})


class PhoneCardDesk:
    """D's `CardDesk`: Approve / Decline tapped on the phone is his press in the Calls panel
    (the same gateway card; a new number, or his passkey in force, opens the console)."""

    def __init__(self, cards: Callable[[], _Cards | None], store: CallStore) -> None:
        self._cards, self._store = cards, store

    async def decide(self, uid: str, card_id: str, decision: str, device_id: str) -> str:
        cards = self._cards()
        if cards is None:
            return "unavailable"
        try:
            if decision == "decline":
                await cards.cancel(uid, card_id)
                return "declined"
            card = await self._store.get_card(uid, card_id)
            if card is None:
                return "gone"
            if card.new_number:
                return "passkey_needed"
            out = await cards.approve(uid, card_id, {})
        except CallsRefused as exc:
            return "gone" if exc.code in _GONE else "unavailable"
        except Exception as exc:  # noqa: BLE001 - the phone says "try in JARVIS"
            log.error("phone card decision failed", extra={"error": type(exc).__name__})
            return "unavailable"
        return "passkey_needed" if out.get("status") == "needs_passkey" else "approved"


class _Hub(Protocol):
    async def phone_event(self, uid: str, ev: CallStateEvent) -> None: ...


class HubPhoneSink:
    """D's `PhoneEventSink`: call states to the hub (the language table read first for a ringing
    call JARVIS may answer); a dial the phone could not place ends that call at once."""

    def __init__(
        self,
        hub: _Hub,
        refresh: Refresh | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._hub, self._refresh, self._clock = hub, refresh, clock

    async def phone_state(self, uid: str, event: CallStateEvent) -> None:
        if event.state == "ringing" and event.call_id is None and self._refresh is not None:
            await self._refresh(uid, None)  # an answered call speaks his default languages
        await self._hub.phone_event(uid, event)

    async def phone_result(self, uid: str, result: Any) -> None:
        call_id, command, code = result.call_id, result.command, result.code
        log.info("phone command result", extra={"command": command, "code": code})
        if command == "call.dial" and not result.ok and code in FAILED_DIAL and call_id:
            ended = CallStateEvent(call_id=call_id, state="ended", at=self._clock())
            await self._hub.phone_event(uid, ended)


class NoPhone:
    """I0's `PhoneLink` when no phone part is built (mobile off): nothing is ever sent."""

    async def send(self, command: PhoneCommand) -> None:
        raise ConnectionError("no phone is linked to JARVIS")

    def last_state(self) -> CallStateEvent | None:
        return None


class _Push(Protocol):
    async def send(self, uid: str, *, kind: str, text: str, silent: bool = False) -> int: ...


class PushNotice:
    """A2's `OwnerNotice`: a Web Push to his own devices (the Calls panel opens on a tap)."""

    def __init__(self, push: Callable[[], _Push | None]) -> None:
        self._push = push

    async def notice(self, uid: str, call_id: str, text: str) -> None:
        push = self._push()
        if push is None:
            return
        try:
            await push.send(uid, kind=NOTICE_KIND, text=" ".join(text.split())[:400])
        except Exception as exc:  # noqa: BLE001 - the Calls panel shows the same
            log.warning("call notice not sent", extra={"error": type(exc).__name__})


# ---- the ready check -----------------------------------------------------------------------------
class _PhoneReady(Protocol):
    async def readiness(self, uid: str) -> Any: ...


async def status_view(
    uid: str,
    *,
    hub: CallHub,
    store: CallStore,
    phone: _PhoneReady | None,
    clock: Callable[[], datetime] = _utcnow,
) -> dict[str, Any]:
    """`GET /v1/calls/status`: the desk and the phone as the cloud last heard them, today's
    calls, this month's ₹ against the calls cap, the call that is on, and the ready cards."""
    now = clock()
    conn = hub.desk(uid)
    st = conn.state() if conn is not None else None
    desk = {
        "connected": conn is not None,
        "ready": conn is not None and conn.is_ready(),
        "problems": desk_problems(st, connected=conn is not None),
        "bt_headset": bool(st and st.bt_headset),
        "cable": bool(st and st.cable),
        "phone_link": bool(st and st.phone_link),
        "version": conn.hello.desk_version if conn is not None and conn.hello else None,
    }
    ready = None if phone is None else await phone.readiness(uid)
    phone_view = {
        "linked": ready is not None and ready.device_id is not None,
        "ready": ready is not None and bool(ready.ready),
        "problems": list(ready.problems) if ready is not None else ["no_phone"],
    }
    settings = await store.settings(uid)
    counts = await store.day_counts(uid, ist_day(now))
    used = await store.month_spend(uid, ist_month(now))
    session = hub.active(uid)
    active = None
    if session is not None:
        active = {"call_id": session.call_id, "state": session.state.value}
    return {
        "desk": desk,
        "phone": phone_view,
        "month": {"used_inr": round(used, 2), "cap_inr": settings.month_cap_inr},
        "today": {"calls": counts.calls, "max": CALLS_PER_DAY},
        "active": active,
        "templates": catalogue(),
        "ready": desk["ready"] is True and phone_view["ready"] is True,
    }


__all__ = [
    "FAILED_DIAL",
    "NOTICE_KIND",
    "RECORD_RATE",
    "AnsweringRules",
    "BookingSlots",
    "EngineStarter",
    "GrantGate",
    "HubAnswering",
    "HubPhoneSink",
    "NoPhone",
    "PhoneApprovals",
    "PhoneCardDesk",
    "PushNotice",
    "VaultRecords",
    "status_view",
    "summary_of",
    "transcript_of",
]
