# tests/test_r7_i1_fixes.py -- R7 I1 fixer: the Workshop's decisions on the two integrated reviews.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from r7_fakes_c import CSRF, ORIGIN, phone_app, sign_in_again

from jarvis.config import Settings
from jarvis.phone import applock

DEV = applock.DEVICE_KEY


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Any]:
    async with phone_app(settings) as a:
        yield a


# ---- security L3: a link from another site cannot mark this browser as the app -------------------
async def test_a_cross_site_visit_to_source_app_marks_nothing(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        r = await c.get("/?source=app", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 302 and r.headers["location"] == "/"  # the page never sees `source`
        # even a mark the page would send is refused when the browser says the call is not its own
        for site in ("cross-site", "same-site"):
            r = await c.post("/v1/session/app", headers={**CSRF, "Sec-Fetch-Site": site})
            assert r.json() == {"app": False}
            assert DEV not in c.cookies and not r.headers.get_list("set-cookie")
        assert (await c.get("/v1/session/lock")).json()["app"] is False


@pytest.mark.parametrize("site", ["none", "same-origin", None])
async def test_a_typed_or_app_launch_still_marks_the_app(app: Any, site: str | None) -> None:
    extra = {} if site is None else {"Sec-Fetch-Site": site}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        await sign_in_again(app, c)
        assert (await c.get("/?source=app", headers=extra)).status_code in (200, 302)
        r = await c.post("/v1/session/app", headers={**CSRF, **extra})
        assert r.json() == {"app": True} and c.cookies.get(DEV)
        assert (await c.get("/v1/session/lock")).json()["app"] is True


# ---- security L4: a flood or a rate limit is a bare 429, never the "unknown phone" 401 -------------
async def test_the_door_answers_a_flood_with_a_bare_429_and_keeps_401_for_authentication(
    app: Any,
) -> None:
    from jarvis.mobile import contract

    now = int(app.state.phone_clock())
    head = contract.header_value("ph_000000000000", now, "ab" * 16, b"signature" * 6)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as anon:
        seen = []
        for _ in range(64):
            r = await anon.post("/phone/v1/hello", content=b"{}", headers={"X-Jarvis-Phone": head})
            seen.append(r.status_code)
        assert seen[:60] == [401] * 60  # an unknown phone is still a bare 401
        assert seen[60:] == [429] * 4
        assert r.content == b"" and "set-cookie" not in r.headers
        # authentication failures are still 401, whichever check refuses
        bare = await anon.post("/phone/v1/hello", content=b"{}", headers={})
        assert bare.status_code == 401 and bare.content == b""
        other = await anon.get("/phone/v1/hello")
        assert other.status_code == 404
