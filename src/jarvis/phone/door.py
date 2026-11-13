# src/jarvis/phone/door.py
"""The phone's door (R7 D6): every check a signed request passes before a handler sees it.

In this order, before anything is parsed (`api/phone.py` runs the first four, which need the raw
request, then `DoorGate.admit`):

    route   one of the four door routes, POST            else a bare 404
    query   no query string at all (the signature covers only the path)
    cookie  no Cookie header (the door never reads one)
    cap     the body under its route's cap (`DOOR_CAPS`), read no further than the cap
    header  exactly one `X-Jarvis-Phone`, exactly the v1 shape
    flood   at most 60 requests a minute from one client before any store is read
    device  a linked phone (read fresh: an unlink closes the door at once)
    time    |now - t| <= phone_clock_skew_s
    nonce   not seen for this phone in the last 10 minutes
    signature  ECDSA P-256 / SHA-256 over `contract.signing_string(...)`, the stored public key
    rate    at most 30 requests a minute per phone (after the signature: only the phone's own)

Every failure is a bare 401 (404 for the route), logged by the check's name and never audited: a
flood cannot fill the audit, and nothing tells a caller which check it failed. The nonce is
recorded only after the signature verifies, so only the phone itself can fill the store; the
store is bounded and, when full of live nonces, refuses (it never forgets one early).
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from jarvis.logging import get_logger
from jarvis.mobile import contract
from jarvis.mobile.ports import DOOR_PREFIX, DOOR_ROUTES, PhoneRequest
from jarvis.phone.store import Phone, PhoneStore

log = get_logger(__name__)

NONCE_TTL_S = 600
NONCE_MAX = 4096  # 3 phones x 30 a minute x 10 minutes = 900, with room to spare
PER_PHONE_MINUTE = 30
PER_CLIENT_MINUTE = 60
CLIENTS_MAX = 1024
WINDOW_S = 60.0


@dataclass(frozen=True)
class Refusal:
    status: int  # 401, or 404 for a route that is not the door's
    check: str  # the check's name, for the log only


def refuse(check: str, route: str = "", status: int = 401) -> Refusal:
    log.info("phone door refused", extra={"check": check, "route": route})
    return Refusal(status, check)


class NonceStore:
    """Nonces seen in the last `ttl_s`, at most `max_entries` (in process: one instance)."""

    def __init__(self, *, max_entries: int = NONCE_MAX, ttl_s: float = NONCE_TTL_S) -> None:
        self._max, self._ttl = max_entries, ttl_s
        self._seen: OrderedDict[str, float] = OrderedDict()

    def __len__(self) -> int:
        return len(self._seen)

    def _purge(self, now: float) -> None:
        while self._seen:
            key, at = next(iter(self._seen.items()))
            if now - at < self._ttl:
                break
            del self._seen[key]

    def seen(self, key: str, now: float) -> bool:
        self._purge(now)
        return key in self._seen

    def add(self, key: str, now: float) -> bool:
        """Record a nonce; False when it was seen or the store is full of live nonces."""
        self._purge(now)
        if key in self._seen or len(self._seen) >= self._max:
            return False
        self._seen[key] = now
        return True


class PerPhoneRate:
    """A sliding one-minute window per key; at most `max_phones` keys (the stalest goes)."""

    def __init__(self, *, per_minute: int = PER_PHONE_MINUTE, max_phones: int = 16) -> None:
        self._per, self._max = per_minute, max_phones
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hits)

    def allow(self, key: str, now: float) -> bool:
        hits = self._hits.get(key)
        if hits is None:
            while len(self._hits) >= self._max:
                self._hits.popitem(last=False)
            hits = self._hits[key] = deque()
        self._hits.move_to_end(key)
        while hits and now - hits[0] >= WINDOW_S:
            hits.popleft()
        if len(hits) >= self._per:
            return False
        hits.append(now)
        return True


def route_of(method: str, path: str) -> str | None:
    """The door route this POST path names, or None (a bare 404)."""
    if method != "POST" or not path.startswith(DOOR_PREFIX):
        return None
    name = path[len(DOOR_PREFIX) :]
    return name if name in DOOR_ROUTES else None


def verify(phone: Phone, signature: bytes, string: bytes) -> bool:
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes.fromhex(phone.public_key)
        )
        key.verify(signature, string, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return True


class DoorGate:
    def __init__(
        self,
        store: PhoneStore,
        *,
        skew_s: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._skew = skew_s
        self._clock = clock
        self.nonces = NonceStore()
        self.rate = PerPhoneRate()
        self.clients = PerPhoneRate(per_minute=PER_CLIENT_MINUTE, max_phones=CLIENTS_MAX)

    async def admit(
        self, route: str, headers: list[str], body: bytes, client: str
    ) -> PhoneRequest | Refusal:
        """The checks after the body was read under its cap (header -> rate)."""
        auth = contract.parse_header(headers[0]) if len(headers) == 1 else None
        if auth is None:
            return refuse("header", route)
        now = self._clock()
        if not self.clients.allow(client, now):
            return refuse("flood", route)
        found = await self.store.find(auth.device_id)
        if found is None:
            return refuse("device", route)
        uid, phone = found
        if abs(now - auth.t) > self._skew:
            return refuse("time", route)
        key = f"{phone.id}:{auth.nonce}"
        if self.nonces.seen(key, now):
            return refuse("nonce", route)
        string = contract.signing_string(
            auth.device_id, auth.t, auth.nonce, "POST", f"{DOOR_PREFIX}{route}", body
        )
        if not verify(phone, auth.signature, string):
            return refuse("signature", route)
        if not self.nonces.add(key, now):
            return refuse("nonce_full", route)
        if not self.rate.allow(phone.id, now):
            return refuse("rate", route)
        return PhoneRequest(route=route, device_id=phone.id, uid=uid, body=body, at=now)


__all__ = [
    "NONCE_MAX",
    "NONCE_TTL_S",
    "PER_PHONE_MINUTE",
    "DoorGate",
    "NonceStore",
    "PerPhoneRate",
    "Refusal",
    "refuse",
    "route_of",
    "verify",
]
