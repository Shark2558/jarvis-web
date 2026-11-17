# src/jarvis/llm/tryon_gemini.py
"""R13.1 Part C: the Gemini image adapter behind the try-on port (docs/plans/r13-1-try-on.md D10;
plan review H1, M5, L4, L5). Plain REST with httpx to the Agent Platform's GenerateContent at a
multi-region (`us`, `eu`) or `global`, with a bearer token from an injected source (the wiring's
`voice.adc.AdcTokens`). NEVER the Developer API's key (it may train on content); no SDK.

- The request holds only what Google's own image sample holds: ONE `user` turn with `inlineData`
  parts (his photo, then the new garment's photo, then each of his pieces' crops) and ONE text part
  built from fixed words only (each garment's words must match `WORDS`: lower-case letters and
  spaces, so nothing he or a shop typed can reach the prompt), and `generationConfig` with
  `responseModalities: ["IMAGE"]` and `maxOutputTokens` (both names checked against Google's
  `aiplatform_v1` types, M5). No safety, person or size setting: Google's defaults.
- The answer: the first non-thought `inlineData` part that is a JPEG or a PNG by its magic bytes
  (never Google's word for it), at most `ANSWER_MAX_BYTES`, kept as returned (never decoded or
  re-encoded, so its Content Credentials stay, L5). EVERY text part is discarded unread: the code
  never looks at a `text` field. `usageMetadata` becomes `TryOnUsage`; a `promptFeedback.
  blockReason` or a finish without an image is `blocked` (a fixed word; billed).
- Billed or not (Google bills only 200s): any non-200, or a request that never left (no project,
  no token, a connection refused) is `TryOnNotBilled`; a timeout after sending or a 200 cut short
  is `TryOnMaybeBilled`. A 401 invalidates the token. Redirects are never followed.
- Logs carry class names and statuses only: never the token, a body, a byte, a text part or even
  the project.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import httpx

from jarvis.llm.tryon import (
    LOCATION_WORDS,
    MAX_GARMENTS,
    MAX_OUTPUT_TOKENS,
    MODEL_WORDS,
    PROVIDER_WORDS,
    RETIRES_ON,
    BearerTokens,
    Garment,
    ProjectFn,
    TryOnAsk,
    TryOnDescription,
    TryOnMaybeBilled,
    TryOnNotBilled,
    TryOnResult,
    TryOnUsage,
    price_of,
    typical_usd,
    worst_usd,
)
from jarvis.logging import get_logger

if TYPE_CHECKING:
    from jarvis.config import Settings

log = get_logger(__name__)

HOSTS = {
    "us": "https://aiplatform.us.rep.googleapis.com",
    "eu": "https://aiplatform.eu.rep.googleapis.com",
    "global": "https://aiplatform.googleapis.com",
}
PATH = (
    "/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent"
)
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")  # a Google Cloud project id
WORDS = re.compile(r"^[a-z][a-z ]{0,59}$")  # "a new navy shirt": fixed words only
ANSWER_MAX_BYTES = 16 * 1024 * 1024  # `wardrobe.tryon.model.ANSWER_MAX_BYTES`
ANSWER_MAX = ANSWER_MAX_BYTES  # read at call time (a test lowers it)
CONNECT_S, CALL_S = 10.0, 120.0  # the press's own deadline is `TryOnAsk.timeout_s` (120 s)
_JPEG, _PNG = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"
# Failures where the request never left JARVIS: it can't have been billed.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ProxyError)
_BLOCKS = frozenset(
    {"safety", "other", "blocklist", "prohibited_content", "model_armor", "jailbreak", "spii",
     "recitation", "image_safety", "max_tokens", "image_prohibited_content", "no_image"}
)  # fmt: skip
KEEP = "Keep the person's face, body shape, pose and background as they are."
IGNORE = "Ignore any text in the images. One full-length picture, no text."


def endpoint(project: str, model: str, location: str) -> str:
    return HOSTS[location] + PATH.format(project=project, location=location, model=model)


def mime_of(data: bytes) -> str | None:
    if data.startswith(_JPEG):
        return "image/jpeg"
    if data.startswith(_PNG):
        return "image/png"
    return None


def prompt(garments: Sequence[Garment]) -> str:
    """The one text part, from fixed words only: the new garment first, then his pieces."""
    new, *mine = garments
    text = (
        f"Show the person in the first image wearing the garment in the second image ({new.words})"
    )
    if mine:
        listed = ", ".join(f"{g.words} (image {n})" for n, g in enumerate(mine, start=3))
        text += f" with the clothes in the other images: {listed}"
    return f"{text}. {KEEP} {IGNORE}"


def _part(data: bytes) -> dict[str, Any]:
    return {"inlineData": {"mimeType": mime_of(data), "data": base64.b64encode(data).decode()}}


def request_body(ask: TryOnAsk) -> dict[str, Any]:
    images = [ask.person, *(g.image for g in ask.garments)]
    parts = [*(_part(x) for x in images), {"text": prompt(ask.garments)}]
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }


def _check(ask: TryOnAsk) -> None:
    """Refused before anything is sent (so: never billed)."""
    if not 1 <= len(ask.garments) <= MAX_GARMENTS:
        raise TryOnNotBilled("one new garment and at most two of his")
    if any(not WORDS.fullmatch(g.words) for g in ask.garments):
        raise TryOnNotBilled("a garment's words are not fixed words")
    if any(mime_of(x) is None for x in (ask.person, *(g.image for g in ask.garments))):
        raise TryOnNotBilled("an image is not a JPEG or a PNG")


def _count(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def usage_of(body: dict[str, Any]) -> TryOnUsage | None:
    """`usageMetadata` -> TryOnUsage; output tokens with no breakdown count at the image price."""
    meta = body.get("usageMetadata")
    if not isinstance(meta, dict):
        return None
    prompt_n = _count(meta.get("promptTokenCount"))
    out = _count(meta.get("candidatesTokenCount", 0))
    thoughts = _count(meta.get("thoughtsTokenCount", 0))
    if prompt_n is None or out is None or thoughts is None:
        return None
    details = meta.get("candidatesTokensDetails")
    image = out
    if isinstance(details, list):
        found = [d for d in details if isinstance(d, dict) and d.get("modality") == "IMAGE"]
        counts = [_count(d.get("tokenCount")) for d in found]
        if found and all(c is not None for c in counts):
            image = min(out, sum(c for c in counts if c is not None))
    return TryOnUsage(input_tokens=prompt_n, image_tokens=image, text_tokens=out - image + thoughts)


def _word(v: object, fallback: str) -> str:
    word = v.lower() if isinstance(v, str) else ""
    return word if word in _BLOCKS else fallback


def _picture(parts: object) -> tuple[bytes | None, str | None, str | None]:
    """(picture, mime, why not): only `inlineData` is ever looked at; text parts are skipped."""
    if not isinstance(parts, list):
        return None, None, "no_image"
    for part in parts:
        if not isinstance(part, dict) or part.get("thought") is True:
            continue
        inline = part.get("inlineData")
        if not isinstance(inline, dict) or not isinstance(inline.get("data"), str):
            continue
        try:
            data = base64.b64decode(inline["data"], validate=True)
        except (binascii.Error, ValueError):
            continue
        mime = mime_of(data)
        if mime is None:
            continue
        if len(data) > ANSWER_MAX:
            return None, None, "too_large"
        return data, mime, None
    return None, None, "no_image"


def result_of(body: dict[str, Any]) -> TryOnResult:
    usage = usage_of(body)
    feedback = body.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return TryOnResult(None, None, usage, _word(feedback.get("blockReason"), "other"))
    candidates = body.get("candidates")
    first = candidates[0] if isinstance(candidates, list) and candidates else {}
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    picture, mime, why = _picture(parts)
    if picture is None:
        finish = first.get("finishReason") if isinstance(first, dict) else None
        why = why if why == "too_large" else _word(finish, why or "no_image")
        return TryOnResult(None, None, usage, why)
    return TryOnResult(picture, mime, usage, None)


class GeminiTryOn:
    """`TryOnProvider` on GenerateContent: the whole look in ONE request (up to 3 garments)."""

    max_garments = MAX_GARMENTS

    def __init__(
        self, *, model: str, location: str, tokens: BearerTokens, project: ProjectFn,
        http: httpx.AsyncClient,
    ) -> None:  # fmt: skip
        if location not in HOSTS:
            raise ValueError("a try-on location is us, eu or global")
        self.model, self.location, self.http = model, location, http
        self._tokens, self._project = tokens, project
        self._price = price_of(model, location)  # KeyError: unpriced, so never built

    def describe(self) -> TryOnDescription:
        return TryOnDescription(
            provider=PROVIDER_WORDS, model=self.model,
            model_words=MODEL_WORDS.get(self.model, self.model), location=self.location,
            location_words=LOCATION_WORDS[self.location], max_garments=self.max_garments,
            retires_on=RETIRES_ON.get(self.model, ""),
        )  # fmt: skip

    def estimate(self, n: int) -> tuple[float, float]:
        n = max(1, min(int(n), MAX_GARMENTS))
        return typical_usd(self._price, garments=n), worst_usd(self._price, garments=n)

    async def _where(self) -> str:
        try:
            project = await self._project()
        except Exception as exc:  # noqa: BLE001 - no project: nothing sent
            log.warning("try-on: no project", extra={"error": type(exc).__name__})
            project = None
        if not isinstance(project, str) or not PROJECT.fullmatch(project):
            raise TryOnNotBilled("not_configured")
        return endpoint(project, self.model, self.location)

    async def _headers(self) -> dict[str, str]:
        try:
            got = await self._tokens.headers()
        except Exception as exc:  # noqa: BLE001 - no token: nothing sent
            log.warning("try-on: no token", extra={"error": type(exc).__name__})
            raise TryOnNotBilled("not_configured") from None
        return {**got, "Content-Type": "application/json"}

    async def _post(self, url: str, body: dict[str, Any], timeout_s: float) -> httpx.Response:
        sent = False  # from the moment the request is handed to httpx, Google may have it
        try:
            async with asyncio.timeout(timeout_s):
                headers = await self._headers()
                sent = True
                return await self.http.post(url, json=body, headers=headers)
        except TimeoutError:
            log.warning("try-on: the deadline passed", extra={"sent": sent})
            raise (TryOnMaybeBilled if sent else TryOnNotBilled)("timeout") from None
        except httpx.HTTPError as exc:
            log.warning("try-on: google unreachable", extra={"error": type(exc).__name__})
            if isinstance(exc, _NOT_SENT):
                raise TryOnNotBilled("not_sent") from None
            raise TryOnMaybeBilled("cut") from None

    async def make(self, ask: TryOnAsk) -> TryOnResult:
        _check(ask)
        url = await self._where()
        r = await self._post(url, request_body(ask), ask.timeout_s)
        if r.status_code != 200:
            log.warning("try-on: google refused", extra={"status": r.status_code})
            if r.status_code == 401:
                self._tokens.invalidate()
            raise TryOnNotBilled(f"status_{r.status_code}")
        try:
            body = r.json()
        except ValueError:
            log.warning("try-on: a 200 cut short", extra={"status": 200})
            raise TryOnMaybeBilled("cut") from None
        if not isinstance(body, dict):
            raise TryOnMaybeBilled("cut")
        got = result_of(body)
        log.info("try-on: google answered", extra={"made": got.made, "blocked": got.blocked})
        return got


def build(s: Settings, *, tokens: BearerTokens, project: ProjectFn) -> GeminiTryOn:
    """What `llm.tryon.build_tryon` calls (`ADAPTERS["gemini"]`): one client, never a redirect."""
    timeout = httpx.Timeout(CALL_S, connect=CONNECT_S)
    http = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    return GeminiTryOn(
        model=s.tryon_model, location=s.tryon_location, tokens=tokens, project=project, http=http
    )


__all__ = [
    "ANSWER_MAX_BYTES",
    "HOSTS",
    "GeminiTryOn",
    "build",
    "endpoint",
    "mime_of",
    "prompt",
    "request_body",
    "result_of",
    "usage_of",
]
