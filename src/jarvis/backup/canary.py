# src/jarvis/backup/canary.py
"""The backups' daily canary (docs/plans/r14-hardening.md D4 "Canary"; data model).

    {prefix}backup_canary/{yyyymmdd}   {hash, sealed, fp, v, at}       kept 30 days

`hash` is the SHA-256 of a fresh random 32-byte nonce; `sealed` is that nonce sealed with the
keyring purpose `backup_probe` (AAD `backup_canary/{yyyymmdd}/v1`); `fp` is the key's fingerprint,
`keyring.mac("backup_probe", "fingerprint/v1")`, first 16 hex characters. The nonce is never stored
in clear and never logged. A restored copy must hold a canary whose sealed nonce opens with the
LIVE key, so the drill proves the backups are readable with today's key; a fingerprint that
differs from yesterday's means the key changed (`backup_problem`, "key_changed").

`make` / `opens` / `fingerprint` are pure (the drill's verifier uses them on both sides);
`CanaryStore` is the daily writer on the live store (the morning tick's `backup_canary` job).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
from typing import Literal

import jarvis
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, DocExists, Docs, Query

log = get_logger(__name__)

COLLECTION = "backup_canary"
PURPOSE = "backup_probe"
FINGERPRINT_DATA = "fingerprint/v1"
FINGERPRINT_CHARS = 16
NONCE_BYTES = 32
KEEP_DAYS = 30
Opened = Literal["ok", "key", "mismatch", "unreadable"]


def day_key(at: dt.datetime | dt.date) -> str:
    return at.strftime("%Y%m%d")


def aad(day: str) -> str:
    return f"backup_canary/{day}/v1"


def fingerprint(keys: Keyring) -> str:
    return keys.mac(PURPOSE, FINGERPRINT_DATA)[:FINGERPRINT_CHARS]


def make(keys: Keyring, day: str, now: dt.datetime) -> Doc:
    nonce = os.urandom(NONCE_BYTES)
    return {
        "hash": hashlib.sha256(nonce).hexdigest(),
        "sealed": keys.cipher(PURPOSE).encrypt(nonce, aad=aad(day)),
        "fp": fingerprint(keys),
        "v": jarvis.__version__,
        "at": now.astimezone(dt.UTC).isoformat(),
    }


def opens(keys: Keyring, doc: Doc, day: str) -> Opened:
    """Does this canary open with `keys`? "key": another key sealed it (or another day's AAD);
    "mismatch": it opens but its nonce is not the one hashed; "unreadable": not a canary."""
    sealed, want, fp = doc.get("sealed"), doc.get("hash"), doc.get("fp")
    if not (isinstance(sealed, str) and isinstance(want, str) and isinstance(fp, str)):
        return "unreadable"
    if not hmac.compare_digest(fp, fingerprint(keys)):
        return "key"
    try:
        nonce = keys.cipher(PURPOSE).decrypt(sealed, aad=aad(day))
    except VaultError:
        return "key"
    return "ok" if hmac.compare_digest(hashlib.sha256(nonce).hexdigest(), want) else "mismatch"


def when(doc: Doc) -> dt.datetime | None:
    raw = doc.get("at")
    try:
        at = raw if isinstance(raw, dt.datetime) else dt.datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=dt.UTC)


class CanaryStore:
    """The daily canary on the live store (one document a day, the last 30 days)."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}{COLLECTION}"

    def path(self, day: str) -> str:
        return f"{self._col}/{day}"

    async def all(self) -> list[tuple[str, Doc]]:
        return sorted(await self._d.query(Query(self._col)))

    async def write(self, keys: Keyring, now: dt.datetime) -> bool:
        """Today's canary, once (True when written now)."""
        day = day_key(now)
        if await self._d.get(self.path(day)) is not None:
            return False
        try:
            await self._d.write([Create(self.path(day), make(keys, day, now))])
        except DocExists:
            return False
        return True

    async def latest_before(self, day: str) -> tuple[str, Doc] | None:
        older = [(d, doc) for d, doc in await self.all() if d < day]
        return older[-1] if older else None

    async def key_changed(self, keys: Keyring, day: str) -> bool:
        """The newest canary before `day` was sealed by another key (or no longer opens)."""
        found = await self.latest_before(day)
        if found is None:
            return False
        return opens(keys, found[1], found[0]) == "key"

    async def prune(self, now: dt.datetime) -> int:
        oldest = day_key(now - dt.timedelta(days=KEEP_DAYS))
        old = [d for d, _ in await self.all() if d < oldest]
        if old:
            await self._d.write([Delete(self.path(d)) for d in old])
        return len(old)


__all__ = [
    "COLLECTION",
    "FINGERPRINT_CHARS",
    "KEEP_DAYS",
    "PURPOSE",
    "CanaryStore",
    "Opened",
    "aad",
    "day_key",
    "fingerprint",
    "make",
    "opens",
    "when",
]
