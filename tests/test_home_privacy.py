# tests/test_home_privacy.py -- R3 D14: the `home` privacy category (export without keys, simple
# delete = unlink) and the store's remaining edges.
from __future__ import annotations

from pathlib import Path

import pytest
from home_fakes import UID, World, build

from jarvis.home.privacy import HomePrivacy
from jarvis.home.store import HomeStoreUnavailable
from jarvis.privacy.ports import PrivacyRegistry


@pytest.fixture
async def w(tmp_path: Path):
    world = build(tmp_path)
    yield world
    await world.aclose()


async def test_not_linked_and_no_key(w: World) -> None:
    view = await HomePrivacy(w.store).describe(UID)
    assert view.count == 0 and view.delete == "none" and view.export is True
    off = await HomePrivacy(None).describe(UID)
    assert off.count == 0 and "no encryption key" in off.note
    assert await HomePrivacy(None).export(UID) is None and await HomePrivacy(None).delete(UID) == 0


async def test_linked_export_has_no_address_or_key_and_delete_unlinks(w: World) -> None:
    await w.link_up()
    await w.devices.expose(
        UID, [{"entity_id": "light.torch", "class": "everyday", "label": "Torch"}]
    )
    src = HomePrivacy(w.store)
    view = await src.describe(UID)
    assert view.count == 1 and view.delete == "simple" and view.encrypted_by_jarvis and view.rev
    assert view.section == "Home" and view.id == "home"
    data = await src.export(UID)
    assert data is not None and data["linked"] is True
    assert data["devices"] == [{"entity_id": "light.torch", "label": "Torch", "class": "everyday"}]
    assert "tail1234" not in str(data) and "seed" not in str(data)
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0
    assert await src.delete(UID) == 0


async def test_registers_in_the_dashboard(w: World) -> None:
    reg = PrivacyRegistry()
    reg.register(HomePrivacy(w.store))
    views = await reg.describe_all(UID)
    assert [v.id for v in views] == ["home"] and views[0].available


async def test_unreadable_devices_fail_closed_and_are_kept(w: World) -> None:
    await w.link_up()
    await w.store.save_devices(UID, ())
    path = f"jarvis_home_devices/{UID}"
    w.docs._data[path]["blob"] = "junk"  # noqa: SLF001
    with pytest.raises(HomeStoreUnavailable):
        await w.store.load_devices(UID)
    with pytest.raises(HomeStoreUnavailable):
        await w.store.save_devices(UID, ())
    assert w.docs._data[path]["blob"] == "junk"  # noqa: SLF001


async def test_bad_owner_ids_are_refused(w: World) -> None:
    for call in (w.store.load, w.store.status, w.store.load_devices, w.store.unlink):
        with pytest.raises(ValueError):
            await call("../x")  # type: ignore[operator]


async def test_add_dropped_counts(w: World) -> None:
    await w.link_up()
    await w.store.add_dropped(UID)
    await w.store.add_dropped(UID)
    status = await w.store.status(UID)
    assert status is not None and status.dropped_disarmed == 2
    await w.link_up()  # a re-link keeps the count (B shows it)
    status = await w.store.status(UID)
    assert status is not None and status.dropped_disarmed == 2


async def test_find_uses_the_index_after_a_restart(w: World) -> None:
    await w.link_up()
    rec = await w.store.load(UID)
    assert rec is not None
    w.store._by_home.clear()  # noqa: SLF001
    found = await w.store.find(rec.home_id)
    assert found is not None and found[0] == UID
    assert await w.store.find("h_ffffffff") is None and await w.store.find("nope") is None
