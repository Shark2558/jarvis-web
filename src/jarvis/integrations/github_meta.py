# src/jarvis/integrations/github_meta.py
"""What GitHub's own response headers say about the owner's token (R5.1 D2), so the Vitals board
can show it without the owner typing anything: when the token expires
(`GitHub-Authentication-Token-Expiration`; absent = it doesn't expire) and the hourly API limit
(`x-ratelimit-limit` / `-used` / `-reset`). No secret: these are clear fields beside the sealed
token in `{prefix}connectors_github/{uid}` (`meta`). A header that can't be read is ignored and
never logged (it is GitHub's text)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from jarvis.logging import get_logger

log = get_logger(__name__)

EXPIRY_HEADER = "github-authentication-token-expiration"
META_WRITE_EVERY_S = 600.0  # the stored copy is refreshed at most this often
HTTP_OK = 200
_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z")
_MAX_INT = 10**12


def parse_expiry(value: str | None) -> float | None:
    """Epoch seconds from GitHub's "2026-12-31 23:59:59 UTC" (or a numeric offset, or ISO 8601);
    None when there is none or it can't be read."""
    text = (value or "").strip()[:64]
    if not text:
        return None
    for fmt in _FORMATS:
        try:
            d = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_INT else None
    if isinstance(value, str) and value.isdigit():
        return _int(int(value))
    return None


def _time(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
        return float(value) if value >= 0 else None
    return None


@dataclass(frozen=True)
class TokenMeta:
    seen_at: float  # when JARVIS last saw an answer from GitHub with this token
    expires_at: float | None = None  # None: GitHub says nothing, so the token doesn't expire
    rate_limit: int | None = None
    rate_used: int | None = None
    rate_reset: float | None = None  # epoch seconds: when the hourly count starts again

    def fields(self) -> dict[str, Any]:
        return {
            "seen_at": self.seen_at,
            "expires_at": self.expires_at,
            "rate_limit": self.rate_limit,
            "rate_used": self.rate_used,
            "rate_reset": self.rate_reset,
        }

    @classmethod
    def read(cls, doc: Any) -> TokenMeta | None:
        """From the stored `meta` field; None when it is missing or malformed."""
        if not isinstance(doc, dict):
            return None
        seen = _time(doc.get("seen_at"))
        if seen is None:
            return None
        return cls(
            seen,
            _time(doc.get("expires_at")),
            _int(doc.get("rate_limit")),
            _int(doc.get("rate_used")),
            _time(doc.get("rate_reset")),
        )

    @classmethod
    def observe(
        cls, headers: httpx.Headers, now: float, *, ok: bool, before: TokenMeta | None
    ) -> TokenMeta | None:
        """From one response. A 200 says everything (no expiry header = no expiry); any other
        answer only updates the hourly count of what was already known (None if nothing was)."""
        limit = _int(headers.get("x-ratelimit-limit"))
        used = _int(headers.get("x-ratelimit-used"))
        reset_s = _int(headers.get("x-ratelimit-reset"))
        reset = None if reset_s is None else float(reset_s)
        if ok:
            return cls(now, parse_expiry(headers.get(EXPIRY_HEADER)), limit, used, reset)
        if before is None or limit is None:
            return before
        return cls(now, before.expires_at, limit, used, reset)


class MetaBook:
    """This process's latest `TokenMeta` per owner and what was last stored: a changed expiry is
    stored at once, anything else at most every `META_WRITE_EVERY_S` (Firestore writes are not
    free). Never raises: bookkeeping must not break a GitHub call."""

    def __init__(self) -> None:
        self._latest: dict[str, TokenMeta] = {}
        self._stored: dict[str, tuple[float, float | None]] = {}  # uid -> (seen_at, expires_at)

    def get(self, uid: str) -> TokenMeta | None:
        return self._latest.get(uid)

    def observe(self, uid: str, status: int, headers: httpx.Headers, now: float) -> None:
        try:
            m = TokenMeta.observe(headers, now, ok=status == HTTP_OK, before=self._latest.get(uid))
        except Exception as exc:  # noqa: BLE001
            log.warning("github meta unreadable", extra={"reason": type(exc).__name__})
            return
        if m is not None:
            self._latest[uid] = m

    def saved(self, uid: str, meta: TokenMeta | None) -> None:
        """`meta` is now what the stored record holds (None: a new record without any)."""
        self.forget(uid)
        if meta is not None:
            self._latest[uid], self._stored[uid] = meta, (meta.seen_at, meta.expires_at)

    def forget(self, uid: str) -> None:
        self._latest.pop(uid, None)
        self._stored.pop(uid, None)

    def due(self, uid: str) -> TokenMeta | None:
        """The facts to store now, or None when the stored copy is recent enough."""
        meta, last = self._latest.get(uid), self._stored.get(uid)
        if meta is None or (
            last is not None
            and last[1] == meta.expires_at
            and meta.seen_at - last[0] < META_WRITE_EVERY_S
        ):
            return None
        return meta

    def stored(self, uid: str, meta: TokenMeta) -> None:
        self._stored[uid] = (meta.seen_at, meta.expires_at)


__all__ = ["EXPIRY_HEADER", "META_WRITE_EVERY_S", "MetaBook", "TokenMeta", "parse_expiry"]
