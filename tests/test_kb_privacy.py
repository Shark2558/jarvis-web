# tests/test_kb_privacy.py -- R2 C: the notes category of the privacy dashboard (D14).
from __future__ import annotations

import pytest
from kb_fakes import OTHER, UID, build_rig, scan

from jarvis.kb.privacy import NotesPrivacy
from jarvis.privacy import PrivacyRegistry, PrivacySource


async def seeded():  # type: ignore[no-untyped-def]
    r = build_rig()
    await r.svc.add(UID, kind="note", text="alpha one", origin="typed")
    await r.svc.add(UID, kind="memo", text="beta two", origin="memo")
    await r.svc.add(UID, kind="link", text="", url="https://example.com/a", origin="typed")
    gone = await r.svc.add(UID, kind="note", text="gamma three", origin="typed")
    await r.svc.remove(UID, gone.id)
    await r.svc.add(OTHER, kind="note", text="theirs only", origin="typed")
    return r, NotesPrivacy(r.svc)


async def test_it_is_a_privacy_source_the_registry_accepts() -> None:
    r, src = await seeded()
    assert isinstance(src, PrivacySource)
    reg = PrivacyRegistry()
    reg.register(src)
    (view,) = await reg.describe_all(UID)
    assert view.id == "notes" and view.available


async def test_describe_counts_only_this_owners_live_items() -> None:
    _, src = await seeded()
    v = await src.describe(UID)
    assert v.count == 3 and v.unit == "items"
    assert v.encrypted_by_jarvis and v.export and v.delete == "passkey" and not v.recoverable
    assert "1" in v.note and "Recently deleted" in v.note
    assert (await src.describe(OTHER)).count == 1
    assert (await src.describe("u_nobody")).count == 0


async def test_rev_changes_when_the_data_changes() -> None:
    r, src = await seeded()
    before = (await src.describe(UID)).rev
    assert before and before == (await src.describe(UID)).rev
    await r.svc.add(UID, kind="note", text="another", origin="typed")
    assert (await src.describe(UID)).rev != before


async def test_export_has_exactly_the_owners_live_notes() -> None:
    _, src = await seeded()
    data = await src.export(UID)
    assert data is not None and data["format"] == "jarvis-notes"
    texts = sorted(n["text"] for n in data["notes"])
    assert texts == ["", "alpha one", "beta two"]
    assert await src.export("u_nobody") is None


async def test_delete_removes_the_data_and_nothing_else() -> None:
    r, src = await seeded()
    assert await src.delete(UID) == 3
    assert (await src.describe(UID)).count == 0
    assert [p for p in r.docs._data if "jarvis_kb" in p and UID in p] == []
    assert (await src.describe(OTHER)).count == 1
    assert scan(r.docs, "alpha one", "beta two") == []


async def test_a_failing_store_shows_the_unavailable_row_instead_of_vanishing() -> None:
    r, src = await seeded()

    async def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    r.store.summary = boom  # type: ignore[method-assign]
    reg = PrivacyRegistry()
    reg.register(src)
    (view,) = await reg.describe_all(UID)
    assert view.id == "notes" and not view.available and view.count is None
    with pytest.raises(RuntimeError):
        await src.describe(UID)
