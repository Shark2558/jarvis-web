# tests/test_r13_i1_settings.py -- R13 I1: the settings join. A's own switches (AI tagging, the
# private display, his own types) have a route (`PUT /v1/wardrobe/settings`, owner-only, never a
# tool); the calendar, its fields, the evening alert and auto-swap are Part C's and A's view reads
# them from C's sealed choice (INTEGRATION-C 6.4, INTEGRATION-A 6.4, INTEGRATION-D 6.5).
from __future__ import annotations

from typing import Any

from test_r13_a_routes import AUTH, _owner, running

from jarvis.config import Settings
from jarvis.wardrobe import http
from jarvis.wardrobe.ports import TOOL_OWNER

PUT = "/v1/wardrobe/settings"


async def test_the_route_is_in_the_contract_and_is_never_a_tool() -> None:
    rows = {(m, p): (part, body, reply) for m, p, part, body, reply, _ in http.ROUTES}
    assert rows[("PUT", PUT)] == ("catalog", http.WardrobeSettingsIn, http.SettingsView)
    assert not [t for t in TOOL_OWNER if "setting" in t]  # the model can never reach it


async def test_his_switches_are_saved_audited_and_read_back(settings: Settings) -> None:
    async with running(_owner(settings)) as (app, c):
        assert (await c.put(PUT, json={"ai_tagging": True})).status_code == 401
        body = {"ai_tagging": True, "show_private": True, "custom_types": ["Poncho", "cape"]}
        got = await c.put(PUT, json=body, headers=AUTH)
        assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
        view = http.SettingsView.model_validate(got.json())
        assert (view.ai_tagging, view.show_private) == (True, True)
        assert view.custom_types == ("poncho", "cape")
        seen = http.WardrobeView.model_validate((await c.get("/v1/wardrobe", headers=AUTH)).json())
        assert seen.settings.ai_tagging and seen.settings.custom_types == ("poncho", "cape")
        entries = [e for e in app.state.gateway.audit._entries if e.tool == "wardrobe_settings"]  # noqa: SLF001
        assert len(entries) == 1 and entries[0].outcome == "changed"
        assert "poncho" not in entries[0].detail  # his words are not in the audit line


async def test_what_he_does_not_send_stays_and_a_bad_body_is_refused(settings: Settings) -> None:
    async with running(_owner(settings)) as (_, c):
        await c.put(PUT, json={"ai_tagging": True, "show_private": True}, headers=AUTH)
        got = await c.put(PUT, json={"show_private": False}, headers=AUTH)
        view = http.SettingsView.model_validate(got.json())
        assert (view.ai_tagging, view.show_private) == (True, False)
        for bad in (
            {"lead_h": 6},  # not a setting of his
            {"auto_swap": True},  # C's: through /v1/outfits/settings
            {"custom_types": ["bad type!"]},
            {"custom_types": [f"t{i}" for i in range(31)]},
            {"ai_tagging": "yes please"},
        ):
            refused = await c.put(PUT, json=bad, headers=AUTH)
            assert refused.status_code == 422, bad
            assert "Traceback" not in refused.text and "pydantic" not in refused.text.lower()


async def test_the_view_reads_the_calendar_choice_from_c_not_from_the_index(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (_, c):
        first = http.WardrobeView.model_validate((await c.get("/v1/wardrobe", headers=AUTH)).json())
        assert (first.settings.plan_alerts, first.settings.auto_swap) == (True, False)
        put: Any = await c.put(
            "/v1/outfits/settings", json={"auto_swap": True, "plan_alerts": False}, headers=AUTH
        )
        assert put.status_code == 200, put.text
        got = http.WardrobeView.model_validate((await c.get("/v1/wardrobe", headers=AUTH)).json())
        assert (got.settings.plan_alerts, got.settings.auto_swap) == (False, True)
        assert got.settings.fields == ("title",) and not got.settings.calendar_chosen
