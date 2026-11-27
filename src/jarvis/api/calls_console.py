# src/jarvis/api/calls_console.py
"""R18 I1: A1's `CardsApi` as the console's Calls screens read and send it (E's
`console-calls-shapes.js`, docs/plans/r18-calls/E-NOTES.md). A1's views are kept whole; this adds
the console's names beside them and reads the console's bodies, so neither part rewrites the
other's:

- a card body: `contact_name` is A1's `contact`, `limits {max_minutes}` its `max_minutes`,
  `from_card` (Edit, the number not retyped) takes that card's number on the server;
- a card: `number_last4`, `passkey_required` (a never-called number, or his passkey in force),
  `ready {ok, problems}` and `refused` (A1's `blocked`);
- the approval: A1's own two presses (propose, then `{approval_id, passkey}`); the console makes
  the passkey for the approval id the first press answered;
- records: `number_last4`; one record's `summary` as its English text (A1's whole summary stays
  in `summary_parts`), `transcript` as its lines, `booking_event`;
- settings: `azure_status`; the language table: `results` (every stored result, and English's
  "not yet checked" stand-in), and the check's progress;
- a card waiting for his tap also waits on his phone (D's Approve / Decline).

The ready cards in `GET /v1/calls/status` are A1's templates by id and title.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from jarvis.api.calls_handlers_cards import CardsApi
from jarvis.calls.cards import PROVISIONAL_ENGLISH
from jarvis.calls.models import CARD_ID_RE, ENGLISH, CallCard, CardStatus
from jarvis.calls.ports import CallsRefused
from jarvis.calls.templates import catalogue
from jarvis.logging import get_logger

log = get_logger(__name__)

CARD_ON_PHONE_S = 600  # a card waits on the phone as long as an approval lives
_DIGITS = re.compile(r"\D")
MSG_FROM = "The card to edit is not there any more: type the number again."


def last4(e164: str | None) -> str:
    digits = _DIGITS.sub("", e164 or "")
    return digits[-4:] if len(digits) >= 4 else ""


def ready_cards() -> list[dict[str, Any]]:
    """A1's templates as the console's ready cards (its form fills the rest)."""
    return [{"id": t["name"], "title": t["title"], "purpose": t["title"]} for t in catalogue()]


class ConsoleCardsApi(CardsApi):
    """`app.state.calls_api`: A1's handlers with the console's names (see the module docstring)."""

    phone: Any = None  # jarvis.phone.calls.PhoneCalls (None without the phone part)
    azure_ready: bool = False

    # ---- cards ----------------------------------------------------------------------------------
    async def _console_body(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in body.items() if k not in ("contact_name", "limits", "from_card")}
        if "contact_name" in body and "contact" not in body and body["contact_name"]:
            out["contact"] = body["contact_name"]
        limits = body.get("limits")
        if isinstance(limits, dict) and "max_minutes" in limits and "max_minutes" not in body:
            out["max_minutes"] = limits["max_minutes"]
        source = body.get("from_card")
        if source is not None and not out.get("number"):
            old = await self._own_card(uid, source)
            out["number"] = old.number_e164
            if not out.get("contact") and old.contact_name:
                out["contact"] = old.contact_name
        return out

    async def _own_card(self, uid: str, card_id: object) -> CallCard:
        if not isinstance(card_id, str) or not CARD_ID_RE.fullmatch(card_id):
            raise CallsRefused(422, "invalid", MSG_FROM)
        card = await self.store.get_card(uid, card_id)
        if card is None:
            raise CallsRefused(404, "not_found", MSG_FROM)
        return card

    async def _console_card(self, uid: str, view: dict[str, Any]) -> dict[str, Any]:
        blocked = view.get("blocked")
        problems = [blocked["words"]] if isinstance(blocked, dict) else []
        passkey = bool(view.get("new_number")) or await self._passkey_in_force(uid)
        return view | {
            "number_last4": last4(view.get("number_e164")),
            "passkey_required": passkey,
            "ready": {"ok": not problems, "problems": problems},
            "refused": problems[0] if problems else None,
        }

    async def create_card(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        out = await super().create_card(uid, await self._console_body(uid, body))
        if self.phone is not None and out.get("blocked") is None:
            await self._offer(uid, str(out.get("id", "")))
        return await self._console_card(uid, out)

    async def estimate(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        out = await super().estimate(uid, await self._console_body(uid, body))
        return await self._console_card(uid, out)

    async def get_card(self, uid: str, card_id: str) -> dict[str, Any]:
        return await self._console_card(uid, await super().get_card(uid, card_id))

    async def cancel(self, uid: str, card_id: str) -> dict[str, Any]:
        return await self._console_card(uid, await super().cancel(uid, card_id))

    async def _offer(self, uid: str, card_id: str) -> None:
        from jarvis.phone.calls_wire import Card

        try:
            card = await self.store.get_card(uid, card_id)
            if card is None or card.status is not CardStatus.DRAFT:
                return
            until = datetime.now(UTC).timestamp() + CARD_ON_PHONE_S
            await self.phone.send(uid, Card.for_card(card, expires_at=until))
        except Exception as exc:  # noqa: BLE001 - the console shows the card anyway
            log.warning("call card not offered on the phone", extra={"error": type(exc).__name__})

    # ---- records --------------------------------------------------------------------------------
    async def list_records(self, uid: str, limit: int) -> dict[str, Any]:
        out = await super().list_records(uid, limit)
        return {
            "records": [v | {"number_last4": last4(v["number_masked"])} for v in out["records"]]
        }

    async def get_record(self, uid: str, call_id: str) -> dict[str, Any]:
        out = await super().get_record(uid, call_id)
        summary, transcript = out.get("summary"), out.get("transcript")
        event = None
        if out.get("booking_added"):
            event = {"title": "", "when": "", "undone": False}
        return out | {
            "number_last4": last4(out.get("number")),
            "summary": summary.get("english", "") if isinstance(summary, dict) else "",
            "summary_parts": summary,
            "transcript": list(transcript.get("lines", ())) if isinstance(transcript, dict) else [],
            "booking_event": event,
        }

    # ---- settings and languages ---------------------------------------------------------------
    async def get_settings(self, uid: str) -> dict[str, Any]:
        out = await super().get_settings(uid)
        return out | {"azure_status": "ready" if self.azure_ready else "off"}

    async def put_settings(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        out = await super().put_settings(uid, body)
        return out | {"azure_status": "ready" if self.azure_ready else "off"}

    async def languages(self, uid: str) -> dict[str, Any]:
        out = await super().languages(uid)
        results = await self.store.language_results()
        rows = [r.model_dump(mode="json") for r in results]
        if not any(r.lang == ENGLISH for r in results):
            stand_in = PROVISIONAL_ENGLISH.model_dump(mode="json")
            rows.append(stand_in | {"checked_at": None, "not_checked": True})
        return out | {"results": rows}


__all__ = ["CARD_ON_PHONE_S", "ConsoleCardsApi", "last4", "ready_cards"]
