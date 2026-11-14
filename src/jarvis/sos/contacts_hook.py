# src/jarvis/sos/contacts_hook.py
"""The code behind I0's Telegram hook (docs/plans/r7-mobile.md D20; `jarvis.sos.hook.SosHook`).

`telegram/service.py` calls it before anything else decides: a `/start sos-...` goes to `join`
(never to the owner's pairing), a known contact's `/stop` to `stop`. This adapter never raises:
the front door must still answer Telegram, so a store that fails means "not a contact" / no
reply (the sender is then turned away and audited as any stranger). The words a contact writes
are never read beyond the command itself and never reach the brain.
"""

from __future__ import annotations

from jarvis.logging import get_logger
from jarvis.sos.service import SosService

log = get_logger(__name__)


class ContactHook:
    def __init__(self, service: SosService) -> None:
        self._svc = service

    async def is_contact(self, tg_user_id: int) -> bool:
        try:
            return await self._svc.is_contact(tg_user_id)
        except Exception as exc:  # noqa: BLE001 - fail closed: not a contact, turned away
            log.warning("SOS contact check failed", extra={"error": type(exc).__name__})
            return False

    async def join(self, word: str, *, tg_user_id: int, chat_id: int) -> str | None:
        try:
            return await self._svc.join(word, tg_user_id=tg_user_id, chat_id=chat_id)
        except Exception as exc:  # noqa: BLE001 - no join, turned away and audited
            log.warning("SOS join failed", extra={"error": type(exc).__name__})
            return None

    async def stop(self, *, tg_user_id: int, chat_id: int) -> str | None:
        try:
            return await self._svc.stop(tg_user_id=tg_user_id, chat_id=chat_id)
        except Exception as exc:  # noqa: BLE001 - no reply; he can send /stop again
            log.warning("SOS stop failed", extra={"error": type(exc).__name__})
            return None


__all__ = ["ContactHook"]
