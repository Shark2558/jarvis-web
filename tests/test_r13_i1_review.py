# tests/test_r13_i1_review.py -- R13 I1 (INTEGRATION-B 6.6): `ReviewEntry` carries `reason`,
# `count` and `answers` for D's panel, and `answers` comes from the ONE function the resolver
# uses, so the panel can never offer an answer the resolver refuses (or hide one it accepts).
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID, ev
from r13_fakes_b import BELT, TEE, TWIN, WATCH, WHITE_SHIRT, rig

from jarvis.wardrobe.laundry import resolve, review, texts
from jarvis.wardrobe.ports import Refused, ReviewNeeded

ALL = ("these", "none", "moved", "dismiss")


async def _accepts(r: Any, entry_id: str, outcome: str) -> bool:
    """Whether the resolver takes this outcome for this entry (any other refusal, such as a
    missing piece or place, still means the outcome itself fits)."""
    view = await r.view()
    try:
        resolve.plan_resolve(
            view, await r.laundry(), await r.review(), entry_id, outcome,  # type: ignore[arg-type]
            to="ready", now=r.clock(),
        )  # fmt: skip
    except Refused as exc:
        return str(exc) != texts.OUTCOME_BAD
    return True


async def _every_kind(r: Any) -> None:
    await r.commit(ev(BELT, "archived", r.clock()))
    r.clock.advance(minutes=1)
    await r.commit(ev(BELT, "restored", r.clock()))  # a hold: "restored"
    await r.commit(ev(WATCH, "missing", r.clock()))  # a hold: "missing"
    await r.commit(ev(TEE, "deposited", r.clock(), verified=False))  # a hold: "unverified"
    await r.desk.move(UID, "basket", one_of=(WHITE_SHIRT, TWIN))  # a "which"/pending deposit
    await r.desk.move(UID, "basket", more=2, category="footwear")  # a pending deposit with a count


async def test_every_answer_the_panel_offers_is_one_the_resolver_takes_and_no_other() -> None:
    r = await rig()
    await _every_kind(r)

    async def need(kind: str, reason: str, *pieces: str) -> None:
        async def fn(view: Any, tx: Any) -> Any:
            from jarvis.wardrobe.ports import Commit

            needs = [ReviewNeeded(kind, p, reason=reason) for p in pieces]  # type: ignore[arg-type]
            return Commit(extra=tuple(await r.writer.entries(UID, view, tx, needs)))

        await r.store.transact(UID, fn)

    await need("stale", "stale", BELT)  # a quick check
    entries = await r.open_entries()
    assert len({e.kind for e in entries}) >= 3 and len(entries) >= 6
    shown = (await r.desk.review_view(UID)).entries
    assert {e.id for e in shown} == {e.id for e in entries}
    for e in shown:
        accepted = [o for o in ALL if await _accepts(r, e.id, o)]
        assert list(e.answers) == accepted, (e.kind, e.reason, e.answers)
        assert e.answers == tuple(o for o in ALL if o in e.answers)  # one fixed order


async def test_reason_and_count_say_why_and_how_many_in_the_closed_set() -> None:
    r = await rig()
    await _every_kind(r)
    shown = (await r.desk.review_view(UID)).entries
    reasons = {(e.kind, e.reason) for e in shown}
    assert ("hold", "restored") in reasons and ("hold", "missing") in reasons
    assert ("hold", "unverified") in reasons
    assert {e.reason for e in shown} <= review.REASONS
    deposits = [e for e in shown if e.kind == "pending_deposit"]
    assert deposits and all(e.count >= 1 for e in deposits) and max(e.count for e in deposits) == 2
    assert all(e.count == 0 for e in shown if e.kind != "pending_deposit")


async def test_a_none_answer_is_only_offered_for_an_unconfirmed_change() -> None:
    r = await rig()
    await _every_kind(r)
    by = {(e.kind, e.reason): e for e in (await r.desk.review_view(UID)).entries}
    assert "none" in by[("hold", "unverified")].answers
    assert "none" not in by[("hold", "missing")].answers
    assert "none" not in by[("hold", "restored")].answers


@pytest.mark.parametrize("reason", ["", "weird", "x" * 50])
async def test_a_reason_outside_the_set_is_never_shown_and_never_fails_a_commit(
    reason: str,
) -> None:
    assert review.REASONS >= {"sweep", "rescan"}
    assert review._reason(reason, "held") == "held"  # noqa: SLF001 - the safe default
