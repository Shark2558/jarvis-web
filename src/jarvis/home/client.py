# src/jarvis/home/client.py
"""Cloud -> home calls (R3 D6; Layer 6 IoT, cross-cutting security).

`HomeClient.call(uid, method, path, body, query=)` is the only way the cloud talks to the bridge:

- the URL comes from the encrypted record only, and is re-checked with R1's `check_url` on EVERY
  call (https, `<machine>.<tailnet>.ts.net:8443`, no IP literal, every resolved address public);
- the connection goes through `PinnedTransport`: it connects to the address it just validated, with
  the host as SNI, so DNS rebinding can't swap it; redirects are off; one 8 s deadline;
- only the bridge's fixed routes (`ports.BRIDGE_ROUTES`) are ever called; the request is signed
  with the DOWN key; the answer must be signed with the UP key, bound to this request (nonce,
  method, target, status), or it is refused; at most 256 KB are read;
- vendor text is never passed on: a refusal is a short code, an unreachable laptop is `HomeOffline`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx

from jarvis.home import signing
from jarvis.home.models import BRIDGE_PORT, HomeRecord
from jarvis.home.ports import BridgeMethod, HomeOffline, HomeRefused, route_allowed
from jarvis.home.store import HomeStore
from jarvis.logging import get_logger
from jarvis.offline.config import (
    PinnedTransport,
    Resolver,
    UrlRejected,
    check_url,
    system_resolver,
)

log = get_logger(__name__)

TIMEOUT_S = 8.0
MAX_REPLY_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 32 * 1024
BAD_REPLY = "Your home laptop's answer couldn't be trusted, so JARVIS ignored it."
NOT_LINKED = "Your home laptop isn't linked yet: link it in Integrations -> Home."
# What a bridge refusal code means, in JARVIS's own words (the bridge's text is never passed on).
CODE_WORDS = {
    "ha_off": "Home Assistant isn't linked yet; the camera still works.",
    "not_exposed": "That device isn't shared with JARVIS.",
    "class_not_allowed": "That device can't be controlled that way.",
    "bad_action": "That device can't do that.",
}
BAD_ADDRESS = "The saved laptop address is no longer allowed. Link your laptop again."


async def check_bridge_url(url: str, *, resolver: Resolver = system_resolver) -> str:
    """The bridge's origin (`https://<host>:8443`) or `UrlRejected` in plain words. Port 8443 is
    required: 443 is R1's local brain on the same Funnel (plan, Re-checked at R3 I0)."""
    text = url.strip(" \t") if isinstance(url, str) else ""
    checked = await check_url(text, resolver=resolver)
    if not checked.base.startswith("https://") or not checked.base.endswith(f":{BRIDGE_PORT}/v1"):
        raise UrlRejected(
            f"Use your Funnel address with port {BRIDGE_PORT}, like https://my-laptop.tail1234.ts.net:{BRIDGE_PORT}"
        )
    return checked.base.removesuffix("/v1")


def request_target(path: str, query: Mapping[str, str] | None) -> str:
    return path if not query else f"{path}?{urlencode(sorted(query.items()))}"


class HomeClient:
    def __init__(
        self,
        store: HomeStore | None,
        *,
        clock: Callable[[], float],
        resolver: Resolver = system_resolver,
        inner: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._store = store
        self._clock = clock
        self._resolver = resolver
        self._inner = inner
        self._timeout = timeout_s

    async def call(
        self,
        uid: str,
        method: BridgeMethod,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._store is None:
            raise HomeRefused("not_linked", NOT_LINKED)
        record = await self._store.load(uid)
        if record is None:
            raise HomeRefused("not_linked", NOT_LINKED)
        return await self.exchange(record, method, path, body, query=query)

    async def exchange(
        self,
        record: HomeRecord,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, str] | None = None,
        keys: signing.HomeKeys | None = None,
    ) -> dict[str, Any]:
        """One signed call. `keys` is only for the link test (keys made from the one-time link
        secret); every other call uses the home's own."""
        if method not in ("GET", "POST") or not route_allowed(method, path):
            raise HomeRefused("not_allowed", "JARVIS doesn't make that call to your laptop.")
        try:
            origin = await check_bridge_url(record.bridge_url, resolver=self._resolver)
        except UrlRejected:
            raise HomeRefused("bad_address", BAD_ADDRESS) from None
        raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        if len(raw) > MAX_REQUEST_BYTES:
            raise HomeRefused("too_large", "That request is too large to send.")
        target = request_target(path, query)
        use = keys or record.keys()
        header = signing.sign(
            use,
            "down",
            home_id=record.home_id,
            method=method,
            target=target,
            body=raw,
            now=self._clock(),
        )
        sent_nonce = signing.parse(header).nonce
        status, headers, reply = await self._send(origin, method, target, header, raw)
        try:
            signing.verify_response(
                headers.get(signing.HEADER.lower()),
                use,
                "up",
                home_id=record.home_id,
                request_nonce=sent_nonce,
                status=status,
                method=method,
                target=target,
                body=reply,
                now=self._clock(),
            )
            data = json.loads(reply) if reply else {}
        except (signing.SignatureError, ValueError):
            log.warning("home reply refused", extra={"home": record.home_id})
            raise HomeRefused("bad_reply", BAD_REPLY) from None
        if not isinstance(data, dict):
            raise HomeRefused("bad_reply", BAD_REPLY)
        if status != 200:
            code = data.get("code")
            safe = code if isinstance(code, str) and code.isascii() and code.isidentifier() else ""
            code = safe[:24] or "refused"
            raise HomeRefused(code, CODE_WORDS.get(code, "Your home laptop didn't do that."))
        return data

    async def _send(
        self, origin: str, method: str, target: str, header: str, raw: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        transport = PinnedTransport(self._resolver, inner=self._inner)
        headers = {signing.HEADER: header, "content-type": "application/json"}
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    transport=transport, follow_redirects=False, timeout=self._timeout
                ) as http:
                    async with http.stream(
                        method, origin + target, content=raw or None, headers=headers
                    ) as resp:
                        if 300 <= resp.status_code < 400:
                            raise HomeRefused("redirect", BAD_REPLY)
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_REPLY_BYTES:
                                raise HomeRefused("too_large", BAD_REPLY)
                            chunks.append(chunk)
                        return resp.status_code, dict(resp.headers), b"".join(chunks)
        except HomeRefused:
            raise
        except (httpx.HTTPError, TimeoutError, OSError):
            raise HomeOffline() from None


__all__ = ["BAD_REPLY", "HomeClient", "check_bridge_url", "request_target"]
