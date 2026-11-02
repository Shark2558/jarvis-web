# evals/permissions/authenticator.py
"""A software WebAuthn authenticator for the slice 10 D evals and tests — no browser, no network.

It does what a platform authenticator (Windows Hello, a phone's fingerprint) does on
`navigator.credentials.create()` / `.get()`, and returns the same JSON a browser's
`PublicKeyCredential` serialises to: an ES256 (P-256) key pair per credential, "none" attestation,
authenticator data with the RP ID hash, flags (UP, UV, AT) and a signature counter, and
clientDataJSON with the challenge and origin. Knobs let a case misbehave on purpose (wrong origin,
no user verification, a counter that goes backwards, a different RP ID).

Self-contained: tests load it by file path (evals never import from tests/).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import encode_cbor

UP, UV, AT = 0x01, 0x04, 0x40
AAGUID = bytes(16)  # "none" attestation: all zeros is allowed


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class SoftCredential:
    id: bytes
    key: ec.EllipticCurvePrivateKey
    rp_id: str
    sign_count: int = 0

    def cose(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return encode_cbor(
            {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        )


@dataclass
class SoftAuthenticator:
    origin: str
    user_verified: bool = True
    counter_step: int = 1  # 0: an authenticator without a counter (allowed: both stay 0)
    credentials: dict[str, SoftCredential] = field(default_factory=dict)

    # ---- navigator.credentials.create() -------------------------------------------------------
    def create(
        self, options: dict[str, Any], *, origin: str | None = None, rp_id: str | None = None
    ) -> dict[str, Any]:
        rp = rp_id or options["rp"]["id"]
        cred = SoftCredential(
            id=secrets.token_bytes(32), key=ec.generate_private_key(ec.SECP256R1()), rp_id=rp
        )
        self.credentials[b64u(cred.id)] = cred
        flags = UP | AT | (UV if self.user_verified else 0)
        attested = AAGUID + struct.pack(">H", len(cred.id)) + cred.id + cred.cose()
        auth_data = self._auth_data(rp, flags, cred.sign_count) + attested
        client = self._client("webauthn.create", options["challenge"], origin)
        att = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64u(cred.id),
            "rawId": b64u(cred.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(client),
                "attestationObject": b64u(att),
                "transports": ["internal"],
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }

    # ---- navigator.credentials.get() ----------------------------------------------------------
    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        rp_id: str | None = None,
        credential_id: str | None = None,
        sign_count: int | None = None,
    ) -> dict[str, Any]:
        allowed = [c["id"] for c in options.get("allowCredentials") or []]
        cid = credential_id or next(c for c in allowed if c in self.credentials)
        cred = self.credentials[cid]
        rp = rp_id or options.get("rpId") or cred.rp_id
        cred.sign_count = (
            sign_count if sign_count is not None else cred.sign_count + self.counter_step
        )
        flags = UP | (UV if self.user_verified else 0)
        auth_data = self._auth_data(rp, flags, cred.sign_count)
        client = self._client("webauthn.get", options["challenge"], origin)
        sig = cred.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(client),
                "authenticatorData": b64u(auth_data),
                "signature": b64u(sig),
                "userHandle": None,
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }

    def _auth_data(self, rp_id: str, flags: int, count: int) -> bytes:
        return hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", count)

    def _client(self, kind: str, challenge: str, origin: str | None) -> bytes:
        body = {
            "type": kind,
            "challenge": challenge,
            "origin": origin or self.origin,
            "crossOrigin": False,
        }
        return json.dumps(body, separators=(",", ":")).encode()


__all__ = ["SoftAuthenticator", "SoftCredential", "b64u", "unb64u"]
