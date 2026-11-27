# src/jarvis/api/calls_console.py
"""R18 I1: A1's `CardsApi` on `app.state.calls_api`, with what the console's Calls screens read
beside A1's own views (E's `console-calls-shapes.js` reads A1's names; docs/plans/r18-calls/
E-NOTES.md). A1's views are kept whole; this only adds:

- a card that waits for his tap also waits on his phone (D's Approve / Decline);
- settings: `azure_status` ("ready" with an Azure key on the server, else "off");
- the language table: `results`, every stored result as one flat list, with English's "not yet
  checked" stand-in (`not_checked`) while English has none (the Workshop's decision).

The language check's {confirm, estimate_inr} is read by `jarvis.calls.join_speech`; a confirmed
settings change's `?confirm=1` by the route (`api.calls_routes`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jarvis.api.calls_handlers_cards import CardsApi
from jarvis.calls.cards import PROVISIONAL_ENGLISH
from jarvis.calls.models import ENGLISH, CardStatus
from jarvis.calls.templates import catalogue
from jarvis.logging import get_logger

log = get_logger(__name__)

CARD_ON_PHONE_S = 600  # a card waits on the phone as long as an approval lives


def ready_cards() -> list[dict[str, Any]]:
    """A1's templates (name, title, fields) as the status's ready cards, by `id` too."""
    return [t | {"id": t["name"]} for t in catalogue()]


class ConsoleCardsApi(CardsApi):
    """`app.state.calls_api` (see the module docstring)."""

    phone: Any = None  # jarvis.phone.calls.PhoneCalls (None without the phone part)
    azure_ready: bool = False

    async def create_card(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        out = await super().create_card(uid, body)
        if self.phone is not None and out.get("blocked") is None:
            await self._offer(uid, str(out.get("id", "")))
        return out

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

    def _azure(self, out: dict[str, Any]) -> dict[str, Any]:
        return out | {"azure_status": "ready" if self.azure_ready else "off"}

    async def get_settings(self, uid: str) -> dict[str, Any]:
        return self._azure(await super().get_settings(uid))

    async def put_settings(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._azure(await super().put_settings(uid, body))

    async def languages(self, uid: str) -> dict[str, Any]:
        out = await super().languages(uid)
        results = await self.store.language_results()
        rows = [r.model_dump(mode="json") for r in results]
        if not any(r.lang == ENGLISH for r in results):
            stand_in = PROVISIONAL_ENGLISH.model_dump(mode="json")
            rows.append(stand_in | {"checked_at": None, "not_checked": True})
        return out | {"results": rows}


__all__ = ["CARD_ON_PHONE_S", "ConsoleCardsApi", "ready_cards"]
