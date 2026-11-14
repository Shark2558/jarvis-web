# tests/test_r14_a_locks.py -- R14 Part A (docs/plans/r14-hardening.md D4 "Unable to write live"):
# the drill's code can't write the live database. (1) the verifier reads both sides through a
# read-only view (get and query only, not a `Docs`); (2) the admin adapter and the drill-side
# reader refuse any database but `jarvis-drill`, and `(default)` and the live id, BEFORE any Google
# call (`backup.ports.drill_target`); (3) the checks' modules import neither the live store's SDK
# adapter nor the drill's log; (5) the adapters refuse a live database named `jarvis-drill`.
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from r14_fakes_a import PROJECT, SNAP
from r14_fakes_a_sdk import FakeAdminClient, FakeFirestoreClient, google_error, sdk_backup

from jarvis.backup.ports import DRILL_DB, LiveTargetRefused
from jarvis.backup.readonly import ReadOnly, read_only
from jarvis.storage.docs import Docs, MemoryDocs, Query, Set
from jarvis.storage.firestore_admin import FirestoreAdmin
from jarvis.storage.firestore_walk import FirestoreWalk

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
CHECKS = ("verify", "walk_checks", "vault_probe")
FORBIDDEN = ("jarvis.storage.firestore_docs", "jarvis.backup.log")


# ---- (1) the read-only view -----------------------------------------------------------------
async def test_the_read_only_view_reads_and_cannot_write() -> None:
    docs = MemoryDocs()
    await docs.write([Set("c/a", {"x": 1}), Set("c/b", {"x": 2})])
    view = read_only(docs)
    assert await view.get("c/a") == {"x": 1}
    assert [i for i, _ in await view.query(Query("c"))] == ["a", "b"]
    assert not isinstance(view, Docs)
    for name in ("write", "transaction", "close", "_data", "__dict__"):
        assert not hasattr(view, name), name
    with pytest.raises(AttributeError):
        view.write = lambda ops: None  # type: ignore[attr-defined]
    before = (docs.sets, docs.deletes)
    await view.get("c/a")
    assert (docs.sets, docs.deletes) == before


def test_a_read_only_view_of_a_view_is_the_same_view() -> None:
    view = read_only(MemoryDocs())
    assert read_only(view) is view and isinstance(view, ReadOnly)


# ---- (2) the admin adapter ------------------------------------------------------------------
@pytest.mark.parametrize("database", ["(default)", "live-db", "other", "", "jarvis-drill2"])
async def test_the_admin_refuses_every_target_but_the_drill_copy_before_any_call(
    database: str,
) -> None:
    client = FakeAdminClient()
    admin = FirestoreAdmin(project=PROJECT, live="live-db", client=client)
    for call in (
        admin.restore(f"projects/{PROJECT}/locations/asia-south1/backups/b1", database),
        admin.get_database(database),
        admin.set_delete_protection(database, False),
        admin.delete_database(database),
    ):
        with pytest.raises(LiveTargetRefused):
            await call
    assert client.calls == []


def test_the_admin_will_not_run_with_the_drill_id_as_the_live_database() -> None:
    with pytest.raises(LiveTargetRefused):
        FirestoreAdmin(project=PROJECT, live=DRILL_DB, client=FakeAdminClient())


async def test_the_admin_acts_only_on_the_drill_copy() -> None:
    client = FakeAdminClient()
    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=client)
    backup = f"projects/{PROJECT}/locations/asia-south1/backups/b1"
    op = await admin.restore(backup, DRILL_DB)
    assert op == f"projects/{PROJECT}/databases/{DRILL_DB}/operations/o1"
    assert await admin.operation_done(op) is True
    info = await admin.get_database(DRILL_DB)
    assert info is not None and info.database == DRILL_DB and info.delete_protection is False
    await admin.set_delete_protection(DRILL_DB, False)
    await admin.delete_database(DRILL_DB)
    target = f"projects/{PROJECT}/databases/{DRILL_DB}"
    restore = client.calls[0][1]
    assert restore == {"parent": f"projects/{PROJECT}", "database_id": DRILL_DB, "backup": backup}
    assert ("get_database", target) in client.calls and ("delete_database", target) in client.calls
    update = next(c[1] for c in client.calls if c[0] == "update_database")
    assert update["database"]["name"] == target
    assert update["update_mask"] == {"paths": ["delete_protection_state"]}
    assert update["database"]["delete_protection_state"] == "DELETE_PROTECTION_DISABLED"


async def test_a_gone_drill_copy_reads_as_none_and_protection_is_seen() -> None:
    client = FakeAdminClient(exists=False)
    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=client)
    assert await admin.get_database(DRILL_DB) is None
    client.exists, client.protection = True, "DELETE_PROTECTION_ENABLED"
    info = await admin.get_database(DRILL_DB)
    assert info is not None and info.delete_protection is True


async def test_googles_no_permission_becomes_a_plain_permission_error() -> None:
    class Denied(FakeAdminClient):
        async def list_backups(self, *, parent: str) -> object:
            raise google_error("PermissionDenied", "no backups permission for this account")

    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=Denied())
    with pytest.raises(PermissionError) as got:
        await admin.list_backups()
    assert "account" not in str(got.value)  # fixed words, never Google's text


async def test_an_operation_on_another_database_is_refused_before_the_call() -> None:
    client = FakeAdminClient()
    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=client)
    with pytest.raises(LiveTargetRefused):
        await admin.operation_done(f"projects/{PROJECT}/databases/(default)/operations/o9")
    assert client.calls == []


async def test_a_backup_of_another_project_is_never_restored() -> None:
    client = FakeAdminClient()
    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=client)
    with pytest.raises(ValueError, match="backup"):
        await admin.restore("projects/someone-else/locations/x/backups/b1", DRILL_DB)
    assert client.calls == []


async def test_the_admin_lists_only_the_live_databases_backups_with_their_stats() -> None:
    client = FakeAdminClient(
        backups=[
            sdk_backup(size=0, count=0),  # READY, stats not filled yet
            sdk_backup(size=2048, count=12),
            sdk_backup(database="other-db", size=5, count=1),
            sdk_backup(state="CREATING"),
        ]
    )
    admin = FirestoreAdmin(project=PROJECT, live="(default)", client=client)
    got = await admin.list_backups()
    assert [(b.state, b.size_bytes, b.document_count) for b in got] == [
        ("READY", None, None),
        ("READY", 2048, 12),
        ("CREATING", None, None),
    ]
    assert [b.stats_ready for b in got] == [False, True, False]
    assert all(b.database == "(default)" and b.snapshot_time == SNAP for b in got)
    assert client.calls == [("list_backups", f"projects/{PROJECT}/locations/-")]
    assert await admin.schedules() == [f"projects/{PROJECT}/databases/(default)/backupSchedules/s"]


# ---- (2) the drill-side reader --------------------------------------------------------------
@pytest.mark.parametrize("database", ["(default)", "live-db", "anything"])
def test_the_drill_reader_refuses_any_database_but_the_drill_copy(database: str) -> None:
    with pytest.raises(LiveTargetRefused):
        FirestoreWalk(project=PROJECT, live="live-db", database=database, client=None)


def test_the_drill_reader_refuses_when_the_live_database_is_the_drill_id() -> None:
    with pytest.raises(LiveTargetRefused):
        FirestoreWalk(project=PROJECT, live=DRILL_DB, client=FakeFirestoreClient())


async def test_the_drill_reader_counts_samples_and_reads() -> None:
    data = {
        "jarvis_a/1": {"x": 1},
        "jarvis_a/2": {"x": 2},
        "jarvis_a/1/turns/t1": {"y": 1},
        "jarvis_b/9": {"z": 9},
    }
    client = FakeFirestoreClient(data)
    walk = FirestoreWalk(project=PROJECT, live="(default)", client=client)
    assert await walk.collections() == ["jarvis_a", "jarvis_b"]
    assert await walk.count("jarvis_a") == 2 and await walk.count("turns") == 1
    assert [i for i, _ in await walk.sample("jarvis_a", 1)] == ["1"]
    assert await walk.get("jarvis_b/9") == {"z": 9} and await walk.get("jarvis_b/0") is None
    assert [i for i, _ in await walk.query(Query("jarvis_a", limit=5))] == ["1", "2"]
    for name in ("write", "transaction"):
        assert not hasattr(walk, name), name


@pytest.mark.parametrize("group", ["", "a/b", "x" * 1600])
async def test_the_drill_reader_refuses_an_odd_collection_id(group: str) -> None:
    client = FakeFirestoreClient()
    walk = FirestoreWalk(project=PROJECT, live="(default)", client=client)
    with pytest.raises(ValueError):
        await walk.count(group)
    assert client.calls == []


# ---- (3) the imports ------------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("module", CHECKS)
def test_the_checks_import_neither_the_live_store_nor_the_log(module: str) -> None:
    names = _imports(SRC / "backup" / f"{module}.py")
    for bad in FORBIDDEN:
        assert not any(n == bad or n.startswith(bad + ".") for n in names), (module, bad)
    assert "google.cloud" not in " ".join(names)


@pytest.mark.parametrize("module", ["firestore_admin", "firestore_walk"])
def test_every_google_call_of_the_adapters_passes_drill_target_first(module: str) -> None:
    text = (SRC / "storage" / f"{module}.py").read_text(encoding="utf-8")
    assert "drill_target(" in text
    assert "jarvis.storage.firestore_docs" not in text
