# tests/test_usage_api.py — slice 7b: GET /v1/usage, PUT /v1/usage/budget (owner-only, CSRF on the
# write), the 402 a paid reply gets at the limit, and the rupee fields beside the USD ones.
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from billing_fakes import PricedMock, put_raw, registry
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
USAGE_KEYS = {
    "month",
    "used_inr",
    "limit_inr",
    "remaining_inr",
    "percent",
    "warn",
    "reached",
    "calls",
    "by_brain",
    "rate",
    "limit_unreadable",
}


@pytest.fixture
def tsettings(settings: Settings) -> Settings:
    """Token auth with a real token, one owner (the bearer token speaks for them)."""
    return settings.model_copy(
        update={"api_token": SecretStr("cli-token"), "owner_emails": [OWNER]}
    )


async def _client(s: Settings, paid: PricedMock) -> AsyncIterator[AsyncClient]:
    app = create_app(s, brains=registry(paid), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
def paid() -> PricedMock:
    return PricedMock(per_call=0.01)  # ₹0.95 a reply


@pytest.fixture
async def api(tsettings: Settings, paid: PricedMock) -> AsyncIterator[AsyncClient]:
    async for c in _client(tsettings, paid):
        yield c


async def _spend(c: AsyncClient, inr: float, brain: str = "anthropic") -> None:
    b = c.app.state.billing  # type: ignore[attr-defined]
    await b.meter.add(UID, brain_id=brain, cost_usd=inr / 95.24, cost_inr=inr, now=b.clock())


async def _put(c: AsyncClient, body: dict[str, Any], headers: dict[str, str] = BEARER) -> Any:
    return await c.put("/v1/usage/budget", json=body, headers=headers)


# ---- GET /v1/usage -------------------------------------------------------------------------------


async def test_usage_shape_with_nothing_spent(api: AsyncClient) -> None:
    r = await api.get("/v1/usage", headers=BEARER)
    assert r.status_code == 200
    j = r.json()
    assert set(j) == USAGE_KEYS
    assert re.fullmatch(r"\d{4}-\d{2}", j["month"])
    assert j["used_inr"] == 0 and j["calls"] == 0 and j["by_brain"] == []
    assert j["limit_inr"] is None and j["remaining_inr"] is None and j["percent"] is None
    assert j["warn"] is False and j["reached"] is False and j["limit_unreadable"] is False
    assert j["rate"] == {"inr_per_usd": 95.24, "as_of": "2026-11-01", "source": "default"}


async def test_usage_with_spend_and_a_limit(api: AsyncClient) -> None:
    await _spend(api, 30.0)
    await _spend(api, 8.13, brain="custom")
    await _put(api, {"monthly_limit_inr": 500})
    j = (await api.get("/v1/usage", headers=BEARER)).json()
    assert j["used_inr"] == 38.13 and j["limit_inr"] == 500 and j["remaining_inr"] == 461.87
    assert j["percent"] == 7.63 and j["warn"] is False and j["reached"] is False and j["calls"] == 2
    assert j["by_brain"] == [
        {"brain": "anthropic", "label": "Claude", "used_inr": 30.0},
        {"brain": "custom", "label": "Local", "used_inr": 8.13},
    ]


@pytest.mark.parametrize(
    ("spent", "warn", "reached", "percent", "remaining"),
    [
        (79.99, False, False, 79.99, 20.01),
        (80.0, True, False, 80.0, 20.0),
        (99.99, True, False, 99.99, 0.01),
        (100.0, True, True, 100.0, 0.0),
        (130.5, True, True, 130.5, 0.0),  # one reply can overshoot by its own cost
    ],
)
async def test_warn_at_80_percent_and_reached_at_the_limit(
    api: AsyncClient, spent: float, warn: bool, reached: bool, percent: float, remaining: float
) -> None:
    await _put(api, {"monthly_limit_inr": 100})
    await _spend(api, spent)
    j = (await api.get("/v1/usage", headers=BEARER)).json()
    assert (j["warn"], j["reached"], j["percent"], j["remaining_inr"]) == (
        warn,
        reached,
        percent,
        remaining,
    )


async def test_usage_needs_auth(api: AsyncClient) -> None:
    assert (await api.get("/v1/usage")).status_code == 401
    assert (await api.put("/v1/usage/budget", json={"monthly_limit_inr": 5})).status_code == 401


# ---- PUT /v1/usage/budget ------------------------------------------------------------------------


async def test_set_lower_raise_and_remove(api: AsyncClient) -> None:
    r = await _put(api, {"monthly_limit_inr": 500})
    assert r.status_code == 200 and set(r.json()) == USAGE_KEYS and r.json()["limit_inr"] == 500
    r = await _put(api, {"monthly_limit_inr": 600})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_budget" and "confirm" in r.json()["detail"]
    assert "$" not in r.json()["detail"]
    r = await _put(api, {"monthly_limit_inr": 600, "confirm_raise": True})
    assert r.status_code == 200 and r.json()["limit_inr"] == 600
    r = await _put(api, {"monthly_limit_inr": 200})  # lowering never asks
    assert r.status_code == 200 and r.json()["limit_inr"] == 200
    r = await _put(api, {"monthly_limit_inr": None})
    assert r.status_code == 422 and "confirm" in r.json()["detail"]
    r = await _put(api, {"monthly_limit_inr": None, "confirm_raise": True})
    assert r.status_code == 200 and r.json()["limit_inr"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"monthly_limit_inr": 0},
        {"monthly_limit_inr": 100_001},
        {"monthly_limit_inr": "500"},
        {"monthly_limit_inr": 12.5},
        {"monthly_limit_inr": 500, "confirm_raise": "yes"},
        {},
    ],
)
async def test_bad_limits_are_refused(api: AsyncClient, body: dict[str, Any]) -> None:
    r = await _put(api, body)
    assert r.status_code == 422
    assert (await api.get("/v1/usage", headers=BEARER)).json()["limit_inr"] is None


async def test_out_of_range_says_why_in_rupees(api: AsyncClient) -> None:
    r = await _put(api, {"monthly_limit_inr": 0})
    assert r.json() == {
        "error": "invalid_budget",
        "detail": "The limit must be a whole number of rupees from ₹1 to ₹1,00,000.",
    }


async def test_a_client_sent_user_id_is_ignored(api: AsyncClient) -> None:
    await _put(api, {"monthly_limit_inr": 50, "user_id": "u_other"})
    b = api.app.state.billing  # type: ignore[attr-defined]
    assert await b.budgets.get(UID) == 50 and await b.budgets.get("u_other") is None


# ---- cookie sessions: CSRF on the write ----------------------------------------------------------


@pytest.fixture
async def gapi(settings: Settings, paid: PricedMock) -> AsyncIterator[AsyncClient]:
    gs = settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )
    async for c in _client(gs, paid):

        async def fake_token(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1"}}

        c.app.state.oauth.google.authorize_access_token = fake_token  # type: ignore[attr-defined]
        await c.get("/auth/callback?code=x&state=y")
        yield c


async def test_cookie_write_needs_the_csrf_header(gapi: AsyncClient) -> None:
    assert (await gapi.get("/v1/usage")).status_code == 200  # reads need no header
    r = await gapi.put("/v1/usage/budget", json={"monthly_limit_inr": 5})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gapi.put("/v1/usage/budget", json={"monthly_limit_inr": 5}, headers=CSRF)
    assert r.status_code == 200 and r.json()["limit_inr"] == 5
    b = gapi.app.state.billing  # type: ignore[attr-defined]
    assert await b.budgets.get(UID) == 5  # the signed-in owner's own id, from the server


# ---- chat: 402 at the limit, rupees beside dollars -----------------------------------------------


async def test_chat_at_the_limit_is_a_402_in_rupees(api: AsyncClient, paid: PricedMock) -> None:
    await _put(api, {"monthly_limit_inr": 20})
    await _spend(api, 25.5)
    r = await api.post("/v1/chat", json={"message": "hi"}, headers=BEARER)
    assert r.status_code == 402
    assert r.json() == {
        "error": "budget_reached",
        "detail": "This month's limit of ₹20 is used up (₹25.50 spent). Raise it in Vitals, or "
        "switch to the free brain.",
    }
    assert paid.calls == []
    # the free brain still answers
    r = await api.post("/v1/chat", json={"message": "hi", "brain": "gemini"}, headers=BEARER)
    assert r.status_code == 200


async def test_stream_at_the_limit_is_a_402_too(api: AsyncClient, paid: PricedMock) -> None:
    await _put(api, {"monthly_limit_inr": 20})
    await _spend(api, 20.0)
    r = await api.post("/v1/chat/stream", json={"message": "hi"}, headers=BEARER)
    assert r.status_code == 402 and r.json()["error"] == "budget_reached"
    assert paid.calls == []
    async with api.stream(
        "POST", "/v1/chat/stream", json={"message": "hi", "brain": "gemini"}, headers=BEARER
    ) as s:
        assert s.status_code == 200
        assert "hi" in "".join([t async for t in s.aiter_text()])


async def test_a_limit_check_that_cannot_read_is_a_503_not_a_crash(api: AsyncClient) -> None:
    b = api.app.state.billing  # type: ignore[attr-defined]

    async def broken(uid: str) -> int | None:
        raise RuntimeError("firestore down")

    b.budgets.get = broken
    r = await api.post("/v1/chat", json={"message": "hi"}, headers=BEARER)
    assert r.status_code == 503 and r.json()["error"] == "budget_unavailable"
    assert "free brain" in r.json()["detail"]


async def test_chat_and_session_views_carry_rupees_beside_dollars(api: AsyncClient) -> None:
    r = (await api.post("/v1/chat", json={"message": "hi"}, headers=BEARER)).json()
    assert r["cost_usd"] == 0.01 and r["cost_inr"] == pytest.approx(0.9524)
    assert r["total_cost_usd"] == pytest.approx(0.01) and r["total_cost_inr"] == pytest.approx(
        0.9524
    )
    sid = r["session_id"]
    r2 = (
        await api.post("/v1/chat", json={"message": "again", "session_id": sid}, headers=BEARER)
    ).json()
    assert r2["total_cost_inr"] == pytest.approx(2 * 0.9524)
    s = (await api.get(f"/v1/sessions/{sid}", headers=BEARER)).json()
    assert s["total_cost_usd"] == pytest.approx(0.02)
    assert s["total_cost_inr"] == pytest.approx(1.9048)
    (row,) = (await api.get("/v1/sessions", headers=BEARER)).json()
    assert row["total_cost_inr"] == pytest.approx(1.9048)
    assert row["total_cost_usd"] == pytest.approx(0.02)
    j = (await api.get("/v1/usage", headers=BEARER)).json()
    assert j["calls"] == 2 and j["used_inr"] == 1.9


async def test_brief_cost_note_is_rupees_only(api: AsyncClient) -> None:
    j = (await api.get("/v1/brief/today", headers=BEARER)).json()
    note = j["ai_cost_note"]
    assert "₹" in note and "$" not in note


# ---- fail closed: a limit or a month total that can't be read ------------------------------------


async def test_an_unreadable_limit_is_shown_and_any_change_needs_the_confirm(
    api: AsyncClient, paid: PricedMock
) -> None:
    b = api.app.state.billing  # type: ignore[attr-defined]
    await put_raw(b.budgets._d, f"jarvis_budget/{UID}", {"monthly_limit_inr": "lots"})
    await _spend(api, 12.0)
    j = (await api.get("/v1/usage", headers=BEARER)).json()
    assert set(j) == USAGE_KEYS and j["limit_unreadable"] is True
    assert j["limit_inr"] is None and j["remaining_inr"] is None and j["percent"] is None
    assert j["reached"] is False and j["warn"] is False and j["used_inr"] == 12.0
    r = await api.post("/v1/chat", json={"message": "hi"}, headers=BEARER)
    assert r.status_code == 503 and r.json()["error"] == "budget_unavailable"
    assert paid.calls == []
    r = await _put(api, {"monthly_limit_inr": 300})  # a "lower"? nobody knows what it was
    assert r.status_code == 422 and r.json()["error"] == "invalid_budget"
    assert "can't be read" in r.json()["detail"] and "$" not in r.json()["detail"]
    r = await _put(api, {"monthly_limit_inr": 300, "confirm_raise": True})
    assert r.status_code == 200
    assert r.json()["limit_inr"] == 300 and r.json()["limit_unreadable"] is False
    assert (await api.post("/v1/chat", json={"message": "hi"}, headers=BEARER)).status_code == 200


async def test_an_unreadable_month_total_is_a_plain_503(api: AsyncClient) -> None:
    b = api.app.state.billing  # type: ignore[attr-defined]
    month = b.meter.month_of(b.clock())
    await put_raw(b.meter._d, f"jarvis_usage/{UID}_{month}", {"inr_total": "lots"})
    r = await api.get("/v1/usage", headers=BEARER)
    assert r.status_code == 503 and r.json()["error"] == "budget_unavailable"
    detail = r.json()["detail"]
    assert "spending" in detail and "$" not in detail and "lots" not in detail


async def test_a_storage_outage_on_the_usage_view_is_a_503_not_a_500(api: AsyncClient) -> None:
    b = api.app.state.billing  # type: ignore[attr-defined]

    async def broken(uid: str) -> int | None:
        raise RuntimeError("firestore down")

    b.budgets.get = broken
    r = await api.get("/v1/usage", headers=BEARER)
    assert r.status_code == 503 and r.json()["error"] == "budget_unavailable"
    assert "firestore" not in r.json()["detail"].lower()


@pytest.mark.parametrize(
    ("path", "raw"),
    [
        ("/v1/usage/budget", '{"monthly_limit_inr": NaN}'),
        ("/v1/usage/budget", '{"monthly_limit_inr": Infinity, "confirm_raise": true}'),
        ("/v1/chat", '{"message": NaN}'),
    ],
)
async def test_nan_in_a_json_body_is_a_422_not_a_crash(
    api: AsyncClient, path: str, raw: str
) -> None:
    """Python's JSON reader accepts NaN; the default 422 echoed it back and failed to render."""
    method = "PUT" if path.endswith("budget") else "POST"
    r = await api.request(
        method, path, content=raw, headers={**BEARER, "Content-Type": "application/json"}
    )
    assert r.status_code == 422
    errs = r.json()["detail"]
    assert errs and all(set(e) <= {"type", "loc", "msg"} for e in errs)  # the input isn't echoed
