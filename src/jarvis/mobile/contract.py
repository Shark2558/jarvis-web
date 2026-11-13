# src/jarvis/mobile/contract.py
"""R7 D6, D24: the phone's signed request, as the server and the app's `core` module both write it.

Written down once more in docs/plans/r7-integration/phone-contract.md; the shared vectors are
tests/fixtures/r7/phone_vectors.json (public key, exact strings, good and bad signatures; no
private key is committed). Part C's door checks a request with these functions; Part E's Kotlin
must produce the same bytes.

    X-Jarvis-Phone: v1;d=<device id>;t=<unix seconds>;n=<32 hex: 16 random bytes>;s=<signature>

The signature is ECDSA P-256 with SHA-256, DER-encoded (what Android Keystore's
"SHA256withECDSA" gives), written base64url without padding, over `signing_string(...)`:

    "jarvis-phone-v1\n" + device id + "\n" + t + "\n" + n + "\n" + METHOD + "\n" + path + "\n"
    + hex(sha256(body))

`canonical_json` is the one way a payload's bytes are written (the app's tiny JSON writer equals
it byte for byte): keys in the order given, no spaces, UTF-8, integers only (a coordinate is an
integer number of micro-degrees), `"` `\\` and control characters escaped as Python's json does.
Standard library only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SCHEME = "jarvis-phone-v1"
HEADER = "X-Jarvis-Phone"
DEVICE_ID = re.compile(r"^ph_[0-9a-f]{12}$")
NONCE_HEX_LEN = 32  # 16 random bytes
SIGNATURE_B64_MAX = 120  # a DER P-256 signature is at most 72 bytes (96 base64url characters)
_HEADER = re.compile(
    r"^v1;d=(ph_[0-9a-f]{12});t=([0-9]{1,12});n=([0-9a-f]{32});s=([A-Za-z0-9_-]{8,120})$"
)
_PATH = re.compile(r"^/phone/v1/(?:hello|health|inbox|sos)$")  # the door's four routes (D6)
METHODS = frozenset({"GET", "POST"})


@dataclass(frozen=True)
class PhoneAuth:
    """A header that has the right shape (nothing is verified yet)."""

    device_id: str
    t: int
    nonce: str
    signature: bytes


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(text: str) -> bytes | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None


def parse_header(value: str | None) -> PhoneAuth | None:
    """The header's parts, or None for anything that is not exactly the v1 shape."""
    m = _HEADER.fullmatch(value or "")
    if m is None:
        return None
    signature = _unb64url(m.group(4))
    if not signature:
        return None
    return PhoneAuth(m.group(1), int(m.group(2)), m.group(3), signature)


def header_value(device_id: str, t: int, nonce: str, signature: bytes) -> str:
    if not DEVICE_ID.fullmatch(device_id) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ValueError("not a device id or nonce")
    if not 0 <= t < 10**12 or not signature:
        raise ValueError("not a time or signature")
    return f"v1;d={device_id};t={t};n={nonce};s={b64url(signature)}"


def signing_string(
    device_id: str, t: int, nonce: str, method: str, path: str, body: bytes
) -> bytes:
    """The exact bytes the phone signs, for one of the door's four routes. A path with a query
    string is refused: the signature covers the path only, so anything after a `?` would be
    unsigned input (D6)."""
    if method not in METHODS or not _PATH.fullmatch(path):
        raise ValueError("not a door method or path")
    digest = hashlib.sha256(body).hexdigest()
    return "\n".join((SCHEME, device_id, str(t), nonce, method, path, digest)).encode("ascii")


def _check(value: Any) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        raise TypeError("payloads carry integers only (a coordinate is in micro-degrees)")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError("payload keys are strings")
            _check(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check(v)
        return
    raise TypeError(f"not a payload value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """A payload's one byte form (see the module docstring)."""
    _check(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


__all__ = [
    "DEVICE_ID",
    "HEADER",
    "METHODS",
    "NONCE_HEX_LEN",
    "SCHEME",
    "PhoneAuth",
    "b64url",
    "canonical_json",
    "header_value",
    "parse_header",
    "signing_string",
]
