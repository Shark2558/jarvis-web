# tests/test_r7_d_fixes_api.py -- R7 Part D's review follow-ups for the SOS routes and the door:
# every error answer carries plain words (never "[object Object]"), a bad place never stops an
# SOS, a locked phone can only send a real SOS and sees no contact label, one press id is one
# send, and a body that nests too deep is a plain 422 (never a 500).
from __future__ import annotations

import json
from typing import Any

import pytest
from r7_fakes_d import ASHA, LAT_E6, LON_E6, UID
from test_r7_d_api import CSRF, PLACE, _lock, running
from test_r7_d_part import Rig

from jarvis.sos.models import parse_press

PRESS = "Zz9_-aB3cD4eF5gH"


async def _joined(rig: Rig) -> None:
    c = await rig.sos.add_contact(UID, *ASHA[:2])
    word = (await rig.sos.join_link(UID, c.id))["link"].split("start=", 1)[1]
    await rig.part.services["sos_hook"].join(word, tg_user_id=ASHA[2], chat_id=ASHA[2])
    rig.bot.calls.clear()


def _door_body(**over: Any) -> bytes:
    body = {"v": 1, "kind": "real", "at": int(Rig().clock().timestamp()), "location": None}
    body.update(over)
    return json.dumps(body).encode()


# ---- the parser ---------------------------------------------------------------------------------
def test_parse_press_keeps_a_good_place_and_drops_a_bad_one() -> None:
    good = parse_press({"kind": "real", "location": PLACE, "press_id": PRESS, "at": 5})
    assert good is not None and good.location is not None and not good.dropped
    assert (good.press_id, good.at) == (PRESS, 5)
    for bad in ({**PLACE, "lat_e6": 9e9}, {**PLACE, "age_s": 10**6}, {**PLACE, "provider": "x"}, 7):
        got = parse_press({"kind": "real", "location": bad})
        assert got is not None and got.location is None and got.dropped is True
    odd = parse_press({"kind": "test", "press_id": "short", "at": "no", "v": 9})
    assert odd is not None and odd.press_id is None and odd.at is None and not odd.dropped


@pytest.mark.parametrize("raw", [None, [], "real", {"kind": "panic"}, {"kind": 5}, {}])
def test_parse_press_needs_a_kind(raw: object) -> None:
    assert parse_press(raw) is None


# ---- the web send -------------------------------------------------------------------------------
async def test_a_bad_place_is_dropped_and_the_sos_still_goes() -> None:
    async with running() as (app, c):
        sos = app.state.r7_parts["body"].services["sos"]
        await c.post("/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF)
        bad = {**PLACE, "lat_e6": 9e9}
        r = await c.post("/v1/sos/send", json={"kind": "real", "location": bad}, headers=CSRF)
        assert r.status_code == 200 and r.json()["outcome"] == "none_joined"
        assert (
            r.json()["sms"]["numbers"] == [ASHA[1]]
            and "location is not available" in r.json()["text"]
        )
        assert (await sos.view(UID))["last"]["location"] is False


async def test_every_error_answer_carries_plain_words_never_an_object() -> None:
    async with running() as (_, c):
        for body in ({"kind": 5}, {"kind": "panic"}, {}, [1, 2]):
            r = await c.post("/v1/sos/send", json=body, headers=CSRF)
            j = r.json()
            assert r.status_code == 422 and isinstance(j["detail"], str), body
            assert "112" in j["detail"] and j["error"] == "invalid" and j["sent"] is False
        raw = await c.post(
            "/v1/sos/send", content=b"{nope", headers={**CSRF, "content-type": "application/json"}
        )
        assert raw.status_code == 422 and isinstance(raw.json()["detail"], str)
        deep = await c.post(
            "/v1/sos/send",
            content=b"[" * 100_000,
            headers={**CSRF, "content-type": "application/json"},
        )
        assert deep.status_code == 422 and isinstance(deep.json()["detail"], str)


async def test_a_server_that_cannot_try_says_so_in_words_and_detail() -> None:
    async with running() as (app, c):
        svc = app.state.r7_parts["body"].services["sos"]

        async def boom(*a: Any, **k: Any) -> None:
            raise RuntimeError("x")

        svc.send = boom
        r = await c.post("/v1/sos/send", json={"kind": "real"}, headers=CSRF)
        j = r.json()
        assert r.status_code == 500 and j["detail"] == j["words"] and j["error"] == "failed"
        assert j["call"]["emergency"] == "112" and j["sent"] is False


async def test_too_many_presses_answer_429_with_words_and_detail() -> None:
    import jarvis.api.sos as api_sos

    async with running() as (_, c):
        api_sos._sends = api_sos.RateLimiter(1)  # noqa: SLF001
        await c.post("/v1/sos/send", json={"kind": "real"}, headers=CSRF)
        r = await c.post("/v1/sos/send", json={"kind": "real"}, headers=CSRF)
        assert r.status_code == 429 and r.json()["detail"] == r.json()["words"]
        api_sos._sends = api_sos.RateLimiter(api_sos.SENDS_PER_MINUTE)  # noqa: SLF001


async def test_while_locked_only_a_real_sos_goes_and_it_names_no_one() -> None:
    async with running() as (app, c):
        await c.put("/v1/sos/label", json={"label": "Kiran Example"}, headers=CSRF)
        await c.post("/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF)
        _lock(app, True)
        for kind in ("test", "safe"):
            r = await c.post("/v1/sos/send", json={"kind": kind}, headers=CSRF)
            assert r.status_code == 423 and r.json()["error"] == "device_locked"
            assert isinstance(r.json()["detail"], str) and "unlock" in r.json()["detail"].lower()
        real = await c.post("/v1/sos/send", json={"kind": "real"}, headers=CSRF)
        assert real.status_code == 200
        assert all(r["label"].startswith("Contact") for r in real.json()["results"])
        assert ASHA[0] not in json.dumps(real.json())
        sheet = (await c.get("/v1/sos/sheet")).json()
        assert sheet["locked"] is True and sheet["numbers"] == [ASHA[1]] and "label" not in sheet
        _lock(app, False)
        assert (
            await c.post("/v1/sos/send", json={"kind": "test"}, headers=CSRF)
        ).status_code == 200
        assert (await c.get("/v1/sos/sheet")).json()["label"] == "Kiran Example"


async def test_a_lock_that_cannot_be_read_counts_as_locked_for_a_test() -> None:
    async with running() as (app, c):
        from jarvis.mobile.ports import MobilePart

        async def broken(scope: Any) -> bool:
            raise RuntimeError("lock unreadable")

        parts = dict(app.state.r7_parts)
        parts["phone"] = MobilePart("phone", services={"app_lock": broken})
        app.state.r7_parts = parts
        assert (
            await c.post("/v1/sos/send", json={"kind": "test"}, headers=CSRF)
        ).status_code == 423
        assert (
            await c.post("/v1/sos/send", json={"kind": "real"}, headers=CSRF)
        ).status_code == 200


async def test_a_repeated_press_id_sends_once_on_the_web() -> None:
    async with running() as (app, c):
        await c.post("/v1/sos/contacts", json={"label": ASHA[0], "phone": ASHA[1]}, headers=CSRF)
        body = {"kind": "real", "location": PLACE, "press_id": PRESS}
        a = await c.post("/v1/sos/send", json=body, headers=CSRF)
        b = await c.post("/v1/sos/send", json=body, headers=CSRF)
        assert a.json() == b.json()
        assert (await c.get("/v1/sos")).json()["left"]["real_hour"] == 3  # none_joined: slot back
        stored = json.dumps(
            app.state.r7_parts["body"].services["sos"].store._docs._data, default=str
        )
        assert str(LAT_E6) not in stored and str(LON_E6) not in stored and PRESS not in stored


# ---- the phone's door ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "over",
    [
        {"location": {**PLACE, "lat_e6": 91_000_000}},
        {"location": {**PLACE, "lat_e6": 1.5}},
        {"location": {**PLACE, "age_s": 99_999}},
        {"location": {**PLACE, "provider": "gps"}},
        {"extra": 1},
        {"v": 2},
    ],
)
async def test_the_door_sends_a_real_sos_whatever_is_wrong_with_the_extras(
    over: dict[str, Any],
) -> None:
    rig = Rig()
    await _joined(rig)
    reply = await rig.door.call("sos", _door_body(**over))
    assert reply.status == 200 and reply.body["outcome"] == "sent" and reply.body["reached"] == 1
    if "location" in over:
        assert "sent without your location" in reply.body["words"]
        assert not rig.bot.of("sendLocation")


@pytest.mark.parametrize("raw", [b"", b"[]", b"{nope", b'{"kind":"panic"}', b"[" * 200_000])
async def test_a_door_body_without_a_kind_is_a_plain_422_with_the_sms_and_112_words(
    raw: bytes,
) -> None:
    rig = Rig()
    reply = await rig.door.call("sos", raw)
    assert reply.status == 422 and rig.bot.calls == [] and rig.notes.sent == []
    assert reply.body["error"] == "invalid" and reply.body["sent"] is False
    assert "SMS" in reply.body["detail"] and "112" in reply.body["detail"]
    assert reply.body["call"]["emergency"] == "112"


async def test_the_door_answers_a_repeated_press_id_with_the_first_result() -> None:
    rig = Rig()
    await _joined(rig)
    first = await rig.door.call("sos", _door_body(press_id=PRESS))
    again = await rig.door.call("sos", _door_body(press_id=PRESS))
    assert first.body == again.body and len(rig.bot.to(ASHA[2])) == 1
    bad = await rig.door.call("sos", _door_body(press_id="short"))
    assert bad.status == 200 and len(rig.bot.to(ASHA[2])) == 2  # no id: just sent


async def test_the_health_door_survives_a_body_nested_too_deep() -> None:
    rig = Rig()
    reply = await rig.door.call("health", b"[" * 200_000)
    assert reply.status == 422
