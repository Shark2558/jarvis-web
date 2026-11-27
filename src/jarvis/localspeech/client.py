# src/jarvis/localspeech/client.py
"""The laptop speech kit's client (R5.2 V2; I0 seams "The kit's API"): the protocol's
`KitClient` over httpx, for the cloud and for the call desk on the same laptop.

- `cloud_kit(url, key, ...)`: the cloud reaches the kit only at the owner's Tailscale **https**
  name (`https://<machine>.<tailnet>.ts.net[:port]`, http refused). The address passes R1's
  `jarvis.offline.config.check_url` before the first call (every address the name resolves to must
  be public), and every request goes through `PinnedTransport`: resolved again, refused unless
  every answer is public, connected to the address it just checked (DNS rebinding can't swap it),
  with the name kept as the Host header and the TLS server name.
- `loopback_kit(key, ...)`: the call desk on the laptop, at exactly `protocol.LOOPBACK_BASE`
  (`http://127.0.0.1:11436/v1`, the kit's gate); no other http address is ever used.

Every request carries `protocol.bearer(key)` (a key under 32 characters is refused before
anything is sent); bodies are the protocol's strict models as JSON, at most `BODY_MAX`. Redirects
are never followed and at most `REPLY_MAX` bytes are read. What the kit's answers become:

    2xx              the reply model (`parse_reply`: anything else is KitUnavailable("protocol"))
    401, 403         KitUnavailable("unauthorized")
    429, `busy`      KitUnavailable("busy")
    5xx              KitUnavailable("error")
    other 4xx        KitRefused(code) in this module's own words (the kit's text is never shown)
    3xx, unreadable  KitUnavailable("protocol")
    timeout          KitUnavailable("timeout")
    no connection    KitUnavailable("offline") (also a name that no longer resolves to public)

Never logged: the key, the laptop's name, audio, text or phrases (only the route, the status and
the reason). Kit-safe: the standard library, httpx, Pydantic, `protocol` and R1's
`jarvis.offline.config` (httpx and the standard library only), so the call desk can ship it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Final, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from jarvis.localspeech.protocol import (
    BODY_MAX,
    CLIP,
    DELETE,
    HEALTH,
    JOBS,
    KEY_MIN_CHARS,
    LOOPBACK_BASE,
    REPLY_MAX,
    RESULTS,
    SCORE,
    STT,
    TTS,
    WAKE_MODEL,
    WAKE_STATUS,
    WAKE_TRAIN,
    ClipIn,
    ClipStored,
    Deleted,
    DeleteIn,
    JobView,
    KitError,
    KitErrorBody,
    KitErrorCode,
    KitHealth,
    KitRefused,
    KitUnavailable,
    ResultsIn,
    ScoreIn,
    SessionHeard,
    SttRequest,
    SttResult,
    TtsRequest,
    TtsResult,
    UnavailableReason,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
    bearer,
    job_path,
    parse_reply,
)
from jarvis.offline.config import (
    PinnedTransport,
    Resolver,
    UrlRejected,
    check_url,
    system_resolver,
)

log = logging.getLogger(__name__)

HEALTH_TIMEOUT_S: Final = 3.0  # a health check never holds a voice turn long
TS_NET: Final = ".ts.net"
M = TypeVar("M", bound=BaseModel)
BaseSource = Callable[[], Awaitable[str]]

# The client's own words for a refusal (the kit's `detail` is never shown: it came over a network)
REFUSED_WORDS: Final[dict[KitErrorCode, str]] = {
    "not_found": "The laptop speech kit doesn't have that (yet).",
    "bad_request": "That request is not one the laptop speech kit understands.",
    "bad_audio": "The laptop speech kit couldn't use that recording.",
    "too_large": "That is too large for the laptop speech kit.",
    "unsupported_language": "The laptop speech kit has no engine for that language.",
    "job_failed": "That job on the laptop speech kit didn't finish.",
}
_UNAVAILABLE_CODES: Final[dict[str, UnavailableReason]] = {
    "unauthorized": "unauthorized",
    "busy": "busy",
    "engine_not_ready": "error",
    "internal": "error",
}


class _Empty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_key(key: SecretStr) -> SecretStr:
    if len(key.get_secret_value()) < KEY_MIN_CHARS:
        raise ValueError(f"the kit's key needs at least {KEY_MIN_CHARS} characters")
    return key


def _require_funnel_name(url: str) -> str:
    """https and a `*.ts.net` name, or ValueError; `check_url` applies the whole rule later."""
    text = url.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        raise ValueError("the kit is reached only at its Tailscale https address") from None
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or not host.endswith(TS_NET) or not text.isascii():
        raise ValueError("the kit is reached only at its Tailscale https address")
    return text


class _CheckedBase:
    """The cloud's base: R1's rule (`check_url`) once it passes, re-tried while it doesn't."""

    def __init__(self, url: str, resolver: Resolver) -> None:
        self._url = url
        self._resolver = resolver
        self._base: str | None = None

    async def __call__(self) -> str:
        if self._base is None:
            try:
                self._base = (await check_url(self._url, resolver=self._resolver)).base
            except UrlRejected:
                log.warning("local speech: the kit's address is not allowed now")
                raise KitUnavailable("offline") from None
        return self._base


async def _loopback() -> str:
    return LOOPBACK_BASE


def _refused(code: str) -> KitRefused:
    for known, words in REFUSED_WORDS.items():
        if known == code:
            return KitRefused(known, words)
    return KitRefused("bad_request", REFUSED_WORDS["bad_request"])


class HttpKit:
    """`KitClient` over httpx; build it with `cloud_kit` or `loopback_kit`. One connection pool,
    closed by `aclose`."""

    def __init__(
        self,
        *,
        base: BaseSource,
        key: SecretStr,
        transport: httpx.AsyncBaseTransport,
        timeout_s: float,
        where: str,
    ) -> None:
        self._base = base
        self._key = _require_key(key)
        self._transport = transport
        self.timeout_s = timeout_s
        self.health_timeout_s = min(HEALTH_TIMEOUT_S, timeout_s)
        self._where = where
        self._http: httpx.AsyncClient | None = None
        self._closed = False

    def __repr__(self) -> str:
        return f"HttpKit({self._where})"

    def _client(self) -> httpx.AsyncClient:
        if self._closed:
            raise httpx.ConnectError("the kit's client is closed")
        if self._http is None:
            self._http = httpx.AsyncClient(
                transport=self._transport, follow_redirects=False, timeout=self.timeout_s
            )
        return self._http

    async def aclose(self) -> None:
        """Close the pool (and its transport) once; a later call is KitUnavailable("offline")."""
        if self._closed:
            return
        self._closed = True
        http, self._http = self._http, None
        if http is not None:
            await http.aclose()
        else:
            await self._transport.aclose()

    # ---- one exchange ----------------------------------------------------------------------------
    async def _call(
        self,
        method: str,
        path: str,
        body: BaseModel | None,
        reply: type[M],
        *,
        route: str,
        timeout_s: float | None = None,
    ) -> M:
        raw = b"" if body is None else body.model_dump_json().encode()
        if len(raw) > BODY_MAX:
            raise _refused("too_large")
        headers = {**bearer(self._key.get_secret_value()), "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with asyncio.timeout(timeout_s or self.timeout_s):
                base = await self._base()
                status, data = await self._send(method, base + path, raw, headers)
        except KitError as exc:
            self._note(route, None, exc)
            raise
        except (TimeoutError, httpx.TimeoutException):
            self._note(route, None, KitUnavailable("timeout"))
            raise KitUnavailable("timeout") from None
        except (httpx.HTTPError, OSError):
            self._note(route, None, KitUnavailable("offline"))
            raise KitUnavailable("offline") from None
        try:
            return self._read(status, data, reply)
        except KitError as exc:
            self._note(route, status, exc)
            raise

    async def _send(
        self, method: str, url: str, raw: bytes, headers: dict[str, str]
    ) -> tuple[int, bytes]:
        async with self._client().stream(method, url, content=raw or None, headers=headers) as resp:
            if 300 <= resp.status_code < 400:  # never followed: the kit has no reason to move
                raise KitUnavailable("protocol")
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > REPLY_MAX:
                    raise KitUnavailable("protocol")
                chunks.append(chunk)
            return resp.status_code, b"".join(chunks)

    @staticmethod
    def _read(status: int, data: bytes, reply: type[M]) -> M:
        if 200 <= status < 300:
            return parse_reply(reply, data)
        if status in (401, 403):
            raise KitUnavailable("unauthorized")
        try:
            code: str | None = KitErrorBody.model_validate_json(data).error
        except ValidationError:
            code = None
        if status == 429 or code == "busy":
            raise KitUnavailable("busy")
        if status >= 500:
            raise KitUnavailable("error")
        if 400 <= status < 500 and code is not None:
            if code in _UNAVAILABLE_CODES:
                raise KitUnavailable(_UNAVAILABLE_CODES[code])
            raise _refused(code)
        raise KitUnavailable("protocol")  # a 4xx that isn't the kit's (an old gate, a proxy)

    @staticmethod
    def _note(route: str, status: int | None, exc: KitError) -> None:
        why = "error"
        if isinstance(exc, KitUnavailable):
            why = exc.reason
        elif isinstance(exc, KitRefused):
            why = exc.code
        log.info("local speech: %s failed", route, extra={"status": status, "why": why})

    # ---- KitClient -------------------------------------------------------------------------------
    async def health(self) -> KitHealth:
        return await self._call(
            "GET", HEALTH, None, KitHealth, route=HEALTH, timeout_s=self.health_timeout_s
        )

    async def stt(self, req: SttRequest) -> SttResult:
        return await self._call("POST", STT, req, SttResult, route=STT)

    async def tts(self, req: TtsRequest) -> TtsResult:
        return await self._call("POST", TTS, req, TtsResult, route=TTS)

    async def put_clip(self, clip: ClipIn) -> ClipStored:
        return await self._call("POST", CLIP, clip, ClipStored, route=CLIP)

    async def score(self, req: ScoreIn) -> JobView:
        return await self._call("POST", SCORE, req, JobView, route=SCORE)

    async def results(self, session_id: str) -> SessionHeard:
        try:
            body = ResultsIn(session_id=session_id)
        except ValidationError:
            raise _refused("bad_request") from None
        return await self._call("POST", RESULTS, body, SessionHeard, route=RESULTS)

    async def delete(self, req: DeleteIn) -> Deleted:
        return await self._call("POST", DELETE, req, Deleted, route=DELETE)

    async def job(self, job_id: str) -> JobView:
        try:
            path = job_path(job_id)
        except ValueError:
            raise _refused("bad_request") from None
        return await self._call("GET", path, None, JobView, route=JOBS)

    async def wakeword_train(self, req: WakeTrainIn) -> JobView:
        return await self._call("POST", WAKE_TRAIN, req, JobView, route=WAKE_TRAIN)

    async def wakeword_status(self) -> WakeStatus:
        return await self._call("POST", WAKE_STATUS, _Empty(), WakeStatus, route=WAKE_STATUS)

    async def wakeword_model(self, artifact: WakeArtifact) -> WakeModel:
        body = WakeModelIn(artifact=artifact)
        return await self._call("POST", WAKE_MODEL, body, WakeModel, route=WAKE_MODEL)


def cloud_kit(
    url: str,
    key: SecretStr,
    *,
    timeout_s: float,
    resolver: Resolver = system_resolver,
    inner: httpx.AsyncBaseTransport | None = None,
) -> HttpKit:
    """The cloud's client for the kit at the owner's Tailscale https address (ValueError for
    anything else, or a short key)."""
    checked = _CheckedBase(_require_funnel_name(url), resolver)
    return HttpKit(
        base=checked,
        key=key,
        transport=PinnedTransport(resolver, inner=inner),
        timeout_s=timeout_s,
        where="tailscale",
    )


def loopback_kit(
    key: SecretStr, *, timeout_s: float, inner: httpx.AsyncBaseTransport | None = None
) -> HttpKit:
    """The call desk's client for the kit's gate on the same laptop (`LOOPBACK_BASE` only)."""
    return HttpKit(
        base=_loopback,
        key=key,
        transport=inner if inner is not None else httpx.AsyncHTTPTransport(),
        timeout_s=timeout_s,
        where="loopback",
    )


__all__ = ["HEALTH_TIMEOUT_S", "REFUSED_WORDS", "HttpKit", "cloud_kit", "loopback_kit"]
