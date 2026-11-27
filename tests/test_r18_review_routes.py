# tests/test_r18_review_routes.py -- R18 combined review: a calls route never answers a bare 500.
# Anything a part raises besides its own `CallsRefused` (a store that is down, a seal that does
# not open, a bug) is logged by its class name and answered 503 in plain words, the error's own
# text never shown; the language check's score answers 422 for a bad score, not a 500.
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_r18_i0_routes import REST, TOKEN

from jarvis.api import calls_routes as cr
from jarvis.config import Settings

AUTH = {"Authorization": f"Bearer {TOKEN}"}
SECRET = "boom-0123456789-secret"


class _Broken:
    """Every slot method raises something that is not a refusal."""

    version = "18.0.0"

    def build(self) -> bytes:
        raise RuntimeError(SECRET)

    def __getattr__(self, name: str) -> Any:
        async def broken(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(SECRET)

        return broken


def _client(settings: Settings) -> TestClient:
    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
    app = FastAPI()
    app.state.settings = s
    for slot in (cr.API_SLOT, cr.DOOR_SLOT, cr.KIT_SLOT, cr.SOCKETS_SLOT):
        setattr(app.state, slot, _Broken())
    cr.install_calls_routes(app)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path"), [*REST, ("POST", "/v1/calls/desk/link")])
def test_review_a_failing_part_answers_503_in_plain_words(
    settings: Settings, method: str, path: str
) -> None:
    if path.endswith("/live/ticket"):
        pytest.skip("the ticket is the route's own: nothing of a part runs")
    c = _client(settings)
    body = {"json": {"keep": True} if path.endswith("/keep") else {}}
    r = c.request(method, path, headers=AUTH, **(body if method in ("POST", "PUT") else {}))
    assert r.status_code == 503, (path, r.status_code)
    assert r.json()["error"] == "unavailable" and SECRET not in r.text
    assert r.headers["cache-control"] == "no-store"


async def test_review_a_bad_voice_score_is_422_not_500() -> None:
    from jarvis.calls.join_speech import LanguageCheckJob
    from jarvis.calls.ports import CallsRefused
    from jarvis.calls.store import MemoryCallStore

    class _Check:
        async def score(self, lang: str, option: str, scores: Any) -> Any:
            raise ValueError("Score at least one sample, 1 to 5.")

    async def make(uid: str, settings: Any) -> Any:
        return _Check()

    job = LanguageCheckJob(make, MemoryCallStore())
    with pytest.raises(CallsRefused) as bad:
        await job.score("u", {"lang": "ml-IN", "option": "google", "scores": [4]})
    assert bad.value.status == 422 and "1 to 5" in bad.value.words

    async def down(uid: str, settings: Any) -> Any:
        raise RuntimeError(SECRET)

    with pytest.raises(CallsRefused) as gone:
        await LanguageCheckJob(down, MemoryCallStore()).score(
            "u", {"lang": "ml-IN", "option": "google", "scores": [4]}
        )
    assert gone.value.status == 503 and SECRET not in gone.value.words


def test_review_a_live_ticket_is_taken_only_when_no_other_credential_came(
    settings: Settings,
) -> None:
    # R18 review: ?ticket= is the token mode's way in only when the socket brought no bearer and
    # no session cookie; a wrong bearer beside a good ticket is refused (and spends no ticket)
    from fastapi import WebSocket
    from starlette.websockets import WebSocketDisconnect
    from test_r18_i0_routes import CALL

    from jarvis.calls import protocol as p

    class _Sockets:
        async def live(self, ws: WebSocket, uid: str, call_id: str) -> None:
            await ws.accept()
            await ws.close()

        async def desk(self, ws: WebSocket) -> None:
            await ws.close()

    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
    app = FastAPI()
    app.state.settings = s
    app.state.calls_sockets = _Sockets()
    cr.install_calls_routes(app)
    origin = {"Origin": "http://testserver"}
    with TestClient(app) as c:
        ticket = c.post(f"/v1/calls/{CALL}/live/ticket", json={}, headers=AUTH).json()["ticket"]
        wrong = origin | {"Authorization": "Bearer " + "w" * 32}
        with pytest.raises(WebSocketDisconnect) as refused:
            with c.websocket_connect(f"/v1/calls/{CALL}/live?ticket={ticket}", headers=wrong) as ws:
                ws.receive_text()
        assert refused.value.code == p.WS_UNAUTHORIZED
        with c.websocket_connect(f"/v1/calls/{CALL}/live?ticket={ticket}", headers=origin):
            pass  # not spent by the refused try
