# tests/test_r52_review_routes.py -- R5.2 combined review: no bare 500 from /v1/voice/profile.
# A part that raised anything but `ProfileRefused` (the profile store down, a session document
# that can't be read, a kit error a handler didn't map) gave Starlette's bare 500. Every route now
# logs the error's class name only and answers 503 `unavailable` in plain words, never the error's
# text (R18 review finding 6, the same rule for the calls' routes).
from __future__ import annotations

import base64
import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from jarvis.api import voice_profile_routes as vr
from jarvis.config import Settings

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SECRET_WORDS = "firestore said: projects/acme-123 /home/someone"
CLIP = {"audio": base64.b64encode(b"RIFF" + b"\x00" * 40).decode()}


class _Broken:
    def __getattr__(self, name: str) -> Any:
        async def handler(*args: Any, **kw: Any) -> Any:
            raise RuntimeError(SECRET_WORDS)

        return handler


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
    vr.install_voice_profile_routes(app)
    app.state.voice_profile_api = _Broken()
    app.state.voice_laptop = _Broken()
    app.state.voice_wakeword = _Broken()
    return app


def _body(path: str) -> dict[str, Any]:
    if path.endswith("/recordings/delete"):
        return {"confirm": vr.CONFIRM_WORD}
    return CLIP if "/clips/" in path else {}


@pytest.mark.parametrize(("method", "path"), sorted(vr.ROUTES))
def test_review_a_failing_part_answers_503_in_plain_words(
    settings: Settings, method: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    url = path.replace("{prompt_id}", "cmd_lights")
    kw: dict[str, Any] = {"json": _body(url)} if method in ("POST", "PUT") else {}
    caplog.set_level(logging.INFO)
    with TestClient(_app(settings), raise_server_exceptions=False) as c:
        got = c.request(method, url, headers=AUTH, **kw)
    assert got.status_code == 503, got.text
    assert got.json()["error"] == "unavailable" and got.headers["cache-control"] == "no-store"
    assert "acme" not in got.text and "someone" not in got.text
    logged = [r for r in caplog.records if r.name == vr.__name__]
    assert [getattr(r, "error", None) for r in logged] == ["RuntimeError"]
    assert SECRET_WORDS not in caplog.text
