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
HTTP_UNAUTHORIZED = 401
META_RETRY_S = META_WRITE_EVERY_S  # after a failed write, wait this long
_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z")
_MAX_INT = 10**12
_MAX_INT_CHARS = 13
_MAX_EPOCH = 4_102_444_800.0  # 2100-01-01: later (or before 1970) is a header we can't trust


def _epoch(value: float | None) -> float | None:
    return value if value is not None and 0 < value <= _MAX_EPOCH else None


def parse_expiry(value: str | None) -> float | None:
    """Epoch seconds from GitHub's "2026-12-31 23:59:59 UTC" (or a numeric offset, or ISO 8601);
    None when there is none or it can't be read (or is before 1970 / after 2100)."""
    text = (value or "").strip()[:64]
    if not text:
        return None
    for fmt in _FORMATS:
        try:
            d = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return _epoch((d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp())
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _epoch(d.timestamp()) if d.tzinfo else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_INT else None
    if (
        isinstance(value, str)
        and len(value) <= _MAX_INT_CHARS
        and value.isascii()
        and value.isdecimal()
    ):
        return _int(int(value))
    return None


def _time(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
        return _epoch(float(value))
    return None


@dataclass(frozen=True)
class TokenMeta:
    seen_at: float  # when JARVIS last saw an answer from GitHub with this token
    expires_at: float | None = None  # None: GitHub says nothing, so the token doesn't expire
    rate_limit: int | None = None
    rate_used: int | None = None
    rate_reset: float | None = None  # epoch seconds: when the hourly count starts again
    rejected_at: float | None = None  # GitHub answered 401 (revoked / deleted token) at this time
    expiry_unreadable: bool = False  # the expiry header was there but could not be read

    def fields(self) -> dict[str, Any]:
        return {
            "seen_at": self.seen_at,
            "expires_at": self.expires_at,
            "rate_limit": self.rate_limit,
            "rate_used": self.rate_used,
            "rate_reset": self.rate_reset,
            "rejected_at": self.rejected_at,
            "expiry_unreadable": self.expiry_unreadable,
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
            _time(doc.get("rejected_at")),
            doc.get("expiry_unreadable") is True,
        )

    @classmethod
    def observe(
        cls, headers: httpx.Headers, now: float, *, status: int, before: TokenMeta | None
    ) -> TokenMeta | None:
        """From one response. A 200 says everything (header absent = no expiry; present but
        unreadable = unknown); a 401 records that the token was refused; any other answer only
        updates the hourly count of what was already known (None if nothing was). One odd header
        drops only its own field."""
        limit = _int(headers.get("x-ratelimit-limit"))
        used = _int(headers.get("x-ratelimit-used"))
        reset_s = _int(headers.get("x-ratelimit-reset"))
        reset = None if reset_s is None else _epoch(float(reset_s))
        if status == HTTP_OK:
            raw = (headers.get(EXPIRY_HEADER) or "").strip()
            expires = parse_expiry(raw)
            return cls(now, expires, limit, used, reset, None, bool(raw) and expires is None)
        if status == HTTP_UNAUTHORIZED:
            base = before or cls(now)
            return cls(
                now,
                base.expires_at,
                base.rate_limit,
                base.rate_used,
                base.rate_reset,
                now,
                base.expiry_unreadable,
            )
        if before is None or limit is None:
            return before
        return cls(
            now, before.expires_at, limit, used, reset, before.rejected_at, before.expiry_unreadable
        )


class MetaBook:
    """This process's latest `TokenMeta` per owner and what was last stored: a changed expiry (or
    a refusal) is stored at once, anything else at most every `META_WRITE_EVERY_S` (Firestore
    writes are not free); after a failed write nothing is tried for `META_RETRY_S`. A per-owner
    generation moves on connect / disconnect, so a read begun before it can't write its answer
    onto the new token. Never raises: bookkeeping must not break a GitHub call."""

    def __init__(self) -> None:
        self._latest: dict[str, TokenMeta] = {}
        self._stored: dict[str, tuple[float, tuple[Any, ...]]] = {}  # uid -> (seen_at, change key)
        self._failed: dict[str, float] = {}
        self._gen: dict[str, int] = {}

    @staticmethod
    def _key(meta: TokenMeta) -> tuple[Any, ...]:
        return (meta.expires_at, meta.expiry_unreadable, meta.rejected_at)

    def get(self, uid: str) -> TokenMeta | None:
        return self._latest.get(uid)

    def generation(self, uid: str) -> int:
        return self._gen.get(uid, 0)

    def observe(
        self, uid: str, status: int, headers: httpx.Headers, now: float, gen: int | None = None
    ) -> None:
        if gen is not None and gen != self.generation(uid):
            return  # the token changed while this read was in flight: its facts are stale
        try:
            m = TokenMeta.observe(headers, now, status=status, before=self._latest.get(uid))
        except Exception as exc:  # noqa: BLE001
            log.warning("github meta unreadable", extra={"reason": type(exc).__name__})
            return
        if m is not None:
            self._latest[uid] = m

    def saved(self, uid: str, meta: TokenMeta | None) -> None:
        """`meta` is now what the stored record holds (None: a new record without any)."""
        self.forget(uid)
        if meta is not None:
            self._latest[uid], self._stored[uid] = meta, (meta.seen_at, self._key(meta))

    def forget(self, uid: str) -> None:
        self._gen[uid] = self.generation(uid) + 1
        self._latest.pop(uid, None)
        self._stored.pop(uid, None)
        self._failed.pop(uid, None)

    def due(self, uid: str, now: float) -> TokenMeta | None:
        """The facts to store now, or None when the stored copy is recent enough (or a write
        failed lately)."""
        meta, last = self._latest.get(uid), self._stored.get(uid)
        failed = self._failed.get(uid)
        if meta is None or (failed is not None and 0 <= now - failed < META_RETRY_S):
            return None
        if (
            last is not None
            and last[1] == self._key(meta)
            and meta.seen_at - last[0] < META_WRITE_EVERY_S
        ):
            return None
        return meta

    def stored(self, uid: str, meta: TokenMeta) -> None:
        self._stored[uid] = (meta.seen_at, self._key(meta))
        self._failed.pop(uid, None)

    def failed(self, uid: str, now: float) -> None:
        self._failed[uid] = now


__all__ = ["EXPIRY_HEADER", "META_WRITE_EVERY_S", "MetaBook", "TokenMeta", "parse_expiry"]
