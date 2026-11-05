# tests/test_kb_service.py -- R2 C: NotesService add / update / remove / restore / purge / search /
# fetch / export / import / wipe.
from __future__ import annotations

import pytest
from kb_fakes import OTHER, UID, Rig, build_rig, scan

from jarvis.kb.models import MAX_LIVE, NotesError, vouches
from jarvis.undo.models import RestoreStatus
from jarvis.undo.service import StillThere


async def add(r: Rig, text: str = "The plumber is Ravi, comes on Tuesdays.", **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {"kind": "note", "text": text, "origin": "typed"}
    args.update(kw)
    return await r.svc.add(UID, **args)  # type: ignore[arg-type]


async def test_add_stores_an_encrypted_note_and_finds_it() -> None:
    r = build_rig()
    n = await add(r)
    assert n.id.startswith("n_") and n.kind == "note" and vouches(n)
    assert scan(r.docs, "plumber", "Ravi") == []
    hits = await r.svc.search(UID, "who is the plumber")
    assert [h.note.id for h in hits] == [n.id]


async def test_add_a_link_keeps_the_address_without_any_network_call() -> None:
    r = build_rig()
    n = await add(r, kind="link", text="", url="https://Example.com/a#x", owner_note="read later")
    assert n.url == "https://example.com/a" and n.title == "example.com/a" and n.page is None
    assert r.fake.requests == []


async def test_sensitive_and_bad_input_store_nothing() -> None:
    r = build_rig()
    with pytest.raises(NotesError) as e:
        await add(r, "card 4111 1111 1111 1111")
    assert e.value.code == "sensitive"
    with pytest.raises(NotesError):
        await add(r, kind="link", text="", url="http://example.com/")
    assert (await r.store.load(UID)).notes == ()


async def test_the_live_limit_is_enforced() -> None:
    r = build_rig()
    from jarvis.kb import service as mod

    original = mod.MAX_LIVE
    mod.MAX_LIVE = 2  # type: ignore[misc]
    try:
        await add(r, "one")
        await add(r, "two")
        with pytest.raises(NotesError) as e:
            await add(r, "three")
        assert e.value.code == "notes_full" and e.value.status == 409
    finally:
        mod.MAX_LIVE = original  # type: ignore[misc]
    assert MAX_LIVE == 2_000


async def test_owners_are_separate() -> None:
    r = build_rig()
    n = await add(r)
    assert await r.svc.search(OTHER, "plumber") == []
    with pytest.raises(NotesError) as e:
        await r.svc.get(OTHER, n.id)
    assert e.value.status == 404


async def test_update_rechecks_and_keeps_the_worse_origin() -> None:
    r = build_rig()
    n = await add(r, origin="outside")
    up = await r.svc.update(UID, n.id, text="changed text here", origin="typed")
    assert (
        up.text == "changed text here" and up.origin == "outside" and up.updated_at >= n.updated_at
    )
    with pytest.raises(NotesError) as e:
        await r.svc.update(UID, n.id, text="password: hunter2hunter2")
    assert e.value.code == "sensitive"
    assert (await r.svc.get(UID, n.id)).text == "changed text here"


async def test_a_console_edit_that_rewrites_the_text_is_the_owners_own() -> None:
    r = build_rig()
    n = await add(r, origin="outside")
    up = await r.svc.update(UID, n.id, text="rewritten by the owner", reviewed=True)
    assert up.origin == "typed"
    again = await r.svc.update(UID, n.id, title="only a title", origin="voice")
    assert again.origin == "voice"


async def test_remove_keeps_a_generic_bin_entry_and_restore_brings_it_back_in_place() -> None:
    r = build_rig()
    n = await add(r)
    item = await r.svc.remove(UID, n.id, session_id="s1")
    assert item.kind == "note" and item.snapshot == {"ref": n.id}
    assert "plumber" not in item.title.lower() and item.title.startswith("A note from ")
    assert item.owner_authored is True
    assert await r.svc.search(UID, "plumber") == []
    out = await r.undo.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED and out.new_id == n.id
    assert out.message == "Restored the note."
    assert [h.note.id for h in await r.svc.search(UID, "plumber")] == [n.id]
    again = await r.undo.restore(UID, item.id)
    assert again.status is RestoreStatus.ALREADY_RESTORED


async def test_restoring_an_outside_note_keeps_it_outside() -> None:
    r = build_rig()
    n = await add(r, origin="outside")
    item = await r.svc.remove(UID, n.id)
    assert item.owner_authored is False
    await r.undo.restore(UID, item.id)
    assert not vouches(await r.svc.get(UID, n.id))


async def test_restore_of_a_live_or_missing_note_makes_nothing() -> None:
    r = build_rig()
    n = await add(r)
    item = await r.svc.remove(UID, n.id)
    await r.svc.restore(UID, item)
    with pytest.raises(StillThere):
        await r.svc.restore(UID, item)
    await r.svc.purge(UID, (await r.svc.remove(UID, n.id)))
    with pytest.raises(NotesError):
        await r.svc.restore(UID, item)


async def test_remove_without_a_bin_deletes_nothing() -> None:
    r = build_rig(with_undo=False)
    n = await add(r)
    with pytest.raises(NotesError) as e:
        await r.svc.remove(UID, n.id)
    assert e.value.status == 503 and e.value.code == "undo_unavailable"
    assert (await r.svc.get(UID, n.id)).id == n.id


async def test_a_failed_tombstone_drops_the_bin_copy() -> None:
    r = build_rig()
    n = await add(r)
    original = r.store.change

    async def broken(*a, **k):  # type: ignore[no-untyped-def]
        raise NotesError(503, "notes_unavailable", "down")

    r.store.change = broken  # type: ignore[method-assign]
    with pytest.raises(NotesError):
        await r.svc.remove(UID, n.id)
    r.store.change = original  # type: ignore[method-assign]
    assert await r.undo.recent(UID) == []


async def test_purge_hard_deletes_only_a_tombstoned_unrestored_note() -> None:
    r = build_rig()
    n = await add(r)
    item = await r.svc.remove(UID, n.id)
    assert await r.undo.purge(UID, item.id) is True
    assert [x for x in (await r.store.load(UID)).notes] == []
    await r.svc.purge(UID, item)  # twice is fine
    # a restored note must survive its old bin entry being swept
    m = await add(r, "keep me around")
    it2 = await r.svc.remove(UID, m.id)
    await r.undo.restore(UID, it2.id)
    stored = await r.undo.store.get(UID, it2.id)
    assert stored is not None
    await r.svc.purge(UID, stored)
    assert (await r.svc.get(UID, m.id)).id == m.id


async def test_the_bin_sweep_hard_deletes_after_thirty_days() -> None:
    r = build_rig()
    n = await add(r)
    await r.svc.remove(UID, n.id)
    r.clock.advance(days=31)
    await r.undo.sweep([UID])
    assert (await r.store.load(UID)).notes == ()


async def test_fetch_saves_the_page_excerpt_and_the_note_stops_vouching() -> None:
    r = build_rig()
    n = await add(r, kind="link", text="", url="https://example.com/story")
    r.fake.pages["https://example.com/story"] = "Story title\n\nSome words about monsoon."
    got = await r.svc.fetch(UID, n.id)
    assert got.page is not None and "monsoon" in got.page.excerpt and not vouches(got)
    assert scan(r.docs, "monsoon") == []
    assert [h.note.id for h in await r.svc.search(UID, "monsoon")] == [n.id]
    assert (await r.allowance.usage()).credits == 1


async def test_fetch_is_for_links_and_is_rate_limited() -> None:
    r = build_rig()
    n = await add(r)
    with pytest.raises(NotesError) as e:
        await r.svc.fetch(UID, n.id)
    assert e.value.code == "input_rejected"
    link = await add(r, kind="link", text="", url="https://example.com/s")
    r.fake.pages["https://example.com/s"] = "Title\n\ntext"
    for _ in range(10):
        await r.svc.fetch(UID, link.id)
    with pytest.raises(NotesError) as e2:
        await r.svc.fetch(UID, link.id)
    assert e2.value.code == "rate_limited" and e2.value.status == 429


async def test_browse_lists_newest_first_in_pages_with_counts() -> None:
    r = build_rig()
    for i in range(25):
        await add(r, f"note number {i}")
        r.clock.advance(minutes=1)
    await add(r, "a memo", kind="memo", origin="memo")
    page1 = await r.svc.browse(UID)
    assert page1.total == 26 and len(page1.items) == 20 and page1.pages == 2
    assert page1.items[0].text == "a memo"
    page2 = await r.svc.browse(UID, page=2)
    assert len(page2.items) == 6
    assert (await r.svc.browse(UID, kind="memo")).total == 1
    assert page1.counts == {"note": 25, "memo": 1, "link": 0}


async def test_browse_with_a_query_returns_ranked_hits_with_snippets() -> None:
    r = build_rig()
    await add(r, "The plumber is Ravi.")
    await add(r, "Bin day is Tuesday.")
    res = await r.svc.browse(UID, q="plumber")
    assert res.total == 1 and "plumber" in (res.items[0].snippet or "").lower()


async def test_export_then_wipe_then_import_is_identical() -> None:
    r = build_rig()
    a = await add(r, "first note", tags=["x", "y"])
    b = await add(r, kind="link", text="", url="https://example.com/s", owner_note="why")
    r.fake.pages["https://example.com/s"] = "Title\n\nbody words"
    await r.svc.fetch(UID, b.id)
    c = await add(r, "memo text", kind="memo", origin="memo")
    gone = await add(r, "will be deleted")
    await r.svc.remove(UID, gone.id)
    before = {n.id: n for n in (await r.store.load(UID)).notes if n.live}
    data = await r.svc.export(UID)
    assert data["format"] == "jarvis-notes" and len(data["notes"]) == 3
    assert await r.svc.wipe(UID) == 3
    assert (await r.store.load(UID)).notes == ()
    res = await r.svc.import_(UID, data)
    assert (res.added, res.skipped) == (3, 0)
    back = {n.id: n for n in (await r.store.load(UID)).notes}
    assert set(back) == {a.id, b.id, c.id}
    for old in (a, b, c):
        assert back[old.id] == before[old.id]
    assert back[b.id].page is not None and not vouches(back[b.id])


async def test_import_skips_sensitive_invalid_duplicates_and_keeps_worse_origins() -> None:
    r = build_rig()
    base = {
        "kind": "note",
        "title": "t",
        "text": "fine words",
        "origin": "outside",
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-01T00:00:00Z",
    }
    data = {
        "format": "jarvis-notes",
        "version": 1,
        "notes": [
            {**base, "id": "n_000000000001"},
            {**base, "id": "n_000000000001"},  # duplicate id
            {**base, "id": "n_000000000002", "text": "card 4111 1111 1111 1111"},
            {**base, "id": "n_000000000003", "kind": "link", "url": "http://x.example/"},
            {"nonsense": True},
            "not a dict",
        ],
    }
    res = await r.svc.import_(UID, data)
    assert (res.added, res.skipped) == (1, 5)
    assert (await r.svc.get(UID, "n_000000000001")).origin == "outside"
    with pytest.raises(NotesError):
        await r.svc.import_(UID, {"format": "something-else", "notes": []})


async def test_wipe_leaves_other_owners_and_counts() -> None:
    r = build_rig()
    await add(r)
    await r.svc.add(OTHER, kind="note", text="theirs", origin="typed")
    assert await r.svc.wipe(UID) == 1
    assert len((await r.store.load(OTHER)).notes) == 1
    assert (await r.svc.counts(UID)) == {"note": 0, "memo": 0, "link": 0, "deleted": 0}


async def test_unreadable_store_fails_closed_for_every_operation() -> None:
    r = build_rig()
    n = await add(r)
    for path in list(r.docs._data):
        if "kb_shards" in path:
            r.docs._data[path]["blob"] = "AAAA"
    r.store._known.clear()
    for coro in (r.svc.search(UID, "x"), r.svc.get(UID, n.id), add(r, "more")):
        with pytest.raises(NotesError) as e:
            await coro
        assert e.value.status == 503
