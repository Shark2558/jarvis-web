# src/jarvis/home/signing.py
"""The one HMAC implementation for the home link (R3 D4, D5; cross-cutting security).

Used by the cloud AND the home bridge (it ships in the home kit): only the standard library and
cryptography. Nothing else in JARVIS signs or verifies home messages.

Keys (D4): a 32-byte seed made at linking; `up = HKDF-SHA256(seed, info "jarvis/home/up/v1")`
signs home -> cloud, `down = HKDF-SHA256(seed, info "jarvis/home/down/v1")` signs cloud -> home
(no salt: the seed is 32 random bytes), so a captured message can't be reflected the other way.

A request carries `X-Jarvis-Home: v1;h=<home_id>;t=<unix>;n=<nonce>;s=<mac>` (nonce: 16 random
bytes, mac: HMAC-SHA256, both base64url without padding) over

    "jarvis-home-v1\n" + direction + "\n" + home_id + "\n" + t + "\n" + n + "\n" + METHOD + "\n"
    + target + "\n" + hex(sha256(body))

where `target` is the path plus "?query" exactly as sent. A response is signed in the other
direction under its own domain, bound to the request it answers (its nonce, method, target) and to
its status:

    "jarvis-home-v1-res\n" + direction + "\n" + home_id + "\n" + t + "\n" + n + "\n"
    + request_nonce + "\n" + status + "\n" + METHOD + "\n" + target + "\n" + hex(sha256(body))

A request may also carry `X-Jarvis-Body-Sha256: hex(sha256(body))` (R11.1 review C-sec M1). The
MAC already covers that hash, so a receiver can check the signature over the DECLARED hash
(`verify_declared`) before it reads a large body, then compare the hash of what it read, and only
then run `verify` (which remembers the nonce). Nothing changes for a request without it.

Checks, in order and before any parsing (D5): the header's shape (`parse`), then (the caller
looks the home id up) the time window (|now - t| <= 60 s), the nonce not seen in 5 minutes, the
MAC (`hmac.compare_digest`), and only then the nonce is remembered, so a flood of bad signatures
can't fill the cache. A failure raises `SignatureError(check)`: the check's name only, never a
value, for the log; the caller answers a bare 401.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

Direction = Literal["up", "down"]
Check = Literal["shape", "time", "nonce", "mac"]

HEADER = "X-Jarvis-Home"
BODY_HASH_HEADER = "X-Jarvis-Body-Sha256"
DOMAIN = "jarvis-home-v1"
RESPONSE_DOMAIN = "jarvis-home-v1-res"
SEED_BYTES = 32
NONCE_BYTES = 16
MAX_SKEW_S = 60
NONCE_TTL_S = 300
MAX_NONCES = 4096
MAX_HEADER_CHARS = 160
METHODS = frozenset({"GET", "POST"})
_HEADER_RE = re.compile(
    r"v1;h=(h_[0-9a-f]{8});t=([0-9]{1,12});n=([A-Za-z0-9_-]{22});s=([A-Za-z0-9_-]{43})"
)
_TARGET_RE = re.compile(r"/[\x21-\x7e]{0,2047}")
_HOME_RE = re.compile(r"h_[0-9a-f]{8}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class SignatureError(Exception):
    """A home message failed a check. `check` names which one (for the log); never a value."""

    def __init__(self, check: Check) -> None:
        super().__init__(f"home signature refused ({check})")
        self.check: Check = check


@dataclass(frozen=True, repr=False)
class HomeKeys:
    up: bytes
    down: bytes

    def key(self, direction: Direction) -> bytes:
        if direction not in ("up", "down"):
            raise ValueError("a direction is up or down")
        return self.up if direction == "up" else self.down

    def __repr__(self) -> str:
        return "HomeKeys(<hidden>)"


@dataclass(frozen=True)
class Signed:
    """A parsed header (its MAC not yet checked)."""

    home_id: str
    t: int
    nonce: str
    mac: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_seed() -> bytes:
    return os.urandom(SEED_BYTES)


def new_nonce() -> str:
    return _b64(os.urandom(NONCE_BYTES))


def _hkdf(seed: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(seed)


def derive_keys(seed: bytes) -> HomeKeys:
    if not isinstance(seed, bytes) or len(seed) != SEED_BYTES:
        raise ValueError("a home seed is 32 bytes")
    return HomeKeys(up=_hkdf(seed, b"jarvis/home/up/v1"), down=_hkdf(seed, b"jarvis/home/down/v1"))


def _target_ok(method: str, target: str) -> bool:
    return (
        method in METHODS and isinstance(target, str) and _TARGET_RE.fullmatch(target) is not None
    )


def _hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def body_hash(body: bytes) -> str:
    """The value of `BODY_HASH_HEADER` for this body."""
    return _hash(body)


def _hashed_message(
    direction: Direction, home_id: str, t: int, nonce: str, method: str, target: str, digest: str
) -> bytes:
    return "\n".join((DOMAIN, direction, home_id, str(t), nonce, method, target, digest)).encode(
        "ascii"
    )


def request_message(
    direction: Direction, *, home_id: str, t: int, nonce: str, method: str, target: str, body: bytes
) -> bytes:
    return _hashed_message(direction, home_id, t, nonce, method, target, _hash(body))


def response_message(
    direction: Direction,
    *,
    home_id: str,
    t: int,
    nonce: str,
    request_nonce: str,
    status: int,
    method: str,
    target: str,
    body: bytes,
) -> bytes:
    lines = (RESPONSE_DOMAIN, direction, home_id, str(t), nonce, request_nonce, str(status))
    return "\n".join((*lines, method, target, _hash(body))).encode("ascii")


def _mac(key: bytes, message: bytes) -> str:
    return _b64(hmac.new(key, message, hashlib.sha256).digest())


def _header(home_id: str, t: int, nonce: str, mac: str) -> str:
    return f"v1;h={home_id};t={t};n={nonce};s={mac}"


def _check_args(home_id: str, method: str, target: str) -> None:
    if not _HOME_RE.fullmatch(home_id) or not _target_ok(method, target):
        raise ValueError("home id, method or target is not one JARVIS signs")


def sign(
    keys: HomeKeys,
    direction: Direction,
    *,
    home_id: str,
    method: str,
    target: str,
    body: bytes,
    now: float,
    nonce: str | None = None,
) -> str:
    """The header value for one request."""
    _check_args(home_id, method, target)
    t, n = int(now), nonce or new_nonce()
    msg = request_message(
        direction, home_id=home_id, t=t, nonce=n, method=method, target=target, body=body
    )
    return _header(home_id, t, n, _mac(keys.key(direction), msg))


def parse(value: str | None) -> Signed:
    """The header's parts, or SignatureError("shape"). Nothing else is looked at first."""
    if not isinstance(value, str) or len(value) > MAX_HEADER_CHARS:
        raise SignatureError("shape")
    m = _HEADER_RE.fullmatch(value)
    if m is None:
        raise SignatureError("shape")
    return Signed(home_id=m.group(1), t=int(m.group(2)), nonce=m.group(3), mac=m.group(4))


def _fresh(t: int, now: float) -> None:
    if abs(now - t) > MAX_SKEW_S:
        raise SignatureError("time")


class NonceCache:
    """Nonces seen in the last 5 minutes, per home, in process (Cloud Run runs one instance; the
    bridge is one process). Full of live entries -> refuses (fails closed)."""

    def __init__(self, *, ttl_s: float = NONCE_TTL_S, max_entries: int = MAX_NONCES) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._until: dict[tuple[str, str], float] = {}

    def seen(self, home_id: str, nonce: str, now: float) -> bool:
        until = self._until.get((home_id, nonce))
        return until is not None and until > now

    def remember(self, home_id: str, nonce: str, now: float) -> None:
        if len(self._until) >= self._max:
            self._until = {k: v for k, v in self._until.items() if v > now}
        if len(self._until) >= self._max:
            raise SignatureError("nonce")
        self._until[(home_id, nonce)] = now + self._ttl


def verify(
    signed: Signed,
    keys: HomeKeys,
    direction: Direction,
    *,
    method: str,
    target: str,
    body: bytes,
    now: float,
    nonces: NonceCache,
) -> None:
    """Passes, or raises SignatureError naming the check that failed."""
    if not _target_ok(method, target):
        raise SignatureError("shape")
    _fresh(signed.t, now)
    if nonces.seen(signed.home_id, signed.nonce, now):
        raise SignatureError("nonce")
    msg = request_message(
        direction,
        home_id=signed.home_id,
        t=signed.t,
        nonce=signed.nonce,
        method=method,
        target=target,
        body=body,
    )
    if not hmac.compare_digest(_mac(keys.key(direction), msg), signed.mac):
        raise SignatureError("mac")
    nonces.remember(signed.home_id, signed.nonce, now)


def verify_declared(
    signed: Signed,
    keys: HomeKeys,
    direction: Direction,
    *,
    method: str,
    target: str,
    digest: str | None,
    now: float,
    nonces: NonceCache,
) -> None:
    """The signature over a DECLARED body hash, before the body is read. Passes, or raises
    SignatureError. The nonce is NOT remembered here: `verify` does that once the body has
    been read and its hash compared."""
    if not _target_ok(method, target) or not isinstance(digest, str):
        raise SignatureError("shape")
    if not _DIGEST_RE.fullmatch(digest):
        raise SignatureError("shape")
    _fresh(signed.t, now)
    if nonces.seen(signed.home_id, signed.nonce, now):
        raise SignatureError("nonce")
    msg = _hashed_message(direction, signed.home_id, signed.t, signed.nonce, method, target, digest)
    if not hmac.compare_digest(_mac(keys.key(direction), msg), signed.mac):
        raise SignatureError("mac")


def sign_response(
    keys: HomeKeys,
    direction: Direction,
    *,
    home_id: str,
    request_nonce: str,
    status: int,
    method: str,
    target: str,
    body: bytes,
    now: float,
) -> str:
    """The header value for the answer to one request (signed in the other direction)."""
    _check_args(home_id, method, target)
    t, n = int(now), new_nonce()
    msg = response_message(
        direction,
        home_id=home_id,
        t=t,
        nonce=n,
        request_nonce=request_nonce,
        status=status,
        method=method,
        target=target,
        body=body,
    )
    return _header(home_id, t, n, _mac(keys.key(direction), msg))


def verify_response(
    value: str | None,
    keys: HomeKeys,
    direction: Direction,
    *,
    home_id: str,
    request_nonce: str,
    status: int,
    method: str,
    target: str,
    body: bytes,
    now: float,
) -> None:
    """Passes only for the answer to exactly this request, from this home, signed just now."""
    signed = parse(value)
    if signed.home_id != home_id or not _target_ok(method, target):
        raise SignatureError("shape")
    _fresh(signed.t, now)
    msg = response_message(
        direction,
        home_id=home_id,
        t=signed.t,
        nonce=signed.nonce,
        request_nonce=request_nonce,
        status=status,
        method=method,
        target=target,
        body=body,
    )
    if not hmac.compare_digest(_mac(keys.key(direction), msg), signed.mac):
        raise SignatureError("mac")


__all__ = [
    "BODY_HASH_HEADER",
    "DOMAIN",
    "HEADER",
    "MAX_SKEW_S",
    "NONCE_TTL_S",
    "RESPONSE_DOMAIN",
    "SEED_BYTES",
    "Direction",
    "HomeKeys",
    "NonceCache",
    "SignatureError",
    "Signed",
    "body_hash",
    "derive_keys",
    "new_nonce",
    "new_seed",
    "parse",
    "request_message",
    "response_message",
    "sign",
    "sign_response",
    "verify",
    "verify_declared",
    "verify_response",
]
