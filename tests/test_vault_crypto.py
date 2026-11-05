# tests/test_vault_crypto.py -- R2 D2: envelope encryption, AAD on everything, fail closed
from __future__ import annotations

import pytest
from vault_fakes import ring

from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.vault import crypto
from jarvis.vault.crypto import CHUNK_BYTES, VaultCrypto, chunk_count

DATA = bytes(range(256)) * 5000  # 1.28 MB: 3 chunks
U, IT, F = "u_a", "v_000000000001", "f_000000000001"


def test_chunk_count_and_sizes() -> None:
    assert chunk_count(0) == 1 and chunk_count(1) == 1
    assert chunk_count(CHUNK_BYTES) == 1 and chunk_count(CHUNK_BYTES + 1) == 2
    assert chunk_count(10 * 1024 * 1024) == 20
    _, blobs = VaultCrypto(ring()).seal(U, IT, F, DATA)
    assert len(blobs) == 3 and all(len(b) < 1_000_000 for b in blobs)


def test_full_size_chunk_fits_a_firestore_document() -> None:
    _, blobs = VaultCrypto(ring()).seal(U, IT, F, b"z" * CHUNK_BYTES)
    assert 690_000 < len(blobs[0]) < 710_000


def test_round_trip() -> None:
    c = VaultCrypto(ring())
    wrapped, blobs = c.seal(U, IT, F, DATA)
    dek = c.unwrap(U, IT, F, wrapped)
    out = b"".join(c.open_chunk(dek, U, IT, F, n, len(blobs), b) for n, b in enumerate(blobs))
    assert out == DATA
    assert DATA[:64] not in "".join(blobs).encode()


def test_empty_file_is_one_chunk() -> None:
    c = VaultCrypto(ring())
    wrapped, blobs = c.seal(U, IT, F, b"")
    dek = c.unwrap(U, IT, F, wrapped)
    assert c.open_chunk(dek, U, IT, F, 0, 1, blobs[0]) == b""


def test_tampered_chunk_refused() -> None:
    c = VaultCrypto(ring())
    wrapped, blobs = c.seal(U, IT, F, DATA)
    dek = c.unwrap(U, IT, F, wrapped)
    bad = blobs[0][:-4] + ("AAAA" if blobs[0][-4:] != "AAAA" else "BBBB")
    with pytest.raises(VaultError):
        c.open_chunk(dek, U, IT, F, 0, 3, bad)


@pytest.mark.parametrize(
    ("uid", "item", "fid"),
    [("u_b", IT, F), (U, "v_000000000002", F), (U, IT, "f_000000000002")],
)
def test_chunk_moved_to_another_owner_item_or_file_refused(uid: str, item: str, fid: str) -> None:
    c = VaultCrypto(ring())
    wrapped, blobs = c.seal(U, IT, F, DATA)
    dek = c.unwrap(U, IT, F, wrapped)
    with pytest.raises(VaultError):
        c.open_chunk(dek, uid, item, fid, 0, 3, blobs[0])


def test_reordered_and_truncated_refused() -> None:
    c = VaultCrypto(ring())
    wrapped, blobs = c.seal(U, IT, F, DATA)
    dek = c.unwrap(U, IT, F, wrapped)
    with pytest.raises(VaultError):
        c.open_chunk(dek, U, IT, F, 1, 3, blobs[0])  # swapped position
    with pytest.raises(VaultError):
        c.open_chunk(dek, U, IT, F, 0, 2, blobs[0])  # told the file is shorter


@pytest.mark.parametrize(
    "args", [("u_b", IT, F), (U, "v_000000000002", F), (U, IT, "f_000000000002")]
)
def test_wrapped_key_bound_to_owner_item_file(args: tuple[str, str, str]) -> None:
    c = VaultCrypto(ring())
    wrapped, _ = c.seal(U, IT, F, DATA)
    with pytest.raises(VaultError):
        c.unwrap(*args, wrapped)


def test_wrong_root_key_refused() -> None:
    wrapped, _ = VaultCrypto(ring()).seal(U, IT, F, DATA)
    other = VaultCrypto(Keyring(bytes(range(40, 72))))
    with pytest.raises(VaultError):
        other.unwrap(U, IT, F, wrapped)


def test_index_round_trip_and_swap_refused() -> None:
    c = VaultCrypto(ring())
    blob = c.seal_index(U, b'{"a":1}')
    assert c.open_index(U, blob) == b'{"a":1}'
    with pytest.raises(VaultError):
        c.open_index("u_b", blob)  # another owner's index put here


def test_chunk_aad_binds_position_and_count() -> None:
    a = crypto.chunk_aad(U, IT, F, 0, 3)
    assert a != crypto.chunk_aad(U, IT, F, 1, 3) and a != crypto.chunk_aad(U, IT, F, 0, 4)
