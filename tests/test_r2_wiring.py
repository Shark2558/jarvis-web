# tests/test_r2_wiring.py -- R2 I1: the app wires the vault, notes, things, the DigiLocker inbox,
# the privacy dashboard and the tick jobs (api/personal.py), each OFF with plain words without the
# token key; the vault's extractor is the sandboxed `DocumentService.extract`; the upload path has
# its own body cap; Activity never shows a note's words; offline mode never offers an R2 tool.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from drive_fakes import FakeDrive, StaticTokens
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.activity.store import day_key
from jarvis.api import create_app
from jarvis.api.personal import (
    NOTES_OFF,
    RESERVED_JOB_NAMES,
    OwnerSweep,
    personal_tick_jobs,
)
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.kb.service import NOT_CONFIGURED
from jarvis.llm.base import ToolCall
from jarvis.llm.fallback import OFFLINE_TOOLS
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import run_jobs
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.policy import Effect, PolicyRule
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

KEY = SecretStr(base64.b64encode(bytes(range(1, 33))).decode())
UID = "owner"
H = {"X-Requested-With": "JARVIS"}
SECRET = "the spare key is under the blue flowerpot"
R2_TOOLS = {
    "vault_list",
    "vault_expiring",
    "vault_set_dates",
    "kb_search",
    "kb_read",
    "kb_add_note",
    "kb_save_link",
    "kb_update",
    "kb_remove",
    "belongings_where",
    "belongings_list",
    "belongings_history",
    "belongings_put",
    "belongings_remove",
}


@dataclass
class App:
    app: Any
    client: AsyncClient
    undo: UndoBin


async def _app(s: Settings, *, drive: DriveService | None = None) -> AsyncIterator[App]:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    app = create_app(
        s, provider=MockProvider(), store=InMemorySessionStore(), undo=undo, drive=drive
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield App(app, c, undo)


def keyed(settings: Settings, **kw: Any) -> Settings:
    return settings.model_copy(update={"token_key": KEY, "tools_enabled": True, **kw})


@pytest.fixture
async def on(settings: Settings) -> AsyncIterator[App]:
    async for a in _app(keyed(settings)):
        yield a


@pytest.fixture
async def off(settings: Settings) -> AsyncIterator[App]:
    async for a in _app(settings.model_copy(update={"tools_enabled": True})):
        yield a


def _drive() -> DriveService:
    return DriveService(
        DriveClient(StaticTokens(), http=FakeDrive().client()), RootsStore(MemoryDocs())
    )


# ---- on / off ----------------------------------------------------------------------------------


async def test_with_the_token_key_every_feature_is_on_and_its_tools_are_registered(on: App) -> None:
    st = on.app.state
    assert st.vault is not None and st.vault_unlock is not None and st.vault_reminders is not None
    assert st.notes is not None and st.belongings is not None
    names = {s.name for s in st.gateway.registry.specs()}
    assert names >= R2_TOOLS


async def test_undo_tools_present_with_bin_without_google(on: App) -> None:
    """R2 review M2: no Google link, yet notes and things can be deleted with Undo, so the model
    can also list and restore them."""
    st = on.app.state
    assert st.google is None
    names = {s.name for s in st.gateway.registry.specs()}
    assert {"kb_remove", "belongings_remove", "deleted_list", "deleted_restore"} <= names


async def test_the_vault_reads_pdfs_only_through_the_sandboxed_extractor(on: App) -> None:
    st = on.app.state
    assert st.vault._extract == st.documents.extract  # the documents' one child-process slot


async def test_restorers_and_purgers_are_registered_for_the_three_kinds(on: App) -> None:
    for kind in ("vault_item", "note", "thing"):
        assert kind in on.undo._restorers and kind in on.undo._purgers


async def test_the_brief_gets_the_documents_section(on: App) -> None:
    assert on.app.state.brief._vault_due is not None


async def test_without_the_token_key_everything_is_off_with_plain_words(off: App) -> None:
    st = off.app.state
    assert st.vault is None and st.notes is None and st.belongings is None
    assert st.vault_inbox is None and st.tick_jobs == ()
    assert st.notes_reason == NOT_CONFIGURED
    names = {s.name for s in st.gateway.registry.specs()}
    assert not names & R2_TOOLS
    v = (await off.client.get("/v1/vault")).json()
    assert v["available"] is False and "no encryption key" in v["reason"]
    n = (await off.client.get("/v1/notes")).json()
    assert n["available"] is False and "no encryption key" in n["reason"]
    t = await off.client.get("/v1/things")
    assert t.status_code == 200, t.text  # review M4: the list says so; it is not an error
    assert t.json()["available"] is False and "no encryption key" in t.json()["reason"]
    w = await off.client.post("/v1/things", json={"name": "keys", "place": "hook"}, headers=H)
    assert w.status_code == 503 and w.json()["error"] == "unavailable", w.text


# ---- the route table (review M4) -----------------------------------------------------------------

R2_ROUTES = {
    ("GET", "/v1/vault"),
    ("POST", "/v1/vault/upload"),
    ("PATCH", "/v1/vault/items/{item_id}"),
    ("DELETE", "/v1/vault/items/{item_id}"),
    ("POST", "/v1/vault/holders"),
    ("DELETE", "/v1/vault/holders/{holder_id}"),
    ("PUT", "/v1/vault/settings"),
    ("POST", "/v1/vault/unlock"),
    ("DELETE", "/v1/vault/unlock"),
    ("POST", "/v1/vault/items/{item_id}/files/{fid}/ticket"),
    ("POST", "/v1/vault/export/ticket"),
    ("GET", "/v1/vault/download/{ticket}"),
    ("GET", "/v1/vault/inbox"),
    ("PUT", "/v1/vault/inbox"),
    ("DELETE", "/v1/vault/inbox"),
    ("POST", "/v1/vault/inbox/check"),
    ("GET", "/v1/things"),
    ("POST", "/v1/things"),
    ("PATCH", "/v1/things/{thing_id}"),
    ("DELETE", "/v1/things/{thing_id}"),
    ("GET", "/v1/things/{thing_id}/history"),
    ("GET", "/v1/things/export"),
    ("GET", "/v1/notes"),
    ("POST", "/v1/notes"),
    ("PATCH", "/v1/notes/{note_id}"),
    ("DELETE", "/v1/notes/{note_id}"),
    ("POST", "/v1/notes/{note_id}/fetch"),
    ("GET", "/v1/notes/export"),
    ("POST", "/v1/notes/import"),
    ("GET", "/v1/privacy"),
    ("GET", "/v1/privacy/{category_id}/export"),
    ("POST", "/v1/privacy/export-all"),
    ("POST", "/v1/privacy/{category_id}/delete"),
    ("POST", "/v1/passkeys/challenge"),
    ("GET", "/v1/telegram"),
    ("PUT", "/v1/telegram/settings"),
    ("POST", "/v1/telegram/pair"),
    ("DELETE", "/v1/telegram/pair"),
    ("POST", "/v1/telegram/test-alert"),
    ("GET", "/v1/deleted"),
    ("POST", "/v1/deleted/{undo_id}/restore"),
    ("DELETE", "/v1/deleted/{undo_id}"),
}


def _route_table(app: Any) -> list[tuple[str, str]]:
    """Every (method, path) the app really serves, through included routers (FastAPI's public
    `iter_route_contexts`), with repeats kept so a duplicate shows."""
    return [
        (m, str(rc.path))
        for rc in iter_route_contexts(app.routes)
        for m in sorted(rc.methods or ())
        if m != "HEAD"
    ]


@pytest.mark.parametrize("keyed_on", [True, False])
async def test_the_app_serves_every_r2_route_exactly_once(
    settings: Settings, keyed_on: bool
) -> None:
    """With or without the token key (off, the routes answer "not available"), with Drive."""
    s = keyed(settings) if keyed_on else settings.model_copy(update={"tools_enabled": True})
    async for a in _app(s, drive=_drive()):
        table = _route_table(a.app)
        assert len(table) > 100  # the whole app, not one router
        repeats = sorted({p for p in table if table.count(p) > 1})
        assert repeats == []
        assert sorted(R2_ROUTES - set(table)) == []


async def test_notes_switched_off_say_so(settings: Settings) -> None:
    async for a in _app(keyed(settings, notes_enabled=False)):
        assert a.app.state.notes is None and a.app.state.notes_reason == NOTES_OFF


# ---- tick jobs ----------------------------------------------------------------------------------


async def test_tick_jobs_have_unique_names_none_of_the_ticks_own(on: App) -> None:
    names = [j.name for j in on.app.state.tick_jobs]
    assert names == ["vault_reminders", "vault_chunks", "vault_unlocks"]
    assert not RESERVED_JOB_NAMES & set(names)
    assert await run_jobs(on.app.state.tick_jobs, [UID]) == dict.fromkeys(names, "ok")


async def test_with_drive_the_inbox_is_wired_and_never_readable_by_drive_tools(
    settings: Settings,
) -> None:
    async for a in _app(keyed(settings), drive=_drive()):
        st = a.app.state
        assert st.vault_inbox is not None and st.drive.inbox is not None
        assert "digilocker_inbox" in [j.name for j in st.tick_jobs]
    async for a in _app(settings.model_copy(update={"tools_enabled": True}), drive=_drive()):
        st = a.app.state
        assert st.vault_inbox is None  # no vault, no import
        assert st.drive.inbox is not None  # but a folder picked earlier stays unreadable


async def test_a_never_drive_row_stops_the_inbox_job(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the job's public `run` (review M4): with the owner's Drive row Never, or rules
    that can't be read, the inbox is never checked for that owner; with Allow it is."""
    checked: list[str] = []

    async def check(uid: str) -> Any:
        checked.append(uid)
        return SimpleNamespace(imported=0, skipped=0)

    async for a in _app(keyed(settings), drive=_drive()):
        job = next(j for j in a.app.state.tick_jobs if j.name == "digilocker_inbox")
        monkeypatch.setattr(a.app.state.vault_inbox, "check", check)

        class Never:
            async def rules_for(self, uid: str) -> list[PolicyRule]:
                return [PolicyRule(tool_pattern="drive_*", effect=Effect.DENY, source="owner")]

        class Broken:
            async def rules_for(self, uid: str) -> list[PolicyRule]:
                raise RuntimeError("down")

        class Allow:
            async def rules_for(self, uid: str) -> list[PolicyRule]:
                return []

        for perms in (Never(), Broken()):
            a.app.state.permissions = perms
            assert await job.run([UID]) == {"owners": 0, "imported": 0, "skipped": 0, "failed": 0}
        assert checked == []
        a.app.state.permissions = Allow()
        assert (await job.run([UID]))["owners"] == 1 and checked == [UID]


async def test_an_owner_sweep_failure_stops_no_one() -> None:
    seen: list[str] = []

    async def sweep(uid: str) -> int:
        seen.append(uid)
        if uid == "a":
            raise RuntimeError("x")
        return 2

    out = await OwnerSweep("x_sweep", sweep).run(["a", "b"])
    assert out == {"owners": 2, "swept": 2, "failed": 1} and seen == ["a", "b"]


def test_job_names_are_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    stack = SimpleNamespace(
        reminders=SimpleNamespace(name="undo"),
        service=SimpleNamespace(store=SimpleNamespace(sweep=None)),
        unlock=SimpleNamespace(sweep=None),
    )
    app = SimpleNamespace(state=SimpleNamespace(vault_stack=stack, vault_inbox=None))
    with pytest.raises(RuntimeError):
        personal_tick_jobs(app)  # type: ignore[arg-type]


# ---- privacy -------------------------------------------------------------------------------------


async def test_privacy_categories_are_in_panel_order_with_faces_last(on: App) -> None:
    ids = on.app.state.privacy.registry.ids()
    assert ids[0] == "memory" and ids[-1] == "faces" and ids.count("faces") == 1
    assert ids.index("activity") < ids.index("vault") < ids.index("notes")
    assert ids.index("notes") < ids.index("belongings") < ids.index("faces")
    body = (await on.client.get("/v1/privacy")).json()
    assert [c["id"] for c in body["categories"]] == ids


async def test_privacy_lists_the_digilocker_folder_after_the_vault(settings: Settings) -> None:
    async for a in _app(keyed(settings), drive=_drive()):
        ids = a.app.state.privacy.registry.ids()
        assert ids.index("vault") + 1 == ids.index("vault_inbox") < ids.index("notes")


async def test_without_the_key_the_r2_categories_are_left_out(off: App) -> None:
    ids = off.app.state.privacy.registry.ids()
    assert not {"vault", "vault_inbox", "notes", "belongings"} & set(ids)
    assert ids[-1] == "faces"


# ---- body cap ------------------------------------------------------------------------------------


async def test_the_vault_upload_has_its_own_body_cap(on: App) -> None:
    big = b"%PDF-" + b"0" * 3_000_000  # over the app-wide 2.1 MB cap, under the vault's 10 MB
    h = {"X-Requested-With": "JARVIS"}
    r = await on.client.post("/v1/vault/upload", content=big, headers=h)
    assert r.status_code != 413, r.text
    r = await on.client.post("/v1/notes/import", content=big, headers=h)
    assert r.status_code == 413


# ---- activity, offline ------------------------------------------------------------------------


async def test_activity_shows_fixed_words_never_the_note(on: App) -> None:
    st = on.app.state
    call = ToolCall(id="n1", name="kb_add_note", arguments={"text": SECRET})
    out = await st.gateway.execute(call, scope=f"{UID}:s1")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    rows = await st.activity_store.day(UID, day_key(date.today()))
    if not rows:  # the recorder's day is the owner's local day
        rows = [
            r
            for d in ("2026-11-04", "2026-11-05", "2026-11-06")
            for r in await st.activity_store.day(UID, d.replace("-", ""))
        ]
    assert [r.words for r in rows] == ["Saved a note"]
    assert all(SECRET not in r.model_dump_json() for r in rows)


def test_offline_mode_offers_no_r2_tool() -> None:
    assert not set(OFFLINE_TOOLS) & R2_TOOLS


async def test_a_spoken_put_through_the_app_gateway_is_voice(on: App) -> None:
    from jarvis.tools.taint import context_trust

    st = on.app.state
    call = ToolCall(
        id="b1", name="belongings_put", arguments={"item": "passport", "place": "blue file"}
    )
    with context_trust(untrusted=False, spoken=True):
        out = await st.gateway.execute(call, scope=f"{UID}:s1")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    (thing,) = (await st.belongings.state(UID)).live()
    assert thing.origin == "voice"
    _ = ActionRisk
