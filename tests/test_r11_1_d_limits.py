# tests/test_r11_1_d_limits.py -- R11.1 Part D, O9 (plan D17): the bounds of picture research.
# The looks an owner may ask for in a minute come back after the minute; only so many reports
# are ever kept in memory (words and links, never a picture); and a result too big for the
# gateway loses results, never the closing marker of a fence around other people's words.
from __future__ import annotations

import re

import pytest
from r11_1_fakes_d import UID, PictureRig, picture

import jarvis.picture.tools as picture_tools
from jarvis.picture.research import MAX_KEPT, RATE_BURST, RATE_WINDOW_S
from jarvis.tools.external import FENCE_END, FENCE_PREFIX
from jarvis.tools.gateway import MAX_RESULT_CHARS, GatewayResult, serialise
from jarvis.web.ports import SearchHit

RED = ((60, 60, 220, 170), (200, 40, 40))
THINGS = ["Parle-G biscuit packet", "Britannia biscuit packet"]


class Ticker:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _rig(*things: str) -> tuple[PictureRig, Ticker]:
    rig, ticker = PictureRig(), Ticker()
    rig.svc.clock = ticker  # type: ignore[method-assign]
    pic = picture("PARLE-G", blocks=[RED])
    subjects = [("product", name) for name in things or ("Parle-G biscuit packet",)]
    rig.eyes.knows(pic, scene="A red packet of biscuits on a table.", subjects=subjects)
    for n in range(MAX_KEPT + 2):
        rig.turn.attach(f"sess_{n}", pic)
    return rig, ticker


async def test_after_the_minute_a_look_is_allowed_again() -> None:
    rig, ticker = _rig()
    first = [(await rig.research("sess_0")).result["status"] for _ in range(RATE_BURST + 1)]

    ticker.now += RATE_WINDOW_S
    again = (await rig.research("sess_0")).result["status"]

    assert first == ["done"] * RATE_BURST + ["busy"] and again == "done"
    assert len(rig.eyes.looks) == RATE_BURST + 1  # the refused one never reached the eyes


async def test_only_so_many_reports_are_kept_in_memory() -> None:
    rig, ticker = _rig()
    for n in range(MAX_KEPT + 2):
        ticker.now += RATE_WINDOW_S  # one conversation a minute: never "busy"
        assert (await rig.research(f"sess_{n}")).result["status"] == "done"

    kept = [n for n in range(MAX_KEPT + 2) if rig.svc.last(UID, f"sess_{n}") is not None]

    assert 1 <= len(kept) <= MAX_KEPT and kept[-1] == MAX_KEPT + 1  # the newest is always there


async def _largest(rig: PictureRig) -> GatewayResult:
    """The largest answer the look's schema allows (600 characters of description, twelve lines
    of 200, six long names) with the longest titles and snippets the search keeps."""
    pic = picture("PARLE-G", blocks=[RED])
    filler = [("word " * 15).strip() + f" {n}" for n in range(4)]  # long names, never searched
    rig.eyes.lies(
        pic,
        {
            "has_person": False,
            "scene": ("A red packet of biscuits on a table. " * 16)[:600].strip(),
            "text": [("WORDS ON THE PACKET " * 10)[:198] + f"{n:02d}" for n in range(12)],
            "subjects": [{"kind": "product", "name": name} for name in THINGS]
            + [{"kind": "other", "name": name} for name in filler],
            "named_in_text": "",
        },
    )
    rig.vendor.default = [
        SearchHit("t" * 400, f"https://example.org/{n}", "s" * 2_000) for n in range(5)
    ]
    return await rig.research("sess_0")


def _fences_closed(shown: str) -> bool:
    opened = len(re.findall(re.escape(FENCE_PREFIX), shown))
    return opened == len(FENCE_END.findall(shown)) > 12


async def test_the_largest_answer_the_schema_allows_reaches_the_model_whole() -> None:
    rig, _ = _rig()

    got = await _largest(rig)

    shown = got.for_model()
    assert rig.vendor.queries == THINGS and 1 <= len(got.result["results"]) <= 6
    assert len(shown) <= MAX_RESULT_CHARS and _fences_closed(shown)
    assert len(got.result["text"]) == 12  # the picture's own words all arrive


async def test_over_the_budget_whole_results_are_dropped_and_no_fence_is_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, _ = _rig()
    monkeypatch.setattr(picture_tools, "RESULT_BUDGET", 9_000)

    got = await _largest(rig)

    shown = got.for_model()
    assert 1 <= len(got.result["results"]) < 6  # whole results went, the last ones first
    assert [r["n"] for r in got.result["results"]] == sorted(r["n"] for r in got.result["results"])
    assert len(serialise(got.result)) <= 9_000 and _fences_closed(shown)
    assert len(got.result["text"]) == 12
