# tests/test_photos_edge.py -- R4 D8: the home edge adapter. Replies are validated; a sleeping or
# refusing laptop is "offline", never a guess; no name ever comes back.
from __future__ import annotations

import base64
from typing import Any

import pytest
from faces_fakes import UID, FakeHome
from photos_fakes import C1, JPEG

from jarvis.home.ports import HomeOffline, HomeRefused
from jarvis.photos.edge import (
    ENROL_PATH,
    PHOTOS_PATH,
    BridgeHomeEdge,
    EdgeOffline,
    parse_faces,
)

PID = "fp_0123456789ab"


class ScriptedHome(FakeHome):
    def __init__(self, reply: Any = None, exc: Exception | None = None) -> None:
        super().__init__()
        self.reply, self.exc = reply, exc

    async def call(self, uid, method, path, body=None, *, query=None):  # type: ignore[no-untyped-def]
        if self.exc:
            raise self.exc
        self.calls.append((method, path, body))
        return self.reply


async def test_analyse_posts_each_picture_and_parses_faces() -> None:
    home = ScriptedHome({"faces": [{"cluster": C1, "person": PID, "score": 0.97}]})
    out = await BridgeHomeEdge(home).analyse(UID, [JPEG, JPEG])  # type: ignore[arg-type]
    assert len(out) == 2 and out[0][0].person == PID
    method, path, body = home.calls[0]
    assert (method, path) == ("POST", PHOTOS_PATH)
    assert base64.b64decode(body["image"]) == JPEG


async def test_enrol_sends_ids_only() -> None:
    home = ScriptedHome({})
    await BridgeHomeEdge(home).enrol(UID, C1, PID)  # type: ignore[arg-type]
    assert home.calls == [("POST", ENROL_PATH, {"cluster": C1, "person": PID})]


@pytest.mark.parametrize("exc", [HomeOffline(), HomeRefused("not_allowed", "no")])
async def test_an_unreachable_or_refusing_home_is_offline(exc: Exception) -> None:
    edge = BridgeHomeEdge(ScriptedHome(exc=exc))  # type: ignore[arg-type]
    with pytest.raises(EdgeOffline):
        await edge.analyse(UID, [JPEG])
    with pytest.raises(EdgeOffline):
        await edge.enrol(UID, C1, PID)


def test_malformed_faces_are_dropped_not_guessed() -> None:
    rows = [
        {"cluster": "nope", "person": None, "score": 0.5},
        {"cluster": C1, "person": "Anjali", "score": 0.99},  # a name is not an id: unnamed
        {"cluster": C1, "person": PID, "score": 7},
        {"cluster": C1, "person": PID, "score": True},
        {"cluster": C1, "person": PID, "score": float("nan")},
        "junk",
    ]
    (only,) = parse_faces({"faces": rows})
    assert only.person is None and only.score == 0.99


def test_a_reply_without_a_faces_list_is_refused() -> None:
    with pytest.raises(EdgeOffline):
        parse_faces({"nothing": 1})
