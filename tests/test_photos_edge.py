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
    EdgeBadReply,
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
    # R11.1 O7: the bridge now serves this route and answers with two facts: how many face
    # pictures it holds for the person, and whether the camera's library has them yet
    home = ScriptedHome({"pictures": 4, "camera": "copied"})
    assert await BridgeHomeEdge(home).enrol(UID, C1, PID) == 4  # type: ignore[arg-type]
    assert home.calls == [("POST", ENROL_PATH, {"cluster": C1, "person": PID})]


@pytest.mark.parametrize("exc", [HomeOffline(), HomeRefused("not_allowed", "no")])
async def test_an_unreachable_or_refusing_home_is_offline(exc: Exception) -> None:
    edge = BridgeHomeEdge(ScriptedHome(exc=exc))  # type: ignore[arg-type]
    with pytest.raises(EdgeOffline):
        await edge.analyse(UID, [JPEG])
    with pytest.raises(EdgeOffline):
        await edge.enrol(UID, C1, PID)


@pytest.mark.parametrize(
    "row",
    [
        {"cluster": "nope", "person": None, "score": 0.5},
        {"cluster": C1, "person": "Anjali", "score": 0.99},  # a name is not an id
        {"cluster": C1, "person": PID, "score": 7},
        {"cluster": C1, "person": PID, "score": True},
        {"cluster": C1, "person": PID, "score": float("nan")},
        {"cluster": C1, "person": PID, "score": "0.9"},
        {"cluster": C1, "person": PID, "score": 0.9, "name": "Anjali"},  # extra field
        "junk",
    ],
)
def test_a_malformed_face_makes_the_whole_reply_bad_not_offline(row: Any) -> None:
    with pytest.raises(EdgeBadReply) as e:
        parse_faces({"faces": [row]})
    assert not isinstance(e.value, EdgeOffline)


def test_a_reply_with_more_than_twenty_faces_or_extra_keys_is_bad() -> None:
    row = {"cluster": C1, "person": None, "score": 0.5}
    with pytest.raises(EdgeBadReply):
        parse_faces({"faces": [row] * 21})
    with pytest.raises(EdgeBadReply):
        parse_faces({"faces": [], "embedding": [0.1]})


def test_a_valid_reply_parses_with_int_scores_and_no_person() -> None:
    (a, b) = parse_faces(
        {
            "faces": [
                {"cluster": C1, "person": None, "score": 1},
                {"cluster": C1, "person": PID, "score": 0},
            ]
        }
    )
    assert a.person is None and a.score == 1.0 and b.person == PID


def test_a_reply_without_a_faces_list_is_bad() -> None:
    with pytest.raises(EdgeBadReply):
        parse_faces({"nothing": 1})
    with pytest.raises(EdgeBadReply):
        parse_faces(["not", "a", "dict"])


async def test_a_bad_reply_is_logged_by_type_only(caplog: pytest.LogCaptureFixture) -> None:
    edge = BridgeHomeEdge(
        ScriptedHome({"faces": [{"cluster": C1, "person": "SECRET-NAME", "score": 2}]})
    )  # type: ignore[arg-type]
    with pytest.raises(EdgeBadReply):
        await edge.analyse(UID, [JPEG])
    assert "SECRET-NAME" not in caplog.text
