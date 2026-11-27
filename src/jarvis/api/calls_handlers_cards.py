# src/jarvis/api/calls_handlers_cards.py
"""R18 A1: what the Calls panel's REST routes call (`jarvis.api.calls_routes`, slot
`app.state.calls_api`; docs/plans/r18-calls/I0-SEAMS.md "Routes"). Thin: owner-only (the route
checked him and passes his id), each body read and checked here, the work done by `jarvis.calls`.

- Cards: `create_card` (structured fields, a template {template, fields}, or free text {text}
  read by the fast tier; {replaces: card_id} edits a waiting card: the new one is written, the
  old one cancelled), `estimate` (the same, nothing stored, with the ₹ parts), `get_card`,
  `approve`, `cancel`. A card that can't be placed now says why (`blocked`).
- Approving runs the gateway's `calls_place` tool for the stored card (`approvals.approving`), as a
  chat card would: the first press proposes the R3 card; when his passkey is in force the answer is
  {status: "needs_passkey", approval_id} and the console asks for a passkey check made for that
  approval (POST /v1/passkeys/challenge, purpose "approve") and presses again with {approval_id,
  passkey}; otherwise the same press approves it. A refused passkey leaves the card waiting.
- Records: list (numbers masked), one call with its transcript and summary (decrypted for him),
  Delete, Keep, the audio, the booking's Undo.
- Settings: GET / PUT a subset of `CallSettings`. Anything that lets calls spend more (a higher
  cap, more minutes, paid Sarvam, the balanced tier) needs {confirm_raise: true}, like the
  monthly limit (`billing.budget`).
- `languages`: the language table and what is offered; `status` and `run_language_check` are the
  hub's (A2) and the language check's (B), passed in by I1 (501 not_built until then).

Refusals are `CallsRefused(status, code, words)`; words never carry a full number, a transcript
or a key.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from jarvis.calls.approvals import SCOPE_SESSION, CallsService, PasskeyPolicy, approving, audit_step
from jarvis.calls.booking import BookingCalendar
from jarvis.calls.cards import (
    CardBuilder,
    CardParser,
    CardRefused,
    Estimate,
    NumberRefused,
    card_args,
    card_text,
    masked,
    offered,
    provisional,
    read_draft,
)
from jarvis.calls.limits import LimitRefused
from jarvis.calls.models import (
    CARD_ID_RE,
    LANGUAGE_NAMES,
    CallCard,
    CallRecord,
    CallSettings,
    CardStatus,
)
from jarvis.calls.ports import CallsRefused, CallStore
from jarvis.calls.records import RecordKeeper, RecordRefused
from jarvis.calls.settings import CallSettingsRejected
from jarvis.calls.templates import TemplateRefused, catalogue, draft_from
from jarvis.calls.tools import PLACE, PlaceArgs
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.permissions.errors import PasskeyDataUnreadable
from jarvis.permissions.models import PasskeyProof
from jarvis.tools.audit import AuditTrail
from jarvis.tools.context import presenting_proof
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

Delegate = Callable[[str], Awaitable[dict[str, Any]]]
BodyDelegate = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
APPROVAL_ID_MAX = 128
# Settings that let calls spend more: raising one needs {confirm_raise: true}
RAISES = ("month_cap_inr", "call_cap_inr", "call_max_minutes")
TURNS_ON = ("sarvam_on", "allow_balanced")

NOT_BUILT = "Calls are not ready yet: this part of R18 is still being built."
MSG_NO_CARD = "There is no such call card."
MSG_NO_PARSER = "JARVIS can't read free text into a card here. Fill in the card's fields."
MSG_PASSKEY = "The passkey check didn't go through, so the call wasn't placed. Try again."
MSG_GONE = "That approval is spent or expired. Press Call again."
MSG_NOT_DONE = "The call wasn't approved: {words}"
MSG_BAD_BODY = "Check the request: {words}"
MSG_RAISE = (
    "This lets calls spend more (a higher cap, more minutes, paid speech or the balanced tier). "
    "Confirm to change it (confirm_raise)."
)
MSG_UNREADABLE = "JARVIS can't read its call data just now."

_STATUS = {
    "invalid": 422,
    "emergency": 422,
    "premium": 422,
    "international": 422,
    "short_code": 422,
    "template": 422,
    "unparsed": 422,
    "language": 409,
    "no_number": 422,
    "no_contact": 422,
    "many_contacts": 409,
    "contacts_down": 503,
    "no_name": 409,
    "needs_passkey": 409,
    "changed": 409,
    "not_waiting": 409,
    "not_found": 404,
    "unreadable": 503,
    "gone": 404,
    "not_recorded": 404,
    "objected": 409,
    "too_big": 413,
    "type": 422,
}


def refused(exc: Exception) -> CallsRefused:
    """A calls refusal as the route's answer (status, stable code, plain words)."""
    if isinstance(exc, CallsRefused):
        return exc
    if isinstance(exc, LimitRefused):
        code = exc.code
        return CallsRefused(503 if code == "unreadable" else 409, code, exc.words)
    if isinstance(exc, NumberRefused):
        return CallsRefused(422, exc.code, str(exc))
    if isinstance(exc, CardRefused | RecordRefused | TemplateRefused):
        return CallsRefused(_STATUS.get(exc.code, 409), exc.code, exc.words)
    if isinstance(exc, CallSettingsRejected):
        return CallsRefused(422, "invalid", str(exc))
    log.error("calls handler failed", extra={"error": type(exc).__name__})
    return CallsRefused(503, "unreadable", MSG_UNREADABLE)


_KNOWN = (CallsRefused, LimitRefused, NumberRefused, CardRefused, RecordRefused, TemplateRefused)


# ---- views ------------------------------------------------------------------------------------
def _estimate_view(e: Estimate) -> dict[str, Any]:
    return {
        "total_inr": e.total_inr,
        "speech_inr": e.speech_inr,
        "brain_inr": e.brain_inr,
        "summary_inr": e.summary_inr,
        "speech_free": e.speech_free,
        "minutes": e.minutes,
    }


def card_view(
    card: CallCard, blocked: CallsRefused | None = None, estimate: Estimate | None = None
) -> dict[str, Any]:
    """The whole card for the Calls panel (the full number: his own panel shows it)."""
    body = card.model_dump(mode="json")
    body |= {
        "number": card.number_e164,
        "number_masked": masked(card.number_e164),
        "language_names": [LANGUAGE_NAMES.get(c, c) for c in card.languages],
        "card_text": card_text(card),
        "needs_passkey": card.new_number,
        "blocked": None if blocked is None else {"code": blocked.code, "words": blocked.words},
    }
    if estimate is not None:
        body["estimate"] = _estimate_view(estimate)
    return body


def record_view(rec: CallRecord) -> dict[str, Any]:
    """A call in the list: the number masked, which parts are kept."""
    return {
        "id": rec.id,
        "card_id": rec.card_id,
        "direction": rec.direction.value,
        "number_masked": masked(rec.number_e164),
        "contact_name": rec.contact_name,
        "state": rec.state.value,
        "end_reason": rec.end_reason.value if rec.end_reason else None,
        "languages_used": list(rec.languages_used),
        "started_at": rec.started_at.isoformat(),
        "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        "seconds": rec.seconds,
        "cost_inr": rec.cost_inr,
        "cost_parts": dict(rec.cost_parts),
        "recorded": rec.recorded,
        "objected": rec.objected,
        "has_audio": bool(rec.audio_ref),
        "has_transcript": bool(rec.transcript_ref),
        "has_summary": bool(rec.summary_ref),
        "booking_added": bool(rec.booking_event_ref),
        "keep": rec.keep,
        "delete_after": rec.delete_after.isoformat(),
    }


def settings_view(s: CallSettings) -> dict[str, Any]:
    return s.model_dump(mode="json") | {"templates": catalogue()}


# ---- the handlers -----------------------------------------------------------------------------
class CardsApi:
    """`ports.CallsApi`: the Calls panel's REST work (wired by I1 on `app.state.calls_api`)."""

    def __init__(
        self,
        *,
        store: CallStore,
        builder: CardBuilder,
        service: CallsService,
        gateway: Gateway,
        keeper: RecordKeeper,
        booking: BookingCalendar,
        parser: CardParser | None = None,
        passkeys: PasskeyPolicy | None = None,
        audit: AuditTrail | None = None,
        status: Delegate | None = None,
        language_check: BodyDelegate | None = None,
        language_score: BodyDelegate | None = None,
        check_progress: Delegate | None = None,
    ) -> None:
        self.store, self.builder, self.service, self.gateway = store, builder, service, gateway
        self.keeper, self.booking, self.parser = keeper, booking, parser
        self.passkeys, self.audit = passkeys, audit
        self._status, self._language_check = status, language_check
        self._language_score, self._check_progress = language_score, check_progress

    # ---- cards ------------------------------------------------------------------------------
    async def _draft(self, uid: str, body: Mapping[str, Any]) -> PlaceArgs:
        fields = {k: v for k, v in body.items() if k != "replaces"}
        if "text" in fields:
            text = fields.get("text")
            if not isinstance(text, str) or len(fields) != 1:
                raise CallsRefused(422, "invalid", MSG_BAD_BODY.format(words="text alone"))
            if self.parser is None:
                raise CallsRefused(501, "not_built", MSG_NO_PARSER)
            return await self.parser.parse(uid, text)
        if "fields" in fields:
            name, inner = fields.get("template"), fields.get("fields")
            if not isinstance(name, str) or not isinstance(inner, dict) or len(fields) != 2:
                raise CallsRefused(422, "invalid", MSG_BAD_BODY.format(words="template, fields"))
            return draft_from(name, inner)
        return read_draft(fields)

    async def _blocked(self, uid: str, card: CallCard) -> CallsRefused | None:
        try:
            await self.service.gates(uid, card)
        except (LimitRefused, CardRefused) as exc:
            return refused(exc)
        return None

    async def create_card(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            old = await self._waiting(uid, body["replaces"]) if "replaces" in body else None
            card, estimate = await self.builder.estimate_for(uid, await self._draft(uid, body))
            await self.store.put_card(uid, card)
            if old is not None:
                await self.service.cancel(uid, old.id)
            await audit_step(
                self.audit,
                PLACE,
                "card_written",
                {"card": card.id},
                f"card {card.id} to {masked(card.number_e164)}"
                + (f"; replaces {old.id}" if old else ""),
                ActionRisk.REVERSIBLE,
            )
            return card_view(card, await self._blocked(uid, card), estimate)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def _waiting(self, uid: str, card_id: object) -> CallCard:
        card = await self._card(uid, card_id)
        if card.status is not CardStatus.DRAFT:
            raise CardRefused("not_waiting", "Only a card waiting for approval can be changed.")
        return card

    async def _card(self, uid: str, card_id: object) -> CallCard:
        if not isinstance(card_id, str) or not CARD_ID_RE.fullmatch(card_id):
            raise CallsRefused(404, "not_found", MSG_NO_CARD)
        card = await self.store.get_card(uid, card_id)
        if card is None:
            raise CallsRefused(404, "not_found", MSG_NO_CARD)
        return card

    async def estimate(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            card, estimate = await self.builder.estimate_for(uid, await self._draft(uid, body))
            return card_view(card, await self._blocked(uid, card), estimate)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def get_card(self, uid: str, card_id: str) -> dict[str, Any]:
        try:
            card = await self._card(uid, card_id)
            blocked = await self._blocked(uid, card) if card.status is CardStatus.DRAFT else None
            return card_view(card, blocked)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def approve(self, uid: str, card_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """His Call press (twice when his passkey is in force: propose, then approve)."""
        try:
            card = await self._waiting(uid, card_id)
            approval_id, proof = self._approval_body(body)
            await self._still_good(uid, card)
            call = ToolCall(id=f"cp-{uuid.uuid4().hex[:8]}", name=PLACE, arguments=card_args(card))
            scope = f"{uid}:{SCOPE_SESSION}"
            with approving(card.id), context_trust(untrusted=False):
                if approval_id is None:
                    asked = await self.gateway.execute(call, scope=scope)
                    if (
                        asked.outcome is not GatewayOutcome.AWAITING_CONFIRMATION
                        or not asked.pending
                    ):
                        raise CallsRefused(409, "not_done", _words(asked))
                    approval_id = asked.pending.id
                    if await self._passkey_in_force(uid):
                        return {
                            "status": "needs_passkey",
                            "approval_id": approval_id,
                            "card_text": asked.pending.summary,
                        }
                done = await self._run(call, approval_id, scope, proof)
            return self._approved(card, done)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def _still_good(self, uid: str, card: CallCard) -> None:
        """The card as stored still builds to the same content and may be placed now (the
        gateway's look-up checks it again; this gives the refusal its own code and words)."""
        fresh = await self.builder.build(uid, read_draft(card_args(card)), card_id=card.id)
        if fresh.digest() != card.digest():
            raise CardRefused("changed", "The call card changed. Check it and press Call again.")
        await self.service.gates(uid, fresh)

    @staticmethod
    def _approval_body(body: Mapping[str, Any]) -> tuple[str | None, PasskeyProof | None]:
        unknown = sorted(k for k in body if k not in ("approval_id", "passkey"))
        if unknown:
            raise CallsRefused(422, "invalid", MSG_BAD_BODY.format(words=", ".join(unknown)[:80]))
        approval_id = body.get("approval_id")
        if approval_id is not None and (
            not isinstance(approval_id, str) or not 8 <= len(approval_id) <= APPROVAL_ID_MAX
        ):
            raise CallsRefused(422, "invalid", MSG_BAD_BODY.format(words="approval_id"))
        raw = body.get("passkey")
        if raw is None:
            return approval_id, None
        if approval_id is None:
            raise CallsRefused(
                422, "invalid", MSG_BAD_BODY.format(words="a passkey needs its approval_id")
            )
        try:
            return approval_id, PasskeyProof.model_validate(raw)
        except ValidationError:
            raise CallsRefused(422, "invalid", MSG_BAD_BODY.format(words="passkey")) from None

    async def _passkey_in_force(self, uid: str) -> bool:
        if self.passkeys is None:
            return False
        try:
            return await self.passkeys.passkey_required(uid)
        except Exception as exc:  # noqa: BLE001 - can't tell: ask for one (the guard decides)
            log.warning("passkey policy unreadable", extra={"error": type(exc).__name__})
            return True

    async def _run(
        self, call: ToolCall, approval_id: str, scope: str, proof: PasskeyProof | None
    ) -> GatewayResult:
        try:
            with presenting_proof(proof):
                return await self.gateway.execute(call, confirmation_id=approval_id, scope=scope)
        except (PermissionError, PasskeyDataUnreadable) as exc:  # the approval guard refused
            log.info(
                "call approval refused by the passkey guard", extra={"error": type(exc).__name__}
            )
            raise CallsRefused(403, "passkey", MSG_PASSKEY) from None

    def _approved(self, card: CallCard, done: GatewayResult) -> dict[str, Any]:
        if done.outcome is GatewayOutcome.EXECUTED and isinstance(done.result, dict):
            return {"status": done.result.get("status", "approved"), "card_id": card.id} | {
                "call_id": done.result.get("call_id")
            }
        if done.outcome is GatewayOutcome.CONFIRMATION_INVALID:
            raise CallsRefused(409, "gone", MSG_GONE)
        if done.outcome is GatewayOutcome.AWAITING_CONFIRMATION:  # changed while looked at
            raise CallsRefused(
                409, "changed", "The call card changed. Check it and press Call again."
            )
        raise CallsRefused(409, "not_done", _words(done))

    async def cancel(self, uid: str, card_id: str) -> dict[str, Any]:
        try:
            card = await self._card(uid, card_id)
            cancelled = await self.service.cancel(uid, card.id)
            await self._withdraw(uid, card)
            return card_view(cancelled)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def _withdraw(self, uid: str, card: CallCard) -> None:
        """A waiting `calls_place` card for it is withdrawn too. Never raises."""
        try:
            args, scope = card_args(card), f"{uid}:{SCOPE_SESSION}"
            for p in await self.gateway.pending():
                if p.tool == PLACE and p.scope == scope and p.arguments == args:
                    await self.gateway.gate.cancel(p.id)
        except Exception as exc:  # noqa: BLE001 - tidying only: it expires in 10 minutes
            log.warning("waiting call approval not withdrawn", extra={"error": type(exc).__name__})

    # ---- records ----------------------------------------------------------------------------
    async def list_records(self, uid: str, limit: int) -> dict[str, Any]:
        try:
            records = await self.store.list_records(uid, limit=limit)
        except Exception as exc:  # noqa: BLE001
            raise refused(exc) from None
        return {"records": [record_view(r) for r in records]}

    async def get_record(self, uid: str, call_id: str) -> dict[str, Any]:
        try:
            rec = await self.keeper.record(uid, call_id)
            transcript = await self.keeper.transcript(uid, call_id)
            summary = await self.keeper.summary(uid, call_id)
        except _KNOWN as exc:
            raise refused(exc) from None
        return record_view(rec) | {
            "number": rec.number_e164,
            "transcript": transcript.model_dump(mode="json") if transcript else None,
            "summary": summary.model_dump(mode="json") if summary else None,
        }

    async def delete_record(self, uid: str, call_id: str) -> dict[str, Any]:
        try:
            gone = await self.keeper.delete(uid, call_id, why="owner")
        except _KNOWN as exc:
            raise refused(exc) from None
        if not gone:
            raise CallsRefused(404, "not_found", "There is no such call record.")
        return {"deleted": True, "id": call_id}

    async def keep_record(self, uid: str, call_id: str, keep: bool) -> dict[str, Any]:
        try:
            return record_view(await self.keeper.keep(uid, call_id, keep))
        except _KNOWN as exc:
            raise refused(exc) from None

    async def record_audio(self, uid: str, call_id: str) -> tuple[bytes, str]:
        try:
            return await self.keeper.audio(uid, call_id)
        except _KNOWN as exc:
            raise refused(exc) from None

    async def undo_booking(self, uid: str, call_id: str) -> dict[str, Any]:
        try:
            await self.keeper.record(uid, call_id)
            out = await self.booking.undo(uid, call_id)
        except _KNOWN as exc:
            raise refused(exc) from None
        return {"status": out.status, "words": out.words, "approval_id": out.approval_id}

    # ---- settings and languages ---------------------------------------------------------------
    async def get_settings(self, uid: str) -> dict[str, Any]:
        try:
            return settings_view(await self.store.settings(uid))
        except Exception as exc:  # noqa: BLE001
            raise refused(exc) from None

    async def put_settings(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        confirm = body.get("confirm_raise") is True
        changes = {k: v for k, v in body.items() if k != "confirm_raise"}
        try:
            current = await self.store.settings(uid)
            if not confirm and _raises(current, changes):
                raise CallsRefused(422, "confirm_raise", MSG_RAISE)
            saved = await self.store.save_settings(uid, changes)
        except Exception as exc:  # noqa: BLE001 - refusals keep their words; the rest is 503
            raise refused(exc) from None
        await audit_step(
            self.audit,
            "calls_settings",
            "changed",
            {"fields": sorted(changes)},
            ", ".join(sorted(changes))[:200],
            ActionRisk.REVERSIBLE,
        )
        return settings_view(saved)

    async def languages(self, uid: str) -> dict[str, Any]:
        try:
            settings = await self.store.settings(uid)
            results = await self.store.language_results()
        except Exception as exc:  # noqa: BLE001
            raise refused(exc) from None
        offer = offered(results, settings)
        rows = [
            {
                "lang": code,
                "name": name,
                "offered": code in offer,
                "option": offer[code].option.value if code in offer else None,
                "inr_per_minute": offer[code].inr_per_minute if code in offer else None,
                "checked": code in offer and not provisional(offer[code]),
                "results": [r.model_dump(mode="json") for r in results if r.lang == code],
            }
            for code, name in LANGUAGE_NAMES.items()
        ]
        out: dict[str, Any] = {"languages": rows}
        if self._check_progress is not None:  # I1: a check running in the background
            out["check"] = await self._check_progress(uid)
        return out

    async def run_language_check(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._language_check is None:
            raise CallsRefused(501, "not_built", NOT_BUILT)
        return await self._language_check(uid, body)

    async def score_language(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._language_score is None:
            raise CallsRefused(501, "not_built", NOT_BUILT)
        return await self._language_score(uid, body)

    async def status(self, uid: str) -> dict[str, Any]:
        if self._status is None:
            raise CallsRefused(501, "not_built", NOT_BUILT)
        return await self._status(uid)


_INNER = re.compile(r"\((?:CardRefused|LimitRefused|NumberRefused): (.+)\)$")


def _words(r: GatewayResult) -> str:
    """A gateway refusal in plain words (the gateway already redacted them)."""
    text = r.error or r.outcome.value
    inner = _INNER.search(text)
    return MSG_NOT_DONE.format(words=(inner.group(1) if inner else text)[:200])


def _raises(current: CallSettings, changes: Mapping[str, Any]) -> bool:
    """Would this change let calls spend more? (Unreadable values count as a raise.)"""
    for key in RAISES:
        if key in changes:
            try:
                if int(changes[key]) > int(getattr(current, key)):
                    return True
            except (TypeError, ValueError):
                return True
    return any(changes.get(k) is True and not getattr(current, k) for k in TURNS_ON)


__all__ = ["CardsApi", "card_view", "record_view", "refused", "settings_view"]
