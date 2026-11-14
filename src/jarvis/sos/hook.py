# src/jarvis/sos/hook.py
"""R7 D20, I0 seam 15: the Telegram front door's one hook for emergency contacts.

`telegram/service.py` calls the hook in exactly two places, both before anything else decides:
- a `/start <word>` whose word carries `SOS_WORD_PREFIX` goes to `join` and NEVER to the owner's
  pairing (so a wrong join word never counts against the pairing tries, and a pairing code never
  joins SOS); with no hook bound such a word is turned away and audited like any stranger;
- a `/stop` from a sender the hook knows as a contact goes to `stop` BEFORE the turn-away.
Anything else a contact writes is turned away as today, never reaches the brain and gets no reply.
The reply each returns (or None: nothing is said and the sender is turned away) is sent once.
Part D builds the hook (`MobilePart("body").services["sos_hook"]`): its words hold at least 128
random bits, are stored only as `keyring.mac("sos", word)`, and have their own wrong-word counter.
"""

from __future__ import annotations

import re
from typing import Protocol

SOS_WORD_PREFIX = "sos-"
# Telegram's start word: at most 64 letters, digits, `_` or `-`; 22 base64url characters = 132 bits
_WORD = re.compile(r"^sos-[A-Za-z0-9_-]{22,60}$")


def is_sos_word(word: str) -> bool:
    """A start word shaped like an SOS join word (it says nothing about whether it is right)."""
    return bool(_WORD.fullmatch(word))


class SosHook(Protocol):
    async def is_contact(self, tg_user_id: int) -> bool: ...

    async def join(self, word: str, *, tg_user_id: int, chat_id: int) -> str | None: ...

    async def stop(self, *, tg_user_id: int, chat_id: int) -> str | None: ...


__all__ = ["SOS_WORD_PREFIX", "SosHook", "is_sos_word"]
