# src/jarvis/sos/service.py
"""Emergency SOS (docs/plans/r7-mobile.md D19, D20): contacts, join links, the send, the limits,
the log and the owner's notice. SOS is NEVER a tool: only the owner's web sheet (cookie + CSRF
header, after the hold and the countdown) and the phone's signed door call `send`; the brain's
one SOS tool is the read `sos_status` (`jarvis.sos.tools`).

`send(uid, kind, location, via=...)`:
1. the book (sealed) and the message, written by code (`jarvis.sos.message`) from his own label;
2. the limits, in one transaction: a real SOS 3 an hour and 10 a day; tests and "I'm safe" have
   their OWN budget (3 an hour, 10 a day), so three tests never block a real SOS. A refusal sends
   nothing, says why, and still offers the SMS screen and 112. If the limits cannot be read, a
   real SOS still goes out (an emergency beats a counter) and a test is refused;
3. each joined contact ONCE (one per Telegram chat), concurrently, a message and then the map pin;
   each result is honest: `sent`, `sent_no_pin`, `failed` (Telegram did not confirm it) or
   `not_joined` (SMS only). Nothing is ever called "sent" that Telegram did not take;
4. one log entry and one audit line (time, kind, counts, location yes / no; never a place), and
   the owner's notice `sos_sent` on every channel (counts only, never a name; no off switch and
   no Telegram cap, D25). A notifier, a log or an audit that fails never fails the send.
The coordinates exist only in the request body that brought them and the bodies sent to Telegram
(the message's map link and the pin); never in a document, a log line, an audit line or an alert.

`HOURLY_CAP` and `OWN_TEST_BUDGET` are read at call time; only the eval's negative controls switch
them off.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from jarvis.alerts import AlertKind
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.sos import message as msg
from jarvis.sos.hook import is_sos_word
from jarvis.sos.models import Book, Contact, Kind, Location, clean_label, clean_phone
from jarvis.sos.store import JOIN_S, Budget, Entry, SosOff, SosStore, SosUnavailable
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)
HOURLY_CAP = True  # read at call time; only the eval's negative control switches it off
OWN_TEST_BUDGET = True  # tests and "I'm safe" never count in the real budget (eval control only)
HOUR_S = 3600
SEND_TIMEOUT_S = 12.0  # one contact's message or pin; a send that does not answer is not "sent"
AT_SLACK_S = 600  # the phone's press time is used for the message when it is this close to ours
HOLD_S, WEB_COUNTDOWN_S = 2, 5  # inside JARVIS: a 2-second hold, then a 5-second countdown
AGENT = "sos"
Outcome = Literal["sent", "partial", "failed", "none_joined", "refused", "unavailable"]
Status = Literal["sent", "sent_no_pin", "failed", "not_joined"]
NOT_A_SERVICE = (
    "This is not an emergency service: in danger, call 112. Set up Android's own Emergency SOS "
    "too (press the power button five times, Android 12 and newer)."
)
OFF_HERE = "Emergency SOS is switched off on this server, Sir."
NO_TELEGRAM = "Telegram isn't switched on, Sir, so nothing could be sent there."
SMS_OR_CALL = "Use the SMS screen or call 112."
WHAT = {"real": "SOS", "test": "Test SOS", "safe": '"I\'m safe"'}


class SosRefused(ValueError):
    """A change or a link that is not allowed, in plain words for the owner."""


@dataclass(frozen=True)
class Reach:
    id: str
    label: str
    status: Status


@dataclass(frozen=True)
class SendResult:
    kind: Kind
    outcome: Outcome
    text: str
    words: str
    reached: int = 0
    joined: int = 0
    total: int = 0
    results: tuple[Reach, ...] = ()
    reason: str | None = None
    numbers: tuple[str, ...] = ()
    told: bool = False

    def view(self) -> dict[str, Any]:
        return {
            "sent": self.reached > 0,
            "kind": self.kind,
            "outcome": self.outcome,
            "reason": self.reason,
            "reached": self.reached,
            "joined": self.joined,
            "total": self.total,
            "results": [{"id": r.id, "label": r.label, "status": r.status} for r in self.results],
            "words": self.words,
            "text": self.text,
            "sms": {"numbers": list(self.numbers), "text": self.text},
            "call": {
                "first": self.numbers[0] if self.numbers else None,
                "emergency": msg.EMERGENCY,
            },
            "told": self.told,
        }


@dataclass
class _Run:
    """One send's facts as they are learnt (never holds a place)."""

    kind: Kind
    via: str
    located: bool
    at: str
    text: str = ""
    numbers: tuple[str, ...] = ()
    total: int = 0
    results: list[Reach] = field(default_factory=list)


def _log_extra(kind: str, outcome: str, reached: int, joined: int, located: bool) -> dict[str, Any]:
    """What a log line may say about a send: kinds and counts, and location yes / no."""
    return {
        "kind": kind,
        "outcome": outcome,
        "reached": reached,
        "joined": joined,
        "location": located,
    }


def _in_hour(times: Sequence[float], now: float) -> int:
    return sum(1 for t in times if now - t < HOUR_S)


class SosService:
    def __init__(
        self,
        store: SosStore,
        s: Settings,
        *,
        telegram: Callable[[], TelegramClient | None],
        notifier: Callable[[], Notifier | None] | None,
        audit: AuditTrail | None,
        now: Callable[[], datetime],
        owners: Sequence[str] = ("owner",),
    ) -> None:
        self._store = store
        self._s = s
        self._telegram = telegram
        self._notifier = notifier
        self._audit = audit
        self._now = now
        self.owners = tuple(owners)

    @property
    def enabled(self) -> bool:
        return bool(self._s.sos_enabled)

    @property
    def store(self) -> SosStore:
        return self._store

    def _zone(self) -> Any:
        try:
            return ZoneInfo(self._s.user_timezone)
        except (KeyError, ValueError):
            return UTC

    def _utc(self) -> datetime:
        at = self._now()
        return at if at.tzinfo is not None else at.replace(tzinfo=UTC)

    def _hhmm(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, self._zone()).strftime("%H:%M")

    # ---- the set-up ---------------------------------------------------------------------------
    def _sealed(self) -> None:
        if not self._store.sealed:
            raise SosRefused(SosOff.WORDS)

    async def set_label(self, uid: str, label: object) -> Book:
        self._sealed()
        name = clean_label(label)
        if not name:
            raise SosRefused("Please give your name for the message, Sir: 1 to 40 letters.")
        return await self._store.update(
            uid, lambda b: b.model_copy(update={"label": name, "label_set": True})
        )

    async def add_contact(self, uid: str, label: object, phone: object) -> Contact:
        self._sealed()
        name = clean_label(label)
        if not name:
            raise SosRefused("Please give the contact a name, Sir: 1 to 40 letters.")
        number = None
        if isinstance(phone, str) and phone.strip():
            number = clean_phone(phone)
            if number is None:
                raise SosRefused(
                    "That phone number doesn't look right, Sir: digits only, with the country "
                    "code if you like (for example +91...)."
                )
        new = Contact(
            id="c_" + secrets.token_hex(5),
            label=name,
            phone=number,
            added_at=self._utc().isoformat(),
        )
        most = self._s.sos_max_contacts

        def add(book: Book) -> Book:
            if len(book.contacts) >= most:
                raise SosRefused(f"You can have at most {most} emergency contacts, Sir.")
            return book.model_copy(update={"contacts": (*book.contacts, new)})

        await self._store.update(uid, add)
        return new

    async def remove_contact(self, uid: str, cid: str) -> bool:
        self._sealed()
        gone: list[Contact] = []

        def drop(book: Book) -> Book:
            gone.extend(c for c in book.contacts if c.id == cid)
            return book.model_copy(
                update={"contacts": tuple(c for c in book.contacts if c.id != cid)}
            )

        await self._store.update(uid, drop)
        for c in gone:
            await self._store.drop_join(c.join_mac)
        return bool(gone)

    async def join_link(self, uid: str, cid: str) -> dict[str, Any]:
        """A one-time join link for one contact (24 hours); the word is shown once, never kept."""
        self._sealed()
        client = self._telegram()
        if client is None:
            raise SosRefused(
                "Telegram isn't switched on yet, Sir: set it up in Integrations → Telegram "
                "first. The SMS screen works without it."
            )
        try:
            bot = await client.get_me()
        except TelegramError:
            raise SosRefused("Telegram couldn't be reached just now, Sir. Try again.") from None
        word = "sos-" + secrets.token_urlsafe(24)  # 192 random bits
        mac = self._store.mac(word)
        until = self._utc().timestamp() + JOIN_S
        old: list[str | None] = []

        def mark(book: Book) -> Book:
            found = [c for c in book.contacts if c.id == cid]
            if not found:
                raise SosRefused("That contact is not on your list any more, Sir.")
            old.append(found[0].join_mac)
            change = {"join_mac": mac, "join_until": until}
            kept = tuple(c.model_copy(update=change) if c.id == cid else c for c in book.contacts)
            return book.model_copy(update={"contacts": kept})

        await self._store.update(uid, mark)
        await self._store.put_join(uid, cid, mac, until, old[0] if old else None)
        log.info("an SOS join link was made")
        expires = datetime.fromtimestamp(until, UTC).isoformat()
        return {"link": f"https://t.me/{bot}?start={word}", "until": expires}

    # ---- the Telegram hook's side (D20) ---------------------------------------------------------
    async def join(self, word: str, *, tg_user_id: int, chat_id: int) -> str | None:
        if not is_sos_word(word) or not self._store.sealed:
            return None
        now = self._utc().timestamp()
        if await self._store.wrong_blocked(now):
            log.warning("SOS join words held for the hour")
            return None
        joined_at = self._utc().isoformat()
        mac = self._store.mac(word)

        def seat(book: Book, cid: str) -> Book | None:
            hit = [c for c in book.contacts if c.id == cid and c.join_mac == mac]
            if not hit:
                return None
            change = {
                "tg_user": tg_user_id,
                "tg_chat": chat_id,
                "joined_at": joined_at,
                "join_mac": None,
                "join_until": None,
            }
            kept = tuple(c.model_copy(update=change) if c.id == cid else c for c in book.contacts)
            return book.model_copy(update={"contacts": kept})

        got = await self._store.join(mac, now, seat)
        if got is None:
            await self._store.count_wrong(now)
            log.info("an SOS join word did not join")
            return None
        uid, book = got
        await self._note_audit(uid, "sos_contact_joined", "joined", {"contact": "joined"})
        return msg.joined_words(book.label)

    async def is_contact(self, tg_user_id: int) -> bool:
        for uid in self.owners:
            book = await self._store.book(uid)
            if any(c.tg_user == tg_user_id for c in book.contacts):
                return True
        return False

    async def stop(self, *, tg_user_id: int, chat_id: int) -> str | None:
        del chat_id
        for uid in self.owners:
            book = await self._store.book(uid)
            if any(c.tg_user == tg_user_id for c in book.contacts):
                return await self._leave(uid, tg_user_id)
        return None

    async def _leave(self, uid: str, tg_user_id: int) -> str:
        gone: list[Contact] = []

        def drop(b: Book) -> Book:
            gone.extend(c for c in b.contacts if c.tg_user == tg_user_id)
            kept = tuple(c for c in b.contacts if c.tg_user != tg_user_id)
            return b.model_copy(update={"contacts": kept})

        new = await self._store.update(uid, drop)
        for c in gone:
            await self._store.drop_join(c.join_mac)
        await self._note_audit(uid, "sos_contact_left", "left", {"contact": "left"})
        await self._tell(uid, "sos_contact_left", msg.LEFT_NOTICE)
        return msg.left_words(new.label)

    # ---- the send (D19) -------------------------------------------------------------------------
    def _fixed_at(self, at: int | None, loc: Location | None) -> str:
        base = self._utc().timestamp()
        if at is not None and abs(at - base) <= AT_SLACK_S:
            base = float(at)
        return self._hhmm(base - (loc.age_s if loc is not None else 0))

    def _decide(self, kind: Kind, now: float) -> Callable[[Budget], str | None]:
        s = self._s

        def decide(b: Budget) -> str | None:
            if kind == "real":
                pool = b.real if OWN_TEST_BUDGET else (*b.real, *b.test)
                hour, day = s.sos_per_hour, s.sos_per_day
            else:
                pool, hour, day = b.test, s.sos_test_per_hour, s.sos_test_per_day
            if HOURLY_CAP and _in_hour(pool, now) >= hour:
                return "hour"
            if len(pool) >= day:
                return "day"
            return None

        return decide

    def _limit_words(self, kind: Kind, why: str) -> str:
        s = self._s
        if kind == "real":
            n = s.sos_per_hour if why == "hour" else s.sos_per_day
        else:
            n = s.sos_test_per_hour if why == "hour" else s.sos_test_per_day
        if why == "unreadable":
            return "the limit couldn't be checked just now."
        span = "an hour" if why == "hour" else "a day"
        tests = "" if kind == "real" else " tests"
        return f"the limit of {n}{tests} {span} was reached."

    async def _take(self, uid: str, kind: Kind, now: float) -> str | None:
        pool: Literal["real", "test"] = "real" if kind == "real" else "test"
        try:
            return await self._store.take(uid, pool, now, self._decide(kind, now))
        except (SosUnavailable, SosOff) as exc:
            if kind == "real":
                log.error(
                    "SOS limits unreadable: a real SOS goes out anyway",
                    extra={"error": type(exc).__name__},
                )
                return None
            return "unreadable"

    async def send(
        self,
        uid: str,
        kind: Kind,
        location: Location | None,
        *,
        via: Literal["web", "phone"],
        at: int | None = None,
    ) -> SendResult:
        loc = location if kind != "safe" else None
        now = self._utc().timestamp()
        run = _Run(kind=kind, via=via, located=loc is not None, at=self._hhmm(now))
        try:
            book = await self._store.book(uid)
        except (SosOff, SosUnavailable) as exc:
            run.text = msg.message_for(kind, Book().label, loc, self._fixed_at(at, loc))
            return await self._finish(uid, run, "unavailable", reason="unreadable", why=str(exc))
        run.text = msg.message_for(kind, book.label, loc, self._fixed_at(at, loc))
        run.numbers = tuple(c.phone for c in book.contacts if c.phone)
        run.total = len(book.contacts)
        if not self.enabled:
            return await self._finish(uid, run, "unavailable", reason="off", why=OFF_HERE)
        why = await self._take(uid, kind, now)
        if why is not None:
            return await self._finish(uid, run, "refused", reason=why)
        return await self._deliver(uid, run, book, loc)

    async def _deliver(self, uid: str, run: _Run, book: Book, loc: Location | None) -> SendResult:
        joined: list[Contact] = []
        chats: set[int] = set()
        for c in book.contacts:
            if c.joined and c.tg_chat is not None and c.tg_chat not in chats:
                chats.add(c.tg_chat)
                joined.append(c)
        run.results = [Reach(c.id, c.label, "not_joined") for c in book.contacts if not c.joined]
        if not joined:
            return await self._finish(uid, run, "none_joined")
        client = self._telegram()
        if client is None:
            run.results = [Reach(c.id, c.label, "failed") for c in joined] + run.results
            return await self._finish(uid, run, "failed", why=NO_TELEGRAM)
        sent = await asyncio.gather(*(self._one(client, c, run.text, loc) for c in joined))
        run.results = [*sent, *run.results]
        reached = sum(1 for r in sent if r.status in ("sent", "sent_no_pin"))
        outcome: Outcome = "sent" if reached == len(joined) else "partial" if reached else "failed"
        return await self._finish(uid, run, outcome)

    async def _one(
        self, client: TelegramClient, c: Contact, text: str, loc: Location | None
    ) -> Reach:
        assert c.tg_chat is not None
        try:
            await asyncio.wait_for(client.send_message(c.tg_chat, text), SEND_TIMEOUT_S)
        except (TelegramError, TimeoutError) as exc:
            log.warning("an SOS message was not taken", extra={"error": type(exc).__name__})
            return Reach(c.id, c.label, "failed")
        except Exception as exc:  # noqa: BLE001 - one contact never stops the others
            log.error("an SOS message failed", extra={"error": type(exc).__name__})
            return Reach(c.id, c.label, "failed")
        if loc is None:
            return Reach(c.id, c.label, "sent")
        try:
            await asyncio.wait_for(
                client.send_location(
                    c.tg_chat, loc.lat_e6 / 1e6, loc.lon_e6 / 1e6, accuracy_m=loc.accuracy_m
                ),
                SEND_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 - the message went; the pin is reported apart
            log.warning("an SOS map pin was not taken", extra={"error": type(exc).__name__})
            return Reach(c.id, c.label, "sent_no_pin")
        return Reach(c.id, c.label, "sent")

    def _words(self, run: _Run, outcome: Outcome, reached: int, joined: int, why: str) -> str:
        what = WHAT[run.kind]
        missed = [r.label for r in run.results if r.status == "failed"]
        no_pin = [r.label for r in run.results if r.status == "sent_no_pin"]
        if outcome == "refused":
            return f"Not sent on Telegram: {why} {SMS_OR_CALL}"
        if outcome == "unavailable":
            return f"{why} {SMS_OR_CALL}"
        if outcome == "none_joined":
            return (
                "No emergency contact has joined on Telegram, so nothing was sent there. "
                + SMS_OR_CALL
            )
        if outcome == "failed":
            lead = why or "Telegram took the message for no contact."
            return f"NOT sent: {lead} Use the SMS screen or call 112 now."
        pin = f" The map pin failed for: {', '.join(no_pin)}." if no_pin and run.located else ""
        if outcome == "partial":
            return (
                f"{what} at {run.at} reached {reached} of {joined} contacts on Telegram. "
                f"Not reached: {', '.join(missed)}. {SMS_OR_CALL}{pin}"
            )
        return (
            f"{what} sent at {run.at} to {reached} of {joined} emergency contacts on Telegram.{pin}"
        )

    async def _finish(
        self, uid: str, run: _Run, outcome: Outcome, *, reason: str | None = None, why: str = ""
    ) -> SendResult:
        reached = sum(1 for r in run.results if r.status in ("sent", "sent_no_pin"))
        joined = sum(1 for r in run.results if r.status != "not_joined")
        if outcome == "refused" and reason is not None:
            why = self._limit_words(run.kind, reason)
        words = self._words(run, outcome, reached, joined, why)
        log.info("SOS finished", extra=_log_extra(run.kind, outcome, reached, joined, run.located))
        entry = Entry(
            at=self._utc().isoformat(),
            kind=run.kind,
            outcome=outcome,
            reached=reached,
            joined=joined,
            location=run.located,
            via=run.via,
        )
        try:
            await self._store.log(uid, entry)
        except (SosUnavailable, ValueError) as exc:
            log.error("an SOS was not logged", extra={"error": type(exc).__name__})
        detail = f"reached {reached} of {joined}; location {'yes' if run.located else 'no'}"
        args = {"kind": run.kind, "via": run.via, "location": run.located}
        await self._note_audit(uid, f"sos_{run.kind}", outcome, args, detail)
        notice = msg.notice_for(run.kind, outcome, reached, joined, run.at, why)
        told = await self._tell(uid, "sos_sent", notice)
        return SendResult(
            kind=run.kind,
            outcome=outcome,
            text=run.text,
            words=words,
            reached=reached,
            joined=joined,
            total=run.total,
            results=tuple(run.results),
            reason=reason,
            numbers=run.numbers,
            told=told,
        )

    # ---- side channels: never fail the caller ---------------------------------------------------
    async def _tell(self, uid: str, kind: AlertKind, words: str) -> bool:
        notifier = self._notifier() if self._notifier is not None else None
        if notifier is None:
            log.warning("no notifier: the owner was not told", extra={"kind": kind})
            return False
        try:
            await notifier.notify(uid, Signal(source="system", kind=kind), words)
        except Exception as exc:  # noqa: BLE001 - the send already happened; say it was not told
            log.error(
                "the owner's SOS notice failed", extra={"kind": kind, "error": type(exc).__name__}
            )
            return False
        return True

    async def _note_audit(
        self, uid: str, tool: str, outcome: str, args: dict[str, Any], detail: str = ""
    ) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent=AGENT,
                tool=tool,
                risk=ActionRisk.IRREVERSIBLE,
                outcome=outcome,
                args={**args, "owner": uid},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - never stops an SOS; logged loudly
            log.error("an SOS audit line was not written", extra={"error": type(exc).__name__})

    # ---- what the card, the sheet, the phone and the brain read --------------------------------
    async def view(self, uid: str) -> dict[str, Any]:
        book = await self._store.book(uid)
        now = self._utc().timestamp()
        budget = await self._store.budget(uid, now)
        last = await self._store.last(uid)
        s = self._s
        return {
            "enabled": self.enabled,
            "sealed": self._store.sealed,
            "telegram": self._telegram() is not None,
            "label": book.label,
            "label_set": book.label_set,
            "max": s.sos_max_contacts,
            "countdown_s": s.sos_countdown_s,
            "hold_s": HOLD_S,
            "web_countdown_s": WEB_COUNTDOWN_S,
            "contacts": [_contact_view(c, now) for c in book.contacts],
            "last": _last_view(last),
            "left": {
                "real_hour": max(0, s.sos_per_hour - _in_hour(budget.real, now)),
                "real_day": max(0, s.sos_per_day - len(budget.real)),
                "test_hour": max(0, s.sos_test_per_hour - _in_hour(budget.test, now)),
                "test_day": max(0, s.sos_test_per_day - len(budget.test)),
            },
            "note": NOT_A_SERVICE,
        }

    async def sheet(self, uid: str) -> dict[str, Any]:
        """What the SOS sheet needs before a press (works while the app is locked, D21)."""
        try:
            book = await self._store.book(uid)
        except (SosOff, SosUnavailable):
            book = Book()
        numbers = [c.phone for c in book.contacts if c.phone]
        return {
            "enabled": self.enabled,
            "label": book.label,
            "numbers": numbers,
            "first": numbers[0] if numbers else None,
            "emergency": msg.EMERGENCY,
            "text": msg.message_for("real", book.label, None, ""),
            "hold_s": HOLD_S,
            "countdown_s": WEB_COUNTDOWN_S,
            "note": NOT_A_SERVICE,
        }

    async def sms_view(self, uid: str) -> dict[str, Any]:
        """For the phone's `hello` reply (Part C): his label and each contact's label and number,
        so the phone's SMS screen works with no internet."""
        book = await self._store.book(uid)
        people = [{"label": c.label, "phone": c.phone} for c in book.contacts if c.phone]
        return {"label": book.label, "contacts": people}

    async def status_words(self, uid: str) -> str:
        """`sos_status`: counts and times only, never a name or a number (it is answerable on
        Telegram), and always how he sends one himself."""
        never = (
            "I can never send an SOS myself, Sir: hold the SOS button in JARVIS or on your phone, "
            "or call 112. " + NOT_A_SERVICE
        )
        if not self.enabled:
            return f"{OFF_HERE} {never}"
        if not self._store.sealed:
            return f"{SosOff.WORDS} {never}"
        try:
            book = await self._store.book(uid)
            last = await self._store.last(uid)
        except SosUnavailable:
            return f"{SosUnavailable.WORDS} {never}"
        n = len(book.contacts)
        joined = sum(1 for c in book.contacts if c.joined)
        if n == 0:
            head = (
                "No emergency contacts are set up yet, Sir: add them in Integrations → "
                "Emergency SOS."
            )
        else:
            people = "1 emergency contact" if n == 1 else f"{n} emergency contacts"
            head = f"Emergency SOS has {people}; {joined} joined on Telegram."
        return f"{head} {_last_words(last, self._zone())} {never}"


def _contact_view(c: Contact, now: float) -> dict[str, Any]:
    return {
        "id": c.id,
        "label": c.label,
        "phone_hint": ("••" + c.phone[-2:]) if c.phone else "",
        "has_phone": c.phone is not None,
        "joined": c.joined,
        "pending": (not c.joined) and c.join_until is not None and c.join_until > now,
    }


def _last_view(last: dict[str, Any] | None) -> dict[str, Any] | None:
    if not last:
        return None
    keys = ("at", "kind", "outcome", "reached", "joined", "location")
    return {k: last.get(k) for k in keys}


def _last_words(last: dict[str, Any] | None, zone: Any) -> str:
    if not last or not isinstance(last.get("at"), str):
        return "No SOS has been sent."
    try:
        when = datetime.fromisoformat(last["at"]).astimezone(zone)
    except ValueError:
        return "No SOS has been sent."
    what = {"real": "an SOS", "test": "a test", "safe": 'an "I\'m safe"'}.get(
        str(last.get("kind")), "an SOS"
    )
    reached = last.get("reached") if isinstance(last.get("reached"), int) else 0
    people = "1 person" if reached == 1 else f"{reached} people"
    stamp = f"{when.strftime('%H:%M')} on {when.day} {when.strftime('%b')}"
    if last.get("outcome") == "refused":
        return f"The last press, {what} at {stamp}, was over the limit and was not sent."
    return f"The last was {what} at {stamp}, reaching {people}."


__all__ = [
    "HOLD_S",
    "HOURLY_CAP",
    "NOT_A_SERVICE",
    "OWN_TEST_BUDGET",
    "WEB_COUNTDOWN_S",
    "Reach",
    "SendResult",
    "SosRefused",
    "SosService",
]
