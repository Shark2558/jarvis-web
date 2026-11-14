# evals/r14/backup.py
"""R14 eval, Part A's suite (`backup`, BUILT): backups and the restore drill (docs/plans/
r14-hardening.md D3, D4, "Per item" A), on in-memory fakes only: nothing calls Google and nothing
is spent (`tests/r14_fakes_a.py`: the live database, its backups and the drill copy in memory; the
real adapters run against recording fake SDK clients).

Cases: a whole drill passes on fakes and deletes its copy; a missing document fails the count; a
changed key fails; a restamped copy (a restore that stamps a new `update_time`) still compares on
the app's own fields; a vault changed since the snapshot never passes vacuously ("nothing
compared"); the live side is never written (the verifier holds only reads on both sides); a
`(default)` or live target is refused before any Google call; empty backup stats never start a
drill; a stale backup alerts once; nothing alerts before the set-up; the copy is deleted whatever
the switches say.

Negative controls (the suite must fail under each): (1) the verifier's read-only view swapped for
the writable store -> "no live write" fails; (2) comparisons keyed on Firestore's `update_time`
with restamped copies -> nothing is compared and the drill does not pass -> "restamped copy still
compares" fails.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r14_fakes_a import (  # noqa: E402
    IST,
    OTHER_KEY,
    PREFIX,
    PROJECT,
    RESTAMP_FIELD,
    SNAP,
    UID,
    FakeAdmin,
    FakeAdminClient,
    FakeWalk,
    RecordingNotifier,
    World,
    ring,
    seed_rest,
    seed_vault,
)

from jarvis.backup import canary, verify  # noqa: E402
from jarvis.backup.drill import Drill, DrillDeps  # noqa: E402
from jarvis.backup.jobs import BackupCanaryJob  # noqa: E402
from jarvis.backup.log import DrillLog, DrillResult  # noqa: E402
from jarvis.backup.ports import LiveTargetRefused  # noqa: E402
from jarvis.backup.readonly import read_only  # noqa: E402
from jarvis.backup.status import BackupStatusService, Teller  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.keyring import Keyring  # noqa: E402
from jarvis.storage.docs import Set  # noqa: E402
from jarvis.storage.firestore_admin import FirestoreAdmin  # noqa: E402
from jarvis.storage.firestore_walk import FirestoreWalk  # noqa: E402
from jarvis.vault.crypto import VaultCrypto  # noqa: E402
from jarvis.vault.store import VaultStore  # noqa: E402

PART = "backup"
BUILT = True
DAY1 = dt.datetime(2026, 12, 1, 0, 0, tzinfo=dt.UTC)  # 05:30 in Kolkata, the drill day
OWNERS = (UID,)
View = Callable[[Any], Any]
STAMP_KEYS = verify.Keys(
    doc=lambda d: d.get(RESTAMP_FIELD),
    item=lambda d, item: d.get(RESTAMP_FIELD),
    sample=lambda d: d.get(RESTAMP_FIELD),
)


class Clock:
    def __init__(self, at: dt.datetime) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, user_timezone="Asia/Kolkata", **kw)


async def _world(**kw: Any) -> World:
    world = World(**kw)
    await seed_vault(world.live, ring())
    await seed_rest(world.live)
    await canary.CanaryStore(world.live, prefix=PREFIX, zone=IST).write(
        ring(), SNAP - dt.timedelta(hours=2)
    )
    world.snapshot()
    return world


class Rig:
    """A drill on fakes; `view` makes the live side the verifier holds; `keys` its comparisons."""

    def __init__(
        self, world: World, *, view: View, keys: verify.Keys, s: Settings | None = None,
        key: Keyring | None = None,
    ) -> None:  # fmt: skip
        self.world, self.clock, self.sent = world, Clock(DAY1), RecordingNotifier()
        self.admin = FakeAdmin(world)
        self.log = DrillLog(world.live, prefix=PREFIX, clock=self.clock, zone=IST)
        self.status = BackupStatusService(
            world.live, self.log, prefix=PREFIX, clock=self.clock, zone=IST
        )

        async def rate() -> float:
            return 95.24

        self.deps = DrillDeps(
            s=s or _settings(), admin=self.admin, walk=lambda: FakeWalk(world),
            live=view(world.live), log=self.log, status=self.status,
            teller=Teller(self.status, lambda: self.sent), ring=key or ring(), rate=rate,
            clock=self.clock, prefix=PREFIX, time_left=lambda: None, keys=keys,
        )  # fmt: skip
        self.drill = Drill(self.deps)

    async def ready(self) -> Rig:
        await self.status.refresh(self.admin)
        return self

    async def run(self, ticks: int = 8) -> DrillResult | None:
        for _ in range(ticks):
            said = await self.drill.step(OWNERS)
            self.clock.at += dt.timedelta(minutes=30)
            if said in ("done", "refused"):
                break
        return await self.log.last_result()


# ---- the cases ------------------------------------------------------------------------------
async def _passes(view: View, keys: verify.Keys) -> list[str]:
    rig = await Rig(await _world(restore_polls=2), view=view, keys=keys).ready()
    last = await rig.run()
    if last is None or last.outcome != "passed":
        return [f"not passed: {last.words if last else 'no result'}"]
    out = [] if last.items and last.samples and last.files else ["nothing compared"]
    return out + ([] if rig.world.drill is None else ["the copy is still there"])


async def _missing_document(view: View, keys: verify.Keys) -> list[str]:
    world = await _world()
    world.drop_on_restore = (f"{PREFIX}sessions/s1/turns/000001",)
    last = await (await Rig(world, view=view, keys=keys).ready()).run()
    return [] if last is not None and last.reason == "count_mismatch" else ["the count passed"]


async def _changed_key(view: View, keys: verify.Keys) -> list[str]:
    rig = await Rig(await _world(), view=view, keys=keys, key=ring(OTHER_KEY)).ready()
    last = await rig.run()
    return [] if last is not None and last.reason == "key" else ["a changed key passed"]


async def _restamped(view: View, keys: verify.Keys) -> list[str]:
    last = await (await Rig(await _world(restamp=True), view=view, keys=keys).ready()).run()
    if last is None or last.outcome != "passed" or not last.items or not last.samples:
        return [f"a restamped copy did not compare: {last.words if last else 'no result'}"]
    return []


async def _vacuous(view: View, keys: verify.Keys) -> list[str]:
    world = await _world()
    rig = await Rig(world, view=view, keys=keys).ready()
    store = VaultStore(world.live, VaultCrypto(ring()), prefix=PREFIX)

    def renew(index: Any) -> tuple[Any, None]:
        item = index.items[0].model_copy(update={"updated_at": SNAP + dt.timedelta(hours=9)})
        return index.model_copy(update={"items": (item,)}), None

    await store.change(UID, renew)  # nothing of the vault is comparable any more
    last = await rig.run()
    return ["passed with nothing compared"] if last is None or last.outcome == "passed" else []


async def _no_live_write(view: View, keys: verify.Keys) -> list[str]:
    rig = await Rig(await _world(), view=view, keys=keys).ready()
    held, out = rig.deps.live, []
    for name in ("write", "transaction"):
        if hasattr(held, name):
            out.append(f"the verifier's live side has {name}")
    try:
        await held.write([Set(f"{PREFIX}planted/x", {"x": 1})])
        out.append("a write through the verifier's live side went through")
    except AttributeError:
        pass
    start = len(rig.world.live.log)
    await rig.run()
    own = {f"{PREFIX}backup_drill", f"{PREFIX}backup_drills", f"{PREFIX}backup_status"}
    stray = {op.path.split("/")[0] for op in rig.world.live.log[start:]} - own
    return out + ([f"the drill wrote {sorted(stray)}"] if stray else [])


async def _target_refused(view: View, keys: verify.Keys) -> list[str]:
    client, out = FakeAdminClient(), []
    admin = FirestoreAdmin(project=PROJECT, live="live-db", client=client)
    for database in ("(default)", "live-db"):
        for call in (admin.restore("projects/x/locations/y/backups/b", database),
                     admin.delete_database(database), admin.get_database(database)):  # fmt: skip
            try:
                await call
                out.append(f"{database} was not refused")
            except LiveTargetRefused:
                pass
    try:
        FirestoreWalk(project=PROJECT, live="live-db", database="(default)")
        out.append("the drill reader took (default)")
    except LiveTargetRefused:
        pass
    return out + ([f"{len(client.calls)} Google calls"] if client.calls else [])


async def _empty_stats(view: View, keys: verify.Keys) -> list[str]:
    world = await _world()
    world.backups[-1] = replace(world.backups[-1], size_bytes=None, document_count=None)
    rig = await Rig(world, view=view, keys=keys).ready()
    said = await rig.drill.step(OWNERS)
    return [] if said == "waiting" and "restore" not in rig.admin.names() else [f"said {said}"]


async def _stale_once(view: View, keys: verify.Keys) -> list[str]:
    world, clock, sent = World(), Clock(SNAP + dt.timedelta(hours=40)), RecordingNotifier()
    world.snapshot()
    log = DrillLog(world.live, prefix=PREFIX, zone=IST)
    status = BackupStatusService(world.live, log, prefix=PREFIX, clock=clock, zone=IST)
    canaries = canary.CanaryStore(world.live, prefix=PREFIX, zone=IST)
    job = BackupCanaryJob(s=_settings(), canaries=canaries,
                          status=status, teller=Teller(status, lambda: sent),
                          admin=FakeAdmin(world), ring=ring(), clock=clock)  # fmt: skip
    for _ in range(4):
        await job.run(OWNERS)
        clock.at += dt.timedelta(minutes=30)
    got = sent.kinds().count(("backup_problem", "stale"))
    return [] if got == 1 else [f"{got} stale alerts"]


async def _quiet_before_set_up(view: View, keys: verify.Keys) -> list[str]:
    rig = Rig(await _world(denied=True), view=view, keys=keys)
    await rig.status.refresh(rig.admin)
    said = await rig.drill.step(OWNERS)
    return [] if said == "not_set_up" and not rig.sent.sent else [f"said {said}"]


async def _cleanup_whatever(view: View, keys: verify.Keys) -> list[str]:
    world = await _world()
    world.restore_into_drill(world.backups[-1].name)
    off = _settings(backup_drill_enabled=False, backup_checks_enabled=False)
    rig = await Rig(world, view=view, keys=keys, s=off).ready()
    await rig.drill.step(OWNERS)
    names = rig.admin.names()
    left = ["the copy is still there"] if world.drill is not None else []
    return left + (["a restore ran"] if "restore" in names else [])


CASES: dict[str, Callable[[View, verify.Keys], Awaitable[list[str]]]] = {
    "drill_passes_on_fakes": _passes,
    "missing_document_fails_the_count": _missing_document,
    "changed_key_fails": _changed_key,
    "restamped_copy_still_compares": _restamped,
    "nothing_compared_never_passes": _vacuous,
    "no_live_write": _no_live_write,
    "default_target_refused_before_the_call": _target_refused,
    "empty_stats_never_start": _empty_stats,
    "stale_backup_alerts_once": _stale_once,
    "nothing_alerts_before_the_set_up": _quiet_before_set_up,
    "cleanup_whatever_the_switches": _cleanup_whatever,
}


async def _run(view: View, keys: verify.Keys) -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        try:
            failures = await case(view, keys)
        except Exception as exc:  # noqa: BLE001 - a case that raises fails, by class only
            failures = [f"raised {type(exc).__name__}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run(read_only, verify.APP_KEYS)


def _writable(docs: Any) -> Any:
    return docs  # control 1: the verifier holds the writable live store


async def control() -> dict[str, Any]:
    writable = [r["id"] for r in await _run(_writable, verify.APP_KEYS) if not r["passed"]]
    stamped = [r["id"] for r in await _run(read_only, STAMP_KEYS) if not r["passed"]]
    want = (f"{PART}:no_live_write", f"{PART}:restamped_copy_still_compares")
    return {
        "name": "writable live store for the verifier + comparisons on update_time",
        "suite_failed": want[0] in writable and want[1] in stamped,
        "failed_cases": sorted(set(writable) | set(stamped)),
    }


__all__ = ["BUILT", "PART", "cases", "control"]
