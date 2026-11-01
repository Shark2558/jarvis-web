# src/jarvis/integrations/vault.py
"""Token vault (Layer 7): where the owner's Google refresh/access tokens live.

`TokenStore` is the port. `MemoryTokenStore` is for dev and tests; `DocTokenStore` keeps one
document per user on the Docs port with the token material encrypted under AES-256-GCM. The
user id is the AAD, so a ciphertext copied onto another user's document fails to decrypt.
Only ciphertext reaches Firestore; nothing here logs a token.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from abc import ABC, abstractmethod

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, SecretStr

from jarvis.storage.docs import Delete, Docs, Set
from jarvis.storage.sessions import safe_id

KEY_BYTES = 32
NONCE_BYTES = 12
# 32 random bytes have ~30 distinct values; fewer than 16 means a typed or placeholder key.
MIN_DISTINCT_KEY_BYTES = 16
KEY_HINT = "generate one with: head -c 32 /dev/urandom | base64"


class VaultError(RuntimeError):
    """Key missing/invalid, ciphertext tampered, or decrypted for the wrong user."""


class GoogleTokens(BaseModel):
    email: str = Field(description="The Google account that consented (must equal the owner)")
    access_token: SecretStr
    refresh_token: SecretStr
    expires_at: float = Field(description="Unix time the access token expires")
    scopes: list[str] = Field(default_factory=list)
    needs_reconnect: bool = Field(
        default=False, description="Refresh failed with invalid_grant (expired 7-day token etc.)"
    )

    def __eq__(self, other: object) -> bool:  # SecretStr compares by value; keep it explicit
        if not isinstance(other, GoogleTokens):
            return NotImplemented
        return self.model_dump() == other.model_dump() and (
            self.access_token.get_secret_value() == other.access_token.get_secret_value()
            and self.refresh_token.get_secret_value() == other.refresh_token.get_secret_value()
        )

    __hash__ = None  # type: ignore[assignment]


def decode_key(value: str) -> bytes:
    """Base64 (standard or url-safe) of exactly 32 random bytes."""
    text = value.strip()
    if not text:
        raise VaultError("token key is empty")
    try:
        padded = text + "=" * (-len(text) % 4)
        raw = base64.urlsafe_b64decode(padded.replace("+", "-").replace("/", "_"))
    except (binascii.Error, ValueError) as exc:
        raise VaultError("token key is not valid base64") from exc
    if len(raw) != KEY_BYTES:
        raise VaultError(f"token key must decode to {KEY_BYTES} bytes, got {len(raw)}")
    if not any(raw) or len(set(raw)) < MIN_DISTINCT_KEY_BYTES:
        raise VaultError(f"token key is weak (all zero or not random); {KEY_HINT}")
    return raw


class TokenCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise VaultError(f"token key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, aad: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        ct = self._aead.encrypt(nonce, plaintext, aad.encode())
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, blob: str, *, aad: str) -> bytes:
        try:
            raw = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise VaultError("ciphertext is not valid base64") from exc
        if len(raw) <= NONCE_BYTES:
            raise VaultError("ciphertext too short")
        try:
            return self._aead.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad.encode())
        except InvalidTag as exc:
            raise VaultError("ciphertext failed authentication (tampered or wrong user)") from exc


class TokenStore(ABC):
    @abstractmethod
    async def get(self, user_id: str) -> GoogleTokens | None: ...

    @abstractmethod
    async def put(self, user_id: str, tokens: GoogleTokens) -> None: ...

    @abstractmethod
    async def delete(self, user_id: str) -> None: ...


class MemoryTokenStore(TokenStore):
    def __init__(self) -> None:
        self._data: dict[str, GoogleTokens] = {}

    async def get(self, user_id: str) -> GoogleTokens | None:
        t = self._data.get(user_id)
        return t.model_copy(deep=True) if t else None

    async def put(self, user_id: str, tokens: GoogleTokens) -> None:
        self._data[user_id] = tokens.model_copy(deep=True)

    async def delete(self, user_id: str) -> None:
        self._data.pop(user_id, None)


class DocTokenStore(TokenStore):
    """Collection `{prefix}tokens/{user_id}`: public fields in clear for the status endpoint,
    token material as one AES-GCM blob bound to the user id."""

    def __init__(self, docs: Docs, *, key: bytes, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._cipher = TokenCipher(key)
        self._col = f"{prefix}tokens"

    def _path(self, user_id: str) -> str:
        return f"{self._col}/{user_id}"

    async def get(self, user_id: str) -> GoogleTokens | None:
        if not safe_id(user_id):
            return None
        doc = await self._d.get(self._path(user_id))
        if doc is None:
            return None
        try:
            return self._decode(doc, user_id)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            # missing field, wrong type, non-JSON plaintext (JSONDecodeError and pydantic's
            # ValidationError are ValueErrors): unusable, so the owner reconnects — never a 500
            raise VaultError(f"token document is malformed ({type(exc).__name__})") from exc

    def _decode(self, doc: dict[str, object], user_id: str) -> GoogleTokens:
        blob = doc["blob"]
        if not isinstance(blob, str):
            raise TypeError("blob is not a string")
        secret = json.loads(self._cipher.decrypt(blob, aad=user_id))
        scopes = doc.get("scopes", [])
        if not isinstance(scopes, list):
            raise TypeError("scopes is not a list")
        return GoogleTokens(
            email=str(doc["email"]),
            access_token=SecretStr(str(secret["access_token"])),
            refresh_token=SecretStr(str(secret["refresh_token"])),
            expires_at=float(doc["expires_at"]),  # type: ignore[arg-type]
            scopes=[str(s) for s in scopes],
            needs_reconnect=bool(doc.get("needs_reconnect", False)),
        )

    async def put(self, user_id: str, tokens: GoogleTokens) -> None:
        if not safe_id(user_id):
            raise ValueError("invalid user id")
        secret = json.dumps(
            {
                "access_token": tokens.access_token.get_secret_value(),
                "refresh_token": tokens.refresh_token.get_secret_value(),
            }
        ).encode()
        await self._d.write(
            [
                Set(
                    self._path(user_id),
                    {
                        "email": tokens.email,
                        "expires_at": tokens.expires_at,
                        "scopes": list(tokens.scopes),
                        "needs_reconnect": tokens.needs_reconnect,
                        "blob": self._cipher.encrypt(secret, aad=user_id),
                    },
                )
            ]
        )

    async def delete(self, user_id: str) -> None:
        if not safe_id(user_id):
            return
        await self._d.write([Delete(self._path(user_id))])


__all__ = [
    "DocTokenStore",
    "GoogleTokens",
    "MemoryTokenStore",
    "TokenCipher",
    "TokenStore",
    "VaultError",
    "decode_key",
]
