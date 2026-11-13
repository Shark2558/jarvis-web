# tests/test_r7_i1_join.py -- R7 I1 (docs/plans/r7-mobile.md "I1"): the joins between the parts,
# end to end on fakes. Part C's `hello` reads Part D's real `services["sos_contacts"]`
# (`SosService.sms_view`) through the real wiring: the answer carries his label and the contacts
# that have a number (phone-contract section 4). When Part D cannot say who the contacts are (no
# token key, the store unreadable, the body part left out) the answer leaves `sos` OUT, so the
# phone keeps the numbers it already holds for its offline SMS screen; an answer whose `sos` says
# there are none is the only one that empties the phone's list (Part E's security fix L6).
from __future__ import annotations

import base64
import logging
from typing import Any

import pytest
from pydantic import SecretStr
from r7_fakes_c import HELLO, browser, door, linked_phone, owner_uid, phone_app

from jarvis.config import Settings
from jarvis.mobile.ports import MobilePart
from jarvis.sos.store import SosUnavailable

KEY = base64.urlsafe_b64encode(bytes(range(1, 33))).decode()  # made for these tests only


@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings, token_key=SecretStr(KEY)) as a:
        yield a


@pytest.fixture
async def phone(app: Any) -> tuple[str, Any]:
    async with browser(app) as c:
        return await linked_phone(app, c)


def _sos(app: Any) -> Any:
    return app.state.r7_parts["body"].services["sos"]


async def test_hello_carries_the_label_and_numbers_part_d_keeps(
    app: Any, phone: tuple[str, Any]
) -> None:
    uid = owner_uid()
    await _sos(app).set_label(uid, "Kiran Example")
    await _sos(app).add_contact(uid, "Asha Example", "+10000000001")
    await _sos(app).add_contact(uid, "Telegram Only", "")  # no number: no SMS for this one
    device, key = phone
    r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200
    assert r.json()["sos"] == {
        "enabled": True,
        "label": "Kiran Example",
        "contacts": [{"label": "Asha Example", "phone": "+10000000001"}],
    }


async def test_hello_with_no_contacts_says_there_are_none(app: Any, phone: tuple[str, Any]) -> None:
    device, key = phone
    r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200
    sos = r.json()["sos"]
    assert sos["enabled"] is True and sos["contacts"] == []  # an empty list: the phone's goes
    assert sos["label"] == "the owner of this JARVIS"  # Part D's words until he names himself


async def test_an_unreadable_sos_store_leaves_sos_out_so_the_phone_keeps_its_list(
    app: Any, phone: tuple[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    async def down(uid: str) -> Any:
        raise SosUnavailable()

    monkeypatch.setattr(_sos(app)._store, "book", down)
    device, key = phone
    with caplog.at_level(logging.WARNING):
        r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200 and "sos" not in r.json()
    assert r.json()["settings"]["sos_countdown_s"] == 10  # the rest of the answer stands
    assert any("sos contacts unreadable" in m for m in caplog.messages)


async def test_a_server_with_no_token_key_leaves_sos_out(settings: Settings) -> None:
    async with phone_app(settings) as app:  # no token key: Part D raises SosOff
        async with browser(app) as c:
            device, key = await linked_phone(app, c)
        r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200 and "sos" not in r.json()


async def test_a_body_part_left_out_leaves_sos_out_and_says_so(
    app: Any, phone: tuple[str, Any], caplog: Any
) -> None:
    app.state.r7_parts["body"] = MobilePart("body", ready="setup failed")
    device, key = phone
    with caplog.at_level(logging.WARNING):
        r = await door(app, key, device, "hello", HELLO)
    assert r.status_code == 200 and "sos" not in r.json()
    assert any("sos contacts seam missing" in m for m in caplog.messages)
