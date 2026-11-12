# tests/test_r11_1_c_edge.py -- R11.1 O7: the cloud's side of the laptop's face routes. Every
# answer is parsed strictly, so nothing but ids and counts gets in: a reply with one field too
# many (a crop, an embedding, a name) is refused as a whole. What the laptop says no to keeps its
# meaning: asleep is "offline", an older kit or a missing face reader is "not ready", and a
# refused picture or name is that one refusal, never "laptop not reachable".
from __future__ import annotations

from typing import Any

import pytest
from faces_fakes import UID, FakeHome
from photos_fakes import C1, JPEG

from jarvis.home.ports import HomeOffline, HomeRefused
from jarvis.photos.edge import (
    FORGET_PATH,
    GROUPS_PATH,
    BridgeHomeEdge,
    EdgeBadReply,
    EdgeNotReady,
    EdgeOffline,
    EdgeRefused,
)

PID = "fp_0123456789ab"
GROUPS: dict[str, Any] = {
    "groups": [{"id": C1, "n": 4, "photos": 23, "first": 1_800_000_000, "last": 1_800_000_500}],
    "more": 0,
    "strays": 7,
    "named": 2,
    "engine": "ready",
    "folder": "on",
    "read": 120,
    "keep_days": 90,
}


class Home(FakeHome):
    def __init__(self, replies: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        super().__init__()
        self.replies, self.exc = replies or {}, exc

    async def call(self, uid, method, path, body=None, *, query=None):  # type: ignore[no-untyped-def]
        if self.exc:
            raise self.exc
        self.calls.append((method, path, body))
        return self.replies[path]


def edge(replies: dict[str, Any] | None = None, exc: Exception | None = None) -> BridgeHomeEdge:
    return BridgeHomeEdge(Home(replies, exc))  # type: ignore[arg-type]


async def test_groups_come_back_as_ids_and_counts() -> None:
    got = await edge({GROUPS_PATH: GROUPS}).groups(UID)
    (g,) = got.groups
    assert (g.id, g.n, g.photos, g.first, g.last) == (C1, 4, 23, 1_800_000_000, 1_800_000_500)
    assert (got.strays, got.named, got.engine_ready, got.folder) == (7, 2, True, "on")
    assert (got.read, got.keep_days, got.more) == (120, 90, 0)


@pytest.mark.parametrize(
    "change",
    [
        {"crop": "/9j/4AAQSkZJRg=="},  # a picture: one field too many
        {"embedding": [0.1] * 128},
        {"engine": "sort of"},
        {"keep_days": 0},
        {"folder": "/mnt/c/Users/someone/Pictures"},  # a path is not one of the three words
        {"strays": -1},
        {"groups": [{"id": C1, "n": 4, "photos": 23, "first": 1, "last": 2, "name": "Anjali"}]},
        {"groups": [{"id": C1, "n": 4, "photos": 23, "first": 1, "last": 2, "crop": "x"}]},
        {"groups": [{"id": "Group 4", "n": 4, "photos": 23, "first": 1, "last": 2}]},
        {"groups": [{"id": C1, "n": 4, "photos": 23, "first": 1, "last": 2}] * 101},
    ],
)
async def test_a_groups_answer_with_anything_else_in_it_is_refused_whole(
    change: dict[str, Any],
) -> None:
    with pytest.raises(EdgeBadReply):
        await edge({GROUPS_PATH: {**GROUPS, **change}}).groups(UID)


async def test_forgetting_is_confirmed_by_the_laptops_own_counts() -> None:
    home = Home({FORGET_PATH: {"forgotten": 2, "left": 0}})
    e = BridgeHomeEdge(home)  # type: ignore[arg-type]
    done = await e.forget(UID, None)
    assert (done.forgotten, done.left) == (2, 0)
    await e.forget(UID, [C1])
    assert [c[2] for c in home.calls] == [{"all": True}, {"groups": [C1]}]
    for bad in ({}, {"forgotten": 1}, {"forgotten": 1, "left": 0, "ok": True}, {"forgotten": "1", "left": 0}):
        with pytest.raises(EdgeBadReply):
            await edge({FORGET_PATH: bad}).forget(UID, None)


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"pictures": 4},
        {"pictures": 4, "camera": "copied", "crop": "x"},
        {"pictures": 999, "camera": "copied"},
        {"pictures": 4, "camera": "soon"},
    ],
)
async def test_an_enrol_answer_is_two_facts_and_nothing_else(reply: dict[str, Any]) -> None:
    with pytest.raises(EdgeBadReply):
        await edge({"/bridge/v1/faces/enrol": reply}).enrol(UID, C1, PID)


@pytest.mark.parametrize(
    ("version", "answer"),
    [("0.2.0", "ready"), ("0.3.1", "ready"), ("1.0.0", "ready"), ("0.1.0", "kit_old"),
     ("0.1.9", "kit_old"), (None, "kit_old"), ("banana", "kit_old")],
)  # fmt: skip
async def test_an_older_kit_is_told_from_a_sleeping_laptop(version: Any, answer: str) -> None:
    health = {"ok": True, "version": version, "ha": False}
    assert await edge({"/bridge/v1/health": health}).ready(UID) == answer


async def test_a_sleeping_or_unlinked_laptop_is_offline_everywhere() -> None:
    for exc in (HomeOffline(), HomeRefused("not_linked", "no"), HomeRefused("bad_reply", "no")):
        e = edge(exc=exc)
        for call in (e.ready(UID), e.groups(UID), e.forget(UID, None), e.analyse(UID, [JPEG])):
            with pytest.raises(EdgeOffline):
                await call


async def test_a_face_reader_that_cannot_run_is_not_ready_not_offline() -> None:
    e = edge(exc=HomeRefused("no_engine", "The face reader isn't ready."))
    with pytest.raises(EdgeNotReady) as err:
        await e.analyse(UID, [JPEG])
    assert "update the home kit" in str(err.value)
    with pytest.raises(EdgeNotReady):
        await e.enrol(UID, C1, PID)


@pytest.mark.parametrize("code", ["bad_image", "no_consent", "unknown_group", "already_named"])
async def test_one_refusal_keeps_its_code(code: str) -> None:
    e = edge(exc=HomeRefused(code, "the cloud's own words"))
    with pytest.raises(EdgeRefused) as err:
        await e.enrol(UID, C1, PID)
    assert err.value.code == code and str(err.value) == "the cloud's own words"
