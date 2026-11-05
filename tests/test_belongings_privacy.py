# tests/test_belongings_privacy.py -- R2 D14: the `belongings` privacy source: count, rev, export,
# delete (index and histories gone from MemoryDocs), another owner untouched, no key = unavailable.
from __future__ import annotations

from belongings_fakes import OTHER, UID, things

from jarvis.belongings.privacy import BelongingsPrivacy
from jarvis.privacy.ports import PrivacyRegistry, PrivacySource


async def test_describe_counts_live_things_and_changes_rev_with_the_data() -> None:
    t = things()
    p = BelongingsPrivacy(t.svc)
    assert isinstance(p, PrivacySource)
    empty = await p.describe(UID)
    assert empty.count == 0 and empty.delete == "none"
    await t.svc.put(UID, "Passport", "file")
    await t.svc.put(OTHER, "Keys", "hook")
    one = await p.describe(UID)
    assert one.count == 1 and one.delete == "passkey" and one.encrypted_by_jarvis and one.export
    assert one.rev and one.rev != empty.rev
    await t.svc.put(UID, "Passport", "almirah")
    assert (await p.describe(UID)).rev != one.rev


async def test_registry_lists_it_and_a_failing_store_keeps_its_row() -> None:
    t = things()
    p = BelongingsPrivacy(t.svc)
    reg = PrivacyRegistry()
    reg.register(p)

    async def boom(*_: object) -> None:
        raise RuntimeError("x")

    t.store.load = boom  # type: ignore[method-assign]
    (view,) = await reg.describe_all(UID)
    assert view.id == "belongings" and view.available is False


async def test_export_has_the_list_and_history_and_delete_wipes_only_this_owner() -> None:
    t = things()
    p = BelongingsPrivacy(t.svc)
    await t.svc.put(UID, "Keys", "hook")
    await t.svc.put(UID, "Keys", "drawer")
    await t.svc.put(OTHER, "Keys", "pocket")
    data = await p.export(UID)
    assert data is not None and data["things"][0]["history"][0]["place"] == "hook"
    assert await p.delete(UID) == 1
    dump = str(t.docs._data)  # type: ignore[attr-defined]
    assert f"jarvis_belongings/{UID}" not in dump and f"{UID}_t_" not in dump
    assert (await p.describe(OTHER)).count == 1


async def test_without_a_key_it_says_not_available() -> None:
    p = BelongingsPrivacy(None)
    v = await p.describe(UID)
    assert v.count == 0 and "no encryption key" in v.note and v.delete == "none"
    assert await p.export(UID) is None and await p.delete(UID) == 0
