# src/jarvis/webpush/ece.py
"""Web Push message encryption, RFC 8291 (aes128gcm content coding of RFC 8188), from the
`cryptography` primitives. One record per message (payload <= 3993 bytes), no padding.

`encrypt(payload, p256dh, auth)` returns the request body: salt(16) | rs(4) | idlen(1) |
sender public key(65) | ciphertext. `p256dh` is the browser's 65-byte public key, `auth` its
16-byte secret. `salt` and `sender_private` exist so a test can reproduce RFC 8291 Appendix A.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RECORD_SIZE = 4096
MAX_PAYLOAD = RECORD_SIZE - 16 - 1  # tag and the delimiter byte
AUTH_BYTES = 16
KEY_BYTES = 65
DELIMITER_LAST = b"\x02"


class EceError(ValueError):
    """The subscription keys or the payload are unusable (our own words, no key material)."""


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def public_key(raw: bytes) -> ec.EllipticCurvePublicKey:
    """The browser's P-256 point, checked to be on the curve."""
    if len(raw) != KEY_BYTES or raw[0] != 4:
        raise EceError("not a P-256 public key")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise EceError("not a P-256 public key") from None


def encrypt(
    payload: bytes,
    p256dh: bytes,
    auth: bytes,
    *,
    salt: bytes | None = None,
    sender_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise EceError("payload too large")
    if len(auth) != AUTH_BYTES:
        raise EceError("bad auth secret")
    ua_public = public_key(p256dh)
    salt = os.urandom(16) if salt is None else salt
    if len(salt) != 16:
        raise EceError("bad salt")
    sender = sender_private or ec.generate_private_key(ec.SECP256R1())
    as_public = sender.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    shared = sender.exchange(ec.ECDH(), ua_public)
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + p256dh + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    sealed = AESGCM(cek).encrypt(nonce, payload + DELIMITER_LAST, None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + sealed


__all__ = ["MAX_PAYLOAD", "EceError", "encrypt", "public_key"]
