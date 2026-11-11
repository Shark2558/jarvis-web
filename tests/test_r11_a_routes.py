# tests/test_r11_a_routes.py -- R11 Part A's routes (`/v1/helpers/today`; D2, D7, D19) on a
# small app around the real router: owner-only and no-store; his own entry adds a bill but never
# a UPI ID;
# setting a UPI ID and Pay are R3 cards through the gateway in HIS conversation (none: 409); the
# approved payment's link and QR are answered once, then 404; numbers in a field are refused;
# off: 404 helpers_off.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r11_fakes import UID, Clock
from r11_fakes_a import FAKE_UPI, OTHER_UPI, Rig, every_text, gateway_rig, today_ctx

from jarvis.api.auth import require_auth
from jarvis.api.helpers import change_limiter
from jarvis.api.helpers_today import PREFIX, router
from jarvis.api.identity import current_user
from jarvis.core.models import Session
from jarvis.helpers.today import part as today_part
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

BILL = {"label": "Electricity", "payee": "Power Co", "amount": "1240", "day": 13}


@dataclass
class Tab:
    client: AsyncClient
    app: FastAPI
    rig: Rig
    docs: MemoryDocs
    clock: Clock
    session: str


@asynccontextmanager
async def tab(*, keys: bool = True, on: bool = True) -> AsyncIterator[Tab]:
    c, _, docs, clock = today_ctx(keys=keys)
    part = today_part.build(c)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    rig = gateway_rig(part)
    store = InMemorySessionStore()
    sess = Session(user_id=UID)
    await store.save(sess)
    st = app.state
    st.r11_parts = {"today": part} if on else {}
    st.helpers_off = None if on else "switched_off"
    st.helpers_now, st.gateway, st.store, st.helpers_limit = (
        clock,
        rig.gateway,
        store,
        change_limiter(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Tab(client, app, rig, docs, clock, sess.id)


async def _add(t: Tab, **over: Any) -> str:
    r = await t.client.post(f"{PREFIX}/bills", json={**BILL, **over})
    assert r.status_code == 201, r.text
    return str(r.json()["bills"]["items"][-1]["id"])


async def test_the_view_and_his_own_entry() -> None:
    async with tab() as t:
        r = await t.client.get(PREFIX)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert r.json()["bills"]["items"] == [] and r.json()["birthdays"]["state"] == "off"
        await _add(t)
        view = (await t.client.get(PREFIX)).json()
        (row,) = view["bills"]["items"]
        assert row["label"] == "Electricity" and row["upi"] == "" and row["ready"] is False
        assert view["top"]["label"] == "Electricity ₹1,240 due Fri 13 Nov"
        bad = await t.client.post(
            f"{PREFIX}/bills", json={**BILL, "label": "Card 4111111111111111"}
        )
        assert bad.status_code == 422 and "last 4" in bad.json()["detail"]
        sneaky = await t.client.post(f"{PREFIX}/bills", json={**BILL, "upi": FAKE_UPI})
        assert sneaky.status_code == 422  # no UPI field on his entry


async def test_a_upi_id_is_an_r3_card_in_his_conversation() -> None:
    async with tab() as t:
        bid = await _add(t)
        none = await t.client.post(f"{PREFIX}/bills/{bid}/payee", json={"upi": FAKE_UPI})
        assert none.status_code == 409 and none.json()["error"] == "no_conversation"
        body = {"upi": FAKE_UPI, "session_id": "sess_not_his"}
        assert (await t.client.post(f"{PREFIX}/bills/{bid}/payee", json=body)).status_code == 409
        r = await t.client.post(
            f"{PREFIX}/bills/{bid}/payee", json={"upi": FAKE_UPI, "session_id": t.session}
        )
        assert r.status_code == 202 and r.json()["status"] == "awaiting"
        (card,) = await t.rig.gateway.pending()
        assert card.tool == "bill_payee_set" and FAKE_UPI in card.summary
        assert (await t.client.get(PREFIX)).json()["bills"]["items"][0]["upi"] == ""  # not yet
        bad = {"upi": "not a upi", "session_id": t.session}
        assert (await t.client.post(f"{PREFIX}/bills/{bid}/payee", json=bad)).status_code == 422


async def _approve(t: Tab) -> None:
    from jarvis.llm.base import ToolCall

    for card in await t.rig.gateway.pending():
        call = ToolCall(id="ok", name=card.tool, arguments=card.arguments)
        await t.rig.gateway.execute(call, confirmation_id=card.id, scope=card.scope)


async def test_pay_is_a_card_and_the_payment_is_shown_once() -> None:
    async with tab() as t:
        bid = await _add(t)
        await t.client.post(
            f"{PREFIX}/bills/{bid}/payee", json={"upi": FAKE_UPI, "session_id": t.session}
        )
        await _approve(t)
        early = await t.client.post(f"{PREFIX}/bills/{bid}/payment")
        assert early.status_code == 404 and early.json()["error"] == "not_ready"
        r = await t.client.post(f"{PREFIX}/bills/{bid}/pay", json={"session_id": t.session})
        assert r.status_code == 202
        (card,) = await t.rig.gateway.pending()
        assert card.summary.startswith(
            "Get a UPI payment ready: ₹1,240.00 to Power Co (test@okfake)"
        )
        await _approve(t)
        assert (await t.client.get(PREFIX)).json()["bills"]["items"][0]["ready"] is True
        shown = await t.client.post(f"{PREFIX}/bills/{bid}/payment")
        assert shown.status_code == 200 and shown.headers["cache-control"] == "no-store"
        got = shown.json()
        assert got["link"].startswith("upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00&cu=INR")
        assert got["qr"].startswith("data:image/svg+xml") and got["amount"] == "₹1,240.00"
        again = await t.client.post(f"{PREFIX}/bills/{bid}/payment")
        assert again.status_code == 404
        assert "upi://" not in every_text(t.docs)


async def test_over_the_cap_paid_prefs_and_remove() -> None:
    async with tab() as t:
        bid = await _add(t)
        await t.client.post(
            f"{PREFIX}/bills/{bid}/payee", json={"upi": OTHER_UPI, "session_id": t.session}
        )
        await _approve(t)
        over = await t.client.post(
            f"{PREFIX}/bills/{bid}/pay", json={"amount": "100001", "session_id": t.session}
        )
        assert over.status_code == 422 and "1,00,000" in over.json()["detail"]
        paid = await t.client.post(f"{PREFIX}/bills/{bid}/paid")
        assert paid.status_code == 200 and paid.json()["top"] is None
        prefs = await t.client.put(
            f"{PREFIX}/prefs", json={"birthdays_on": True, "bills_at": "08:00"}
        )
        assert prefs.json()["bills"]["prefs"]["bills_at"] == "08:00"
        assert prefs.json()["birthdays"]["state"] == "not_connected"
        bad = await t.client.put(f"{PREFIX}/prefs", json={"bills_at": "9am"})
        assert bad.status_code == 422
        gone = await t.client.delete(f"{PREFIX}/bills/{bid}")
        assert gone.status_code == 200 and gone.json()["bills"]["items"] == []
        assert (await t.client.delete(f"{PREFIX}/bills/{bid}")).status_code == 422
        assert (await t.client.post(f"{PREFIX}/bills/aaaaaaaaaaaa/pay", json={})).status_code == 404


async def test_off_and_no_keyring() -> None:
    async with tab(on=False) as t:
        r = await t.client.get(PREFIX)
        assert r.status_code == 404 and r.json()["error"] == "helpers_off"
    async with tab(keys=False) as t:
        view = (await t.client.get(PREFIX)).json()
        assert view["bills"]["available"] is False and "token key" in view["bills"]["note"]
        r = await t.client.post(f"{PREFIX}/bills", json=BILL)
        assert r.status_code == 409 and r.json()["error"] == "bills_off"
