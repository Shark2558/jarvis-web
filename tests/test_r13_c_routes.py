# tests/test_r13_c_routes.py -- R13 Part C's routes (docs/plans/r13-wardrobe.md "The HTTP contract",
# H5, D10, D13): `GET /v1/outfits`, `GET /v1/outfits/calendars`, `PUT /v1/outfits/settings` answer
# exactly the contract's models (`jarvis.wardrobe.http`), `no-store`, plain words on errors, the
# private basics' words only when he chose to see them, the settings change on the audit chain.
from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient
from r13_fakes import UID
from r13_fakes_c import N, World, app_of, ist, world

from jarvis.storage.docs import Set
from jarvis.wardrobe import http


async def _client(w: World) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://test")


def test_the_three_routes_are_the_contracts_styling_rows() -> None:
    from jarvis.api.outfits import router

    mine = {(m, r.path) for r in router.routes for m in getattr(r, "methods", ())}
    rows = {(m, p) for m, p, part, *_ in http.ROUTES if part == "styling"}
    assert mine == rows


async def test_get_outfits_answers_the_contract_with_tomorrows_look_and_weather() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0), place=False)
    await w.call("outfit_plan", action="save", day="tomorrow", occasion="meeting", start="10:00",
                 end="12:00")  # fmt: skip
    async with await _client(w) as c:
        got = await c.get("/v1/outfits")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    body = http.OutfitsView.model_validate(got.json())  # exactly the contract's shape
    assert body.ready == "ready" and body.weather == "Weather unknown: I assumed indoors."
    (plan,) = body.tomorrow
    assert plan.dress_code == "business_formal" and plan.starts == ist(2026, 11, 17, 10, 0)
    assert plan.look is not None and plan.look.reasons[0].startswith(
        "Business formal for your 10:00"
    )
    assert [p.id for p in body.today] == ["suggestion"]
    text = json.dumps(got.json())
    assert "White formal shirt" not in text and "Light blue office shirt" not in text
    under = next(p for p in plan.look.pieces if p.slot == "underwear")
    assert under.piece == N.under and under.words == "a private basic"


async def test_his_private_basics_show_their_words_only_when_he_chose_to_see_them() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0), place=False)
    view = await w.store.view(UID)
    on = view.settings.model_copy(update={"show_private": True})
    await w.store.docs.write(
        [Set(f"jarvis_wardrobe/{UID}", view.model_copy(update={"settings": on}).to_json())]
    )
    async with await _client(w) as c:
        body = http.OutfitsView.model_validate((await c.get("/v1/outfits")).json())
    under = next(p for p in body.tomorrow[0].look.pieces if p.slot == "underwear")  # type: ignore[union-attr]
    assert under.words == "grey underpants"


async def test_off_without_a_key_is_503_in_plain_words_and_the_calendars_say_why() -> None:
    w = await world(keyring=None)
    async with await _client(w) as c:
        got = await c.get("/v1/outfits")
        assert got.status_code == 503
        assert got.json() == {
            "detail": "Outfits are off: JARVIS has no token key to seal your plans."
        }
        cals = http.Calendars.model_validate((await c.get("/v1/outfits/calendars")).json())
        assert cals.calendars == () and "token key" in cals.why
        put = await c.put("/v1/outfits/settings", json={"calendar": None})
        assert put.status_code == 422 and "token key" in put.json()["detail"]


async def test_put_settings_answers_the_settings_view_and_is_audited_without_an_id() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    async with await _client(w) as c:
        refs = (await c.get("/v1/outfits/calendars")).json()["calendars"]
        got = await c.put("/v1/outfits/settings", json={
            "calendar": refs[1]["id_ref"], "fields": ["title"],
            "plan_alerts": True, "auto_swap": True,
        })  # fmt: skip
    assert got.status_code == 200
    view = http.SettingsView.model_validate(got.json())
    assert (view.calendar_chosen, view.auto_swap, view.tag_cap_inr) == (True, True, 30)
    assert "lead_h" not in got.json()  # dropped from the contract at I1 (review C-1 M8)
    async with await _client(w) as c:
        shown = (await c.get("/v1/outfits/calendars")).json()["calendars"]
    assert [x["chosen"] for x in shown] == [x["id_ref"] == refs[1]["id_ref"] for x in shown]
    assert sum(x["chosen"] for x in shown) == 1  # the panel can show and keep the pick (H2)
    (line,) = [e for e in w.audit._entries if e.tool == "outfit_settings"]  # noqa: SLF001
    assert line.outcome == "changed" and line.agent == "outfits"
    assert "example.com" not in line.detail and "example.com" not in line.args_hash


async def test_a_bad_settings_body_is_refused() -> None:
    w = await world()
    async with await _client(w) as c:
        got = await c.put("/v1/outfits/settings", json={"lead_h": 6})
        bad = await c.put("/v1/outfits/settings", json={"calendar": "x" * 99})
    assert got.status_code == 422 and bad.status_code == 422  # lead_h is not in the contract
