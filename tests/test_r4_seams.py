# tests/test_r4_seams.py -- R4 I1 seams outside the wiring module: the home bridge's two new
# routes and the PER-ROUTE request cap (W9), the Photos Grant (W8), the BrainOff line on Telegram
# and in the CLI (W13), and the Activity words for the new tool prefixes (W14).
from __future__ import annotations

import builtins
import json
from typing import Any

import pytest
from telegram_fakes import World, build_world, message

from jarvis import cli
from jarvis.activity.words import _read_words
from jarvis.config import Settings
from jarvis.home.client import (
    MAX_REQUEST_BYTES,
    MAX_REQUEST_BYTES_BY_ROUTE,
    HomeClient,
    request_limit,
)
from jarvis.home.models import HomeRecord
from jarvis.home.ports import BRIDGE_ROUTES, HomeRefused, route_allowed
from jarvis.integrations.google import GRANT_ACCEPTS, GRANTS, held_grants
from jarvis.llm.router import NO_AI_REFUSAL, BrainOff
from jarvis.photos.models import PHOTOS_SCOPE

PHOTOS = ("POST", "/bridge/v1/faces/photos")
ENROL = ("POST", "/bridge/v1/faces/enrol")
SIX_MB = 6 * 1024 * 1024


# ---- W9: bridge routes and the per-route cap ----------------------------------------------------


def test_the_two_photo_routes_are_allowed_and_nothing_else_changed() -> None:
    assert PHOTOS in BRIDGE_ROUTES and ENROL in BRIDGE_ROUTES
    assert route_allowed(*PHOTOS) and route_allowed(*ENROL)
    assert not route_allowed("GET", "/bridge/v1/faces/photos")
    assert len(BRIDGE_ROUTES) == 9


def test_only_the_photo_route_gets_the_six_megabyte_cap() -> None:
    assert MAX_REQUEST_BYTES == 32 * 1024
    assert MAX_REQUEST_BYTES_BY_ROUTE == {PHOTOS: SIX_MB}
    assert request_limit(*PHOTOS) == SIX_MB
    assert request_limit(*ENROL) == MAX_REQUEST_BYTES
    assert request_limit("POST", "/bridge/v1/state") == MAX_REQUEST_BYTES
    assert request_limit("GET", "/bridge/v1/health") == MAX_REQUEST_BYTES


class _Sent(Exception):
    """Raised by the stubbed transport: the size check let the request through."""


async def _public(host: str) -> list[str]:
    return ["8.8.8.8"]  # a public address: the bridge URL check passes (home_fakes)


async def test_the_client_refuses_a_large_body_on_a_32k_route_but_sends_it_to_photos() -> None:
    record = HomeRecord(
        home_id="h_0a1b2c3d", bridge_url="https://laptop.tail1234.ts.net:8443", seed=bytes(32)
    )
    client = HomeClient(None, clock=lambda: 1.0, resolver=_public)

    async def stub(*a: Any, **k: Any) -> Any:
        raise _Sent

    client._send = stub  # type: ignore[method-assign]
    big = {"image": "A" * (100 * 1024)}  # 100 KB: over 32 KB, far under 6 MB
    with pytest.raises(HomeRefused) as err:
        await client.exchange(record, "POST", "/bridge/v1/state", big)
    assert err.value.code == "too_large"
    with pytest.raises(HomeRefused) as err:
        await client.exchange(record, *ENROL, big)
    assert err.value.code == "too_large"
    with pytest.raises(_Sent):  # the photo route takes it
        await client.exchange(record, *PHOTOS, big)
    with pytest.raises(HomeRefused) as err:
        await client.exchange(record, *PHOTOS, {"image": "A" * (SIX_MB + 1)})
    assert err.value.code == "too_large"


# ---- W8: the Photos Grant ------------------------------------------------------------------------


def test_the_photos_grant_asks_for_exactly_the_picker_scope() -> None:
    assert GRANTS["photos"] == PHOTOS_SCOPE
    assert GRANT_ACCEPTS["photos"] == frozenset({PHOTOS_SCOPE})
    assert PHOTOS_SCOPE.endswith("/auth/photospicker.mediaitems.readonly")
    assert "photos" in held_grants([PHOTOS_SCOPE])
    assert "photos" not in held_grants(["https://www.googleapis.com/auth/photoslibrary.readonly"])
    assert list(GRANTS) == ["tasks", "contacts", "youtube", "photos"]  # Grant order


# ---- W13: the BrainOff line on Telegram and in the CLI -----------------------------------------


async def _paired() -> World:
    w = build_world()
    await w.pair()
    return w


async def test_telegram_says_the_fixed_no_ai_line_on_brain_off() -> None:
    w = await _paired()

    async def off(req: Any) -> Any:
        raise BrainOff(NO_AI_REFUSAL)

    w.brain.chat = off  # type: ignore[method-assign]
    await w.send(message(1, "draft a reply to the vendor"))
    assert w.bot.texts == [NO_AI_REFUSAL]


async def test_the_cli_prints_the_fixed_no_ai_line_and_keeps_going(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = iter(["run a systems check", "/quit"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(lines))

    async def off(self: Any, req: Any) -> Any:
        raise BrainOff(NO_AI_REFUSAL)

    monkeypatch.setattr(cli.Brain, "chat", off)
    await cli._repl(stream=False)  # noqa: SLF001
    out = capsys.readouterr()
    assert f"(jarvis: {NO_AI_REFUSAL})" in out.err
    assert "Traceback" not in out.err and "JARVIS online" in out.out


# ---- W14: Activity words -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "past"),
    [
        ("vitals_show", "Checked your Vitals board"),
        ("systems_check", "Ran a systems check"),
        ("people_open_profiles", "Looked up a public profile"),
        ("research_person", "Researched a public figure"),
        ("connect_github", "Checked a connected account"),
        ("github_repos", "Looked at your GitHub"),
        ("photos_import", "Looked at your picked photos"),
    ],
)
def test_activity_words_read_well_for_every_r4_prefix(tool: str, past: str) -> None:
    got_past, imperative = _read_words(tool)
    assert got_past == past
    assert imperative[0].isupper() and not imperative.endswith("ed")
    assert json.dumps(got_past)  # plain text, nothing to escape
