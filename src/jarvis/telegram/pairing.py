# src/jarvis/telegram/pairing.py
"""One-time pairing codes (R1 D2): 8 Crockford base32 characters (40 bits), 10 minutes, single
use, stored only as a SHA-256 hash, void after 5 wrong tries. Pure helpers; `store` applies them."""

from __future__ import annotations

import hashlib
import re
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U
CODE_LEN = 8
CODE_TTL_S = 600
MAX_TRIES = 5  # wrong tries per SENDER in TRY_WINDOW_S
GLOBAL_TRIES = 30  # wrong tries by everyone in TRY_WINDOW_S (cooldown)
TRY_WINDOW_S = 600
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})
_VALID = re.compile(rf"[{ALPHABET}]{{{CODE_LEN}}}")


def new_code() -> str:
    bits = secrets.randbits(5 * CODE_LEN)
    return "".join(ALPHABET[(bits >> (5 * i)) & 31] for i in range(CODE_LEN))


def normalise(raw: str) -> str | None:
    """The canonical code for what the owner typed or tapped, or None when it can't be one."""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    text = re.sub(r"[\s-]+", "", raw).upper().translate(_LOOKALIKES)
    return text if _VALID.fullmatch(text) else None


def hash_code(raw: str) -> str:
    code = normalise(raw)
    if code is None:
        raise ValueError("not a pairing code")
    return hashlib.sha256(code.encode()).hexdigest()


def deep_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={code}"


__all__ = [
    "ALPHABET",
    "CODE_LEN",
    "CODE_TTL_S",
    "GLOBAL_TRIES",
    "MAX_TRIES",
    "TRY_WINDOW_S",
    "deep_link",
    "hash_code",
    "new_code",
    "normalise",
]
