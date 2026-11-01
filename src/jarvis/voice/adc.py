# src/jarvis/voice/adc.py
"""Application Default Credentials → request headers for Google's speech APIs (slice 9 D2, D3).

The ONLY module in jarvis.voice that imports google-auth (it arrives with the Firestore
dependency): on Cloud Run the credentials are the service account jarvis-run, so no key or secret
exists anywhere. google-auth is synchronous, so discovery and token refresh run in a worker
thread (never on the event loop), one at a time, bounded by a timeout.

    no credentials (DefaultCredentialsError)  → VoiceUnavailable("not_configured"), cached 10 min
    refresh failed (RefreshError, transport)  → VoiceUnavailable("upstream_error"), not cached
    discovery / refresh took too long         → VoiceUnavailable("timeout")

Tokens are never logged.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import google.auth
from google.auth import exceptions as gexc
from google.auth.transport.requests import Request

from jarvis.logging import get_logger
from jarvis.voice.ports import VoiceUnavailable

log = get_logger(__name__)

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
TIMEOUT_S = 10.0
NOT_CONFIGURED_TTL_S = 600.0


def _discover(scopes: list[str]) -> Any:
    creds, _project = google.auth.default(scopes=scopes)
    return creds


class AdcTokens:
    """A `TokenSource` backed by Application Default Credentials."""

    def __init__(
        self,
        *,
        timeout_s: float = TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        discover: Callable[[list[str]], Any] = _discover,
    ) -> None:
        self._timeout = timeout_s
        self._clock = clock
        self._discover = discover
        self._creds: Any = None
        self._stale = False
        self._missing_until = 0.0
        self._lock = asyncio.Lock()

    @property
    def not_configured(self) -> bool:
        return self._clock() < self._missing_until

    def invalidate(self) -> None:
        """The API refused the token (401): refresh before the next call."""
        self._stale = True

    async def _off_loop(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), self._timeout)
        except TimeoutError:
            log.warning("google credentials: no answer in time")
            raise VoiceUnavailable("timeout") from None

    async def headers(self) -> dict[str, str]:
        if self.not_configured:
            raise VoiceUnavailable("not_configured")
        async with self._lock:
            if self._creds is None:
                try:
                    self._creds = await self._off_loop(self._discover, [SCOPE])
                except gexc.DefaultCredentialsError:
                    self._missing_until = self._clock() + NOT_CONFIGURED_TTL_S
                    log.warning("google credentials not found: cloud voice is off")
                    raise VoiceUnavailable("not_configured") from None
            creds = self._creds
            if self._stale or not creds.valid:
                try:
                    await self._off_loop(creds.refresh, Request())
                except (gexc.RefreshError, gexc.TransportError) as exc:
                    log.warning("google token refresh failed", extra={"reason": type(exc).__name__})
                    raise VoiceUnavailable("upstream_error") from None
                self._stale = False
            out = {"Authorization": f"Bearer {creds.token}"}
            quota = getattr(creds, "quota_project_id", None)
            if isinstance(quota, str) and quota:
                out["x-goog-user-project"] = quota  # user credentials (local dev) bill a project
            return out


__all__ = ["NOT_CONFIGURED_TTL_S", "SCOPE", "AdcTokens"]
