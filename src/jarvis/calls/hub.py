# src/jarvis/calls/hub.py
"""The call hub (R18 A2; docs/plans/r18-calls.md 4 and 8; Layers 3 and 6). In memory: Cloud Run
runs one instance (`--max-instances 1`), so one hub joins everything.

- `DeskStore` + `DeskDoorService` (`app.state.calls_desk_door`): linking the call desk like the
  home bridge. The owner asks for a code (8 Crockford characters, 10 minutes, one use, stored as
  SHA-256); the desk sends it to `POST /v1/calls/desk/link` and gets its id (`h_` + 8 hex, so
  `jarvis.home.signing` is reused unchanged) and a 32-byte seed ONCE. The seed is stored sealed
  (`Keyring` purpose `calls`, bound to the owner). Every desk socket is then signed with the UP
  key derived from it (`jarvis.api.calls_ws`).
- `DeskConnection` (the `DeskLink` of one live desk socket) and `DeskProxy` (what a call uses: it
  always reaches the owner's CURRENT desk socket, so a desk that reconnects carries on the call).
- `CallHub`: the owner's one call at a time (one phone line), phone events in (D), the answering
  decision for a missed call (A1's `AnsweringPolicy`), the call's live listeners.
- `BillingSpend`: the engine's `Spend` on `jarvis.billing` and `jarvis.calls.prices`.

Nothing here logs a number, a seed, audio or a transcript.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from jarvis.billing.service import Billing, BudgetError
from jarvis.calls.engine import CallSession
from jarvis.calls.engine_ports import EngineDeps, Kind
from jarvis.calls.live import LiveListener
from jarvis.calls.models import (
    CallCard,
    CallRecord,
    CallSettings,
    CallState,
    Direction,
    SpeechMode,
    SpeechOption,
)
from jarvis.calls.ports import CallsRefused, CallStore
from jarvis.calls.prices import PriceUnknown, SpeechPrice
from jarvis.calls.protocol import (
    DESK_WS_PATH,
    CallStateEvent,
    CloudToDesk,
    DeskState,
    Hello,
    dump,
    pack_audio,
)
from jarvis.calls.protocol import AudioKind as _Audio
from jarvis.home import signing
from jarvis.llm.base import Completion
from jarvis.llm.brains import BrainSpec
from jarvis.llm.pricing import cost_usd
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, Query, Set
from jarvis.storage.sessions import safe_id
from jarvis.voice.catalogue import STT_KEY, TTS_KEYS

log = get_logger(__name__)

CODE_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)
CODE_LEN = 8
CODE_TTL_S = 600.0
MAX_WRONG_CODES = 20  # a 10-minute window, every client together (the route is rate-limited too)
WRONG_WINDOW_S = 600.0
DESK_COLL, CODE_COLL = "call_desk", "call_desk_codes"
SEND_TIMEOUT_S = 5.0
_FIX = str.maketrans({"I": "1", "L": "1", "O": "0"})
_CODE_RE = re.compile(r"[0-9A-Z]{8}")
_VERSION_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
_DESK_RE = re.compile(r"h_[0-9a-f]{8}")
BAD_CODE = "That code isn't right or has expired. Ask JARVIS for a new one in the Calls panel."
BAD_LINK = "That link request isn't valid."
BUSY_LINE = "A call is already on: one call at a time."


# ---- the desk's link ---------------------------------------------------------------------------
class SeedCipher(Protocol):
    """`Keyring.cipher("calls")` fits (`TokenCipher`)."""

    def encrypt(self, plaintext: bytes, *, aad: str) -> str: ...

    def decrypt(self, blob: str, *, aad: str) -> bytes: ...


@dataclass(frozen=True, repr=False)
class DeskRecord:
    uid: str
    desk_id: str
    seed: bytes

    def keys(self) -> signing.HomeKeys:
        return signing.derive_keys(self.seed)

    def __repr__(self) -> str:
        return f"DeskRecord({self.desk_id})"


def normalise_code(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    text = code.upper().replace("-", "").replace(" ", "").translate(_FIX)
    if not _CODE_RE.fullmatch(text) or any(c not in CODE_CHARS for c in text):
        return None
    return text


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


class DeskStore:
    """{prefix}call_desk/{uid}         desk_id, seed_sealed, desk_version, linked_at
    {prefix}call_desk_codes/{uid}   code_hash, expires_at"""

    def __init__(
        self,
        docs: Docs,
        cipher: SeedCipher,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._d = docs
        self._cipher = cipher
        self._desks = f"{prefix}{DESK_COLL}"
        self._codes = f"{prefix}{CODE_COLL}"
        self._clock = clock
        self._by_desk: dict[str, str] = {}
        self._wrong: tuple[int, float] = (0, 0.0)

    @staticmethod
    def _owner(uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("not an owner id")
        return uid

    def _aad(self, uid: str) -> str:
        return f"calls/desk/{uid}"

    async def put_code(self, uid: str, digest: str, expires_at: float) -> None:
        doc = {"code_hash": digest, "expires_at": expires_at}
        await self._d.write([Set(f"{self._codes}/{self._owner(uid)}", doc)])

    async def take_code(self, digest: str) -> str | None:
        """The owner whose live code this is, else None (a wrong one is counted; after
        `MAX_WRONG_CODES` in the window every code is refused until it passes)."""
        now = self._clock()
        count, since = self._wrong
        if since and now - since >= WRONG_WINDOW_S:
            count, since = 0, 0.0
        if count >= MAX_WRONG_CODES:
            self._wrong = (count, since)
            return None
        for uid, doc in await self._d.query(Query(self._codes, limit=20)):
            expires = doc.get("expires_at")
            live = isinstance(expires, int | float) and expires > now
            if live and secrets.compare_digest(str(doc.get("code_hash", "")), digest):
                return uid
        self._wrong = (count + 1, since or now)
        return None

    async def spend_code(self, uid: str) -> None:
        await self._d.write([Delete(f"{self._codes}/{self._owner(uid)}")])

    async def link(self, uid: str, desk_id: str, seed: bytes, version: str) -> None:
        sealed = self._cipher.encrypt(seed, aad=self._aad(uid))
        doc = {
            "desk_id": desk_id,
            "seed_sealed": sealed,
            "desk_version": version,
            "linked_at": self._clock(),
        }
        old = await self.load(uid)
        await self._d.write([Set(f"{self._desks}/{self._owner(uid)}", doc)])
        if old is not None:
            self._by_desk.pop(old.desk_id, None)
        self._by_desk[desk_id] = uid

    async def unlink(self, uid: str) -> bool:
        old = await self.load(uid)
        await self._d.write([Delete(f"{self._desks}/{self._owner(uid)}")])
        if old is not None:
            self._by_desk.pop(old.desk_id, None)
        return old is not None

    async def load(self, uid: str) -> DeskRecord | None:
        doc = await self._d.get(f"{self._desks}/{self._owner(uid)}")
        if not doc:
            return None
        desk_id, sealed = doc.get("desk_id"), doc.get("seed_sealed")
        if not isinstance(desk_id, str) or not _DESK_RE.fullmatch(desk_id):
            return None
        if not isinstance(sealed, str):
            return None
        try:
            seed = self._cipher.decrypt(sealed, aad=self._aad(uid))
        except Exception:  # noqa: BLE001 - a seed that does not open is no desk (never a guess)
            log.error("call desk seed does not open")
            return None
        if len(seed) != signing.SEED_BYTES:
            return None
        return DeskRecord(uid=uid, desk_id=desk_id, seed=seed)

    async def find(self, desk_id: str) -> DeskRecord | None:
        if not _DESK_RE.fullmatch(desk_id):
            return None
        uid = self._by_desk.get(desk_id)
        if uid is None:
            rows = await self._d.query(Query(self._desks, where=("desk_id", desk_id), limit=1))
            if not rows:
                return None
            uid = rows[0][0]
        rec = await self.load(uid)
        if rec is None or rec.desk_id != desk_id:
            self._by_desk.pop(desk_id, None)
            return None
        self._by_desk[desk_id] = uid
        return rec


class DeskDoorService:
    """`app.state.calls_desk_door` (I0's `DeskDoor`)."""

    def __init__(
        self, store: DeskStore, hub: CallHub, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._store = store
        self._hub = hub
        self._clock = clock

    async def code(self, uid: str) -> dict[str, Any]:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))
        await self._store.put_code(uid, code_hash(code), self._clock() + CODE_TTL_S)
        return {"code": f"{code[:4]}-{code[4:]}", "expires_in_s": int(CODE_TTL_S)}

    async def link(self, body: dict[str, Any]) -> dict[str, Any]:
        norm = normalise_code(body.get("code"))
        version = body.get("desk_version")
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise CallsRefused(422, "bad_request", BAD_LINK)
        uid = None if norm is None else await self._store.take_code(code_hash(norm))
        if uid is None:
            raise CallsRefused(401, "bad_code", BAD_CODE)
        desk_id = "h_" + secrets.token_hex(4)
        seed = signing.new_seed()
        await self._store.link(uid, desk_id, seed, version)
        await self._store.spend_code(uid)
        await self._hub.drop_desk(uid)  # an older desk's socket stops at once
        log.info("call desk linked")
        seed_b64 = base64.urlsafe_b64encode(seed).decode("ascii").rstrip("=")
        return {"desk_id": desk_id, "seed": seed_b64, "ws_path": DESK_WS_PATH}

    async def unlink(self, uid: str) -> dict[str, Any]:
        gone = await self._store.unlink(uid)
        await self._hub.drop_desk(uid)
        return {"unlinked": gone}


# ---- one live desk socket ----------------------------------------------------------------------
class DeskSocket(Protocol):
    async def send_text(self, data: str) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, code: int) -> None: ...


class DeskConnection:
    """The `DeskLink` of one desk socket. Sends are serialised and time-limited."""

    def __init__(self, uid: str, sock: DeskSocket, *, send_timeout_s: float = SEND_TIMEOUT_S):
        self.uid = uid
        self._sock = sock
        self._lock = asyncio.Lock()
        self._timeout = send_timeout_s
        self.hello: Hello | None = None
        self.last_state: DeskState | None = None
        self.open = True

    async def _send(self, text: str | None, data: bytes | None) -> None:
        if not self.open:
            raise ConnectionError("the call desk is not connected")
        async with self._lock:
            try:
                if text is not None:
                    await asyncio.wait_for(self._sock.send_text(text), self._timeout)
                elif data is not None:
                    await asyncio.wait_for(self._sock.send_bytes(data), self._timeout)
            except Exception as exc:
                self.open = False
                raise ConnectionError("the call desk did not take the message") from exc

    async def send(self, msg: CloudToDesk) -> None:
        await self._send(dump(msg), None)

    async def send_audio(self, pcm: bytes) -> None:
        await self._send(None, pack_audio(_Audio.JARVIS, pcm))

    def is_ready(self) -> bool:
        return self.open and self.last_state is not None and self.last_state.ready

    def state(self) -> DeskState | None:
        return self.last_state if self.open else None

    async def close(self, code: int = 1000) -> None:
        self.open = False
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._sock.close(code), self._timeout)


class DeskProxy:
    """What a call holds: always the owner's current desk socket (or none)."""

    def __init__(self, hub: CallHub, uid: str) -> None:
        self._hub = hub
        self._uid = uid

    def _conn(self) -> DeskConnection:
        conn = self._hub.desk(self._uid)
        if conn is None:
            raise ConnectionError("the call desk is not connected")
        return conn

    async def send(self, msg: CloudToDesk) -> None:
        await self._conn().send(msg)

    async def send_audio(self, pcm: bytes) -> None:
        await self._conn().send_audio(pcm)

    def is_ready(self) -> bool:
        conn = self._hub.desk(self._uid)
        return conn is not None and conn.is_ready()

    def state(self) -> DeskState | None:
        conn = self._hub.desk(self._uid)
        return conn.state() if conn is not None else None


# ---- the hub -----------------------------------------------------------------------------------
class AnsweringPolicy(Protocol):
    """A1 (row 104): answer this ringing call for the owner? Off by default; after N rings; all /
    saved contacts only / everyone except saved contacts."""

    async def should_answer(
        self, uid: str, number_e164: str, rings: int, settings: CallSettings
    ) -> bool: ...


DepsFor = Callable[[str, DeskProxy], EngineDeps]


class CallHub:
    def __init__(
        self,
        deps_for: DepsFor,
        store: CallStore,
        *,
        answering: AnsweringPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._deps_for = deps_for
        self._clock = clock
        self._store = store
        self._answering = answering
        self._desks: dict[str, DeskConnection] = {}
        self._calls: dict[str, tuple[str, CallSession]] = {}
        self._active: dict[str, str] = {}  # uid -> call id (one phone line)
        self._asked: set[str] = set()  # owners whose ringing call was decided on
        self._tasks: set[asyncio.Task[Any]] = set()

    # ---- desks -----------------------------------------------------------------------------
    def desk(self, uid: str) -> DeskConnection | None:
        conn = self._desks.get(uid)
        return conn if conn is not None and conn.open else None

    async def desk_joined(self, conn: DeskConnection) -> None:
        old = self._desks.get(conn.uid)
        self._desks[conn.uid] = conn
        if old is not None and old is not conn:
            await old.close(4409)  # one socket per desk: the newest wins
        session = self.active(conn.uid)
        if session is not None:
            await session.on_desk_back()

    def desk_left(self, conn: DeskConnection) -> None:
        if self._desks.get(conn.uid) is not conn:
            return  # an older socket the newest replaced
        del self._desks[conn.uid]
        session = self.active(conn.uid)
        if session is not None:
            session.on_desk_lost()

    async def drop_desk(self, uid: str) -> None:
        conn = self._desks.pop(uid, None)
        if conn is not None:
            await conn.close(4401)
            session = self.active(uid)
            if session is not None:
                session.on_desk_lost()

    # ---- calls -----------------------------------------------------------------------------
    def active(self, uid: str) -> CallSession | None:
        call_id = self._active.get(uid)
        found = self._calls.get(call_id) if call_id else None
        return found[1] if found is not None else None

    def session(self, uid: str, call_id: str) -> CallSession | None:
        found = self._calls.get(call_id)
        if found is None or found[0] != uid:
            return None
        return found[1]

    def _new(
        self, uid: str, record: CallRecord, card: CallCard | None, s: CallSettings
    ) -> CallSession:
        if self.active(uid) is not None:
            raise CallsRefused(409, "line_busy", BUSY_LINE)
        session = CallSession(
            self._deps_for(uid, DeskProxy(self, uid)),
            uid=uid,
            record=record,
            card=card,
            settings=s,
        )
        self._calls[record.id] = (uid, session)
        self._active[uid] = record.id
        return session

    def _run(self, uid: str, session: CallSession, start: Any) -> None:
        async def go() -> None:
            try:
                await start
            finally:
                await session.done.wait()
                await session.settle()
                if self._active.get(uid) == session.call_id:
                    del self._active[uid]
                self._calls.pop(session.call_id, None)

        task = asyncio.ensure_future(go())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start_outgoing(
        self,
        uid: str,
        card: CallCard,
        approval_id: str,
        *,
        speech_mode: SpeechMode = SpeechMode.CLOUD,
    ) -> CallRecord:
        """A1, after his tap: the call runs in the background; its record comes back at once."""
        settings = await self._store.settings(uid)
        record = CallRecord(
            card_id=card.id,
            direction=Direction.OUTGOING,
            number_e164=card.number_e164,
            contact_name=card.contact_name,
            speech_mode=speech_mode,
            started_at=self._clock(),
            retention_days=settings.retention_days,
            recorded=settings.record_audio,
        )
        session = self._new(uid, record, card, settings)
        self._run(uid, session, session.start_outgoing(approval_id))
        return record

    async def phone_event(self, uid: str, ev: CallStateEvent) -> None:
        """D: a call state from the owner's phone (already checked by the phone's door)."""
        session = self.session(uid, ev.call_id) if ev.call_id else self.active(uid)
        if session is not None:
            await session.on_phone_state(ev)
            if ev.state == "ended":
                self._asked.discard(uid)
            return
        if ev.state == "ended":
            self._asked.discard(uid)
            return
        if ev.state == "ringing" and ev.call_id is None and ev.number_e164:
            await self._maybe_answer(uid, ev)

    async def _maybe_answer(self, uid: str, ev: CallStateEvent) -> None:
        number = ev.number_e164
        if self._answering is None or not number or uid in self._asked or self.active(uid):
            return
        self._asked.add(uid)  # before any await: a second ringing event can't race this one
        try:
            settings = await self._store.settings(uid)
            if not settings.answering_on or ev.rings < settings.answer_after_rings:
                self._asked.discard(uid)  # not yet: a later ring may still be answered
                return
            yes = await self._answering.should_answer(uid, number, ev.rings, settings)
        except Exception as exc:  # noqa: BLE001 - when in doubt, JARVIS does not answer
            log.warning("answering policy failed", extra={"error": type(exc).__name__})
            yes = False
        if not yes or self.active(uid) is not None:
            return
        record = CallRecord(
            direction=Direction.INCOMING,
            number_e164=number,
            state=CallState.PREPARING,
            started_at=ev.at,
            retention_days=settings.retention_days,
            recorded=settings.record_audio,
        )
        session = self._new(uid, record, None, settings)
        self._run(uid, session, session.start_answering())

    # ---- listeners -------------------------------------------------------------------------
    def listen(self, uid: str, call_id: str, listener: LiveListener) -> CallSession | None:
        session = self.session(uid, call_id)
        if session is not None:
            session.add_listener(listener)
        return session

    async def aclose(self) -> None:
        for uid in list(self._desks):
            await self.drop_desk(uid)
        for task in list(self._tasks):
            task.cancel()


# ---- metering ----------------------------------------------------------------------------------
PriceTable = Callable[[float], Mapping[SpeechOption, SpeechPrice]]
METER_LABEL = "calls"


def _keys(option: SpeechOption) -> tuple[str, str]:
    """(hearing seconds key, voice characters key) of the allowance counter."""
    if option is SpeechOption.GOOGLE:
        return STT_KEY, TTS_KEYS["chirp3-hd"]  # shared with JARVIS's own voice (one allowance)
    return f"calls_{option.value}_stt_seconds", f"calls_{option.value}_tts_chars"


class BillingSpend:
    """The engine's `Spend`: model calls through `Billing.record`; speech above the free
    allowance through `Billing.record_units` at `jarvis.calls.prices` (a price JARVIS does not
    know is counted at Google's, never ₹0). `allowed`: the owner's monthly limit for the call
    brain (fail closed)."""

    def __init__(self, billing: Billing, prices: PriceTable, brain: BrainSpec) -> None:
        self._billing = billing
        self._prices = prices
        self._brain = brain

    async def model(self, uid: str, brain_id: str, completion: Completion) -> float:
        cost = completion.cost_usd or cost_usd(completion.model, completion.usage)
        return await self._billing.record(uid, brain_id, cost, used=completion)

    async def _rate(self) -> float:
        try:
            return (await self._billing.fx.rate()).inr_per_usd
        except Exception:  # noqa: BLE001 - FxRates never raises; belt and braces
            return self._billing.fx.peek().inr_per_usd

    async def speech(self, uid: str, option: str, kind: Kind, units: float) -> float:
        if units <= 0:
            return 0.0
        rate = await self._rate()
        table = self._prices(rate)
        try:
            opt = SpeechOption(option)
        except ValueError:
            opt = SpeechOption.GOOGLE  # an unknown option is priced like Google: never ₹0
        price = table.get(opt) or table[SpeechOption.GOOGLE]
        if not price.can_bill:
            return 0.0
        hear_key, voice_key = _keys(opt)
        try:
            per_unit = price.inr_per_minute() / 60 if kind == "hear" else price.inr_per_chars(1)
            free = price.hear_free_seconds if kind == "hear" else price.voice_free_chars
        except PriceUnknown:
            google = table[SpeechOption.GOOGLE]
            per_unit = google.inr_per_minute() / 60 if kind == "hear" else google.inr_per_chars(1)
            free = 0
        charge = await self._billing.record_units(
            uid,
            key=hear_key if kind == "hear" else voice_key,
            units=units,
            free_units=free,
            usd_per_unit=per_unit / rate,
            label=METER_LABEL,
        )
        return charge.inr

    async def allowed(self, uid: str) -> bool:
        try:
            await self._billing.ensure_allowed(uid, self._brain)
        except BudgetError:
            return False
        return True


def deps_factory(base: EngineDeps) -> DepsFor:
    """The hub's `deps_for` from one set of shared parts: only the desk differs per owner."""

    def make(uid: str, desk: DeskProxy) -> EngineDeps:
        del uid
        return replace(base, desk=desk)

    return make


__all__ = [
    "BAD_CODE",
    "CODE_TTL_S",
    "AnsweringPolicy",
    "BillingSpend",
    "CallHub",
    "DeskConnection",
    "DeskDoorService",
    "DeskProxy",
    "DeskRecord",
    "DeskSocket",
    "DeskStore",
    "SeedCipher",
    "code_hash",
    "deps_factory",
    "normalise_code",
]
