# tests/test_r18_i0_routes.py -- R18 I0: the calls router skeleton. Every REST path of the brief
# (and the desk link and kit) answers 501 until its part is wired on app.state, owner-only like
# the other owner routes; the two WebSockets close with 4501; a wired handler gets the owner's id.
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from jarvis.api import calls_routes as cr
from jarvis.api.identity import primary_user_id
from jarvis.calls import protocol as p
from jarvis.calls.ports import CallsRefused
from jarvis.config import Settings

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CARD, CALL = "cc_0123456789ab", "call_0123456789ab"
REST = [
    ("GET", "/v1/calls/status"),
    ("POST", "/v1/calls/cards"),
    ("POST", "/v1/calls/cards/estimate"),
    ("GET", f"/v1/calls/cards/{CARD}"),
    ("POST", f"/v1/calls/cards/{CARD}/approve"),
    ("POST", f"/v1/calls/cards/{CARD}/cancel"),
    ("GET", "/v1/calls/records"),
    ("GET", f"/v1/calls/records/{CALL}"),
    ("DELETE", f"/v1/calls/records/{CALL}"),
    ("PUT", f"/v1/calls/records/{CALL}/keep"),
    ("GET", f"/v1/calls/records/{CALL}/audio"),
    ("POST", f"/v1/calls/records/{CALL}/booking/undo"),
    ("GET", "/v1/calls/settings"),
    ("PUT", "/v1/calls/settings"),
    ("GET", "/v1/calls/languages"),
    ("POST", "/v1/calls/languages/check"),
    ("POST", "/v1/calls/languages/score"),  # I1: his 1-5 scores of a language's samples
    ("POST", "/v1/calls/desk/code"),
    ("DELETE", "/v1/calls/desk"),
    ("GET", "/v1/calls/desk/kit"),
    ("GET", "/v1/calls/desk/kit/info"),
]
DESK_LINK = ("POST", "/v1/calls/desk/link")  # the desk's own request: a link code, no session


def _settings(settings: Settings, **over: Any) -> Settings:
    return settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)} | over)


def _app(s: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = s
    cr.install_calls_routes(app)
    return app


def _send(c: TestClient, method: str, path: str, **kw: Any) -> Any:
    json_body = {"keep": True} if path.endswith("/keep") else {}
    body = {"json": json_body} if method in ("POST", "PUT") else {}
    return c.request(method, path, **(body | kw))


@pytest.mark.parametrize(("method", "path"), [*REST, DESK_LINK])
def test_every_path_answers_501_until_its_part_is_wired(
    settings: Settings, method: str, path: str
) -> None:
    with TestClient(_app(_settings(settings))) as c:
        got = _send(c, method, path, headers=AUTH)
    assert got.status_code == 501, got.text
    assert got.json()["error"] == "not_built" and got.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path"), REST)
def test_the_owner_routes_need_the_owner(settings: Settings, method: str, path: str) -> None:
    with TestClient(_app(_settings(settings))) as c:
        assert _send(c, method, path).status_code == 401


def test_the_desk_link_needs_no_owner_session(settings: Settings) -> None:
    with TestClient(_app(_settings(settings))) as c:
        assert _send(c, *DESK_LINK).status_code == 501  # not 401: the code is its proof


def test_calls_off_answers_503(settings: Settings) -> None:
    with TestClient(_app(_settings(settings, calls_enabled=False))) as c:
        got = c.get("/v1/calls/settings", headers=AUTH)
    assert got.status_code == 503 and got.json()["error"] == "calls_off"


def test_the_route_table_is_the_seams() -> None:
    assert {(m, r) for m, r in cr.ROUTES} == {
        (m, path.replace(CARD, "{card_id}").replace(CALL, "{call_id}")) for m, path in REST
    } | {DESK_LINK}
    assert cr.WEBSOCKETS == (p.DESK_WS_PATH, p.LIVE_WS_PATH)


class _Api:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        async def handler(*args: Any) -> dict[str, Any]:
            self.calls.append((name, args))
            if name == "cancel":
                raise CallsRefused(409, "already_used", "That card was already used.")
            if name == "record_audio":
                return b"OggS", "audio/ogg"  # type: ignore[return-value]
            return {"ok": True, "op": name}

        return handler


def test_a_wired_api_gets_the_owner_and_the_body(settings: Settings) -> None:
    s = _settings(settings)
    app = _app(s)
    api = _Api()
    app.state.calls_api = api
    with TestClient(app) as c:
        made = c.post("/v1/calls/cards", json={"purpose": "x"}, headers=AUTH)
        assert made.status_code == 200 and made.json() == {"ok": True, "op": "create_card"}
        refused = c.post(f"/v1/calls/cards/{CARD}/cancel", json={}, headers=AUTH)
        assert refused.status_code == 409
        assert refused.json() == {"error": "already_used", "detail": "That card was already used."}
        kept = c.put(f"/v1/calls/records/{CALL}/keep", json={"keep": True}, headers=AUTH)
        assert kept.status_code == 200
        audio = c.get(f"/v1/calls/records/{CALL}/audio", headers=AUTH)
        assert audio.content == b"OggS" and audio.headers["content-type"] == "audio/ogg"
        assert c.get("/v1/calls/records?limit=5", headers=AUTH).status_code == 200
        assert c.get("/v1/calls/records?limit=999", headers=AUTH).status_code == 422
        assert c.get("/v1/calls/cards/not-a-card", headers=AUTH).status_code == 422
        bad = c.post("/v1/calls/cards", content=b"[1]", headers=AUTH)
        assert bad.status_code == 422 and bad.json()["error"] == "input_rejected"
        big = c.post("/v1/calls/cards", content=b"{" + b" " * cr.BODY_MAX + b"}", headers=AUTH)
        assert big.status_code == 413
    uid = primary_user_id(s)
    assert api.calls[0] == ("create_card", (uid, {"purpose": "x"}))
    assert ("keep_record", (uid, CALL, True)) in api.calls
    assert ("list_records", (uid, 5)) in api.calls


def test_the_websockets_close_4501_until_wired(settings: Settings) -> None:
    with TestClient(_app(_settings(settings))) as c:
        with pytest.raises(WebSocketDisconnect) as desk:
            with c.websocket_connect(p.DESK_WS_PATH):
                pass
        assert desk.value.code == p.WS_NOT_BUILT
        live = p.LIVE_WS_PATH.format(call_id=CALL)
        with pytest.raises(WebSocketDisconnect) as nobody:
            with c.websocket_connect(live):
                pass
        assert nobody.value.code == p.WS_UNAUTHORIZED  # the owner first, then the part
        with pytest.raises(WebSocketDisconnect) as owner:
            with c.websocket_connect(live, headers=AUTH):
                pass
        assert owner.value.code == p.WS_NOT_BUILT
        with pytest.raises(WebSocketDisconnect) as bad:
            with c.websocket_connect(p.LIVE_WS_PATH.format(call_id="nope"), headers=AUTH):
                pass
        assert bad.value.code == p.WS_GONE


class _Sockets:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def desk(self, ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(p.dump(p.Ping()))
        await ws.close()

    async def live(self, ws: WebSocket, uid: str, call_id: str) -> None:
        self.seen.append((uid, call_id))
        await ws.accept()
        await ws.close()


def test_wired_sockets_get_the_socket_and_the_owner(settings: Settings) -> None:
    s = _settings(settings)
    app = _app(s)
    sockets = _Sockets()
    app.state.calls_sockets = sockets
    with TestClient(app) as c:
        with c.websocket_connect(p.DESK_WS_PATH) as ws:
            assert p.parse_cloud_to_desk(ws.receive_text()) == p.Ping()
        with c.websocket_connect(p.LIVE_WS_PATH.format(call_id=CALL), headers=AUTH):
            pass
    assert sockets.seen == [(primary_user_id(s), CALL)]


def test_a_cookie_session_from_another_origin_is_refused() -> None:
    class _WS:
        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = headers

    s = Settings(_env_file=None, public_base_url="https://jarvis.example.test")
    assert cr.same_origin(_WS({"origin": "https://jarvis.example.test"}), s)  # type: ignore[arg-type]
    assert not cr.same_origin(_WS({"origin": "https://evil.example.test"}), s)  # type: ignore[arg-type]
    assert not cr.same_origin(_WS({}), s)  # type: ignore[arg-type]
    dev = Settings(_env_file=None)
    assert cr.same_origin(_WS({"origin": "http://localhost:8000", "host": "localhost:8000"}), dev)  # type: ignore[arg-type]


def _flat(routes: Any, prefix: str = "") -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in routes:
        inner = getattr(r, "original_router", None)  # a lazily included router
        if inner is not None:
            out |= _flat(inner.routes, prefix + r.include_context.prefix)
            continue
        for m in getattr(r, "methods", None) or ("WEBSOCKET",):
            out.add((m, prefix + r.path))
    return out


def test_the_app_mounts_every_calls_route(settings: Settings) -> None:
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    mounted = _flat(create_app(settings, provider=MockProvider()).routes)
    assert set(cr.ROUTES) <= mounted
    assert {("WEBSOCKET", path) for path in cr.WEBSOCKETS} <= mounted
