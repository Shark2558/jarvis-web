# tests/test_r11_1_d_lows.py -- R11.1 Part D, the review's low findings on picture research:
# what the model is shown is fenced (`about` too); the console's press keeps the message's search
# cap (a press outside a conversation is counted against the picture's own message); the reports
# kept in memory lose the oldest first and keep only finished ones; a look and a search that hang
# end in plain words by their own deadlines; the status route says "can't tell" in plain words.
# Everything is made up.
from __future__ import annotations

import asyncio

import pytest
from r11_1_fakes_d import UID, PictureRig, picture

import jarvis.picture.eyes as eyes_mod
import jarvis.picture.research as research_mod
import jarvis.picture.search as search_mod
from jarvis.picture.eyes import UNREACHABLE, BrainEyes, CantLook
from jarvis.picture.research import MAX_KEPT, RATE_WINDOW_S
from jarvis.picture.search import SEARCH_SLOW, TURN_LIMIT
from jarvis.tools.external import FENCE_PREFIX
from jarvis.web.tools import MAX_SEARCHES_PER_TURN

RED = ((60, 60, 220, 170), (200, 40, 40))
THING = "Charminar monument"


class Ticker:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _rig(*sessions: str) -> tuple[PictureRig, Ticker]:
    rig, ticker = PictureRig(), Ticker()
    rig.svc.clock = ticker  # type: ignore[method-assign]
    pic = picture(blocks=[RED])
    rig.eyes.knows(pic, scene="A stone monument with four towers.", subjects=[("landmark", THING)])
    for sid in sessions or ("sess_1",):
        rig.turn.attach(sid, pic)
    return rig, ticker


# ---- security LOW-1: the thing a result is about is fenced too -----------------------------------
async def test_what_each_result_is_about_reaches_the_model_fenced() -> None:
    rig, _ = _rig()

    out = (await rig.research()).result

    assert out["results"] and all(r["about"].startswith(FENCE_PREFIX) for r in out["results"])
    assert all(THING in r["about"] for r in out["results"])


# ---- security LOW-2: the console's presses keep the message's search cap -------------------------
async def test_presses_on_one_message_share_its_search_cap() -> None:
    rig, ticker = _rig()
    notes = []
    for _ in range(MAX_SEARCHES_PER_TURN + 2):
        ticker.now += RATE_WINDOW_S  # never "busy"
        notes += (await rig.research()).result["searched"]

    assert len(rig.vendor.queries) == MAX_SEARCHES_PER_TURN
    assert notes == [TURN_LIMIT, TURN_LIMIT]


async def test_a_new_message_with_a_picture_gets_its_own_cap() -> None:
    rig, ticker = _rig()
    for _ in range(MAX_SEARCHES_PER_TURN):
        ticker.now += RATE_WINDOW_S
        await rig.research()
    other = picture("CHARMINAR", blocks=[RED])
    rig.eyes.knows(other, scene="A stone monument at dusk.", subjects=[("landmark", THING)])
    rig.turn.attach("sess_1", other)  # his next message carries another picture

    ticker.now += RATE_WINDOW_S
    out = (await rig.research()).result

    assert len(rig.vendor.queries) == MAX_SEARCHES_PER_TURN + 1 and out["results"]


# ---- code review LOW-1: the kept reports ---------------------------------------------------------
async def test_at_the_cap_the_oldest_report_goes_and_the_others_stay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_mod, "RATE_BURST", 10 * MAX_KEPT)  # all inside ten minutes
    sessions = [f"sess_{n}" for n in range(MAX_KEPT + 1)]
    rig, _ = _rig(*sessions)
    for sid in sessions:
        await rig.research(sid)

    kept = [sid for sid in sessions if rig.svc.last(UID, sid) is not None]

    assert kept == sessions[1:]  # only the oldest was let go


async def test_a_failed_look_does_not_replace_the_last_good_report() -> None:
    rig, ticker = _rig()
    await rig.research()
    good = rig.svc.last(UID, "sess_1")
    rig.eyes.cant = CantLook("unreachable", UNREACHABLE)

    ticker.now += RATE_WINDOW_S
    failed = (await rig.research()).result

    assert failed["status"] == "unreachable" and good is not None
    assert rig.svc.last(UID, "sess_1") is good


# ---- code review LOW-3: a look and a search have their own deadlines -----------------------------
class SlowRouter:
    async def complete(self, **_: object) -> object:
        await asyncio.sleep(5)
        raise AssertionError("never reached")


class SlowRegistry:
    """A registry whose one seeing brain never answers."""

    def __init__(self) -> None:
        from jarvis.llm.brains import BrainSpec
        from jarvis.llm.mock_provider import MockProvider
        from jarvis.llm.router import ModelTier

        class Seeing(MockProvider):
            vision = True

        tiers = {t: f"mock-{t.value}" for t in ModelTier}
        self.default = BrainSpec("seeing", "Seeing", Seeing(), tiers, trains_on_content=False)

    def list(self) -> list[object]:
        return [self.default]

    def router_for(self, _: str) -> SlowRouter:
        return SlowRouter()


async def test_a_look_that_hangs_ends_as_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eyes_mod, "LOOK_TIMEOUT_S", 0.05)
    eyes = BrainEyes(lambda: SlowRegistry(), lambda: None, lambda: None)  # type: ignore[arg-type,return-value]

    with pytest.raises(CantLook) as caught:
        await eyes.look(UID, "system", "ask", picture(blocks=[RED]), max_tokens=10)

    assert caught.value.why == "unreachable" and str(caught.value) == UNREACHABLE


async def test_a_search_that_hangs_ends_in_plain_words(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_mod, "SEARCH_TIMEOUT_S", 0.05)
    rig, _ = _rig()

    async def hang(*_: object, **__: object) -> object:
        await asyncio.sleep(5)
        raise AssertionError("never reached")

    rig.vendor.search = hang  # type: ignore[method-assign]
    out = (await rig.research()).result

    assert out["status"] == "done" and out["results"] == [] and out["searched"] == [SEARCH_SLOW]


def test_the_deadlines_are_named_and_sane() -> None:
    assert 0 < search_mod.SEARCH_TIMEOUT_S < eyes_mod.LOOK_TIMEOUT_S <= 60
