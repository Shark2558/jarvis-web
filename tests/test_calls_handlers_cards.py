# tests/test_calls_handlers_cards.py — R18 A1: the Calls panel's REST handlers
# (api.calls_handlers_cards) behind I0's routes: cards (fields, template, free text, edit), the
# two-press approval with a passkey, cancel, records, the booking's Undo, settings (a raise needs
# confirm_raise), the language table; refusals in plain words with stable codes.
from __future__ import annotations

from typing import Any

import httpx
import pytest
from calls_a1_fakes import NUMBER, UID, Rig, api, known, rig
from fastapi import FastAPI
from pydantic import SecretStr

from jarvis.api import calls_routes as cr
from jarvis.api.calls_handlers_cards import CardsApi
from jarvis.api.identity import primary_user_id
from jarvis.calls.models import CallRecord, CardStatus
from jarvis.calls.ports import CallsRefused
from jarvis.calls.records import CallSummary
from jarvis.config import Settings

FIELDS = {"number": NUMBER, "purpose": "Book a laundry pickup", "languages": ["ml-IN", "en-IN"]}
TOKEN = "t" * 32


async def _api(**kw: Any) -> tuple[CardsApi, Rig]:
    r = await rig(**kw)
    return api(r), r


async def _refused(coro: Any) -> CallsRefused:
    with pytest.raises(CallsRefused) as err:
        await coro
    return err.value


async def test_a_card_from_fields_is_stored_with_its_estimate() -> None:
    a, r = await _api()
    await known(r.store)
    view = await a.create_card(UID, FIELDS)
    assert view["status"] == "draft" and view["blocked"] is None
    assert view["number"] == NUMBER and view["number_masked"] == "+91 …0001"
    assert view["estimate"]["total_inr"] is not None and view["estimate"]["speech_free"]
    assert view["language_names"] == ["Malayalam", "English"]
    assert (await r.store.get_card(UID, view["id"])) is not None


async def test_a_new_number_without_passkeys_says_why_it_is_blocked() -> None:
    a, _ = await _api()
    view = await a.create_card(UID, FIELDS)
    assert view["needs_passkey"] and view["blocked"]["code"] == "needs_passkey"


async def test_a_card_from_a_template() -> None:
    a, r = await _api()
    await known(r.store)
    window = {"day": "2026-11-28", "start": "10:00", "end": "12:00"}
    body = {
        "template": "laundry_pickup",
        "fields": {"number": NUMBER, "windows": [window], "give_name": "Sam"},
    }
    view = await a.create_card(UID, body)
    assert view["template"] == "laundry_pickup" and view["booking"]["reason"] == "Laundry pickup"


class _Model:
    async def complete(self, uid: str, *, system: str, prompt: str, max_tokens: int) -> str:
        return '{"number": "90000 00001", "purpose": "Book a pickup", "languages": ["en-IN"]}'


async def test_a_card_from_free_text_through_the_fast_tier() -> None:
    from jarvis.calls.cards import CardParser

    r = await rig()
    await known(r.store)
    a = api(r, parser=CardParser(_Model()))
    view = await a.create_card(UID, {"text": "Call 90000 00001 to book a pickup"})
    assert view["number"] == NUMBER and view["purpose"] == "Book a pickup"
    assert (await _refused(api(r).create_card(UID, {"text": "x"}))).status == 501


@pytest.mark.parametrize(
    ("body", "code", "status"),
    [
        (FIELDS | {"number": "+9119001234567"}, "premium", 422),
        (FIELDS | {"languages": ["ta-IN"]}, "language", 409),
        ({"purpose": "x"}, "invalid", 422),
        ({"template": "pizza", "fields": {}}, "template", 422),
        ({"text": 5}, "invalid", 422),
    ],
)
async def test_refusals_carry_a_code_and_plain_words(
    body: dict[str, Any], code: str, status: int
) -> None:
    a, _ = await _api()
    err = await _refused(a.create_card(UID, body))
    assert (err.code, err.status) == (code, status) and "9000" not in err.words


async def test_editing_a_waiting_card_replaces_it() -> None:
    a, r = await _api()
    await known(r.store)
    old = await a.create_card(UID, FIELDS)
    new = await a.create_card(
        UID, FIELDS | {"purpose": "Ask about the bill", "replaces": old["id"]}
    )
    assert new["id"] != old["id"]
    stored = await r.store.get_card(UID, old["id"])
    assert stored is not None and stored.status is CardStatus.CANCELLED


async def test_estimate_stores_nothing() -> None:
    a, r = await _api()
    view = await a.estimate(UID, FIELDS)
    assert await r.store.get_card(UID, view["id"]) is None and view["estimate"]["minutes"] == 6


async def test_one_press_approves_a_known_number_when_no_passkey_is_in_force() -> None:
    a, r = await _api()
    await known(r.store)
    card = await a.create_card(UID, FIELDS)
    done = await a.approve(UID, card["id"], {})
    assert done == {"status": "placing", "card_id": card["id"], "call_id": "call_00000000000a"}
    assert (await a.get_card(UID, card["id"]))["status"] == "approved"
    assert (await _refused(a.approve(UID, card["id"], {}))).code == "not_waiting"


async def test_with_a_passkey_in_force_it_takes_two_presses() -> None:
    a, r = await _api(passkey=True)
    card = await a.create_card(UID, FIELDS)
    first = await a.approve(UID, card["id"], {})
    assert first["status"] == "needs_passkey" and "0001" in first["card_text"]
    proof = {"challenge_id": "c" * 32, "credential": {}}
    bad = await _refused(
        a.approve(UID, card["id"], {"approval_id": first["approval_id"], "passkey": proof})
    )
    assert bad.code == "invalid"  # not a passkey answer at all
    r.guard.passkeys.required = True
    refused = await _refused(a.approve(UID, card["id"], {"approval_id": first["approval_id"]}))
    assert refused.code == "passkey" and refused.status == 403
    assert (await r.store.get_card(UID, card["id"])).status is CardStatus.DRAFT  # type: ignore[union-attr]


async def test_an_approval_body_with_unknown_fields_is_refused() -> None:
    a, r = await _api()
    await known(r.store)
    card = await a.create_card(UID, FIELDS)
    assert (await _refused(a.approve(UID, card["id"], {"dont_ask_again": True}))).code == "invalid"


async def test_a_spent_approval_id_is_gone() -> None:
    a, r = await _api()
    await known(r.store)
    card = await a.create_card(UID, FIELDS)
    err = await _refused(a.approve(UID, card["id"], {"approval_id": "nope-nope-nope"}))
    assert err.code == "gone"


async def test_a_blocked_card_is_refused_at_the_press() -> None:
    a, r = await _api()
    await known(r.store)
    card = await a.create_card(UID, FIELDS)
    r.clock.advance(hours=10)  # 22:00 IST
    err = await _refused(a.approve(UID, card["id"], {}))
    assert err.code == "quiet_hours" and await r.gateway.pending() == []


async def test_cancel_withdraws_the_waiting_approval() -> None:
    a, r = await _api(passkey=True)
    card = await a.create_card(UID, FIELDS)
    await a.approve(UID, card["id"], {})
    assert len(await r.gateway.pending()) == 1
    view = await a.cancel(UID, card["id"])
    assert view["status"] == "cancelled" and await r.gateway.pending() == []
    assert (await _refused(a.get_card(UID, "cc_ffffffffffff"))).status == 404


async def _record(r: Rig, **kw: Any) -> CallRecord:
    rec = CallRecord(number_e164=NUMBER, started_at=r.clock(), contact_name="Shop", **kw)
    await r.store.put_record(UID, rec)
    return rec


async def test_records_list_masked_and_one_call_with_its_summary() -> None:
    a, r = await _api()
    rec = await _record(r)
    await a.keeper.save_summary(UID, rec.id, CallSummary(english="Pickup booked."))
    listed = await a.list_records(UID, 10)
    assert listed["records"][0]["number_masked"] == "+91 …0001"
    assert "9000000001" not in str(listed)
    one = await a.get_record(UID, rec.id)
    assert one["summary"]["english"] == "Pickup booked." and one["transcript"] is None
    kept = await a.keep_record(UID, rec.id, True)
    assert kept["keep"] is True
    assert (await _refused(a.record_audio(UID, rec.id))).status == 404
    assert await a.delete_record(UID, rec.id) == {"deleted": True, "id": rec.id}
    assert (await _refused(a.delete_record(UID, rec.id))).status == 404


async def test_undo_with_nothing_on_the_calendar() -> None:
    a, r = await _api()
    rec = await _record(r)
    assert (await a.undo_booking(UID, rec.id))["status"] == "nothing"
    assert (await _refused(a.undo_booking(UID, "call_ffffffffffff"))).status == 404


async def test_settings_lowering_runs_raising_needs_confirm_raise() -> None:
    a, _ = await _api()
    lower = await a.put_settings(UID, {"month_cap_inr": 100})
    assert lower["month_cap_inr"] == 100 and lower["templates"]
    err = await _refused(a.put_settings(UID, {"month_cap_inr": 150}))
    assert err.code == "confirm_raise"
    assert (await _refused(a.put_settings(UID, {"sarvam_on": True}))).code == "confirm_raise"
    raised = await a.put_settings(UID, {"month_cap_inr": 150, "confirm_raise": True})
    assert raised["month_cap_inr"] == 150
    assert (await _refused(a.put_settings(UID, {"answer_after_rings": 99}))).status == 422
    assert (await a.put_settings(UID, {"answering_on": True}))["answering_on"] is True


async def test_the_language_table_says_what_is_offered() -> None:
    a, _ = await _api(languages=("en-IN",))
    rows = {row["lang"]: row for row in (await a.languages(UID))["languages"]}
    assert rows["en-IN"]["offered"] and rows["en-IN"]["option"] == "azure"
    assert not rows["ta-IN"]["offered"] and len(rows) == 23


async def test_review_the_language_table_offers_free_first() -> None:
    # R18 review HIGH: the table shows the option a call would use, ₹0 now before a cheaper paid one
    from jarvis.calls.cards import CardBuilder, Estimator
    from jarvis.calls.models import LanguageResult, SpeechOption
    from jarvis.calls.prices import SpeechPrice

    a, r = await _api(languages=())
    for option, inr in ((SpeechOption.SARVAM, 0.70), (SpeechOption.GOOGLE, 1.57)):
        await r.store.put_language_result(
            LanguageResult(
                lang="hi-IN", option=option, checked_at=cr_now(), passed=True, inr_per_minute=inr
            )
        )
    await r.store.save_settings(UID, {"sarvam_on": True})
    prices = {
        SpeechOption.GOOGLE: SpeechPrice(SpeechOption.GOOGLE, 2.0, 2.5, 3600, 1_000_000),
        SpeechOption.SARVAM: SpeechPrice(SpeechOption.SARVAM, 0.5, 3.0, paid=True),
    }

    class _Plenty:
        async def left(self, option: SpeechOption) -> tuple[float, float] | None:
            return (1e6, 1e7) if option is SpeechOption.GOOGLE else None

    a.builder = CardBuilder(r.store, Estimator(prices, None, allowance=_Plenty()))
    rows = {row["lang"]: row for row in (await a.languages(UID))["languages"]}
    assert rows["hi-IN"]["option"] == "google"


def cr_now() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 11, 27, 6, 30, tzinfo=UTC)


async def test_status_and_the_language_check_wait_for_their_parts() -> None:
    a, _ = await _api()
    assert (await _refused(a.status(UID))).status == 501
    assert (await _refused(a.run_language_check(UID, {}))).status == 501


# ---- through the routes ------------------------------------------------------------------------
async def test_through_the_routes_owner_only_and_no_store(settings: Settings) -> None:
    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
    uid = primary_user_id(s)
    r = await rig(uid=uid)
    await known(r.store, uid=uid)
    app = FastAPI()
    app.state.settings = s
    app.state.calls_api = api(r)
    cr.install_calls_routes(app)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        made = await c.post("/v1/calls/cards", json=FIELDS, headers=auth)
        assert made.status_code == 200 and made.headers["cache-control"] == "no-store"
        card_id = made.json()["id"]
        assert (await c.post("/v1/calls/cards", json=FIELDS)).status_code == 401
        bad = await c.post("/v1/calls/cards", json=FIELDS | {"number": "112"}, headers=auth)
        assert bad.status_code == 422 and bad.json()["error"] == "invalid"
        done = await c.post(f"/v1/calls/cards/{card_id}/approve", json={}, headers=auth)
        assert done.status_code == 200 and done.json()["status"] == "placing"
        listed = await c.get("/v1/calls/records?limit=5", headers=auth)
        assert listed.status_code == 200 and listed.json() == {"records": []}
