# tests/test_r13_b_store.py -- R13 Part B's documents (docs/plans/r13-wardrobe.md "Data model"):
# `wardrobe_laundry/{uid}` and `wardrobe_review/{uid}` sealed with the `wardrobe` key (a shop's
# label, a bag reference and every piece id only inside the blob), `wardrobe_told/{uid}_{key}`
# once-only claims (no seal, B's keys start "laundry_"), every document with `updated_at`. A
# document that can't be opened is never overwritten. B's `WardrobeData` (D20) counts, exports
# in plain JSON and deletes everything of B's.
from __future__ import annotations

from datetime import date

import pytest
from r13_fakes import UID, ev
from r13_fakes_b import BLAZER, TEE, TROUSERS, TWIN, WHITE_SHIRT, rig

from jarvis.storage.docs import Set
from jarvis.wardrobe.laundry.holds import admit
from jarvis.wardrobe.laundry.store import LaundryData, LaundryStore, LaundryUnavailable
from jarvis.wardrobe.ports import WardrobeData


async def test_the_laundry_document_is_sealed_and_names_nothing_in_clear() -> None:
    r = await rig()
    await r.desk.send_out(UID, (BLAZER,), "Corner dry cleaner", bag="Bag 7", due=date(2026, 11, 18))
    raw = await r.docs.get(r.desk.store.laundry_path(UID))
    assert raw is not None and set(raw) == {"v", "kid", "blob", "updated_at"}
    for needle in ("Corner dry cleaner", "Bag 7", BLAZER, "2026-11-18"):
        assert needle not in repr(raw)
    assert "Corner dry cleaner" not in r.text()


async def test_a_document_that_cant_be_opened_is_never_overwritten() -> None:
    r = await rig()
    path = r.desk.store.laundry_path(UID)
    await r.docs.write([Set(path, {"blob": "x"})])
    with pytest.raises(LaundryUnavailable) as no:
        await r.desk.move(UID, "basket", pieces=(TEE,))
    assert (
        str(no.value) == "JARVIS couldn't open your laundry list just now. Try again in a minute."
    )
    assert await r.docs.get(path) == {"blob": "x"} and await r.state(TEE) == "ready"


async def test_claims_are_once_only_and_carry_no_seal_and_his_part_prefix() -> None:
    r = await rig()
    store = r.desk.store
    assert await store.claim(UID, "laundry_overdue_bt_00000001_2026-11-19", r.clock())
    assert not await store.claim(UID, "laundry_overdue_bt_00000001_2026-11-19", r.clock())
    await store.release(UID, "laundry_overdue_bt_00000001_2026-11-19")
    assert await store.claim(UID, "laundry_overdue_bt_00000001_2026-11-19", r.clock())
    with pytest.raises(ValueError):
        await store.claim(UID, "styling_ready_x", r.clock())  # C's prefix: never B's
    (path,) = [p for p in r.docs._data if "wardrobe_told" in p]  # noqa: SLF001
    assert path.endswith(f"{UID}_laundry_overdue_bt_00000001_2026-11-19")
    assert set(r.docs._data[path]) == {"uid", "part", "updated_at"}  # noqa: SLF001


async def test_bs_data_counts_exports_plainly_and_deletes_everything_of_bs() -> None:
    r = await rig()
    (data,) = r.part.data
    assert isinstance(data, WardrobeData) and data.name == "laundry"
    await r.desk.send_out(UID, (BLAZER, TROUSERS), "Dry cleaner")
    await r.commit(admit(ev(TEE, "deposited", r.clock(), source="camera")))
    await r.desk.store.claim(UID, "laundry_review_2026-11-16", r.clock())
    assert await data.count(UID) == 2  # one open batch, one open check
    out = await data.export(UID)
    assert out["batches"][0]["shop"] == "Dry cleaner" and out["review"][0]["kind"] == "hold"
    assert await data.delete(UID) == 3
    assert await data.count(UID) == 0
    assert not [p for p in r.docs._data if "wardrobe_told" in p or "wardrobe_review" in p]  # noqa: SLF001


async def test_without_a_key_the_data_says_nothing_is_kept() -> None:
    r = await rig(keyring=False)
    (data,) = r.part.data
    assert await data.count(UID) == 0 and await data.export(UID) == {
        "loads": [],
        "batches": [],
        "review": [],
    }


async def test_m7_without_a_key_delete_still_deletes_and_count_says_what_remains() -> None:
    r = await rig()
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))  # the queue
    await r.desk.send_out(UID, (BLAZER,), "Dry cleaner")  # the laundry list
    await r.desk.store.claim(UID, "laundry_review_2026-11-16", r.clock())
    prefix = r.desk.store.laundry_path(UID).split("wardrobe_laundry/")[0]
    nokey = LaundryData(LaundryStore(r.docs, None, prefix=prefix))  # the key is gone
    for read in (nokey.count, nokey.export):
        with pytest.raises(LaundryUnavailable) as kept:
            await read(UID)  # never "0" while sealed records remain
        assert str(kept.value) == (
            "Laundry records are kept on this server, but it has no token key to read them. "
            "They can still be deleted."
        )
    assert await nokey.delete(UID) == 3  # deleting needs no key
    bs = ("wardrobe_laundry/", "wardrobe_review/", "wardrobe_told/")
    assert not [p for p in r.docs._data if any(c in p for c in bs)]  # noqa: SLF001
    assert await nokey.count(UID) == 0 and await nokey.export(UID) == {
        "loads": [],
        "batches": [],
        "review": [],
    }
