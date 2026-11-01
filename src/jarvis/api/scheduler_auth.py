# src/jarvis/api/scheduler_auth.py
"""Who may call POST /internal/brief/tick: only Cloud Scheduler, proven by a Google-signed OIDC
token (cross-cutting security, Layer 1 surface).

Checks: RS256 only (the header is checked before any key is touched; `none`/HS256 never reach
the signature step), signature against Google's JWKS (fetched over HTTPS, cached per its
Cache-Control, refetched for an unknown key id at most once a minute), `iss` ∈ Google's two
spellings, `aud` == {public_base_url}/internal/brief/tick exactly, `email` == the configured
scheduler service account and `email_verified` is true, `exp`/`iat` within 60 s of skew.

The owner's API token and browser cookie are NOT accepted here, and every failure is the same
bare 401: a caller learns nothing about which check failed. The token is never logged.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Request
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from jarvis.integrations.google import JWKS_URL
from jarvis.logging import get_logger
from jarvis.tools.gmail_mime import b64url_decode

log = get_logger(__name__)

TICK_PATH = "/internal/brief/tick"
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
ALGORITHM = "RS256"
SKEW_S = 60
MAX_TOKEN_CHARS = 4_096
JWKS_TIMEOUT_S = 10.0
JWKS_DEFAULT_TTL_S = 3_600
JWKS_MIN_TTL_S, JWKS_MAX_TTL_S = 300, 86_400
MIN_REFETCH_S = 60
_MAX_AGE = re.compile(r"max-age=(\d+)")


class SchedulerUnauthorized(Exception):
    """Mapped to a bare 401 (no body) by the app."""


def _header(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return None
    try:
        h = json.loads(b64url_decode(parts[0]))
    except (ValueError, TypeError):
        return None
    if not isinstance(h, dict) or h.get("alg") != ALGORITHM:
        return None
    kid = h.get("kid")
    return h if isinstance(kid, str) and 0 < len(kid) <= 128 else None


def _number(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


class GoogleOIDCVerifier:
    def __init__(
        self,
        *,
        audience: str,
        email: str,
        http: httpx.AsyncClient | None = None,
        jwks_url: str = JWKS_URL,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._audience = audience
        self._email = email.strip().lower()
        self.http = http or httpx.AsyncClient(timeout=JWKS_TIMEOUT_S)
        self._jwks_url = jwks_url
        self._now = now
        self._keys: KeySet | None = None
        self._kids: frozenset[str] = frozenset()
        self._expires = 0.0
        self._fetched = float("-inf")
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self.http.aclose()

    async def verify(self, token: str) -> bool:
        if not token or len(token) > MAX_TOKEN_CHARS:
            return False
        header = _header(token)
        if header is None:
            return self._refuse("header")
        keys = await self._key_set(str(header["kid"]))
        if keys is None:
            return self._refuse("key")
        try:
            claims = jwt.decode(token, keys, algorithms=[ALGORITHM]).claims
        except (JoseError, ValueError, TypeError, KeyError):
            return self._refuse("signature")
        return self._claims_ok(claims) or self._refuse("claims")

    @staticmethod
    def _refuse(reason: str) -> bool:
        log.warning("scheduler token refused", extra={"reason": reason})
        return False

    def _claims_ok(self, c: dict[str, Any]) -> bool:
        now, exp, iat = self._now(), _number(c.get("exp")), _number(c.get("iat"))
        if exp is None or iat is None:
            return False
        return (
            c.get("iss") in GOOGLE_ISSUERS
            and isinstance(c.get("aud"), str)
            and c.get("aud") == self._audience
            and isinstance(c.get("email"), str)
            and str(c["email"]).lower() == self._email
            and c.get("email_verified") is True
            and now < exp + SKEW_S
            and iat <= now + SKEW_S
        )

    async def _key_set(self, kid: str) -> KeySet | None:
        async with self._lock:
            now = self._now()
            stale = self._keys is None or now >= self._expires
            unknown = kid not in self._kids and now - self._fetched >= MIN_REFETCH_S
            if stale or unknown:
                await self._fetch(now)
            return self._keys if kid in self._kids else None

    async def _fetch(self, now: float) -> None:
        self._fetched = now
        try:
            r = await self.http.get(self._jwks_url, timeout=JWKS_TIMEOUT_S)
            r.raise_for_status()
            keys = [
                k
                for k in r.json().get("keys") or []
                if isinstance(k, dict)
                and k.get("kty") == "RSA"
                and k.get("use", "sig") == "sig"
                and k.get("alg", ALGORITHM) == ALGORITHM
                and isinstance(k.get("kid"), str)
            ]
            key_set = KeySet.import_key_set({"keys": keys})
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, JoseError) as exc:
            log.warning("google jwks unavailable", extra={"reason": type(exc).__name__})
            return  # keep any keys we had; an empty cache fails closed
        m = _MAX_AGE.search(r.headers.get("cache-control", ""))
        ttl = int(m.group(1)) if m else JWKS_DEFAULT_TTL_S
        self._keys = key_set
        self._kids = frozenset(str(k["kid"]) for k in keys)
        self._expires = now + min(max(ttl, JWKS_MIN_TTL_S), JWKS_MAX_TTL_S)


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def require_scheduler(request: Request) -> None:
    """FastAPI dependency for the tick route. Cookies and the API token are never consulted."""
    verifier: GoogleOIDCVerifier | None = getattr(request.app.state, "scheduler_verifier", None)
    token = bearer_token(request)
    if verifier is None or token is None or not await verifier.verify(token):
        raise SchedulerUnauthorized()


__all__ = [
    "TICK_PATH",
    "GoogleOIDCVerifier",
    "SchedulerUnauthorized",
    "bearer_token",
    "require_scheduler",
]
