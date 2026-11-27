# tests/test_r131_wiring.py -- R13.1 I0 (docs/plans/r13-1-try-on.md seam 6; review M4, L2, L12):
# the two new parts in R13's one join. Six parts build through the real modules; `check_part`
# refuses a `tryon` or `seeme` part that offers `data`, or a Privacy row, job or service it doesn't
# own; with both R13.1 parts failed R13's Wardrobe rows still read while the Try-on rows say
# "Couldn't check right now" and delete by path; `ctx.tryon` is built lazily, once; the routes and
# the mannequin's manifest-checked files.
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r13_fakes import FixedClock, ist
from r14_fakes import RecordingJob

import jarvis.api.r13_wiring as wiring
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.privacy.ports import CategoryView
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.ports import NOT_BUILT, PARTS, WardrobeContext, WardrobePart
from jarvis.wardrobe.seeme import texts as seeme_texts
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon import part as tryon_part

UID = "owner-r131"


def _ctx(s: Settings, docs: MemoryDocs | None = None, state: dict[str, Any] | None = None) -> Any:
    async def zone(uid: str) -> Any:
        return None

    return WardrobeContext(
        s=s, docs=docs, keyring=None, audit=None, now=FixedClock(ist(2026, 11, 17)), zone=zone,
        state=(state if state is not None else {}).get,
    )  # fmt: skip


class _Data:
    name, row = "laundry", "history"

    async def count(self, uid: str) -> int:
        return 0

    async def export(self, uid: str) -> dict[str, Any]:
        return {}

    async def delete(self, uid: str) -> int:
        return 0


class _Row:
    section, label = "Try-on", "a row"

    def __init__(self, rid: str) -> None:
        self.id = rid

    async def describe(self, uid: str) -> CategoryView:
        raise NotImplementedError

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


# ---- the six parts ------------------------------------------------------------------------------
def test_six_parts_build_through_the_real_modules_and_say_off_in_words_without_a_key(
    settings: Settings,
) -> None:
    parts = wiring.build_parts(_ctx(settings, MemoryDocs()))
    assert tuple(parts) == PARTS and PARTS[-2:] == ("tryon", "seeme")
    # I1: A and C are built (no longer I0's NOT_BUILT stubs); with no keyring each says why
    assert parts["tryon"].ready == tryon_part.OFF_NO_KEY
    assert parts["seeme"].ready == f"off: {seeme_texts.OFF_NO_KEY}"
    assert NOT_BUILT not in {parts[p].ready for p in PARTS}
    for name in ("tryon", "seeme"):
        assert parts[name].data == () and parts[name].tools == ()  # rows on privacy only (M4)
    assert [r.id for r in parts["tryon"].privacy] == ["tryon_figure", "tryon_all", "tryon_device"]
    assert [r.id for r in parts["seeme"].privacy] == [
        "tryon_photo",
        "tryon_pictures",
        "tryon_spend",
    ]
    assert {r.section for p in ("tryon", "seeme") for r in parts[p].privacy} == {"Try-on"}


@pytest.mark.parametrize(
    "part",
    [
        WardrobePart("tryon", data=(_Data(),)),  # type: ignore[arg-type]  # M4: rows on privacy
        WardrobePart("seeme", data=(_Data(),)),  # type: ignore[arg-type]
        WardrobePart("seeme", privacy=(_Row("tryon_figure"),)),  # A's row
        WardrobePart("tryon", privacy=(_Row("tryon_spend"),)),  # C's row
        WardrobePart("tryon", privacy=(_Row("tryon_secrets"),)),  # no such row
        WardrobePart("tryon", privacy=(object(),)),  # type: ignore[arg-type]
        WardrobePart("tryon", daily_jobs=(RecordingJob("seeme_daily"),)),  # C's job
        WardrobePart("seeme", clock_jobs=(RecordingJob("seeme_daily"),)),  # daily only
        WardrobePart("seeme", services={"tryon_looks": object()}),  # A's service
        WardrobePart("tryon", services={"seeme": object()}),  # C's service
        WardrobePart("tryon", services={"store": object()}),  # R13 A's service
    ],
)
def test_the_contract_refuses_what_an_r131_part_does_not_own(part: WardrobePart) -> None:
    with pytest.raises(ValueError, match="part"):
        wiring.check_part(part.name, part)


def test_an_r131_part_keeps_what_it_owns() -> None:
    a = WardrobePart("tryon", privacy=(_Row("tryon_figure"), _Row("tryon_all")),
                     services={"tryon_looks": object()}, ready="ok")  # fmt: skip
    c = WardrobePart("seeme", daily_jobs=(RecordingJob("seeme_daily"),),
                     privacy=(_Row("tryon_photo"),), services={"seeme": object()})  # fmt: skip
    assert wiring.check_part("tryon", a) is a and wiring.check_part("seeme", c) is c
    app = FastAPI()
    app.state.r13_parts = {"tryon": a, "seeme": c}
    assert [j.name for j in wiring.r13_tick_jobs(app)] == ["seeme_daily"]
    assert wiring.r13_tools(app.state.r13_parts) == () and wiring.r13_data(app) == ()


def test_a_built_parts_own_rows_are_kept_and_no_stand_in_is_added(settings: Settings) -> None:
    own = WardrobePart("tryon", privacy=(_Row("tryon_figure"),))
    got = wiring._with_kept(own, _ctx(settings, MemoryDocs()))  # noqa: SLF001
    assert got is own


# ---- M4: both R13.1 parts failed ----------------------------------------------------------------
async def _seed(docs: MemoryDocs, prefix: str) -> list[str]:
    paths = [
        f"{prefix}tryon/{UID}", f"{prefix}tryon_person/{UID}", f"{prefix}tryon_consent/{UID}",
        f"{prefix}tryon_picture/{UID}_tp_0123456789ab", f"{prefix}tryon_spend/{UID}_2026-11",
        f"{prefix}tryon_garment/{UID}_tg_0123456789ab",  # D22: a new garment's photo
    ]  # fmt: skip
    await docs.write([Set(p, {"owner": UID, "blob": "sealed", "updated_at": "x"}) for p in paths])
    return paths


async def test_both_r131_parts_failed_r13s_rows_still_read_and_the_tryon_rows_cant_check(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = wiring._build  # noqa: SLF001

    def build(name: str, ctx: WardrobeContext) -> WardrobePart:
        if name in ("tryon", "seeme"):
            raise RuntimeError("boom")
        return real(name, ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(wiring, "_build", build)
    docs, state = MemoryDocs(), {}
    paths = await _seed(docs, settings.firestore_prefix)
    parts = wiring.build_parts(_ctx(settings, docs, state))
    state["r13_parts"] = parts
    assert parts["tryon"].ready == parts["seeme"].ready == wiring.SETUP_FAILED
    app = FastAPI()
    app.state.r13_parts = parts
    rows = {r.id: r for r in wiring.r13_privacy_sources(app)}
    for rid in ("wardrobe_pieces", "wardrobe_history", "wardrobe_plans", "wardrobe_photos"):
        seen = await rows[rid].describe(UID)
        assert seen.available and not seen.note.startswith("Couldn't check"), rid
    for rid in kept.ROW_IDS[:5]:
        seen = await rows[rid].describe(UID)
        assert seen.section == "Try-on" and seen.count is None, rid
        assert seen.note.startswith("Couldn't check right now"), rid
    assert (await rows["tryon_spend"].describe(UID)).delete == "none"  # his cap's record
    assert (await rows["tryon_all"].describe(UID)).delete == "passkey"  # OPS-05
    assert await rows["tryon_all"].delete(UID) == 5  # by path, with no key; the spend stays
    left = [p for p in paths if await docs.get(p) is not None]
    assert left == [f"{settings.firestore_prefix}tryon_spend/{UID}_2026-11"]
    assert (await rows["tryon_figure"].describe(UID)).note == kept.NOTHING_YET


async def test_the_stand_ins_order_ops05_and_erase_cs_half_by_path(settings: Settings) -> None:
    docs = MemoryDocs()
    prefix = settings.firestore_prefix
    await _seed(docs, prefix)
    assert await kept.erase_seeme(docs, prefix, UID) == 4  # picture, garment photo, photo, YES
    assert kept.PICTURES_OWNED == (("tryon_picture", "owner"), ("tryon_garment", "owner"))
    assert "garment" in kept.SPECS[kept.PICTURES_ID].label  # the row names what it holds
    assert "not in your wardrobe" in kept.SPECS[kept.PICTURES_ID].what
    assert await docs.get(f"{prefix}tryon/{UID}") is not None  # A's own document is A's to go
    assert "within 7 days" in kept.BACKUP_WORDS  # read from backup/status.py (M2)
    device = kept.DeviceRow()
    assert "nothing is kept" in device.label and (await device.describe(UID)).count is None


# ---- ctx.tryon: the provider, lazily ------------------------------------------------------------
def test_no_provider_and_no_credentials_while_pictures_are_off(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.api import tryon_wiring

    made: list[str] = []
    monkeypatch.setattr(tryon_wiring, "build_tryon", lambda *a, **k: made.append("x"))
    get = tryon_wiring.tryon_provider(settings.model_copy(update={"tryon_pictures": False}))
    assert get() is None and get() is None and made == []


def test_the_provider_is_built_once_with_adc_tokens_while_pictures_are_on(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from r131_fake_tryon import ScriptedTryOn

    from jarvis.api import tryon_wiring
    from jarvis.voice.adc import AdcTokens

    calls: list[Any] = []

    def build(s: Settings, *, tokens: Any, project: Any) -> Any:
        calls.append(tokens)
        return ScriptedTryOn(max_garments=3)

    monkeypatch.setattr(tryon_wiring, "build_tryon", build)
    get = tryon_wiring.tryon_provider(settings.model_copy(update={"tryon_pictures": True}))
    first = get()
    assert first is get() and isinstance(first, ScriptedTryOn)
    assert len(calls) == 1 and isinstance(calls[0], AdcTokens)


def test_a_broken_adapter_is_no_provider_never_an_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.api import tryon_wiring

    def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("adapter bug")

    monkeypatch.setattr(tryon_wiring, "build_tryon", broken)
    assert (
        tryon_wiring.tryon_provider(settings.model_copy(update={"tryon_pictures": True}))() is None
    )


async def test_the_projects_is_the_settings_else_adcs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.api import tryon_wiring

    seen: list[Any] = []

    def build(s: Settings, *, tokens: Any, project: Any) -> Any:
        seen.append(project)
        return None

    async def adc() -> str:
        return "adc-project"

    monkeypatch.setattr(tryon_wiring, "build_tryon", build)
    monkeypatch.setattr(tryon_wiring, "adc_project", adc)
    on = settings.model_copy(update={"tryon_pictures": True, "firestore_project": None})
    tryon_wiring.tryon_provider(on)()
    assert await seen[0]() == "adc-project"
    named = on.model_copy(update={"firestore_project": "named-project"})
    tryon_wiring.tryon_provider(named)()
    assert await seen[1]() == "named-project"


# ---- the real app: six parts, the routes, the mannequin's files ---------------------------------
TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _owner(s: Settings) -> Settings:
    from pydantic import SecretStr

    return s.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    from jarvis.api import create_app

    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    app.state.wardrobe_now = FixedClock(ist(2026, 11, 17, 10, 0))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_the_app_builds_six_parts_and_v1_r13_lists_them(settings: Settings) -> None:
    async with running(_owner(settings)) as (app, c):
        assert tuple(app.state.r13_parts) == PARTS
        body = (await c.get("/v1/r13", headers=AUTH)).json()
        assert body["version"] == "v5.2.0"  # R5.2 (18.0.0 at R18, 6.4.0 at R6.4)
        assert [p["part"] for p in body["parts"]] == list(PARTS)
        # I1: A's and C's routes are built; this app has no keyring, so each says Off in words
        assert body["parts"][-2] == {"part": "tryon", "ready": tryon_part.OFF_NO_KEY}
        assert body["parts"][-1] == {"part": "seeme", "ready": f"off: {seeme_texts.OFF_NO_KEY}"}
        off = await c.get("/v1/tryon", headers=AUTH)
        assert off.status_code == 503
        assert off.json() == {"error": "off", "detail": tryon_part.OFF_NO_KEY}
        seeme = await c.get("/v1/seeme", headers=AUTH)
        assert seeme.status_code == 503 and seeme.json()["error"] == "not_configured"
        assert (await c.get("/v1/tryon")).status_code == 401
        assert (await c.get("/v1/seeme")).status_code == 401


def _release(
    root: Path, files: dict[str, tuple[bytes, str]], *, sums: dict[str, str] | None = None
) -> None:
    folder = root / "m9"
    folder.mkdir(parents=True)
    listed = {}
    for name, (data, kind) in files.items():
        (folder / name).write_bytes(data)
        digest = (sums or {}).get(name) or hashlib.sha256(data).hexdigest()
        listed[name] = {"sha256": digest, "type": kind}
    (folder / "MANIFEST.json").write_text(json.dumps({"files": listed}), encoding="utf-8")


async def test_the_mannequin_route_serves_only_listed_data_files_with_their_sums(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from jarvis.api import tryon_assets

    octet, js = "application/octet-stream", "application/javascript"
    files = {"body.glb": (b"glTF-body", octet), "evil.js": (b"alert(1)", js),
             "bad.glb": (b"glTF-bad", octet)}  # fmt: skip
    _release(tmp_path, files, sums={"bad.glb": "0" * 64})
    monkeypatch.setattr(tryon_assets, "MANNEQUIN", tmp_path)
    tryon_assets.mannequin_files.cache_clear()
    async with running(settings) as (_, c):
        ok = await c.get("/static/vendor/mannequin/m9/body.glb")
        assert ok.status_code == 200 and ok.content == b"glTF-body"
        assert "immutable" in ok.headers["cache-control"]
        assert ok.headers["x-content-type-options"] == "nosniff"
        for name in ("evil.js", "bad.glb", "MANIFEST.json", "missing.glb", "..%2Fm9%2Fbody.glb"):
            assert (await c.get(f"/static/vendor/mannequin/m9/{name}")).status_code == 404, name
        assert (await c.get("/static/vendor/mannequin/m8/body.glb")).status_code == 404
    tryon_assets.mannequin_files.cache_clear()


def test_the_vision_check_still_reads_its_folder_at_call_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from jarvis.api import console

    _release(tmp_path, {"model.onnx": (b"onnx", "application/octet-stream")})
    monkeypatch.setattr(console, "_VISION", tmp_path)  # what R7's five tests do (L2)
    console.vision_files.cache_clear()
    assert console.vision_files("m9") == {"model.onnx": "application/octet-stream"}
    console.vision_files.cache_clear()
