# src/jarvis/integrations/google_key.py
"""JARVIS's own server-side Google API key (slice 12 D2; Layer 6): one door for every call made
with it — Places API (New), Routes API and YouTube Data API v3. Not the owner's OAuth link
(`jarvis.integrations.google`): this key identifies the deployment's Cloud project and is never
sent to the browser.

The key travels only in the `X-Goog-Api-Key` header, never in a URL (Google's system parameter,
docs.cloud.google.com/apis/docs/system-parameters, checked 2026-11-03; every API here accepts it),
and only to the hosts in `ALLOWED` over https. Redirects are never followed (a redirect could carry
the header elsewhere). Every call has an overall deadline; the answer is read in a stream and
refused past `MAX_RESPONSE_BYTES`; it must be a JSON object (the callers validate each field).

Errors carry our own plain words, never Google's text. Each says whether the call clearly never
reached Google (`clear`: the connection was refused before a byte was sent — the allowance ledger
gives the reservation back) and whether Google says the quota is gone (`exhausted`: the ledger
latches the period as used up). Every answer from Google keeps its reservation, error or not:
YouTube counts even invalid requests against the quota
(developers.google.com/youtube/v3/determine_quota_cost: "All API requests, including invalid
requests, incur a quota cost of at least one point"), and Maps billing for an error answer is not
documented (checked 2026-11-03), so the safe reading is that it counts. A timeout or a dropped
answer counts too: Google may have done the work.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.config import Settings
from jarvis.logging import get_logger

log = get_logger(__name__)

ALLOWED = frozenset(
    {
        ("places.googleapis.com", "/v1/"),
        ("routes.googleapis.com", "/directions/v2:"),
        ("www.googleapis.com", "/youtube/v3/"),
    }
)
DEADLINE_S = 15.0  # the whole call, connect to last byte
HTTP_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
MAX_RESPONSE_BYTES = 1_000_000

# Google's machine-readable reasons (errors[].reason, details[].reason), never its message text
EXHAUSTED = frozenset(
    {"quotaExceeded", "dailyLimitExceeded", "RESOURCE_EXHAUSTED", "rateLimitExceeded_daily"}
)
SERVICE_OFF = frozenset(
    {"SERVICE_DISABLED", "accessNotConfigured", "API_KEY_SERVICE_BLOCKED", "API_KEY_API_BLOCKED"}
)
KEY_REFUSED = frozenset(
    {"API_KEY_INVALID", "keyInvalid", "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED"}
)

INVALID = "Google rejected the request as invalid."
KEY_BAD = "Google refused JARVIS's API key (check the jarvis-google-api-key secret)."
OFF = (
    "That Google service is not switched on for your JARVIS project yet: re-run deploy/cloudrun.sh."
)
USED_UP = "Google says today's or this month's free allowance for that service is used up."
BUSY = "Google is busy right now; try again in a minute."
DOWN = "Google's service is temporarily unavailable; try again shortly."
SLOW = "Google took too long to answer; try again shortly."
UNREACHABLE = "Could not reach Google; try again shortly."
UNREADABLE = "Google returned an unreadable response."
TOO_LARGE = "Google's answer was too large to use."


class KeyAPIError(RuntimeError):
    """A call with the server key failed. The message is plain English, free of vendor text.
    `clear`: the call never reached Google (give its reservation back). `exhausted`: Google says
    the quota is gone (latch the period)."""

    def __init__(self, message: str, *, clear: bool = False, exhausted: bool = False) -> None:
        super().__init__(message)
        self.clear = clear
        self.exhausted = exhausted


def _reasons(raw: bytes) -> set[str]:
    try:
        err = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        return set()
    if not isinstance(err, dict):
        return set()
    found: set[str] = set()
    for key in ("errors", "details"):
        items = err.get(key)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                found.add(item["reason"][:64])
    status = err.get("status")
    if isinstance(status, str):
        found.add(status[:64])
    return found


def _error(status: int, raw: bytes) -> KeyAPIError:
    """Google answered: the reservation stands (see the module docstring)."""
    reasons = _reasons(raw)
    if reasons & EXHAUSTED:
        return KeyAPIError(USED_UP, exhausted=True)
    if reasons & SERVICE_OFF:
        return KeyAPIError(OFF)
    if reasons & KEY_REFUSED or status in (401, 403):
        return KeyAPIError(KEY_BAD)
    if status in (400, 404, 411, 413):
        return KeyAPIError(INVALID)
    if status == 429:
        return KeyAPIError(BUSY)
    if status >= 500:
        return KeyAPIError(DOWN)
    return KeyAPIError(f"Google returned an unexpected status ({status}).")


def _allowed(url: str) -> bool:
    try:
        u = httpx.URL(url)
    except httpx.InvalidURL:
        return False
    if u.scheme != "https" or u.userinfo or u.port is not None:
        return False
    return any(u.host == host and u.path.startswith(prefix) for host, prefix in ALLOWED)


class GoogleKeyClient:
    """Per deployment: one key, one httpx client (redirects off)."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        http: httpx.AsyncClient | None = None,
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self._key = api_key
        self._own = http is None
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._deadline = deadline_s

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    async def get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._call("GET", url, params=params)

    async def post(self, url: str, body: dict[str, Any], *, field_mask: str) -> dict[str, Any]:
        return await self._call("POST", url, body=body, field_mask=field_mask)

    async def _call(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        field_mask: str | None = None,
    ) -> dict[str, Any]:
        if not _allowed(url):
            raise ValueError("not an allow-listed Google API address")
        headers = {  # stripped: a Secret Manager value often ends with a newline
            "X-Goog-Api-Key": self._key.get_secret_value().strip(),
            "Accept": "application/json",
        }
        if field_mask is not None:
            headers["X-Goog-FieldMask"] = field_mask
        path = httpx.URL(url).path
        try:
            async with asyncio.timeout(self._deadline):
                async with self.http.stream(
                    method,
                    url,
                    params=params,
                    json=body,
                    headers=headers,
                    timeout=HTTP_TIMEOUT,
                    follow_redirects=False,
                ) as r:
                    raw = await _read_capped(r)
                    status = r.status_code
        except TimeoutError as exc:
            raise KeyAPIError(SLOW) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.UnsupportedProtocol) as exc:
            log.warning("google key api unreachable", extra={"reason": type(exc).__name__})
            raise KeyAPIError(UNREACHABLE, clear=True) from exc  # nothing reached Google
        except httpx.HTTPError as exc:
            log.warning("google key api failed", extra={"reason": type(exc).__name__})
            raise KeyAPIError(UNREACHABLE) from exc
        if status != 200:
            err = _error(status, raw)
            log.warning(
                "google key api error",
                extra={"status": status, "path": path, "exhausted": err.exhausted},
            )
            raise err
        try:
            data = json.loads(raw, parse_constant=_no_constant)
        except ValueError as exc:
            raise KeyAPIError(UNREADABLE) from exc
        if not isinstance(data, dict):
            raise KeyAPIError(UNREADABLE)
        return data


def _no_constant(_: str) -> Any:
    raise ValueError("NaN / Infinity are not JSON")


async def _read_capped(r: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in r.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise KeyAPIError(TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def google_key_configured(s: Settings) -> bool:
    key = s.google_api_key.get_secret_value().strip() if s.google_api_key else ""
    return bool(key)


def build_google_key_client(
    s: Settings, *, http: httpx.AsyncClient | None = None
) -> GoogleKeyClient | None:
    """None without a key: the Maps and YouTube tools are then not registered."""
    if not google_key_configured(s):
        return None
    assert s.google_api_key is not None
    return GoogleKeyClient(s.google_api_key, http=http)


__all__ = [
    "ALLOWED",
    "MAX_RESPONSE_BYTES",
    "GoogleKeyClient",
    "KeyAPIError",
    "build_google_key_client",
    "google_key_configured",
]
