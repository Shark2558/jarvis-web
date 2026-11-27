# src/jarvis/localspeech/wakejoin.py
"""The kit's wake word, joined (R5.2 I1; row 83): V4's `build_wakeword` with the two ports it
asks V1 for. Kit-safe: the standard library and `cryptography` (pinned in the kit's
requirements); never imported by the cloud.

- `Sealer`: the trained files are sealed at rest like the recordings (AES-256-GCM, a fresh 96-bit
  nonce, bound to their purpose), but with **their own key**, `wakeword.secret`: deleting every
  recording replaces the recordings' key (`clips.ClipVault.delete`), and the owner may keep the
  wake-word files when he deletes the recordings ("Delete my recordings" asks separately), so
  they must stay readable. Deleting the wake-word files deletes the files; the key stays.
- `Voices`: none in kit 1.0.0. The kit's voice slots are empty (the GPL phonemiser and Piper are
  left out, `deploy/local-speech/models.json`), so stage 1 trains without other speakers'
  negatives (its evals say so) and stage 2 refuses with V4's plain words until a permissively
  licensed voice is pinned.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from jarvis.localspeech.kitconfig import KitConfig, write_private
from jarvis.localspeech.wakeword.port import WakewordKit
from jarvis.localspeech.wakeword.service import build_wakeword

MAGIC: Final = b"JVW1"
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32
TAG_BYTES: Final = 16
PURPOSE: Final = b"jarvis-wakeword-file"
KEY_FILE: Final = "wakeword.secret"


class FileSealer:
    """V4's `Sealer` with a key of its own, made on first use, readable by the owner only."""

    def __init__(self, key_file: Path) -> None:
        self.key_file = key_file
        self._aead: AESGCM | None = None

    def __repr__(self) -> str:
        return "FileSealer(encrypted)"

    def _cipher(self) -> AESGCM:
        if self._aead is None:
            try:
                key = self.key_file.read_bytes()
            except FileNotFoundError:
                key = b""
            if len(key) != KEY_BYTES:
                key = secrets.token_bytes(KEY_BYTES)
                write_private(self.key_file, key)
            self._aead = AESGCM(key)
        return self._aead

    def seal(self, data: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return MAGIC + nonce + self._cipher().encrypt(nonce, data, PURPOSE)

    def unseal(self, data: bytes) -> bytes:
        if not data.startswith(MAGIC) or len(data) < len(MAGIC) + NONCE_BYTES + TAG_BYTES:
            raise ValueError("not a sealed wake-word file")
        nonce = data[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
        try:
            return self._cipher().decrypt(nonce, data[len(MAGIC) + NONCE_BYTES :], PURPOSE)
        except InvalidTag:
            raise ValueError("the wake-word file does not open with this kit's key") from None


def kit_wakeword(config: KitConfig) -> WakewordKit:
    """`build_service(config, wakeword=kit_wakeword(config))`: V4's wake word on this kit."""
    sealer = FileSealer(config.data_dir / KEY_FILE)
    return build_wakeword(config.wakeword_dir, sealer=sealer, voices=None)


__all__ = ["KEY_FILE", "FileSealer", "kit_wakeword"]
