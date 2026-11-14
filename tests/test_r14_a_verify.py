# tests/test_r14_a_verify.py -- R14 Part A (docs/plans/r14-hardening.md D4 "verifying", review A2):
# the restore drill's checks on a throw-away copy, both sides read only. (1) counts by `count()`
# per collection group over the root ids, the known sub-collections and the activity days, equal
# to Google's document count exactly (an unknown collection fails closed); (2) the newest canary
# within 26 hours before the snapshot is there, matches the live one and opens with the live key;
# (3) a sealed vault item opens through the vault store's own read path, compared on the app's
# own fields (`rev`, `updated_at`), never Firestore's `update_time`; (4) up to 20 documents per
# collection compared with live on their own time field. Nothing compared is a failure; no vault
# is "skipped", never a pass. Resumable within the tick's time.
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
from r14_fakes_a import (
    BACKUP_NAME,
    OTHER_KEY,
    PREFIX,
    RESTAMP_FIELD,
    SNAP,
    UID,
    FakeWalk,
    World,
    data_of,
    ring,
    seed_rest,
    seed_vault,
)

from jarvis.backup import canary, verify, walk_checks
from jarvis.backup.readonly import read_only
from jarvis.backup.vault_probe import probe
from jarvis.keyring import Keyring
from jarvis.storage.docs import Set
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.models import VaultIndex
from jarvis.vault.store import VaultStore

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
NOT_FIRESTORE = frozenset({"v", "events", "export"})  # an AAD's "v1", two Google API URLs


async def _world(*, vault: bool = True, **kw: object) -> World:
    world = World(**kw)  # type: ignore[arg-type]
    keys = ring()
    if vault:
        await seed_vault(world.live, keys)
    await seed_rest(world.live)
    await canary.CanaryStore(world.live, prefix=PREFIX).write(keys, SNAP - dt.timedelta(hours=2))
    world.snapshot()
    return world


def _job(
    world: World, *, keys: Keyring | None = None, the_keys: verify.Keys = verify.APP_KEYS
) -> verify.VerifyJob:
    world.restore_into_drill(BACKUP_NAME)
    walk = FakeWalk(world)
    return verify.VerifyJob(
        walk=walk,
        drill=walk,
        live=read_only(world.live),
        ring=keys or ring(),
        prefix=PREFIX,
        snapshot=SNAP,
        expected=world.backups[-1].document_count or 0,
        owners=(UID,),
        keys=the_keys,
    )


async def _run(job: verify.VerifyJob) -> verify.Progress:
    return await verify.advance(verify.Progress(), job, time_left=lambda: None)


async def test_a_good_copy_passes_and_says_what_it_compared() -> None:
    world = await _world()
    before = (world.live.sets, world.live.deletes)
    p = await _run(_job(world))
    assert p.phase == "done" and p.reason is None and p.canary_ok
    assert p.counted == world.backups[-1].document_count and p.collections > 0
    assert p.vault == "opened" and p.items == 1 and p.files == 1
    assert p.samples > 0
    assert verify.outcome(p) == ("passed", None)
    assert (world.live.sets, world.live.deletes) == before  # the live side was only read


async def test_a_missing_document_fails_the_count() -> None:
    world = await _world()
    world.drop_on_restore = (f"{PREFIX}sessions/s1/turns/000001",)
    p = await _run(_job(world))
    assert verify.outcome(p) == ("failed", "count_mismatch")


async def test_an_unknown_sub_collection_fails_closed() -> None:
    world = World()
    await seed_rest(world.live)
    await world.live.write([Set(f"{PREFIX}notes/n1/mystery/m1", {"at": "x"})])
    await canary.CanaryStore(world.live, prefix=PREFIX).write(ring(), SNAP - dt.timedelta(hours=1))
    world.snapshot()
    p = await _run(_job(world))
    assert verify.outcome(p) == ("failed", "count_mismatch")


async def test_a_changed_key_fails_the_drill() -> None:
    world = await _world()
    p = await _run(_job(world, keys=ring(OTHER_KEY)))
    assert verify.outcome(p) == ("failed", "key")


async def test_a_copy_without_the_days_canary_fails() -> None:
    world = World()
    await seed_vault(world.live, ring())
    await seed_rest(world.live)
    await canary.CanaryStore(world.live, prefix=PREFIX).write(ring(), SNAP - dt.timedelta(hours=30))
    world.snapshot()
    p = await _run(_job(world))
    assert verify.outcome(p) == ("failed", "canary_missing")


async def test_a_canary_that_differs_from_the_live_one_fails() -> None:
    world = await _world()
    day = canary.day_key(SNAP - dt.timedelta(hours=2))
    path = f"{PREFIX}{canary.COLLECTION}/{day}"
    world.tamper_on_restore = {path: canary.make(ring(), day, SNAP - dt.timedelta(hours=2))}
    p = await _run(_job(world))
    assert verify.outcome(p) == ("failed", "canary_mismatch")


async def test_a_restamped_copy_still_compares_on_the_apps_own_fields() -> None:
    world = await _world(restamp=True)
    p = await _run(_job(world))
    assert verify.outcome(p) == ("passed", None) and p.items == 1 and p.samples > 0


async def test_compared_on_firestores_update_time_a_restamped_copy_compares_nothing() -> None:
    world = await _world(restamp=True)
    stamp = verify.Keys(
        doc=lambda d: d.get(RESTAMP_FIELD),
        item=lambda d, item: d.get(RESTAMP_FIELD),
        sample=lambda d: d.get(RESTAMP_FIELD),
    )
    p = await _run(_job(world, the_keys=stamp))
    assert verify.outcome(p) == ("failed", "nothing_compared")


async def test_an_owner_with_no_vault_is_skipped_never_a_pass() -> None:
    world = await _world(vault=False)
    p = await _run(_job(world))
    assert p.vault == "no_vault" and verify.outcome(p) == ("skipped", "no_vault")


async def test_a_vault_missing_from_the_copy_fails() -> None:
    world = await _world()
    world.drop_on_restore = (f"{PREFIX}vault/{UID}",)
    p = await _run(_job(world))
    assert verify.outcome(p)[0] == "failed" and p.reason in ("vault_missing", "count_mismatch")
    check = await probe(
        UID,
        drill=FakeWalk(world),
        live=read_only(world.live),
        ring=ring(),
        prefix=PREFIX,
        snapshot=SNAP,
    )
    assert (check.outcome, check.reason) == ("failed", "vault_missing")


async def _restored(world: World) -> FakeWalk:
    world.restore_into_drill(BACKUP_NAME)
    return FakeWalk(world)


async def _probe(world: World, walk: FakeWalk, keys: Keyring | None = None) -> tuple[str, ...]:
    got = await probe(
        UID, drill=walk, live=read_only(world.live), ring=keys or ring(), prefix=PREFIX,
        snapshot=SNAP,
    )  # fmt: skip
    return (got.outcome, got.reason or "", str(got.items), str(got.files))


async def test_a_vault_item_that_differs_in_the_copy_fails() -> None:
    world = await _world()
    walk = await _restored(world)
    assert world.drill is not None
    store = VaultStore(world.drill, VaultCrypto(ring()), prefix=PREFIX)
    _, index = await store.load(UID)
    other = index.items[0].model_copy(update={"title": "Changed"})
    raw = data_of(world.drill)[f"{PREFIX}vault/{UID}"]
    blob = VaultCrypto(ring()).seal_index(
        UID, VaultIndex(items=(other,)).model_dump_json().encode()
    )
    world.drill._data[f"{PREFIX}vault/{UID}"] = {**raw, "blob": blob}  # noqa: SLF001
    assert (await _probe(world, walk))[:2] == ("failed", "vault_mismatch")


async def test_a_vault_file_that_does_not_open_in_the_copy_fails() -> None:
    world = await _world()
    walk = await _restored(world)
    assert world.drill is not None
    chunk = next(p for p in data_of(world.drill) if "/vault_chunks/" in p)
    world.drill._data[chunk] = {**world.drill._data[chunk], "blob": "AAAA"}  # noqa: SLF001
    assert (await _probe(world, walk))[:2] == ("failed", "vault_file")


async def test_a_vault_sealed_by_another_key_fails_with_key() -> None:
    world = await _world()
    walk = await _restored(world)
    assert (await _probe(world, walk, ring(OTHER_KEY)))[:2] == ("failed", "key")


async def test_a_vault_changed_since_the_snapshot_compares_its_unchanged_items_only() -> None:
    world = await _world()
    walk = await _restored(world)
    store = VaultStore(world.live, VaultCrypto(ring()), prefix=PREFIX)
    await store.change(UID, lambda i: (i, None))  # rev and updated_at move; the item stays
    assert await _probe(world, walk) == ("opened", "", "1", "1")
    later = SNAP + dt.timedelta(hours=3)

    def touch(index: VaultIndex) -> tuple[VaultIndex, None]:
        item = index.items[0].model_copy(update={"title": "Renewed", "updated_at": later})
        return index.model_copy(update={"items": (item,)}), None

    await store.change(UID, touch)
    assert (await _probe(world, walk))[:2] == ("failed", "nothing_compared")


async def test_a_vault_made_after_the_snapshot_is_no_vault_yet() -> None:
    world = await _world(vault=False)
    walk = await _restored(world)
    await seed_vault(world.live, ring())
    raw = data_of(world.live)[f"{PREFIX}vault/{UID}"]
    world.live._data[f"{PREFIX}vault/{UID}"] = {  # noqa: SLF001
        **raw,
        "updated_at": (SNAP + dt.timedelta(hours=1)).isoformat(),
    }
    assert (await _probe(world, walk))[0] == "no_vault"


async def test_a_sample_that_differs_with_the_same_time_fails() -> None:
    world = await _world()
    raw = data_of(world.live)[f"{PREFIX}notes/n1"]
    world.tamper_on_restore = {f"{PREFIX}notes/n1": {**raw, "blob": "other"}}
    p = await _run(_job(world))
    assert verify.outcome(p) == ("failed", "sample_mismatch") and f"{PREFIX}notes" in p.differ


async def test_the_checks_resume_within_the_ticks_time() -> None:
    world = await _world()
    job = _job(world)
    p, steps = verify.Progress(), 0
    left = iter([60.0, 1.0] * 50)
    while p.phase != "done" and steps < 50:
        p = await verify.advance(p, job, time_left=lambda: next(left))
        p = verify.Progress.model_validate(p.model_dump(mode="json"))  # stored between ticks
        steps += 1
    assert verify.outcome(p) == ("passed", None) and steps > 5


async def test_out_of_time_does_nothing() -> None:
    world = await _world()
    p = await verify.advance(verify.Progress(), _job(world), time_left=lambda: 0.5)
    assert p == verify.Progress()


def test_the_content_hash_ignores_reserved_names_and_reads_times() -> None:
    a = {"x": 1, "at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC), RESTAMP_FIELD: "1"}
    b = {"at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "x": 1, RESTAMP_FIELD: "2"}
    assert walk_checks.content_hash(a) == walk_checks.content_hash(b)
    assert walk_checks.content_hash({"x": 2}) != walk_checks.content_hash({"x": 1})
    assert walk_checks.own_time({"updated_at": "u", "at": "a"}) == "u"
    assert walk_checks.own_time({"created_at": "c"}) is None


def test_the_known_sub_collections_are_pinned_against_the_stores() -> None:
    found: set[str] = set()
    pattern = re.compile(r'\}[a-z_]*/\{[^}"]+\}/([a-z_]+)')
    for path in SRC.rglob("*.py"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    stores = found - NOT_FIRESTORE
    assert stores - {"d"} <= set(walk_checks.KNOWN_SUBCOLLECTIONS), stores
    assert "d" in stores  # the activity days, counted from their own index
    assert walk_checks.activity_group("20261113") == "d20261113"


@pytest.mark.parametrize("bad", ["2026111", "x0261113", "../x"])
def test_an_odd_activity_day_is_never_a_group(bad: str) -> None:
    assert walk_checks.activity_group(bad) is None
