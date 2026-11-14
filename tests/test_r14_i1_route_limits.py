# tests/test_r14_i1_route_limits.py -- R14 I1 follow-up (integrated security review LOW-5): the
# four R14 status reads (`GET /v1/backup`, `/v1/selfwatch`, `/v1/skills`, `/v1/costs/ledger`)
# each cost 1 to 31 Firestore reads, and only the app-wide limit held them. Each now has its own
# per-owner limit, as `POST /v1/backup/drill` and other routes do: past it, a 429 with no
# body of data, `no-store` and `Retry-After`; another owner has his own allowance.
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from jarvis.api import backup as backup_api
from jarvis.api import r14_status
from jarvis.api import selfwatch as selfwatch_api
from jarvis.api import skills as skills_api
from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.config import Settings

ROUTES = ("/v1/backup", "/v1/selfwatch", "/v1/skills", "/v1/costs/ledger")


def _app(settings: Settings, who: dict[str, str]) -> FastAPI:
    app = FastAPI()
    for router in (backup_api.router, selfwatch_api.router, skills_api.router):
        app.include_router(router)
    app.state.settings, app.state.r14_parts = settings, {}
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: who["uid"]
    return app


@pytest.mark.parametrize("path", ROUTES)
async def test_each_status_read_has_its_own_per_owner_limit(settings: Settings, path: str) -> None:
    who = {"uid": "u_aaaaaaaaaaaaaaaa"}
    transport = httpx.ASGITransport(app=_app(settings, who))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        for _ in range(r14_status.READS_PER_MINUTE):
            assert (await client.get(path)).status_code == 200
        over = await client.get(path)
        assert over.status_code == 429
        assert over.json() == {
            "error": "rate_limited",
            "detail": "Too many requests; wait a minute.",
        }
        assert over.headers["cache-control"] == "no-store" and int(over.headers["retry-after"]) >= 1
        other = next(p for p in ROUTES if p != path)
        assert (await client.get(other)).status_code == 200  # each route has its own
        who["uid"] = "u_bbbbbbbbbbbbbbbb"
        assert (await client.get(path)).status_code == 200  # and each owner
