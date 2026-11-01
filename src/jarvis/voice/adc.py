# src/jarvis/voice/adc.py
"""Application Default Credentials → request headers for Google's speech APIs (slice 9 D2, D3).

The ONLY module in jarvis.voice that imports google-auth (it arrives with the Firestore
dependency): on Cloud Run the credentials are the service account jarvis-run, so no key or secret
exists anywhere. google-auth is synchronous, so discovery and token refresh run in a worker
thread (never on the event loop), bounded by a timeout.

    no credentials (DefaultCredentialsError)  → VoiceUnavailable("not_configured"), cached 10 min
    discovery took > 5 s                      → the same: on Cloud Run the metadata server answers
                                                in milliseconds; off Google Cloud google-auth
                                                probes it for ~10 s before giving up (dev)
    refresh failed (RefreshError, transport)  → VoiceUnavailable("upstream_error"), not cached
    refresh took too long                     → VoiceUnavailable("timeout"), not cached

One refresh at a time: a refresh is a single in-flight task that every caller awaits (shielded,
each with its own timeout), so a caller that gave up never leaves a second refresh thread
running beside the next one. Every refresh uses the same google-auth transport (one
requests.Session), closed by `close()` when the app shuts down. Tokens are never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
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
DISCOVERY_TIMEOUT_S = 5.0
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
        discovery_timeout_s: float = DISCOVERY_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        discover: Callable[[list[str]], Any] = _discover,
        transport: Callable[[], Any] = Request,
    ) -> None:
        self._timeout = timeout_s
        self._discovery_timeout = discovery_timeout_s
        self._clock = clock
        self._discover = discover
        self._transport_factory = transport
        self._transport: Any = None  # made on the first refresh, reused, closed by close()
        self._refreshing: asyncio.Future[Any] | None = None
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

    def close(self) -> None:
        """Close the refresh transport's HTTP session (app shutdown). Safe to call twice."""
        transport, self._transport = self._transport, None
        session = getattr(transport, "session", None)
        if session is not None:
            with contextlib.suppress(Exception):
                session.close()

    async def _refresh(self, creds: Any) -> None:
        """Refresh `creds` in a worker thread: join the refresh in flight, else start one."""
        task = self._refreshing
        if task is None or task.done():
            if self._transport is None:
                self._transport = self._transport_factory()
            task = asyncio.ensure_future(asyncio.to_thread(creds.refresh, self._transport))
            # nobody may be waiting when it ends (a caller timed out): read its outcome
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._refreshing = task
        try:
            await asyncio.wait_for(asyncio.shield(task), self._timeout)
        except TimeoutError:
            log.warning("google credentials: no answer in time")
            raise VoiceUnavailable("timeout") from None

    async def _off_loop(self, timeout: float, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
        except TimeoutError:
            log.warning("google credentials: no answer in time")
            raise VoiceUnavailable("timeout") from None

    def _missing(self, why: str) -> VoiceUnavailable:
        self._missing_until = self._clock() + NOT_CONFIGURED_TTL_S
        log.warning("google credentials not found: cloud voice is off", extra={"why": why})
        return VoiceUnavailable("not_configured")

    async def headers(self) -> dict[str, str]:
        if self.not_configured:
            raise VoiceUnavailable("not_configured")
        async with self._lock:
            if self._creds is None:
                try:
                    self._creds = await self._off_loop(
                        self._discovery_timeout, self._discover, [SCOPE]
                    )
                except gexc.DefaultCredentialsError:
                    raise self._missing("none") from None
                except VoiceUnavailable:
                    raise self._missing("lookup timed out") from None
            creds = self._creds
            if self._stale or not creds.valid:
                try:
                    await self._refresh(creds)
                except (gexc.RefreshError, gexc.TransportError) as exc:
                    log.warning("google token refresh failed", extra={"reason": type(exc).__name__})
                    raise VoiceUnavailable("upstream_error") from None
                self._stale = False
            out = {"Authorization": f"Bearer {creds.token}"}
            quota = getattr(creds, "quota_project_id", None)
            if isinstance(quota, str) and quota:
                out["x-goog-user-project"] = quota  # user credentials (local dev) bill a project
            return out


__all__ = ["DISCOVERY_TIMEOUT_S", "NOT_CONFIGURED_TTL_S", "SCOPE", "TIMEOUT_S", "AdcTokens"]
