# tests/test_r8_i1_track.py -- R8 I1 (D6): "track me", "track everyone" and "track <name>" by
# voice. The console's local router (console-coach-desk.js) and jarvis.coach.target hold the same
# phrases and the same name rule (one or two words, never a first word like "my" or "parcel", so
# "track my parcel" stays a chat message); the browser half is tests/browser/test_r8_desk_pane.py.
from __future__ import annotations

import json
import re

import pytest
from r8_fakes import STATIC

from jarvis.coach import target as T


def _js_list(name: str) -> list[str]:
    js = (STATIC / "console-coach-desk.js").read_text(encoding="utf-8")
    m = re.search(rf"/\*{name}-BEGIN\*/(.*?)/\*{name}-END\*/", js, re.S)
    assert m is not None, name
    return list(json.loads(m.group(1).replace("'", '"')))


def test_the_console_and_the_server_hold_the_same_phrases_and_name_rule() -> None:
    assert tuple(_js_list("TRACK-ME")) == T.TRACK_ME
    assert tuple(_js_list("TRACK-ALL")) == T.TRACK_ALL
    assert set(_js_list("NOT-NAMES")) == T.NOT_NAMES
    js = (STATIC / "console-coach-desk.js").read_text(encoding="utf-8")
    assert "/^(?:track|follow)(?: only)? ([a-z][a-z.'-]*(?: [a-z][a-z.'-]*)?)$/" in js
    assert T._TRACK_NAME.pattern == (  # noqa: SLF001
        r"^(?:track|follow)(?: only)? (?P<name>[a-z][a-z.'-]*(?: [a-z][a-z.'-]*)?)$"
    )


@pytest.mark.parametrize(
    "said,want",
    [
        ("Jarvis, track me.", T.TrackTarget(kind="me")),
        ("follow everyone", T.EVERYONE),
        ("track Shruti", "shruti"),
        ("track only Anil Kumar", "anil kumar"),
        ("track my parcel", None),
        ("track the flight", None),
        ("follow packages", None),
        ("track ana and the dog", None),  # more than two words: a chat message
        ("turn on the lights", None),
    ],
)
def test_a_tracking_phrase_is_a_target_a_name_or_nothing(said: str, want: object) -> None:
    assert T.phrase_target(said) == want
