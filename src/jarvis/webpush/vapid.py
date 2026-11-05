# src/jarvis/webpush/vapid.py
"""VAPID (RFC 8292) for Web Push (R3 D11): an ES256 JWT signed with `joserfc`.

The private key is not stored: `VapidKey.from_secret` reduces the keyring's 48 raw bytes
(`Keyring.secret("webpush_vapid", length=48)`) into the P-256 range (d = bytes mod (n-1) + 1), so
the key is the same on every deploy. `aud` is the push service's origin, `exp` at most 12 hours,
`sub` the public base URL (or a mailto:).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from joserfc import jwt
from joserfc.jwk import ECKey

P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
SECRET_BYTES = 48
MAX_LIFETIME = timedelta(hours=12)
LIFETIME = timedelta(hours=10)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class VapidKey:
    def __init__(self, private: ec.EllipticCurvePrivateKey, subject: str) -> None:
        self._private = private
        self._subject = subject

    def __repr__(self) -> str:
        return "VapidKey(<hidden>)"

    @classmethod
    def from_secret(cls, raw: bytes, subject: str) -> VapidKey:
        if len(raw) < 32:
            raise ValueError("the VAPID secret is too short")
        d = int.from_bytes(raw, "big") % (P256_ORDER - 1) + 1
        return cls(ec.derive_private_key(d, ec.SECP256R1()), subject)

    @property
    def public_key(self) -> str:
        """The application server key the browser subscribes with (base64url, 65 bytes)."""
        raw = self._private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return b64url(raw)

    def token(self, endpoint: str, now: datetime) -> str:
        parts = urlsplit(endpoint)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("a push endpoint is an https address")
        port = f":{parts.port}" if parts.port not in (None, 443) else ""
        claims = {
            "aud": f"https://{parts.hostname}{port}",
            "exp": int((now + LIFETIME).timestamp()),
            "sub": self._subject,
        }
        pem = self._private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        key = ECKey.import_key(pem)
        return jwt.encode({"typ": "JWT", "alg": "ES256"}, claims, key)

    def header(self, endpoint: str, now: datetime) -> str:
        """The `Authorization` header value: `vapid t=<jwt>, k=<public key>`."""
        return f"vapid t={self.token(endpoint, now)}, k={self.public_key}"


__all__ = ["LIFETIME", "MAX_LIFETIME", "SECRET_BYTES", "VapidKey", "b64url"]
