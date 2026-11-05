# src/jarvis/vault/crypto.py
"""Envelope encryption for vault files and the vault index (R2 D1, D2).

A file is cut into 512 KiB chunks; each chunk is sealed with the file's own random data key
(DEK, AES-256-GCM via `TokenCipher`), with an AAD that names owner, item, file, position and
count, so a chunk moved to another file, item or owner, reordered or cut short fails to open. The
DEK is wrapped by the keyring's `vault` key (`Keyring.wrap`) with its own AAD. The index is one
blob under `vault_index`. Only `jarvis.keyring` derives keys; every failure is a `VaultError`
with fixed words (never a plaintext, key or blob).
"""

from __future__ import annotations

from jarvis.integrations.vault import TokenCipher
from jarvis.keyring import Keyring

CHUNK_BYTES = 512 * 1024


def chunk_count(size: int) -> int:
    return max(1, -(-size // CHUNK_BYTES))


def index_aad(uid: str) -> str:
    return f"vault/index/{uid}/v1"


def dek_aad(uid: str, item_id: str, fid: str) -> str:
    return f"vault/dek/{uid}/{item_id}/{fid}/v1"


def chunk_aad(uid: str, item_id: str, fid: str, n: int, count: int) -> str:
    return f"vault/chunk/{uid}/{item_id}/{fid}/{n}/{count}/v1"


class VaultCrypto:
    def __init__(self, ring: Keyring) -> None:
        self._ring = ring

    @property
    def ring(self) -> Keyring:
        return self._ring

    def seal(self, uid: str, item_id: str, fid: str, data: bytes) -> tuple[str, list[str]]:
        """(wrapped DEK, sealed chunks) for a file's bytes."""
        dek = self._ring.new_dek()
        cipher = TokenCipher(dek)
        count = chunk_count(len(data))
        blobs = [
            cipher.encrypt(
                data[n * CHUNK_BYTES : (n + 1) * CHUNK_BYTES],
                aad=chunk_aad(uid, item_id, fid, n, count),
            )
            for n in range(count)
        ]
        return self._ring.wrap(dek, aad=dek_aad(uid, item_id, fid)), blobs

    def unwrap(self, uid: str, item_id: str, fid: str, wrapped: str) -> bytes:
        return self._ring.unwrap(wrapped, aad=dek_aad(uid, item_id, fid))

    def open_chunk(
        self, dek: bytes, uid: str, item_id: str, fid: str, n: int, count: int, blob: str
    ) -> bytes:
        return TokenCipher(dek).decrypt(blob, aad=chunk_aad(uid, item_id, fid, n, count))

    def seal_index(self, uid: str, payload: bytes) -> str:
        return self._ring.cipher("vault_index").encrypt(payload, aad=index_aad(uid))

    def open_index(self, uid: str, blob: str) -> bytes:
        return self._ring.cipher("vault_index").decrypt(blob, aad=index_aad(uid))


__all__ = [
    "CHUNK_BYTES",
    "VaultCrypto",
    "chunk_aad",
    "chunk_count",
    "dek_aad",
    "index_aad",
]
