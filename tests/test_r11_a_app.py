# tests/test_r11_a_app.py -- R11 Part A on the REAL app, wired by I0's unchanged `wire_r11`: the
# part is built (its jobs ride the helpers' clock, its rows join the privacy dashboard, its tools
# are in the gateway), the Today routes answer, and with the AI off "pay the electricity bill" in
# the chat makes the R3 card through the gateway (no model), whose approval leaves a payment the
# tab shows once.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r11_fakes_a import FAKE_UPI, TEST_ROOT

from jarvis.api import create_app
from jarvis.api.identity import primary_user_id
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

CSRF = {"X-Requested-With": "JARVIS"}
TODAY = "/v1/helpers/today"


@asynccontextmanager
async def app_with_key(settings: Settings) -> AsyncIterator[tuple[Any, AsyncClient]]:
    s = settings.model_copy(update={"token_key": SecretStr(base64.b64encode(TEST_ROOT).decode())})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_part_a_is_wired_into_the_app(settings: Settings) -> None:
    async with app_with_key(settings) as (app, c):
        st = app.state
        assert st.r11_parts["today"].ready.startswith("Bills, birthdays")
        assert {"bills_due", "birthdays"} <= set(st.helpers_clock.job_names)
        for name in ("bill_pay_prepare", "bill_payee_set", "focus_now", "contacts_birthdays"):
            assert st.gateway.registry.get(name) is not None
        assert {"helpers_bills", "helpers_birthdays"} <= set(st.privacy.registry.ids())
        r = await c.get(TODAY)
        assert r.status_code == 200 and r.json()["bills"]["available"] is True


async def test_no_ai_pay_makes_the_card_and_the_payment_shows_once(settings: Settings) -> None:
    async with app_with_key(settings) as (app, c):
        body = {"label": "Electricity", "payee": "Power Co", "amount": "1240", "day": 13}
        bid = (await c.post(f"{TODAY}/bills", json=body, headers=CSRF)).json()["bills"]["items"][0][
            "id"
        ]
        svc = app.state.r11_parts["today"].services["bills"]
        owner = primary_user_id(app.state.settings)  # who the routes and the chat run for
        await svc.set_payee(owner, bid, upi=FAKE_UPI)  # his typing, as an approved card does
        r = await c.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=CSRF)
        assert r.status_code == 200, r.text
        chat = await c.post("/v1/chat", json={"message": "pay the electricity bill"})
        assert chat.status_code == 200, chat.text
        (card,) = chat.json()["pending_approvals"]
        assert card["summary"].startswith(
            "Get a UPI payment ready: ₹1,240.00 to Power Co (test@okfake)"
        )
        sid = chat.json()["session_id"]
        ok = await c.post(
            f"/v1/approvals/{card['id']}/approve", json={"session_id": sid}, headers=CSRF
        )
        assert ok.status_code == 200, ok.text
        assert "upi://" not in ok.text
        shown = await c.post(f"{TODAY}/bills/{bid}/payment", json={}, headers=CSRF)
        assert shown.status_code == 200 and shown.json()["link"].startswith(
            "upi://pay?pa=test@okfake"
        )
        again = await c.post(f"{TODAY}/bills/{bid}/payment", json={}, headers=CSRF)
        assert again.status_code == 404
        convo = (await c.get(f"/v1/sessions/{sid}")).text
        assert "upi://" not in convo and "svg" not in convo
