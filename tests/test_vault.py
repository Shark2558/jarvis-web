# tests/test_vault.py — slice 6: encrypted Google token vault (AES-256-GCM, AAD = user id)
from __future__ import annotations

import base64
import json
import os

import pytest

from jarvis.integrations.vault import (
    DocTokenStore,
    GoogleTokens,
    MemoryTokenStore,
    TokenCipher,
    VaultError,
    decode_key,
)
from jarvis.storage.docs import MemoryDocs

KEY = os.urandom(32)
KEY_B64 = base64.b64encode(KEY).decode()


def _tokens(**over: object) -> GoogleTokens:
    base: dict[str, object] = {
        "email": "akash@example.com",
        "access_token": "ya29.access",
        "refresh_token": "1//refresh",
        "expires_at": 1_800_000_000.0,
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }
    base.update(over)
    return GoogleTokens.model_validate(base)


# ---- key handling ---------------------------------------------------------------------------


def test_decode_key_accepts_32_byte_base64_and_urlsafe() -> None:
    assert decode_key(KEY_B64) == KEY
    assert decode_key(base64.urlsafe_b64encode(KEY).decode()) == KEY


@pytest.mark.parametrize("bad", ["", "not base64!!", base64.b64encode(b"short").decode()])
def test_decode_key_rejects_wrong_length_or_garbage(bad: str) -> None:
    with pytest.raises(VaultError):
        decode_key(bad)


# ---- cipher ---------------------------------------------------------------------------------


def test_cipher_round_trip_and_fresh_nonce() -> None:
    c = TokenCipher(KEY)
    ct1 = c.encrypt(b"secret", aad="u_1")
    ct2 = c.encrypt(b"secret", aad="u_1")
    assert ct1 != ct2  # random nonce every time
    assert c.decrypt(ct1, aad="u_1") == b"secret"
    assert "secret" not in ct1


def test_cipher_rejects_tamper_wrong_user_and_wrong_key() -> None:
    c = TokenCipher(KEY)
    ct = c.encrypt(b"secret", aad="u_1")
    with pytest.raises(VaultError):
        c.decrypt(ct, aad="u_2")  # ciphertext copied onto another user's document
    raw = bytearray(base64.b64decode(ct))
    raw[-1] ^= 0x01
    with pytest.raises(VaultError):
        c.decrypt(base64.b64encode(bytes(raw)).decode(), aad="u_1")
    with pytest.raises(VaultError):
        TokenCipher(os.urandom(32)).decrypt(ct, aad="u_1")
    with pytest.raises(VaultError):
        c.decrypt("@@not-base64@@", aad="u_1")


# ---- stores ---------------------------------------------------------------------------------


async def test_memory_store_round_trip_and_delete() -> None:
    st = MemoryTokenStore()
    assert await st.get("u_1") is None
    await st.put("u_1", _tokens())
    got = await st.get("u_1")
    assert got == _tokens() and got is not None
    await st.delete("u_1")
    assert await st.get("u_1") is None
    await st.delete("u_1")  # idempotent


async def test_doc_store_persists_only_ciphertext() -> None:
    docs = MemoryDocs()
    st = DocTokenStore(docs, key=KEY, prefix="t_")
    await st.put("u_1", _tokens())
    raw = await docs.get("t_tokens/u_1")
    assert raw is not None
    blob = json.dumps(raw)
    assert "ya29.access" not in blob and "1//refresh" not in blob
    assert raw["email"] == "akash@example.com" and raw["needs_reconnect"] is False
    assert await st.get("u_1") == _tokens()
    await st.delete("u_1")
    assert await docs.get("t_tokens/u_1") is None and await st.get("u_1") is None


async def test_doc_store_refuses_ciphertext_copied_to_another_user() -> None:
    docs = MemoryDocs()
    st = DocTokenStore(docs, key=KEY, prefix="t_")
    await st.put("u_1", _tokens())
    doc = await docs.get("t_tokens/u_1")
    assert doc is not None
    from jarvis.storage.docs import Set

    await docs.write([Set("t_tokens/u_2", doc)])
    with pytest.raises(VaultError):
        await st.get("u_2")


async def test_doc_store_with_wrong_key_fails_closed() -> None:
    docs = MemoryDocs()
    await DocTokenStore(docs, key=KEY, prefix="t_").put("u_1", _tokens())
    with pytest.raises(VaultError):
        await DocTokenStore(docs, key=os.urandom(32), prefix="t_").get("u_1")


async def test_doc_store_rejects_unsafe_ids() -> None:
    st = DocTokenStore(MemoryDocs(), key=KEY)
    with pytest.raises(ValueError):
        await st.put("../x", _tokens())
    assert await st.get("a/b") is None


def test_tokens_never_repr_secrets() -> None:
    t = _tokens()
    assert "ya29" not in repr(t) and "1//refresh" not in str(t)
    assert t.access_token.get_secret_value() == "ya29.access"


# ---- security review L7: weak keys fail at start-up ------------------------------------------


@pytest.mark.parametrize(
    "weak",
    [
        bytes(32),  # all zero ("A" * 43 + "=")
        bytes([1]) * 32,
        bytes(range(15)) * 2 + bytes([0, 1]),  # only 15 distinct byte values
    ],
)
def test_decode_key_rejects_low_entropy_keys(weak: bytes) -> None:
    with pytest.raises(VaultError, match="weak"):
        decode_key(base64.b64encode(weak).decode())


def test_decode_key_accepts_sixteen_distinct_values() -> None:
    ok = bytes(range(16)) * 2
    assert decode_key(base64.b64encode(ok).decode()) == ok


# ---- security review L4: a malformed document reads as "reconnect", never a crash ------------


async def _doc_with(docs: MemoryDocs, user: str, **fields: object) -> None:
    from jarvis.storage.docs import Set

    await docs.write([Set(f"t_tokens/{user}", dict(fields))])


def _blob(plain: bytes, user: str = "u_1") -> str:
    return TokenCipher(KEY).encrypt(plain, aad=user)


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "a@b.c", "expires_at": 1.0},  # no blob
        {"email": "a@b.c", "expires_at": 1.0, "blob": _blob(b"not json")},
        {"email": "a@b.c", "expires_at": 1.0, "blob": _blob(b"[1, 2]")},
        {"email": "a@b.c", "expires_at": 1.0, "blob": _blob(b'{"access_token": "x"}')},
        {
            "email": "a@b.c",
            "expires_at": "soon",
            "blob": _blob(b'{"access_token": "x", "refresh_token": "y"}'),
        },
        {"expires_at": 1.0, "blob": _blob(b'{"access_token": "x", "refresh_token": "y"}')},
        {
            "email": "a@b.c",
            "expires_at": 1.0,
            "scopes": 5,
            "blob": _blob(b'{"access_token": "x", "refresh_token": "y"}'),
        },
        {"email": "a@b.c", "expires_at": 1.0, "blob": 12345},
    ],
)
async def test_malformed_document_is_a_vault_error(fields: dict[str, object]) -> None:
    docs = MemoryDocs()
    await _doc_with(docs, "u_1", **fields)
    with pytest.raises(VaultError):
        await DocTokenStore(docs, key=KEY, prefix="t_").get("u_1")
