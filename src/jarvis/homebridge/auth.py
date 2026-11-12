# src/jarvis/homebridge/auth.py
"""Checking requests from the cloud (R3 D5, D6; cross-cutting security). Ships in the home kit.

Everything the cloud sends is signed with the DOWN key; `BridgeAuth.check` runs BEFORE the body is
parsed: header shape, the home id is this bridge's, |now - t| <= 60 s (the bridge's clock is
corrected from the cloud's `Date` header, see `cloud.py`), the nonce not seen,
`hmac.compare_digest`, and only then the nonce is remembered (`jarvis.home.signing`, the one
implementation).

While a link is pending (the owner typed the code into the script) the cloud's test call is signed
with keys made from a one-time secret, and ONLY `GET /bridge/v1/health` accepts them: the bridge
has no seed yet, so it can't verify with the new one.

Answers are signed with the UP key, bound to the request they answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis.home import signing
from jarvis.homebridge.state import BridgeStore

HEALTH = ("GET", "/bridge/v1/health")


@dataclass(frozen=True, repr=False)
class Verified:
    home_id: str
    nonce: str
    keys: signing.HomeKeys

    def __repr__(self) -> str:
        return f"Verified({self.home_id})"


class BridgeAuth:
    def __init__(self, store: BridgeStore, clock: Callable[[], float]) -> None:
        self._store = store
        self._clock = clock
        self._nonces = signing.NonceCache()
        # The nonce cache is in memory. After a restart a message captured earlier would still be
        # inside the 60 s window, so nothing at or before the newest time accepted so far is taken.
        self._floor = store.last_message_t()
        self._newest = self._floor
        self.offset_s = 0.0  # added to the local clock (set from the cloud's Date header)

    def now(self) -> float:
        return self._clock() + self.offset_s

    def precheck(self, header: str | None, *, method: str, target: str, digest: str | None) -> bool:
        """Before a LARGE body is read (R11.1 O7: one photo; review C-sec M1): the signature over
        the body hash the cloud declared (`X-Jarvis-Body-Sha256`), with this home's keys, a fresh
        time and an unseen nonce. Only the cloud can pass it, so nobody else can make the bridge
        buffer megabytes or hold its one upload slot. `check` still runs on the body itself."""
        try:
            signed = signing.parse(header)
        except signing.SignatureError:
            return False
        linked = self._store.linked()
        if linked is None or signed.home_id != linked.home_id or signed.t <= self._floor:
            return False
        try:
            signing.verify_declared(
                signed,
                linked.keys,
                "down",
                method=method,
                target=target,
                digest=digest,
                now=self.now(),
                nonces=self._nonces,
            )
        except signing.SignatureError:
            return False
        return True

    def check(self, header: str | None, *, method: str, target: str, body: bytes) -> Verified:
        """Passes, or raises SignatureError (the caller answers a bare 401)."""
        signed = signing.parse(header)
        path = target.split("?", 1)[0]
        candidates: list[signing.HomeKeys] = []
        linked = self._store.linked()
        if linked is not None and signed.home_id == linked.home_id:
            candidates.append(linked.keys)
        if (method, path) == HEALTH:  # only the health route takes the one-time link keys
            pending = self._store.pending_keys()
            if pending is not None:
                candidates.append(pending)
        if not candidates:
            raise signing.SignatureError("shape")
        last: signing.SignatureError | None = None
        for keys in candidates:
            if linked is not None and keys is linked.keys and signed.t <= self._floor:
                last = signing.SignatureError("time")  # older than the last one seen (review M3)
                continue
            try:
                signing.verify(
                    signed,
                    keys,
                    "down",
                    method=method,
                    target=target,
                    body=body,
                    now=self.now(),
                    nonces=self._nonces,
                )
            except signing.SignatureError as exc:
                last = exc
                continue
            if linked is not None and keys is linked.keys:
                self._advance(signed.t)
            return Verified(home_id=signed.home_id, nonce=signed.nonce, keys=keys)
        raise last if last is not None else signing.SignatureError("mac")

    def _advance(self, t: int) -> None:
        if t > self._newest:
            self._newest = t
            self._store.save_last_message_t(t)

    def reply_header(
        self, who: Verified, *, status: int, method: str, target: str, body: bytes
    ) -> str:
        return signing.sign_response(
            who.keys,
            "up",
            home_id=who.home_id,
            request_nonce=who.nonce,
            status=status,
            method=method,
            target=target,
            body=body,
            now=self.now(),
        )


__all__ = ["BridgeAuth", "Verified"]
