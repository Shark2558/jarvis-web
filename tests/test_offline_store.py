# tests/test_offline_store.py -- R1 C (D10): the deployment-wide laptop-brain config doc
# `<prefix>local_brain/config`. URL and key are stored encrypted with the token key (AAD
# "local_brain/config"); the model, switch and bookkeeping are plain.
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from jarvis.integrations.vault import TokenCipher
from jarvis.offline.store import LocalBrainStore
from jarvis.storage.docs import MemoryDocs, Set

URL = "https://laptop.tail1234.ts.net/v1"
KEY = "k" * 8 + "S3cretKeyValue-abcdefghijklmnop"
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def _cipher() -> TokenCipher:
    return TokenCipher(bytes(range(32)))


def _store(docs: MemoryDocs | None = None, cipher: TokenCipher | None = None) -> LocalBrainStore:
    return LocalBrainStore(docs or MemoryDocs(), cipher or _cipher(), now=lambda: T0)


async def test_nothing_stored_means_not_configured() -> None:
    assert await _store().get() is None


async def test_round_trip_keeps_the_key_secret() -> None:
    st = _store()
    await st.put(url=URL, key=SecretStr(KEY), model="qwen2.5:7b", enabled=True, set_by="u1")
    got = await st.get()
    assert got is not None
    assert got.url == URL and got.model == "qwen2.5:7b" and got.enabled is True
    assert got.set_by == "u1" and got.updated_at == T0 and got.last_ok_at is None
    assert got.key.get_secret_value() == KEY
    assert KEY not in repr(got) and KEY not in str(got)  # SecretStr everywhere


async def test_url_and_key_are_encrypted_at_rest() -> None:
    docs = MemoryDocs()
    await _store(docs).put(url=URL, key=SecretStr(KEY), model="m", enabled=False, set_by="u1")
    raw = await docs.get("jarvis_local_brain/config")
    assert raw is not None
    dump = repr(raw)
    assert KEY not in dump and "ts.net" not in dump and "laptop" not in dump
    assert raw["model"] == "m" and raw["enabled"] is False and raw["set_by"] == "u1"
    assert set(raw) == {"blob", "model", "enabled", "set_by", "updated_at", "last_ok_at"}


async def test_another_token_key_cannot_read_it_and_it_reads_as_not_configured() -> None:
    docs = MemoryDocs()
    await _store(docs).put(url=URL, key=SecretStr(KEY), model="m", enabled=True, set_by="u1")
    other = TokenCipher(os.urandom(32))
    assert await _store(docs, other).get() is None


async def test_a_copied_blob_from_another_document_does_not_decrypt() -> None:
    docs = MemoryDocs()
    c = _cipher()
    blob = c.encrypt(b'{"url": "https://x.a.ts.net/v1", "key": "k"}', aad="some/other/doc")
    await docs.write(
        [
            Set(
                "jarvis_local_brain/config",
                {
                    "blob": blob,
                    "model": "m",
                    "enabled": True,
                    "set_by": "u",
                    "updated_at": T0.isoformat(),
                    "last_ok_at": None,
                },
            )
        ]
    )
    assert await _store(docs, c).get() is None  # AAD is bound to local_brain/config


async def test_garbage_documents_read_as_not_configured() -> None:
    docs = MemoryDocs()
    await docs.write([Set("jarvis_local_brain/config", {"blob": 5, "model": None})])
    assert await _store(docs).get() is None


async def test_set_enabled_flips_only_the_switch() -> None:
    st = _store()
    await st.put(url=URL, key=SecretStr(KEY), model="m", enabled=False, set_by="u1")
    await st.set_enabled(True, by="u2")
    got = await st.get()
    assert got is not None and got.enabled is True and got.set_by == "u2"
    assert got.url == URL and got.key.get_secret_value() == KEY


async def test_set_enabled_with_nothing_stored_is_a_noop() -> None:
    st = _store()
    assert await st.set_enabled(True, by="u") is False
    assert await st.get() is None


async def test_touch_ok_records_the_time_and_changes_nothing_else() -> None:
    st = _store()
    await st.put(url=URL, key=SecretStr(KEY), model="m", enabled=True, set_by="u1")
    later = T0 + timedelta(minutes=3)
    await st.touch_ok(later)
    got = await st.get()
    assert got is not None and got.last_ok_at == later and got.updated_at == T0
    assert got.enabled is True and got.model == "m"


async def test_a_new_address_forgets_the_old_last_ok() -> None:
    st = _store()
    await st.put(url=URL, key=SecretStr(KEY), model="m", enabled=True, set_by="u1")
    await st.touch_ok(T0 + timedelta(minutes=1))
    await st.put(
        url="https://other.tail1234.ts.net/v1",
        key=SecretStr(KEY),
        model="m",
        enabled=True,
        set_by="u1",
    )
    got = await st.get()
    assert got is not None and got.last_ok_at is None


async def test_delete_removes_everything() -> None:
    docs = MemoryDocs()
    st = _store(docs)
    await st.put(url=URL, key=SecretStr(KEY), model="m", enabled=True, set_by="u1")
    await st.delete()
    assert await st.get() is None
    assert await docs.get("jarvis_local_brain/config") is None
    await st.delete()  # idempotent


async def test_prefix_is_honoured() -> None:
    docs = MemoryDocs()
    st = LocalBrainStore(docs, _cipher(), prefix="t_", now=lambda: T0)
    await st.put(url=URL, key=SecretStr(KEY), model="m", enabled=True, set_by="u1")
    assert await docs.get("t_local_brain/config") is not None


async def test_touch_ok_never_creates_a_document() -> None:
    docs = MemoryDocs()
    await _store(docs).touch_ok(T0)
    assert await docs.get("jarvis_local_brain/config") is None


@pytest.mark.parametrize("model", ["", " ", "a" * 200, "bad model", "x;rm", "\u00fcn\u00ef"])
async def test_a_bad_model_name_is_refused_by_the_store(model: str) -> None:
    with pytest.raises(ValueError):
        await _store().put(url=URL, key=SecretStr(KEY), model=model, enabled=True, set_by="u")
