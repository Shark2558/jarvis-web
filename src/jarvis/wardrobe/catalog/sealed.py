# src/jarvis/wardrobe/catalog/sealed.py
"""Part A's one way to seal and open (docs/plans/r13-wardrobe.md D2, D9, D17).

Only `jarvis.keyring` derives keys and only `TokenCipher` encrypts: this module picks the purpose
(`wardrobe` for the index, the logs and the backup; `wardrobe_photos` for photos and fingerprints)
and the AAD, which names the owner and the document, so a blob moved to another owner, piece or
page does not open. JSON keeps Unicode (his Malayalam labels) and has no spaces (the byte guard).
Nothing here logs a key, a blob or a plaintext.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from jarvis.keyring import KEY_ID, Keyring
from jarvis.undo.store import owner_ok
from jarvis.wardrobe.model import PHOTO_ID, PIECE_ID

Purpose = Literal["wardrobe", "wardrobe_photos"]
VERSION = 1


def check_owner(uid: str) -> str:
    if not isinstance(uid, str) or not owner_ok(uid):
        raise ValueError("bad owner id")
    return uid


def check_piece(pid: str) -> str:
    if not isinstance(pid, str) or not PIECE_ID.match(pid):
        raise ValueError("bad piece id")
    return pid


def check_photo(photo: str) -> str:
    if not isinstance(photo, str) or not PHOTO_ID.match(photo):
        raise ValueError("bad photo id")
    return photo


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode()


class Sealer:
    def __init__(self, keyring: Keyring) -> None:
        self._ring = keyring

    @property
    def kid(self) -> str:
        return KEY_ID

    def seal_bytes(self, purpose: Purpose, aad: str, data: bytes) -> str:
        return self._ring.cipher(purpose).encrypt(data, aad=aad)

    def open_bytes(self, purpose: Purpose, aad: str, blob: object) -> bytes:
        if not isinstance(blob, str):
            raise ValueError("envelope")
        return self._ring.cipher(purpose).decrypt(blob, aad=aad)

    def seal(self, purpose: Purpose, aad: str, obj: Any) -> str:
        return self.seal_bytes(purpose, aad, dumps(obj))

    def open(self, purpose: Purpose, aad: str, blob: object) -> Any:
        return json.loads(self.open_bytes(purpose, aad, blob))

    def mac(self, data: str) -> str:
        return self._ring.mac("wardrobe", data)


# ---- the AADs (each names the owner and the document) -------------------------------------------
def aad_index(uid: str) -> str:
    return f"wardrobe/index/{uid}/v1"


def aad_log(uid: str, pid: str, page: int) -> str:
    return f"wardrobe/log/{uid}/{pid}/{page}/v1"


def aad_photo(uid: str, photo: str) -> str:
    return f"wardrobe/photo/{uid}/{photo}/v1"


def aad_prints(uid: str, shard: int) -> str:
    return f"wardrobe/fp/{uid}/{shard}/v1"


def aad_backup(uid: str) -> str:
    return f"wardrobe/backup/{uid}/v1"


def aad_restore(uid: str) -> str:
    return f"wardrobe/restore/{uid}/v1"


__all__ = [
    "VERSION",
    "Purpose",
    "Sealer",
    "aad_backup",
    "aad_index",
    "aad_log",
    "aad_photo",
    "aad_prints",
    "aad_restore",
    "check_owner",
    "check_photo",
    "check_piece",
    "dumps",
    "owner_ok",
]
