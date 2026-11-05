# src/jarvis/home/link.py
"""Linking the laptop (R3 D4). Cloud only.

The owner presses Link: `LinkService.code(uid)` makes an 8-character Crockford-base32 code (40 bits,
10 minutes, single use, stored as SHA-256, void after 5 wrong tries). The bridge calls
`POST /home/link {code, bridge_url, bridge_version, link_secret}` and `complete` then:

1. finds the live code (a wrong one counts a try) and checks `bridge_url` with R1's `check_url`
   plus port 8443;
2. makes a home id and a 32-byte seed, and calls the bridge's `GET /bridge/v1/health` with the
   request signed by keys made from `link_secret`, a one-time secret the bridge made and sent with
   the code. The bridge has no seed yet, so it can't sign with the new one: a correctly signed
   answer proves the machine at that address is the one that asked, and it is the plan's "test
   call" (a deviation, said in the report);
3. only then saves the record, spends the code and returns the seed once. A failed test call does
   not spend the code and is not a wrong try (Funnel DNS can take 10 minutes).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.home import signing
from jarvis.home.client import HomeClient, check_bridge_url
from jarvis.home.models import HomeRecord
from jarvis.home.ports import HomeOffline, HomeRefused
from jarvis.home.store import HomeStore
from jarvis.offline.config import Resolver, UrlRejected, system_resolver

CODE_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)
CODE_LEN = 8
CODE_TTL_S = 600.0
_FIX = str.maketrans({"I": "1", "L": "1", "O": "0"})
_CODE_RE = re.compile(r"[0-9A-Z]{8}")
_VERSION_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")


class LinkRefused(Exception):
    """`code` is bad_code | bad_url | not_reachable | bad_request; `reason` is plain words."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class LinkCode:
    code: str
    expires_in_s: int


@dataclass(frozen=True)
class Linked:
    home_id: str
    seed: bytes


def normalise(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    text = code.upper().replace("-", "").replace(" ", "").translate(_FIX)
    if not _CODE_RE.fullmatch(text) or any(c not in CODE_CHARS for c in text):
        return None
    return text


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def link_keys(secret_b64: object) -> signing.HomeKeys:
    if not isinstance(secret_b64, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret_b64):
        raise LinkRefused("bad_request", "That link request isn't valid.")
    try:
        raw = base64.urlsafe_b64decode(secret_b64 + "=")
    except (binascii.Error, ValueError):
        raise LinkRefused("bad_request", "That link request isn't valid.") from None
    return signing.derive_keys(raw)


class LinkService:
    def __init__(
        self,
        store: HomeStore,
        client: HomeClient,
        *,
        clock: Callable[[], float],
        resolver: Resolver = system_resolver,
    ) -> None:
        self._store = store
        self._client = client
        self._clock = clock
        self._resolver = resolver

    async def code(self, uid: str) -> LinkCode:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))
        await self._store.put_code(uid, code_hash(code), self._clock() + CODE_TTL_S)
        return LinkCode(code=f"{code[:4]}-{code[4:]}", expires_in_s=int(CODE_TTL_S))

    async def complete(
        self,
        code: object,
        bridge_url: object,
        bridge_version: object,
        link_secret: object,
        *,
        client: str = "",
    ) -> Linked:
        norm = normalise(code)
        uid = None if norm is None else await self._store.take_code(code_hash(norm), client)
        if uid is None:
            raise LinkRefused("bad_code", "")
        if not isinstance(bridge_version, str) or not _VERSION_RE.fullmatch(bridge_version):
            raise LinkRefused("bad_request", "That link request isn't valid.")
        keys = link_keys(link_secret)
        try:
            origin = await check_bridge_url(str(bridge_url), resolver=self._resolver)
        except UrlRejected as exc:
            raise LinkRefused("bad_url", exc.reason) from None
        home_id = "h_" + secrets.token_hex(4)
        seed = signing.new_seed()
        record = HomeRecord(home_id=home_id, bridge_url=origin, seed=seed)
        try:
            reply = await self._client.exchange(record, "GET", "/bridge/v1/health", keys=keys)
        except (HomeOffline, HomeRefused):
            raise LinkRefused(
                "not_reachable",
                "JARVIS couldn't reach your laptop yet. The address can take up to 10 minutes "
                "to start working; the script will try again.",
            ) from None
        if reply.get("ok") is not True:
            raise LinkRefused("not_reachable", "Your laptop didn't answer the way JARVIS expects.")
        await self._store.link(uid, home_id, origin, seed)
        await self._store.spend_code(uid)
        return Linked(home_id=home_id, seed=seed)


__all__ = ["LinkCode", "LinkRefused", "LinkService", "Linked", "code_hash", "normalise"]
