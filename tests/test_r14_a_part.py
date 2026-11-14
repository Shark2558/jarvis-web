# tests/test_r14_a_part.py -- R14 Part A's join (docs/plans/r14-hardening.md "Part split" A, D3, D4,
# D12): `backup.part.build` through the real wiring; its two tools (`vitals_backups` R1, and
# `vitals_drill_start` R2 that always asks: a card, never part of Approve all); its Vitals items
# (`backups`, `backup_drill`, `db_size`: "not set up" before the owner's step, the real figure
# after the first copy); the "Backups" privacy row; its jobs and its one service `backup_status`;
# and its routes `GET /v1/backup` and `POST /v1/backup/drill` (the same card, his conversation,
# rate-limited per owner), owner-only and `no-store`.
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r14_fakes_a import (
    GIB,
    SNAP,
    UID,
    FakeAdmin,
    FakeWalk,
    World,
    ring,
)

from jarvis.api import create_app
from jarvis.api import r14_wiring as wiring
from jarvis.backup import part as backup_part
from jarvis.backup.log import DrillResult
from jarvis.backup.privacy import BackupsPrivacy
from jarvis.backup.tools import NO_FIRESTORE_LINE, SHOW, START, BackupDesk
from jarvis.backup.vitals import NOT_SET_UP_NOTE
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk, AskReason, PendingAction
from jarvis.hardening.ports import VITALS_IDS, HardeningContext, HardeningPart
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.context import tool_context

TZ = ZoneInfo("Asia/Kolkata")
NOW = SNAP + dt.timedelta(hours=3)
KEYED = ring()
CSRF = {"X-Requested-With": "JARVIS"}


def _ctx(s: Settings, docs: MemoryDocs | None) -> HardeningContext:
    state: dict[str, Any] = {}
    return HardeningContext(s=s, docs=docs, audit=None, state=state.get)


def _built(
    s: Settings, world: World, *, admin: bool = True, keys: Keyring | None = KEYED
) -> HardeningPart:
    return backup_part.build_with(
        _ctx(s, world.live),
        admin=FakeAdmin(world) if admin else None,
        walk=lambda: FakeWalk(world),
        keys=keys,
        clock=lambda: NOW,
    )


def _desk(part: HardeningPart) -> BackupDesk:
    desk = part.services["backup"]
    assert isinstance(desk, BackupDesk)
    return desk


# ---- the part ---------------------------------------------------------------------------------
def test_the_part_keeps_its_contract_through_the_real_wiring(settings: Settings) -> None:
    built = wiring.build_parts(_ctx(settings, MemoryDocs()))
    part = built["backup"]
    assert part.ready != wiring.SETUP_FAILED
    assert [t.name for t in part.tools] == [SHOW, START]
    assert [j.name for j in part.daily_jobs] == ["backup_canary", "backup_drill"]
    assert part.clock_jobs == () and [p.id for p in part.privacy] == ["backups"]
    assert callable(getattr(part.services["backup_status"], "facts", None))
    assert len(part.vitals) == 1


def test_without_firestore_the_part_says_so_and_keeps_its_tools(settings: Settings) -> None:
    part = backup_part.build(_ctx(settings, MemoryDocs()))
    assert part.ready == backup_part.NO_FIRESTORE
    assert [t.name for t in part.tools] == [SHOW, START]


def test_without_a_document_store_there_is_nothing_to_keep(settings: Settings) -> None:
    part = backup_part.build(_ctx(settings, None))
    assert part.ready == backup_part.NO_STORE and part.tools == ()


def test_the_real_adapters_are_made_only_for_firestore(settings: Settings) -> None:
    from jarvis.config import SessionBackend
    from jarvis.storage.firestore_admin import FirestoreAdmin

    s = settings.model_copy(
        update={"session_backend": SessionBackend.FIRESTORE, "firestore_project": "proj-example"}
    )
    admin = backup_part.admin_for(s)
    assert isinstance(admin, FirestoreAdmin)
    assert backup_part.admin_for(settings) is None
    assert backup_part.admin_for(s.model_copy(update={"firestore_project": None})) is None


async def test_the_part_counts_days_and_months_on_his_clock(settings: Settings) -> None:
    clock = {"at": dt.datetime(2026, 11, 13, 22, 45, tzinfo=dt.UTC)}  # 04:15 in Kolkata
    world = World()
    part = backup_part.build_with(
        _ctx(settings, world.live), admin=FakeAdmin(world), walk=lambda: FakeWalk(world),
        keys=ring(), clock=lambda: clock["at"],
    )  # fmt: skip
    desk = _desk(part)
    assert await desk.status.claim("stale")
    clock["at"] = dt.datetime(2026, 11, 14, 0, 15, tzinfo=dt.UTC)  # 05:45, the same morning
    assert not await desk.status.claim("stale")
    assert desk.log.month_of(dt.datetime(2026, 11, 30, 23, 30, tzinfo=dt.UTC)) == "202612"


# ---- the tools --------------------------------------------------------------------------------
async def test_the_two_tools_and_the_drill_card(settings: Settings) -> None:
    world = World()
    part = _built(settings, world)
    show, start = part.tools
    assert show.risk is ActionRisk.READ_ONLY and show.agent == "vitals"
    assert start.risk is ActionRisk.REVERSIBLE and start.asks({}) is True
    card = start.summary({})
    assert "restore drill" in card and "₹100" in card and "2 a month" in card
    with tool_context(f"{UID}:s1"):
        said = await show.run({})
    assert said["set_up"] is False and "aren't set up" in said["spoken"]
    with tool_context(f"{UID}:s1", confirmed=True):
        ran = await start.run({})
    assert "aren't set up" in ran["message"]


def test_the_tool_names_can_be_imported_by_the_guardrails_without_a_cycle() -> None:
    import ast
    import os
    import subprocess
    import sys
    from pathlib import Path

    from jarvis.backup import names, tools

    assert (tools.SHOW, tools.START) == (names.SHOW, names.START) == (SHOW, START)
    source = Path(names.__file__).read_text(encoding="utf-8")
    imports = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Import | ast.ImportFrom)]
    assert [getattr(n, "module", None) for n in imports] == ["__future__"]
    probe = (
        "import sys, jarvis.backup.names; "
        "print(any(m.startswith('jarvis.core') for m in sys.modules))"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(names.__file__).resolve().parents[2])}
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, env=env
    )
    assert done.stdout.strip() == "False"  # core/guardrails.py may import it at its top


def test_the_drill_card_is_never_part_of_approve_all() -> None:
    card = PendingAction(
        tool=START,
        arguments={},
        risk=ActionRisk.IRREVERSIBLE,
        tool_risk=ActionRisk.REVERSIBLE,
        summary="Start a restore drill",
        reason=AskReason.OWNER_RULE,
    )
    assert card.bulk_ok is False


async def test_after_the_set_up_the_tool_says_the_last_copy_and_the_drill(
    settings: Settings,
) -> None:
    world = World()
    world.snapshot(document_count=11)
    part = _built(settings, world)
    desk = _desk(part)
    await desk.status.refresh(FakeAdmin(world))
    await desk.log.record(DrillResult(outcome="passed", at=SNAP - dt.timedelta(days=13)))
    with tool_context(f"{UID}:s1"):
        said = await part.tools[0].run({})
    assert said["set_up"] is True and said["copies"] == 1 and said["size_mb"] == 100.0
    assert said["last_copy"] == SNAP.isoformat() and said["drill"] == "passed"
    assert said["month_inr"] == pytest.approx(3.81, abs=0.01)
    assert "14 Nov, 08:30" in said["spoken"] and "passed" in said["spoken"]
    assert "7 days" in said["spoken"]


# ---- Vitals -----------------------------------------------------------------------------------
async def _items(part: HardeningPart) -> dict[str, Any]:
    (read,) = part.vitals
    got = await read(UID, NOW, TZ)
    assert all(i.provider.id in VITALS_IDS for i in got)
    return {i.provider.id: i for i in got}


async def test_vitals_says_not_set_up_and_nothing_else_before_his_step(settings: Settings) -> None:
    items = await _items(_built(settings, World()))
    assert list(items) == ["backups"]
    assert items["backups"].base == ("unknown", "is not set up")
    assert "backup_setup.sh" in items["backups"].provider.note


async def test_vitals_after_the_first_copy_shows_the_real_figure(settings: Settings) -> None:
    world = World()
    world.snapshot(document_count=11)
    part = _built(settings, world)
    await _desk(part).status.refresh(FakeAdmin(world))
    items = await _items(part)
    assert set(items) == {"backups", "backup_drill", "db_size"}
    assert items["backups"].base[0] == "ok" and "₹3.81" in items["backups"].provider.note
    assert items["backup_drill"].base == ("unknown", "hasn't run yet")
    size = items["db_size"].provider
    assert (size.limit, size.used, size.unit, size.kind) == (1024.0, 100.0, "MB", "storage")


async def test_vitals_marks_a_stale_copy_and_a_failed_drill(settings: Settings) -> None:
    world = World()
    world.snapshot(document_count=11)
    part = _built(settings, world)
    desk = _desk(part)
    await desk.status.refresh(FakeAdmin(world))
    await desk.log.record(DrillResult(outcome="failed", reason="count_mismatch", at=NOW))
    (read,) = part.vitals
    later = {i.provider.id: i for i in await read(UID, SNAP + dt.timedelta(hours=40), TZ)}
    assert later["backups"].base[0] == "amber"
    assert later["backup_drill"].base[0] == "red" and "count" in later["backup_drill"].base[1]
    world.schedules.clear()
    await desk.status.refresh(FakeAdmin(world))
    later = {i.provider.id: i for i in await read(UID, NOW, TZ)}
    assert later["backups"].base[0] == "red"


async def test_vitals_says_skipped_for_no_vault(settings: Settings) -> None:
    world = World()
    world.snapshot(size_bytes=int(0.9 * GIB), document_count=11)
    part = _built(settings, world)
    desk = _desk(part)
    await desk.status.refresh(FakeAdmin(world))
    await desk.log.record(DrillResult(outcome="skipped", reason="no_vault", at=NOW))
    items = await _items(part)
    assert items["backup_drill"].base[0] == "amber"
    assert items["db_size"].provider.used == pytest.approx(921.6, abs=0.1)


async def _after_set_up(settings: Settings, **kw: Any) -> tuple[HardeningPart, BackupDesk]:
    world = World()
    world.snapshot(document_count=11)
    part = _built(settings, world, **kw)
    desk = _desk(part)
    await desk.status.refresh(FakeAdmin(world))
    return part, desk


async def _spoken(part: HardeningPart) -> str:
    with tool_context(f"{UID}:s1"):
        said = await part.tools[0].run({})
    return str(said["spoken"])


async def test_a_pass_older_than_forty_days_is_overdue_and_an_old_one_has_its_year(
    settings: Settings,
) -> None:
    part, desk = await _after_set_up(settings)
    await desk.log.record(DrillResult(outcome="passed", at=NOW - dt.timedelta(days=41)))
    item = (await _items(part))["backup_drill"]
    assert item.base == ("amber", "is overdue") and "4 Oct" in item.provider.note
    assert "overdue" in await _spoken(part)
    part, desk = await _after_set_up(settings)
    await desk.log.record(DrillResult(outcome="passed", at=NOW - dt.timedelta(days=200)))
    assert "28 Apr 2026" in (await _items(part))["backup_drill"].provider.note


async def test_a_drill_skipped_because_it_was_switched_off_says_so(settings: Settings) -> None:
    part, desk = await _after_set_up(settings)
    await desk.log.record(DrillResult(outcome="skipped", reason="switched_off", at=NOW))
    item = (await _items(part))["backup_drill"]
    assert item.base == ("unknown", "was skipped: switched off")
    assert "vault" not in item.provider.note and "switched off" in await _spoken(part)


async def test_a_count_mismatch_shows_both_counts(settings: Settings) -> None:
    part, desk = await _after_set_up(settings)
    failed = DrillResult(
        outcome="failed", reason="count_mismatch", at=NOW, expected=1_204, counted=1_198
    )
    await desk.log.record(failed)
    note = (await _items(part))["backup_drill"].provider.note
    assert "1,204" in note and "1,198" in note
    summary = await desk.summary()
    assert (summary["drill_expected"], summary["drill_counted"]) == (1_204, 1_198)


async def test_without_a_key_vitals_says_the_drill_cannot_run(settings: Settings) -> None:
    part, _ = await _after_set_up(settings, keys=None)
    item = (await _items(part))["backup_drill"]
    assert item.base[0] == "amber" and "key" in item.base[1]


async def test_off_firestore_the_drill_card_says_why_not_set_up(settings: Settings) -> None:
    part = _built(settings, World(), admin=False)
    with tool_context(f"{UID}:s1", confirmed=True):
        ran = await part.tools[1].run({})
    assert ran["message"] == NO_FIRESTORE_LINE and "Firestore" in ran["message"]


def test_the_set_up_note_says_about_four_rupees_at_100_mb() -> None:
    assert "about ₹4 a month at 100 MB" in NOT_SET_UP_NOTE and "₹5" not in NOT_SET_UP_NOTE


async def test_a_live_rate_that_fails_falls_back_to_the_setting_and_says_so(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    class Fx:
        async def rate(self) -> object:
            raise RuntimeError("the rate source is down")

    billing = type("Billing", (), {"fx": Fx()})()
    world = World()
    ctx = HardeningContext(s=settings, docs=world.live, audit=None, state={"billing": billing}.get)
    part = backup_part.build_with(
        ctx, admin=FakeAdmin(world), walk=lambda: FakeWalk(world), keys=ring(), clock=lambda: NOW
    )
    with caplog.at_level("WARNING"):
        assert await _desk(part).rate() == settings.usd_inr_rate
    assert any("rate" in r.getMessage() for r in caplog.records)


# ---- Privacy ----------------------------------------------------------------------------------
async def test_the_backups_privacy_row(settings: Settings) -> None:
    world = World()
    part = _built(settings, world)
    (row,) = part.privacy
    assert isinstance(row, BackupsPrivacy)
    view = await row.describe(UID)
    assert view.id == "backups" and view.delete == "none" and view.export is False
    assert view.count == 0 and "Not set up" in view.note
    world.snapshot(document_count=11)
    await _desk(part).status.refresh(FakeAdmin(world))
    view = await row.describe(UID)
    assert view.count == 1 and "7 days" in view.retention and "delete" in view.what
    assert "jarvis-drill" in view.note  # the name is the drill's: a database by it is deleted
    assert await row.export(UID) is None and await row.delete(UID) == 0


# ---- the routes, in the real app ---------------------------------------------------------------
@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_the_app_wires_part_a(settings: Settings) -> None:
    async with running(settings) as (app, client):
        part = app.state.r14_parts["backup"]
        assert part.ready == backup_part.NO_FIRESTORE
        for name in (SHOW, START):
            assert app.state.gateway.registry.get(name) is not None
        assert "backups" in app.state.privacy.registry.ids()
        assert wiring.backup_status(app) is part.services["backup_status"]
        r = await client.get("/v1/backup")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["part"] == "backup" and body["ready"] == backup_part.NO_FIRESTORE
        assert body["set_up"] is False and body["drill"] is None


async def test_the_drill_route_makes_the_same_card_in_his_conversation(settings: Settings) -> None:
    async with running(settings) as (_, client):
        none = await client.post("/v1/backup/drill", json={}, headers=CSRF)
        assert none.status_code == 409 and none.json()["error"] == "no_conversation"
        chat = await client.post("/v1/chat", json={"message": "hello"})
        sid = chat.json()["session_id"]
        r = await client.post("/v1/backup/drill", json={"session_id": sid}, headers=CSRF)
        assert r.status_code == 202, r.text
        assert r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["status"] == "awaiting" and "restore drill" in body["card"]
        ok = await client.post(
            f"/v1/approvals/{body['approval_id']}/approve", json={"session_id": sid}, headers=CSRF
        )
        assert ok.status_code == 200, ok.text
        bad = await client.post("/v1/backup/drill", json={"session_id": "x y"}, headers=CSRF)
        assert bad.status_code == 422


async def test_the_drill_route_is_rate_limited_per_owner(settings: Settings) -> None:
    async with running(settings) as (_, client):
        chat = await client.post("/v1/chat", json={"message": "hello"})
        sid = chat.json()["session_id"]
        codes = [
            (
                await client.post("/v1/backup/drill", json={"session_id": sid}, headers=CSRF)
            ).status_code
            for _ in range(6)
        ]
        assert codes[0] == 202 and codes[-1] == 429


async def test_the_routes_need_the_owner(settings: Settings) -> None:
    from pydantic import SecretStr

    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr("t" * 32)})
    async with running(s) as (_, client):
        assert (await client.get("/v1/backup")).status_code == 401
        assert (await client.post("/v1/backup/drill", json={}, headers=CSRF)).status_code == 401
