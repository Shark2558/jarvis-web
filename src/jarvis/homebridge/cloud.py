# src/jarvis/homebridge/cloud.py
"""The bridge's way to JARVIS (R3 D4, D5, D9). Ships in the home kit.

- Every event is one signed `POST /home/webhook` (UP key). The answer must be signed with the DOWN
  key and bound to this request, or it is ignored (the bridge only trusts the arm state it gets
  back from the real cloud).
- A failed detection is retried at 2, 5, 15 and 30 seconds with the same event id (the cloud
  claims ids, so a retry is a no-op), then given up (logged, never with the body). The outbox
  holds at most 100 events and none older than 60 seconds; it lives in memory (a restart drops
  what was waiting: an alert that old is no use).
- Clock: the cloud's `Date` header (TLS-authenticated) corrects the bridge's offset, so WSL's clock
  drifting after Windows sleeps can't make every message look stale. A 401 with a skewed clock is
  retried once.
- If the cloud answers 401 three heartbeats in a row it no longer knows this home (it was unlinked
  or re-linked): `on_unlinked` fires, the bridge drops its secret and stops sending detections.
- Nothing here logs a body, a snapshot or a signature.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from jarvis.home import signing
from jarvis.home.ports import (
    LINK_PATH,
    WEBHOOK_PATH,
    Ack,
    BridgeState,
    Detection,
    FaceSeen,
    Hazard,
    Heartbeat,
    Package,
)
from jarvis.homebridge.config import BRIDGE_VERSION, BridgeConfig
from jarvis.homebridge.state import BridgeStore

log = logging.getLogger(__name__)

Event = Heartbeat | Detection | FaceSeen | Package | Hazard | Ack
RETRY_DELAYS_S = (2.0, 5.0, 15.0, 30.0)
OUTBOX_MAX = 100
OUTBOX_MAX_AGE_S = 60.0
POST_TIMEOUT_S = 10.0
UNLINKED_AFTER = 3
MAX_REPLY_BYTES = 256 * 1024
_SKEW_FIX_S = 20.0


class LinkFailed(Exception):
    """Linking didn't work. `reason` is plain words for the setup script."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CloudLink:
    def __init__(
        self,
        cfg: BridgeConfig,
        store: BridgeStore,
        auth: Any,
        *,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
        on_unlinked: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._auth = auth
        self._http = http or httpx.AsyncClient(timeout=POST_TIMEOUT_S, follow_redirects=False)
        self._sleep = sleep
        self._clock = clock
        self._on_unlinked = on_unlinked
        self._pending: set[asyncio.Task[None]] = set()
        self._refused = 0
        self.unlinked = False

    async def aclose(self) -> None:
        for task in tuple(self._pending):
            task.cancel()
        await self._http.aclose()

    # ---- linking -------------------------------------------------------------------------------

    async def link(self, code: str, bridge_url: str, secret: bytes) -> str:
        """POST /home/link. On success the secret is saved and the home id returned."""
        self._store.set_pending(secret)
        body = {
            "code": code,
            "bridge_url": bridge_url,
            "bridge_version": BRIDGE_VERSION,
            "link_secret": _b64(secret),
        }
        try:
            resp = await self._http.post(self._cfg.jarvis_url + LINK_PATH, json=body)
        except httpx.HTTPError:
            raise LinkFailed("Couldn't reach JARVIS. Check this computer's internet.") from None
        if resp.status_code == 401:
            raise LinkFailed("That code is wrong, used or out of time. Make a new one in JARVIS.")
        if resp.status_code == 409:
            raise LinkFailed("JARVIS couldn't reach your laptop yet (Funnel can take 10 minutes).")
        if resp.status_code == 429:
            raise LinkFailed("Too many tries. Wait a minute.")
        if resp.status_code == 422:
            raise LinkFailed("JARVIS didn't accept the laptop address.")
        if resp.status_code != 201:
            raise LinkFailed("JARVIS couldn't link right now.")
        try:
            data = resp.json()
            seed = _unb64(data["seed"])
            home_id = data["home_id"]
            signing.derive_keys(seed)
        except (ValueError, KeyError, TypeError):
            raise LinkFailed("JARVIS gave an answer the bridge couldn't read.") from None
        self._store.save_link(home_id, seed)
        self.unlinked = False
        return str(home_id)

    # ---- events --------------------------------------------------------------------------------

    async def post_event(self, event: Event) -> bool:
        """One attempt now. A detection that fails is retried in the background (2, 5, 15, 30 s)."""
        if self.unlinked:
            return False
        sent = await self._attempt(event)
        if sent is True or sent is None:
            return sent is True
        if event.type == "heartbeat":  # the next heartbeat is the retry
            return False
        if len(self._pending) >= OUTBOX_MAX:
            log.warning("bridge outbox full: an event was dropped")
            return False
        task = asyncio.create_task(self._retry(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return False

    async def _retry(self, event: Event) -> None:
        started = self._clock()
        for delay in RETRY_DELAYS_S:
            await self._sleep(delay)
            if self._clock() - started > OUTBOX_MAX_AGE_S or self.unlinked:
                break
            if await self._attempt(event) is not False:
                return
        log.warning("an event could not be delivered and was dropped", extra={"type": event.type})

    async def heartbeat(self, event: Heartbeat) -> BridgeState | None:
        """Post a heartbeat; the cloud's answer carries its state (None if nothing usable)."""
        reply = await self._exchange(event)
        if not isinstance(reply, dict):
            return None
        state = reply.get("state")
        if not isinstance(state, dict):
            return None
        try:
            return BridgeState.model_validate(state)
        except ValueError:
            log.warning("the cloud's state didn't fit; ignored")
            return None

    async def _attempt(self, event: Event) -> bool | None:
        """True delivered, None refused for good (don't retry), False try again."""
        reply = await self._exchange(event)
        if reply is _REFUSED:
            return None
        return reply is not None

    async def _exchange(self, event: Event, *, again: bool = True) -> object | None:
        linked = self._store.linked()
        if linked is None:
            return _REFUSED
        raw = event.model_dump_json(exclude_none=True).encode()
        header = signing.sign(
            linked.keys,
            "up",
            home_id=linked.home_id,
            method="POST",
            target=WEBHOOK_PATH,
            body=raw,
            now=self._auth.now(),
        )
        nonce = signing.parse(header).nonce
        try:
            resp = await self._http.post(
                self._cfg.jarvis_url + WEBHOOK_PATH,
                content=raw,
                headers={signing.HEADER: header, "content-type": "application/json"},
            )
        except httpx.HTTPError:
            return None
        corrected = self._learn_clock(resp)
        status = resp.status_code
        if status == 401:
            if corrected and again:  # our clock was off: now fixed, try once more
                return await self._exchange(event, again=False)
            return self._unauthorised(event)
        if status in (413, 422):
            log.warning("the cloud refused an event for good", extra={"status": status})
            return _REFUSED
        if status != 200 or len(resp.content) > MAX_REPLY_BYTES:
            return None
        try:
            signing.verify_response(
                resp.headers.get(signing.HEADER),
                linked.keys,
                "down",
                home_id=linked.home_id,
                request_nonce=nonce,
                status=status,
                method="POST",
                target=WEBHOOK_PATH,
                body=resp.content,
                now=self._auth.now(),
            )
            data = json.loads(resp.content) if resp.content else {}
        except (signing.SignatureError, ValueError):
            log.warning("an unsigned answer from the cloud was ignored")
            return None
        self._refused = 0
        return data if isinstance(data, dict) else None

    def _unauthorised(self, event: Event) -> object | None:
        self._refused += 1
        if event.type == "heartbeat" and self._refused >= UNLINKED_AFTER:
            self.unlinked = True
            self._store.forget_link()
            log.warning("the cloud no longer knows this home: unlinked")
            if self._on_unlinked is not None:
                self._on_unlinked()
        return None

    def _learn_clock(self, resp: httpx.Response) -> bool:
        """Correct the clock from the cloud's Date header if clearly off (True = changed)."""
        raw = resp.headers.get("date")
        if not raw:
            return False
        try:
            server = parsedate_to_datetime(raw).timestamp()
        except (TypeError, ValueError):
            return False
        off = server - self._clock()
        if abs(off) <= _SKEW_FIX_S and self._auth.offset_s == 0.0:
            return False
        new = off if abs(off) > 2.0 else 0.0
        changed = abs(new - self._auth.offset_s) > 2.0
        self._auth.offset_s = new
        return bool(changed)


_REFUSED = object()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


__all__ = ["CloudLink", "LinkFailed"]
