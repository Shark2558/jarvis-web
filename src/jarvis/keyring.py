# src/jarvis/keyring.py
"""The one place keys are derived (R2 D2; Layer 7 data, cross-cutting security).

`Keyring(root)` turns the existing token key (Secret Manager `jarvis-token-key`) into one key per
purpose with HKDF-SHA256 (salt `jarvis-keyring-v1`, info `jarvis/<purpose>/v1`). Only this module
derives keys; only `TokenCipher` (AES-256-GCM, random nonce, a string AAD) encrypts with them. The
token vault keeps using the raw key, so tokens stored before R2 still decrypt.

- `wrap` / `unwrap`: a per-file data key (DEK) sealed under the `vault` key with a caller AAD.
- `mac`: HMAC-SHA256 for single-use ticket hashes. Its key comes from a separate HKDF domain
  (`jarvis/mac/<purpose>/v1`), never the AES key itself.
- Everything fails closed: an unknown purpose, a wrong key, a wrong AAD or a tampered blob raises
  `VaultError`; nothing here logs a key, a blob or a plaintext, and `repr` shows neither.
- `Keyring.from_settings` is None without a token key: the vault, notes and things are then OFF
  (R2 never stores them in clear).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from jarvis.integrations.vault import KEY_BYTES, MIN_DISTINCT_KEY_BYTES, TokenCipher, VaultError

if TYPE_CHECKING:
    from jarvis.config import Settings

KEY_ID = "tk1"  # carried in stored envelopes so a later rotation can re-wrap DEKs
SALT = b"jarvis-keyring-v1"
PURPOSES: tuple[str, ...] = ("vault", "vault_index", "notes", "belongings", "tickets")


class Keyring:
    def __init__(self, root: bytes) -> None:
        if len(root) != KEY_BYTES or len(set(root)) < MIN_DISTINCT_KEY_BYTES:
            raise VaultError("keyring root must be 32 random bytes")
        self._root = bytes(root)
        self._ciphers: dict[str, TokenCipher] = {}

    def __repr__(self) -> str:
        return "Keyring(<hidden>)"

    @property
    def kid(self) -> str:
        return KEY_ID

    @classmethod
    def from_settings(cls, settings: Settings) -> Keyring | None:
        root = settings.token_key_bytes()
        return None if root is None else cls(root)

    def _derive(self, info: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(), length=KEY_BYTES, salt=SALT, info=info.encode()
        ).derive(self._root)

    @staticmethod
    def _check(purpose: str) -> None:
        if purpose not in PURPOSES:
            raise VaultError("unknown key purpose")

    def cipher(self, purpose: str) -> TokenCipher:
        self._check(purpose)
        found = self._ciphers.get(purpose)
        if found is None:
            found = self._ciphers[purpose] = TokenCipher(self._derive(f"jarvis/{purpose}/v1"))
        return found

    def new_dek(self) -> bytes:
        return os.urandom(KEY_BYTES)

    def wrap(self, dek: bytes, *, aad: str) -> str:
        if len(dek) != KEY_BYTES:
            raise VaultError("a data key must be 32 bytes")
        return self.cipher("vault").encrypt(dek, aad=aad)

    def unwrap(self, blob: str, *, aad: str) -> bytes:
        dek = self.cipher("vault").decrypt(blob, aad=aad)
        if len(dek) != KEY_BYTES:
            raise VaultError("not a data key")
        return dek

    def mac(self, purpose: str, data: bytes | str) -> str:
        self._check(purpose)
        raw = data.encode() if isinstance(data, str) else data
        key = self._derive(f"jarvis/mac/{purpose}/v1")
        return hmac.new(key, raw, hashlib.sha256).hexdigest()

    def mac_matches(self, purpose: str, data: bytes | str, tag: str) -> bool:
        return hmac.compare_digest(self.mac(purpose, data), tag)


__all__ = ["KEY_ID", "PURPOSES", "Keyring"]
