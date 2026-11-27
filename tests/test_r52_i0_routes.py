# tests/test_r52_i0_routes.py -- R5.2 I0: the voice profile router skeleton. Every path answers 501
# until its part is wired on app.state (V2 the laptop, V3 the session and profile, V4 the wake
# word), owner-only, no-store; the recordings' delete asks for its confirmation word; a wired part
# gets the owner's id and the checked body.
from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from jarvis.api import voice_profile_routes as vr
from jarvis.api.identity import primary_user_id
from jarvis.config import Settings
from jarvis.voice.profile_ports import ProfileRefused

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PROMPT = "cmd_lights"
REST = [
    ("GET", "/v1/voice/profile"),
    ("PUT", "/v1/voice/profile"),
    ("GET", "/v1/voice/profile/session"),
    ("POST", "/v1/voice/profile/session/start"),
    ("PUT", f"/v1/voice/profile/session/clips/{PROMPT}"),
    ("POST", "/v1/voice/profile/session/score"),
    ("GET", "/v1/voice/profile/session/results"),
    ("POST", "/v1/voice/profile/recheck"),
    ("POST", "/v1/voice/profile/recordings/delete"),
    ("GET", "/v1/voice/profile/laptop"),
    ("GET", "/v1/voice/profile/wakeword"),
    ("POST", "/v1/voice/profile/wakeword/train"),
    ("GET", "/v1/voice/profile/wakeword/verifier"),
    ("GET", "/v1/voice/profile/wakeword/model"),
]
WAV = b"RIFF" + b"\x00" * 40
CLIP = {"audio": base64.b64encode(WAV).decode(), "browser_heard": "lights on"}


def _settings(settings: Settings, **over: Any) -> Settings:
    return settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)} | over)


def _app(s: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = s
    vr.install_voice_profile_routes(app)
    return app


def _body(path: str) -> dict[str, Any]:
    if path.endswith("/recordings/delete"):
        return {"confirm": vr.CONFIRM_WORD}
    if "/clips/" in path:
        return CLIP
    return {}


def _send(c: TestClient, method: str, path: str, **kw: Any) -> Any:
    body = {"json": _body(path)} if method in ("POST", "PUT") else {}
    return c.request(method, path, **(body | kw))


@pytest.mark.parametrize(("method", "path"), REST)
def test_every_path_answers_501_until_its_part_is_wired(
    settings: Settings, method: str, path: str
) -> None:
    with TestClient(_app(_settings(settings))) as c:
        got = _send(c, method, path, headers=AUTH)
    assert got.status_code == 501, got.text
    assert got.json()["error"] == "not_built" and got.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path"), REST)
def test_every_path_needs_the_owner(settings: Settings, method: str, path: str) -> None:
    with TestClient(_app(_settings(settings))) as c:
        assert _send(c, method, path).status_code == 401


def test_switched_off_answers_503(settings: Settings) -> None:
    with TestClient(_app(_settings(settings, voice_profile_enabled=False))) as c:
        got = c.get("/v1/voice/profile", headers=AUTH)
    assert got.status_code == 503 and got.json()["error"] == "voice_profile_off"


def test_the_route_table_is_the_seams() -> None:
    assert set(vr.ROUTES) == {(m, path.replace(PROMPT, "{prompt_id}")) for m, path in REST}
    assert {slot for slot, _ in vr.SLOTS.values()} == {
        "voice_profile_api",
        "voice_laptop",
        "voice_wakeword",
    }
    assert set(vr.SLOTS) == set(vr.ROUTES)


class _Part:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        async def handler(*args: Any) -> Any:
            self.calls.append((name, args))
            if name == "score":
                raise ProfileRefused(402, "needs_yes", "This uses ₹12.40 of Google time. Go on?")
            if name in ("verifier", "model"):
                return b"\x08\x01onnx", "application/octet-stream"
            return {"ok": True, "op": name}

        return handler


def test_wired_parts_get_the_owner_and_the_body(settings: Settings) -> None:
    s = _settings(settings)
    app = _app(s)
    api, laptop, wake = _Part(), _Part(), _Part()
    app.state.voice_profile_api, app.state.voice_laptop, app.state.voice_wakeword = (
        api,
        laptop,
        wake,
    )
    uid = primary_user_id(s)
    with TestClient(app) as c:
        assert c.get("/v1/voice/profile", headers=AUTH).json() == {"ok": True, "op": "view"}
        put = c.put(f"/v1/voice/profile/session/clips/{PROMPT}", json=CLIP, headers=AUTH)
        assert put.status_code == 200, put.text
        asked = c.post("/v1/voice/profile/session/score", json={}, headers=AUTH)
        assert asked.status_code == 402 and asked.json()["error"] == "needs_yes"
        model = c.get("/v1/voice/profile/wakeword/model", headers=AUTH)
        assert model.content == b"\x08\x01onnx" and model.headers["cache-control"] == "no-store"
        assert c.get("/v1/voice/profile/laptop", headers=AUTH).json()["op"] == "status"
        bad = c.put("/v1/voice/profile/session/clips/Not%20An%20Id", json=CLIP, headers=AUTH)
        assert bad.status_code == 422
        unconfirmed = c.post("/v1/voice/profile/recordings/delete", json={}, headers=AUTH)
        assert unconfirmed.status_code == 422 and unconfirmed.json()["error"] == "confirm_needed"
        gone = c.post(
            "/v1/voice/profile/recordings/delete", json={"confirm": "DELETE"}, headers=AUTH
        )
        assert gone.status_code == 200
        big = {"audio": "A" * vr.CLIP_BODY_MAX}
        assert (
            c.put(f"/v1/voice/profile/session/clips/{PROMPT}", json=big, headers=AUTH).status_code
            == 413
        )
        not_object = c.post("/v1/voice/profile/session/start", content=b"[1]", headers=AUTH)
        assert not_object.status_code == 422 and not_object.json()["error"] == "input_rejected"
    assert ("put_clip", (uid, PROMPT, CLIP)) in api.calls
    assert ("delete_recordings", (uid,)) in api.calls and len(api.calls) == 4
    assert ("model", (uid,)) in wake.calls


def _flat(routes: Any, prefix: str = "") -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            out |= _flat(inner.routes, prefix + r.include_context.prefix)
            continue
        for m in getattr(r, "methods", None) or ("WEBSOCKET",):
            out.add((m, prefix + r.path))
    return out


def test_the_app_mounts_every_voice_profile_route(settings: Settings) -> None:
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    mounted = _flat(create_app(settings, provider=MockProvider()).routes)
    assert set(vr.ROUTES) <= mounted
