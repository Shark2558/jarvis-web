# tests/test_r51b_vitals_board.py -- R5.1 D2: the board never fails because the owner's manual
# records can't be read (automatic items + a fixed note instead), and every item carries a fixed
# `impact`, `fix` and `group` for the panel and the systems-check briefing.
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from vitals_fakes import UID, FakeBilling, Rig, key, usage_view

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.billing.meter import AllowanceUse
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.api import router
from jarvis.vitals.auto import AllowanceSpec
from jarvis.vitals.service import MANUAL_UNAVAILABLE, VitalsService
from jarvis.vitals.store import VitalsStore, VitalsUnavailable


def by_id(board, pid):  # type: ignore[no-untyped-def]
    return next(v for v in board.items if v.provider.id == pid)


async def _down(*_a: object, **_k: object) -> list[object]:
    raise VitalsUnavailable("JARVIS couldn't open the Vitals list just now.")


async def test_unreadable_manual_records_keep_the_automatic_items() -> None:
    rig = Rig(billing=FakeBilling(usage_view(120, 500)))
    rig.store.list_manual = _down  # type: ignore[method-assign]

    board = await rig.svc.board(UID)

    assert board.manual_unavailable is True and board.manual_note == MANUAL_UNAVAILABLE
    assert by_id(board, "ai_spend").status == "ok"
    out = board.to_json()
    assert out["manual_unavailable"] is True and out["manual_note"] == MANUAL_UNAVAILABLE
    assert "couldn't open the Vitals list" not in MANUAL_UNAVAILABLE


async def test_readable_manual_records_say_so() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brave", label="Brave search"))

    out = (await rig.svc.board(UID)).to_json()

    assert out["manual_unavailable"] is False and out["manual_note"] == ""
    assert {i["id"] for i in out["items"]} == {"ai_spend", "brave"}


async def test_the_board_opens_on_a_store_without_composite_indexes() -> None:
    docs = MemoryDocs(strict_indexes=True)
    svc = VitalsService(VitalsStore(docs), Rig().settings, billing=FakeBilling())  # type: ignore[arg-type]
    await svc.set_key(UID, key("brave"))

    board = await svc.board(UID)

    assert board.manual_unavailable is False
    assert {v.provider.id for v in board.items} == {"ai_spend", "brave"}


async def test_every_item_has_impact_fix_and_group_in_json() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brave", kind="quota"))
    await rig.svc.set_key(UID, key("insurance", kind="billing"))

    items = {i["id"]: i for i in (await rig.svc.board(UID)).to_json()["items"]}

    for item in items.values():
        assert {"impact", "fix", "group"} <= item.keys()
        assert isinstance(item["impact"], str) and isinstance(item["fix"], str)
    assert items["ai_spend"]["group"] == "bills"
    assert "paid replies pause" in items["ai_spend"]["impact"]
    assert "free brain" in items["ai_spend"]["impact"]
    assert items["ai_spend"]["fix"]
    assert items["brave"]["group"] == "allowances" and items["insurance"]["group"] == "bills"
    assert items["brave"]["impact"] == "" and items["brave"]["fix"] == ""


@pytest.mark.parametrize(
    ("kind", "group"),
    [
        ("key", "keys"),
        ("quota", "allowances"),
        ("allowance", "allowances"),
        ("billing", "bills"),
        ("storage", "bills"),
    ],
)
async def test_manual_items_are_grouped_by_kind(kind: str, group: str) -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("thing", kind=kind))

    view = by_id(await rig.svc.board(UID), "thing")

    assert view.group == group and getattr(view, "impact", None) == ""


async def test_allowances_and_quotas_carry_fixed_words() -> None:
    class Bill(FakeBilling):
        def allowance_resets_at(self):  # type: ignore[no-untyped-def]
            return None

        async def allowance(self, keys):  # type: ignore[no-untyped-def]
            return AllowanceUse("2026-11", {"tts_x": 10.0})

    rig = Rig(billing=Bill(), with_ledger=True)
    rig.svc._allowances = (AllowanceSpec("tts_x", "Voice (X)", 100, "characters"),)  # noqa: SLF001

    board = await rig.svc.board(UID)

    voice = by_id(board, "allowance_tts_x")
    assert voice.group == "allowances" and voice.impact.startswith("If this runs out")
    assert voice.fix
    quotas = [v for v in board.items if v.provider.id.startswith("quota_")]
    assert quotas and all(q.group == "allowances" and q.impact and q.fix for q in quotas)
    assert all(q.provider.label in q.impact for q in quotas)


async def test_get_answers_200_with_the_note_when_manual_records_cant_be_read() -> None:
    rig = Rig()
    rig.store.list_manual = _down  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(router)
    app.state.vitals = rig.svc
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/v1/vitals")

    body = r.json()
    assert r.status_code == 200 and body["manual_unavailable"] is True
    assert [i["id"] for i in body["items"]] == ["ai_spend"]
