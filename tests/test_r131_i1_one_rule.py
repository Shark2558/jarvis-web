# tests/test_r131_i1_one_rule.py -- R13.1 I1, the integrated code review's M5: ONE copy of each
# rule R13 and R13.1 share, so the early check (A's words on the figure and in "Use this look")
# and the guarantee (R13's `outfit_plan` refusal, D20) can never disagree, and a private slot
# added to R13 is covered on the card and the figure at once.
#   - the readiness rule and its words (`styling/ready.py`): R13's `unready` and A's
#     `options.blocker` + `confirm.words_of` read it; for every way a piece can be unready, both
#     refuse it with the same words for its state, and both take a ready one;
#   - the private slots (`styling.look.PRIVATE_SLOTS`) and the covered rule
#     (`styling.look.covered`): A's model and looks, and the try-on card, use R13's own objects;
#   - no module keeps its own copy (a static pin).
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from r131_fakes_a import UID, AWorld, T, a_world

from jarvis.wardrobe.styling import actions, ready, tryon_card
from jarvis.wardrobe.styling import look as r13_look
from jarvis.wardrobe.tryon import confirm, looks
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon import options as o

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "wardrobe"
LOCK = ": it can't be locked into this plan."
CONFIRM = ": it can't be confirmed for this event."


async def _both(a: AWorld, plan: str, slot: str, pid: str) -> tuple[str | None, str | None]:
    """(R13's refusal, A's refusal) for `pid` in `plan`, from the SAME fresh read."""
    view, doc = await a.view(), await a.styling.plans.read(UID)
    found = doc.plan(plan)
    assert found is not None
    here = await a.styling.where(UID)
    r13 = actions.unready(a.styling, view, found, (pid,))
    f = o.fresh_of(view, doc, a.styling.rules, here.zone, day=found.day, code=found.code,
                   plan=found)  # fmt: skip
    block = o.blocker(f, slot, (pid,))
    return r13, (confirm.words_of(f, block) if block is not None and block[0] != "held" else None)


@pytest.mark.parametrize("kind", ["deposited", "wear_started", "damaged", "sent_out"])
async def test_a_piece_that_isnt_ready_is_refused_alike_by_the_plan_and_the_figure(
    kind: Any,
) -> None:
    a = await a_world()
    plan = await a.plan()
    await a.w.move(T.rain_jacket, kind)
    r13, mine = await _both(a, plan, "outer", T.rain_jacket)
    assert r13 is not None and mine is not None, (r13, mine)
    assert r13.endswith(LOCK) and mine.endswith(CONFIRM)
    assert r13.removesuffix(LOCK) == mine.removesuffix(CONFIRM)  # "The ... is in the laundry"
    p = (await a.view()).pieces[T.rain_jacket]
    assert r13 == f"{ready.the(p)} {ready.state_words(p)}{LOCK}"


async def test_a_ready_piece_is_taken_alike_by_the_plan_and_the_figure() -> None:
    a = await a_world()
    plan = await a.plan()
    assert await _both(a, plan, "outer", T.rain_jacket) == (None, None)


def test_the_private_slots_and_the_covered_rule_are_r13s_own_objects() -> None:
    assert m.PRIVATE_SLOTS is r13_look.PRIVATE_SLOTS
    assert looks.covered is r13_look.covered and confirm.covered is r13_look.covered
    assert tryon_card.covered is r13_look.covered
    assert o.PRIVATE_SLOTS is r13_look.PRIVATE_SLOTS


async def test_the_card_and_the_figure_cover_exactly_the_same_slots() -> None:
    from jarvis.wardrobe.styling.look import Pick

    a = await a_world()
    await a.w.edit(T.white, private=True)
    view = await a.view()
    for slot, pid in (("top", T.white), ("top", T.shirt), ("base", T.vest), ("bottom", "wi_x")):
        card = tryon_card._slot(view, Pick(slot, (pid,)))
        assert card.private is r13_look.covered(view, slot, (pid,)), (slot, pid)


DEFINED = {  # a rule's definition -> the files that may hold it
    r"^PRIVATE_SLOTS\s*=": ["styling/look.py"],
    r"^def covered\(view": ["styling/look.py"],
    r"^def _?the\(": ["styling/ready.py"],
    # R13's engine keeps its own `_handed` over the ask's shared map (`Ask.shared`, since R13):
    # the plan's rule is `ready.handed`, which `outfit_plan` and the figure both read
    r"^def _?handed\(": ["styling/engine.py", "styling/ready.py"],
    r"^(NOT_READY|STATE_WORDS)\s*(:[^=]*)?=\s*\{": ["styling/ready.py"],
}


@pytest.mark.parametrize(("pattern", "homes"), list(DEFINED.items()))
def test_no_module_keeps_its_own_copy_of_a_shared_rule(pattern: str, homes: list[str]) -> None:
    found = [
        str(f.relative_to(SRC))
        for f in sorted(SRC.rglob("*.py"))
        if re.search(pattern, f.read_text(encoding="utf-8"), flags=re.M)
    ]
    assert found == homes, found
