# src/jarvis/home/webhook.py
"""`POST /home/webhook`: signed events from the bridge (R3 D5; cross-cutting security).

Order of checks, each before anything is parsed, every failure a BARE answer (no body, no header),
logged by check name only and never audited (a flood must not fill the audit chain):

0. <= 120 requests a minute per network client (429), before anything is read
1. body <= 128 KB (413), read with a cap
2. header shape, home id known (401 for both: no oracle)
3. |now - t| <= 60 s, nonce not seen in 5 minutes, `hmac.compare_digest` over the UP key, and only
   then the nonce is remembered (`signing.verify`)
4. <= `per_minute` verified messages a minute per home (429)
5. strict parsing (`ports.parse_event`): 413 too large, 422 anything else wrong
6. event ids are claimed create-only, so a replay or a bridge retry is a no-op 200
7. dispatch to every registered `HomeEventHandler` that takes the type; a handler that fails gives
   the claim back and answers 503, so the bridge's retry is not lost

The answer is signed with the DOWN key and bound to the request, so the bridge trusts the state it
gets back. A heartbeat's answer carries the cloud's `BridgeState` (the laptop catches up when it
wakes). Nothing in the body is ever logged: it may carry an opted-in snapshot (D12).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from fastapi import Request
from fastapi.responses import Response

from jarvis.api.ratelimit import RateLimiter, client_key
from jarvis.home import signing
from jarvis.home.ports import (
    MAX_WEBHOOK_BYTES,
    WEBHOOK_PATH,
    BridgeState,
    EventRejected,
    HomeEventHandler,
    StateSource,
    parse_event,
)
from jarvis.home.store import HomeStore, HomeStoreUnavailable
from jarvis.logging import get_logger

log = get_logger(__name__)

CLIENT_PER_MINUTE = 120  # per network client, before the home id is even looked up (review H1)


def bare(status: int) -> Response:
    return Response(status_code=status, headers={"Cache-Control": "no-store"})


async def read_capped(request: Request, cap: int) -> bytes | None:
    """The body, or None if it is over `cap` (never reads past it)."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > cap):
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


class HomeWebhook:
    def __init__(
        self,
        store: HomeStore,
        handlers: Sequence[HomeEventHandler],
        state_sources: Sequence[StateSource] = (),
        *,
        clock: Callable[[], float],
        per_minute: int = 60,
        client_per_minute: int = CLIENT_PER_MINUTE,
    ) -> None:
        self._store = store
        self._handlers = tuple(handlers)
        self._sources = tuple(state_sources)
        self._clock = clock
        self._nonces = signing.NonceCache()
        self._limit = RateLimiter(per_minute, now=clock)
        self._client_limit = RateLimiter(client_per_minute, now=clock)

    async def _state(self, uid: str) -> dict[str, object]:
        merged = BridgeState()
        for source in self._sources:
            try:
                merged = merged.merged(await source.state_part(uid))
            except Exception as exc:  # noqa: BLE001 - one part failing must not stop the rest
                log.error("home state part failed", extra={"error": type(exc).__name__})
        return merged.model_dump(mode="json", exclude_none=True)

    async def receive(self, request: Request) -> Response:
        # Before the body, the home id or any store read: a stranger's flood costs nothing here.
        if not self._client_limit.allow(client_key(request))[0]:
            return bare(429)
        body = await read_capped(request, MAX_WEBHOOK_BYTES)
        if body is None:
            return bare(413)
        try:
            signed = signing.parse(request.headers.get(signing.HEADER))
            found = await self._store.find(signed.home_id)
            if found is None:
                raise signing.SignatureError("shape")
            uid, record = found
            signing.verify(
                signed,
                record.keys(),
                "up",
                method="POST",
                target=WEBHOOK_PATH,
                body=body,
                now=self._clock(),
                nonces=self._nonces,
            )
        except signing.SignatureError as exc:
            log.info("home webhook refused", extra={"check": exc.check})
            return bare(401)
        except HomeStoreUnavailable:
            return bare(503)
        allowed, _ = self._limit.allow(signed.home_id)
        if not allowed:
            return bare(429)
        try:
            event = parse_event(body)
        except EventRejected as exc:
            log.info("home webhook event rejected", extra={"reason": exc.code})
            return bare(413 if exc.code == "too_large" else 422)
        try:
            data = await self._dispatch(uid, event)
        except HomeStoreUnavailable:
            return bare(503)
        except Exception as exc:  # noqa: BLE001 - give the claim back so the retry counts
            log.error("home event handler failed", extra={"error": type(exc).__name__})
            if event.type != "heartbeat":
                await self._store.release(uid, event.id)
            return bare(503)
        return self._answer(record.keys(), record.home_id, signed.nonce, data)

    async def _dispatch(self, uid: str, event: object) -> dict[str, object]:
        etype = event.type  # type: ignore[attr-defined]
        if etype != "heartbeat" and not await self._store.claim(uid, event.id):  # type: ignore[attr-defined]
            return {}
        for handler in self._handlers:
            if etype in handler.handles:
                await handler.handle(uid, event)  # type: ignore[arg-type]
        return {"state": await self._state(uid)} if etype == "heartbeat" else {}

    def _answer(
        self, keys: signing.HomeKeys, home_id: str, nonce: str, data: dict[str, object]
    ) -> Response:
        raw = json.dumps(data, separators=(",", ":")).encode()
        header = signing.sign_response(
            keys,
            "down",
            home_id=home_id,
            request_nonce=nonce,
            status=200,
            method="POST",
            target=WEBHOOK_PATH,
            body=raw,
            now=self._clock(),
        )
        return Response(
            content=raw,
            media_type="application/json",
            headers={signing.HEADER: header, "Cache-Control": "no-store"},
        )


__all__ = ["HomeWebhook", "bare", "read_capped"]
