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
- R3: cipher purposes for the home link, the home feed, faces and Web Push subscriptions, and one
  SECRET purpose: `secret("webpush_vapid")` is raw HKDF output (its own domain,
  `jarvis/secret/<purpose>/v1`) that R3 D reduces into a P-256 private key. A secret purpose is
  never a cipher or MAC purpose and the other way round; still no new stored secret (R3 D4).
- R6: `book_index` (the sealed build-book index) and `book_session` (book sessions; used both as a
  cipher and as a MAC domain, which `mac` keeps apart by its own HKDF info).
- R11: `bills`, `spend`, `wellbeing`, `alerts_place` and `kitchen` (the helpers' sealed data).
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
PURPOSES: tuple[str, ...] = (
    "vault",
    "vault_index",
    "notes",
    "belongings",
    "tickets",
    # R3: home link record, home feed, faces registry, Web Push subscriptions
    "home",
    "home_feed",
    "faces",
    "webpush",
    "notify",  # R3 I1: the Alerts VIP list (phone / email references), its own key
    "connectors",  # R4 D9: the owner's own GitHub token (own-account read), its own key
    # R6 D6, D9: the sealed build-book index, and the book sessions (their sealed turns AND, as
    # a MAC domain, the hash of a session token: `mac("book_session", token)`)
    "book_index",
    "book_session",
    # R11 (docs/plans/r11-free-helpers.md, data model): the helpers' own data, each its own key:
    # bills and their UPI IDs (A), grocery spend from receipts (D), the water and activity log
    # (C, health-adjacent), his place for weather and disaster alerts (B), the pantry, diet and
    # saved recipes (D)
    "bills",
    "spend",
    "wellbeing",
    "alerts_place",
    "kitchen",
)
SECRET_PURPOSES: tuple[str, ...] = ("webpush_vapid",)
MIN_SECRET_BYTES, MAX_SECRET_BYTES = 16, 64


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

    def secret(self, purpose: str, *, length: int = KEY_BYTES) -> bytes:
        """Raw key material for a SECRET purpose (R3: the VAPID private key), 16-64 bytes."""
        if purpose not in SECRET_PURPOSES:
            raise VaultError("unknown secret purpose")
        if isinstance(length, bool) or not MIN_SECRET_BYTES <= length <= MAX_SECRET_BYTES:
            raise VaultError("a derived secret is 16 to 64 bytes")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=SALT,
            info=f"jarvis/secret/{purpose}/v1".encode(),
        ).derive(self._root)


__all__ = ["KEY_ID", "PURPOSES", "SECRET_PURPOSES", "Keyring"]
