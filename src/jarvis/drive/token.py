# src/jarvis/drive/token.py
"""JARVIS's own Drive token: the Cloud Run metadata server, read-only scope (slice 12 D1).

    GET http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/
        token?scopes=https://www.googleapis.com/auth/drive.readonly   (Metadata-Flavor: Google)

Verified 2026-11-03: google-auth's `compute_engine.Credentials` documents that "on Cloud Run,
Flex and App Engine the server honours requested scopes" (only Compute Engine ignores them), and
sends them exactly like this (`scopes`, comma-separated). So no IAM Credentials call and no
`iam.serviceAccountTokenCreator` grant is needed: the token is the runtime account's own, scoped
to read Drive. (The official Cloud Run page could not be fetched from the build sandbox; recorded
in the plan as "verified via the client library", with a live check after deploy.)

The service account's address (for Integrations: "share your folder with …") comes from the same
server (`…/default/email`) once and is kept.

One refresh at a time: every caller awaits the same in-flight request (shielded, each with its
own deadline). A token is kept until 60 s before it expires, or until `invalidate()` (Drive said
401). When the metadata server can't be reached (a passing network hiccup on Cloud Run looks the
same as running elsewhere), the answer is "couldn't reach Google just now", remembered for a few
seconds only, so a chat turn doesn't wait on the same failure each call yet a hiccup heals fast.
Redirects are never followed, answers are size-capped and type-checked; the token is never logged.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from jarvis.drive.ports import DRIVE_SCOPE, DriveUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)

METADATA_BASE = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
)
TOKEN_URL = METADATA_BASE + "/token"
EMAIL_URL = METADATA_BASE + "/email"
HEADERS = {"Metadata-Flavor": "Google"}
DEADLINE_S = 5.0
HTTP_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
SKEW_S = 60.0
UNREACHABLE_TTL_S = 5.0
MAX_ANSWER_BYTES = 64 * 1024
MAX_EXPIRES_S = 24 * 3600
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9._~+/=-]{1,4096}")
_SA_EMAIL = re.compile(r"[a-z0-9][a-z0-9-]{4,62}@[a-z0-9-]{4,64}\.iam\.gserviceaccount\.com")

UNREACHABLE = "JARVIS couldn't reach Google just now for its Drive access. Try again in a minute."
NO_TOKEN = "JARVIS couldn't get its Google Drive access just now. Try again in a minute."
SLOW = "Google took too long to give JARVIS its Drive access. Try again in a minute."


class MetadataTokens:
    """A `TokenSource` backed by the Cloud Run metadata server."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        deadline_s: float = DEADLINE_S,
        scope: str = DRIVE_SCOPE,
    ) -> None:
        self._own = http is None
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._clock = clock
        self._deadline = deadline_s
        self._scope = scope
        self._token: str | None = None
        self._expires_at = 0.0
        self._inflight: asyncio.Future[tuple[str, float]] | None = None
        self._unreachable_until = 0.0
        self._email: str | None = None

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    def invalidate(self) -> None:
        """Drive refused the token (401): fetch a new one on the next call."""
        self._token = None
        self._expires_at = 0.0

    async def token(self) -> str:
        if self._token is not None and self._clock() < self._expires_at - SKEW_S:
            return self._token
        if self._clock() < self._unreachable_until:
            raise DriveUnavailable(UNREACHABLE)
        task = self._inflight
        if task is None or task.done():
            task = asyncio.ensure_future(self._fetch())
            # nobody may be waiting when it ends (every caller timed out): read its outcome
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._inflight = task
        try:
            async with asyncio.timeout(self._deadline):
                value, lifetime = await asyncio.shield(task)
        except TimeoutError:
            log.warning("drive token: no answer in time")
            raise DriveUnavailable(SLOW) from None
        self._token, self._expires_at = value, self._clock() + lifetime
        return value

    async def _get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        try:
            async with self.http.stream(
                "GET", url, params=params, headers=HEADERS, timeout=HTTP_TIMEOUT
            ) as r:
                if r.status_code != 200:
                    log.warning("metadata server refused", extra={"status": r.status_code})
                    raise DriveUnavailable(NO_TOKEN)
                chunks: list[bytes] = []
                size = 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_ANSWER_BYTES:
                        raise DriveUnavailable(NO_TOKEN)
                    chunks.append(chunk)
                return b"".join(chunks)
        except (httpx.ConnectError, httpx.UnsupportedProtocol) as exc:
            self._unreachable_until = self._clock() + UNREACHABLE_TTL_S
            log.warning("metadata server unreachable", extra={"reason": type(exc).__name__})
            raise DriveUnavailable(UNREACHABLE) from None
        except httpx.HTTPError as exc:
            log.warning("metadata server error", extra={"reason": type(exc).__name__})
            raise DriveUnavailable(NO_TOKEN) from None

    async def _fetch(self) -> tuple[str, float]:
        raw = await self._get(TOKEN_URL, {"scopes": self._scope})
        return _parse_token(raw)

    async def email(self) -> str:
        """The service account's address (what the owner shares folders with)."""
        if self._email is not None:
            return self._email
        if self._clock() < self._unreachable_until:
            raise DriveUnavailable(UNREACHABLE)
        try:
            async with asyncio.timeout(self._deadline):
                raw = await self._get(EMAIL_URL)
        except TimeoutError:
            raise DriveUnavailable(SLOW) from None
        text = raw.decode("utf-8", "replace").strip().lower()
        if not _SA_EMAIL.fullmatch(text):
            log.warning("metadata server: unexpected account address")
            raise DriveUnavailable(NO_TOKEN)
        self._email = text
        return text


def _parse_token(raw: bytes) -> tuple[str, float]:
    try:
        data: Any = json.loads(raw)
    except ValueError:
        raise DriveUnavailable(NO_TOKEN) from None
    if not isinstance(data, dict):
        raise DriveUnavailable(NO_TOKEN)
    value, life = data.get("access_token"), data.get("expires_in")
    if not isinstance(value, str) or not _TOKEN_CHARS.fullmatch(value):
        raise DriveUnavailable(NO_TOKEN)
    if isinstance(life, bool) or not isinstance(life, int) or not 0 < life <= MAX_EXPIRES_S:
        raise DriveUnavailable(NO_TOKEN)
    return value, float(life)


__all__ = [
    "EMAIL_URL",
    "SKEW_S",
    "TOKEN_URL",
    "UNREACHABLE",
    "UNREACHABLE_TTL_S",
    "MetadataTokens",
]
