# tests/test_r11_1_c_api.py -- R11.1 Part C on the real app: the part is built by `wire_r11_1`
# with its two jobs on the helpers' 5-minute clock, its two read tools on the gateway and its two
# rows on the privacy dashboard; its routes under /v1/facegroups are owner-only, `no-store`,
# rate-limited, and carry ids and counts only. Photos, Faces and the home link are found late on
# `app.state`, so here the app's Photos is the in-process cloud + bridge rig.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from home_fakes import UID
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r11_1_fakes_c import Cloud, build_cloud, consent, leaks, picture

from jarvis.api import create_app
from jarvis.api.identity import current_user
from jarvis.config import Settings
from jarvis.integrations.google import GoogleNotConnected
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

BASE = "/v1/facegroups"
CSRF = {"X-Requested-With": "JARVIS"}


@dataclass
class Running:
    app: FastAPI
    client: AsyncClient
    cloud: Cloud
    bodies: list[str]

    async def get(self, path: str) -> Any:
        r = await self.client.get(BASE + path)
        self.bodies.append(r.text)
        return r

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        r = await self.client.post(BASE + path, json=body or {}, headers=CSRF)
        self.bodies.append(r.text)
        return r


@asynccontextmanager
async def running(s: Settings, tmp: Path, *, photos: bool = True) -> AsyncIterator[Running]:
    cloud = await build_cloud(tmp)
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    app.dependency_overrides[current_user] = lambda: UID
    async with app.router.lifespan_context(app):
        if photos:
            app.state.photos = cloud.photos  # found late by the part, as on the real server
            cloud.groups = app.state.r111_parts["photos"].services["groups"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield Running(app, c, cloud, [])
    await cloud.home.aclose()


async def test_the_part_is_wired_into_the_app(settings: Settings, tmp_path: Path) -> None:
    async with running(settings, tmp_path) as w:
        part = w.app.state.r111_parts["photos"]
        assert part.ready == "ready" and len(part.tools) == 2
        registry = w.app.state.gateway.registry
        assert all(registry.get(n) is not None for n in ("faces_groups", "photos_import_status"))
        clock = w.app.state.helpers_clock
        assert {"photos_import", "face_groups_poll"} <= set(clock.job_names)
        ids = w.app.state.privacy.registry.ids()
        assert ids.index("photo_imports") < ids.index("face_groups") < ids.index("faces")
        r = await w.get("")
        assert r.json() == {"part": "photos", "ready": "ready"}
        assert r.headers["cache-control"] == "no-store"


async def test_without_photos_on_this_server_the_part_says_why(
    settings: Settings, tmp_path: Path
) -> None:
    async with running(settings, tmp_path, photos=False) as w:
        assert (await w.get("")).json()[
            "ready"
        ] == "off: needs Google sign-in, Faces and the home kit"
        body = (await w.get("/groups")).json()
        assert body["available"] is False and "home kit" in body["reason"] and body["groups"] == []
        # R11.1 I1: a read answers the state (the browser logs any 503 as a console error)
        job = await w.get("/import")
        assert job.status_code == 200 and job.json()["status"] == "off"
        assert job.json()["available"] is False and "home kit" in job.json()["reason"]
        r = await w.client.delete(BASE + "/import", headers=CSRF)
        assert r.status_code == 503  # an action that cannot be done still says so
        r = await w.post("/groups/c_0123456789ab/name", consent())
        assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_groups_are_listed_as_ids_and_counts(settings: Settings, tmp_path: Path) -> None:
    async with running(settings, tmp_path) as w:
        gid = await w.cloud.group_of(1)
        await w.cloud.at_home(2, needle=True)
        r = await w.get("/groups")
        body = r.json()
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert body["available"] is True and body["laptop"] == "online"
        assert body["groups"] == [
            {
                "id": gid,
                "n": 1,
                "photos": 3,
                "first": body["groups"][0]["first"],
                "last": body["groups"][0]["last"],
            }
        ]
        assert (body["strays"], body["named"], body["keep_days"]) == (1, 0, 90)
        assert body["local_url"] == "http://localhost:8098/faces"  # where the owner sees who it is
        assert leaks("".join(w.bodies)) == []


async def test_naming_over_http_needs_the_consent_statement(
    settings: Settings, tmp_path: Path
) -> None:
    async with running(settings, tmp_path) as w:
        gid = await w.cloud.group_of(1)
        r = await w.post(f"/groups/{gid}/name", consent(confirm=False))
        assert r.status_code == 422 and r.json()["error"] == "consent_missing"
        r = await w.post(f"/groups/{gid}/name", consent(name="Mini", child=True))
        assert r.status_code == 422 and r.json()["error"] == "child_needs_guardian"
        assert (await w.cloud.home.faces.state(UID)).people == ()
        r = await w.post(f"/groups/{gid}/name", consent())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["at_home"] is True and body["person_id"].startswith("fp_")
        assert set(body) == {"person_id", "at_home", "contact_matched"}
        assert (await w.get("/groups")).json()["groups"] == []
        for path, payload, status in (
            ("/groups/c_0123456789ab/name", consent(), 404),
            ("/groups/not-a-group/name", consent(), 404),
            (f"/groups/{gid}/name", {}, 422),  # neither a name nor a person
            (f"/groups/{gid}/name", {**consent(), "person_id": body["person_id"]}, 422),  # both
            (f"/groups/{gid}/name", {**consent(), "crop": "x"}, 422),  # nothing else is taken
        ):
            assert (await w.post(path, payload)).status_code == status, (path, payload)


async def test_a_second_group_of_someone_already_added_asks_for_nothing_again(
    settings: Settings, tmp_path: Path
) -> None:
    async with running(settings, tmp_path) as w:
        first = await w.cloud.group_of(1)
        second = await w.cloud.group_of(40, start=10)
        pid = (await w.post(f"/groups/{first}/name", consent())).json()["person_id"]
        r = await w.post(f"/groups/{second}/name", {"person_id": pid})
        assert r.status_code == 200 and r.json()["person_id"] == pid
        assert len((await w.cloud.home.faces.state(UID)).people) == 1
        r = await w.post(f"/groups/{second}/name", {"person_id": "fp_ffffffffffff"})
        assert r.status_code == 404


async def test_forget_says_done_only_when_the_laptop_confirmed(
    settings: Settings, tmp_path: Path
) -> None:
    async with running(settings, tmp_path) as w:
        one = await w.cloud.group_of(1)
        two = await w.cloud.group_of(2, start=10)
        r = await w.post(f"/groups/{one}/forget")
        assert r.json() == {"done": True, "forgotten": 1, "left": 1}
        w.cloud.home.online = False
        r = await w.post(f"/groups/{two}/forget")
        assert r.status_code == 200 and r.json() == {"done": False, "forgotten": 0, "left": 0}
        body = (await w.get("/groups")).json()
        assert body["laptop"] == "offline" and body["forgets_waiting"] == 1
        assert (await w.post("/groups/nope/forget")).status_code == 404


async def test_the_import_routes_step_report_and_stop(settings: Settings, tmp_path: Path) -> None:
    s = settings.model_copy(update={"photos_import_batch": 2})
    async with running(s, tmp_path) as w:
        assert (await w.get("/import")).json()["status"] == "no_session"
        w.cloud.picker.photos = [picture(1, n=i, needle=True) for i in range(60)]
        w.cloud.picker.items = type(w.cloud.picker)(w.cloud.picker.photos).items
        await w.cloud.photos.begin(UID)
        r = await w.post("/import/step")
        body = r.json()
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        # review C-code M6: as many as fit the panel's short step (here all 50 a step may read),
        # never fewer than the setting (2), never the whole pick in one request
        assert (body["status"], body["photos"], body["total"]) == ("reading", 50, 60)
        assert body["line"].startswith("50 of 60 read · 50 faces found")
        assert (await w.get("/import")).json()["photos"] == 50
        r = await w.client.delete(BASE + "/import", headers=CSRF)
        assert r.status_code == 200 and r.json()["status"] == "no_session"
        assert (await w.post("/import/step")).json()["status"] == "no_session"
        assert leaks("".join(w.bodies)) == []


async def test_changes_are_rate_limited_per_owner(settings: Settings, tmp_path: Path) -> None:
    async with running(settings, tmp_path) as w:
        codes = [(await w.post("/groups/c_0123456789ab/forget")).status_code for _ in range(35)]
        assert 429 in codes and codes[:10] == [200] * 10
        body = (await w.post("/groups/c_0123456789ab/forget")).json()
        assert body == {"error": "rate_limited", "detail": "Too many changes; wait a moment."}


async def test_the_routes_are_owner_only(settings: Settings, tmp_path: Path) -> None:
    s = settings.model_copy(update={"api_token": SecretStr("the-test-token-0123456789")})
    async with running(s, tmp_path) as w:
        for path in ("", "/groups", "/import"):
            assert (await w.client.get(BASE + path)).status_code == 401, path
        r = await w.client.post(BASE + "/groups/c_0123456789ab/forget")
        assert r.status_code == 401
        ok = await w.client.get(
            BASE + "/groups", headers={"Authorization": "Bearer the-test-token-0123456789"}
        )
        assert ok.status_code == 200


async def test_nothing_but_ids_and_counts_comes_back(settings: Settings, tmp_path: Path) -> None:
    async with running(settings, tmp_path) as w:
        gid = await w.cloud.group_of(1)
        await w.get("/groups")
        await w.post(f"/groups/{gid}/name", consent())
        await w.post(f"/groups/{gid}/forget")
        await w.get("/import")
        text = "".join(w.bodies)
        assert leaks(text) == [] and "embedding" not in text and "crop" not in text
        assert json.loads(w.bodies[0])["groups"][0].keys() == {"id", "n", "photos", "first", "last"}


async def test_google_not_linked_is_said_plainly_and_nothing_breaks(
    settings: Settings, tmp_path: Path
) -> None:
    async with running(settings, tmp_path) as w:
        await w.cloud.photos.begin(UID)

        async def unlinked(uid: str, sid: str) -> None:
            raise GoogleNotConnected("Sign in with Google first: Integrations -> Google.")

        w.cloud.picker.get_session = unlinked  # type: ignore[method-assign]
        r = await w.post("/import/step")
        assert r.status_code == 409 and r.json()["error"] == "photos_unavailable"
        assert r.json()["detail"] == "Sign in with Google first: Integrations -> Google."
        assert (await w.get("/import")).status_code == 200  # the progress is still readable
        assert (await w.get("/groups")).json()["available"] is True  # and the groups do not care
