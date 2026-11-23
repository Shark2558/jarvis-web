# tests/test_r63_b_rows.py -- R6.3 part B's rows (docs/plans/r6-3-book-content.md "What is built"):
# each named test of B's rows, through the writer's service on the fakes (the scripted brains of
# r63_fake_brains, a fixed clock, in-memory documents). No model is ever called.
from __future__ import annotations

from typing import Any

import pytest
from r63_fake_brains import (
    FAKE_PATH_DRAFT,
    GOOD_DRAFT,
    RecordingLaptop,
    claude_like,
    down,
    gemini_like,
    paid_gemini,
    provider_of,
    registry,
)
from r63_fakes import FIXTURE_FACTS, NOW, FakeBilling
from r63_fakes_b import (
    TRIAL_FACTS,
    MovableSource,
    files,
    hold_payer,
    pick,
    run_first,
    seal_r6,
    service,
    steps,
    trial_source,
)

import jarvis.llm.write as write
from jarvis.buildbook.facts_model import CardFact, IndexedPage
from jarvis.buildbook.writer.http import PickIn, RunIn, TrialIn
from jarvis.buildbook.writer.model import EXAMPLE_MARK, FACT_PLACEHOLDER, NOT_WRITTEN, Caps
from jarvis.buildbook.writer.texts import WriterRefused
from jarvis.llm.router import ModelTier


def _calls(*specs: Any) -> int:
    return sum(len(provider_of(s).calls) for s in specs)


async def _refused(code: str, coro: Any) -> WriterRefused:
    with pytest.raises(WriterRefused) as no:
        await coro
    assert no.value.code == code, (no.value.code, no.value.detail)
    return no.value


# ---- row 379 -------------------------------------------------------------------------------------
async def test_row379_a_page_is_written_at_balanced_with_an_example_and_every_source_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fake Claude brain writes the fixture's `pg_card_c01` (A's real pack and `pg_card_c16`
    join at I1: INTEGRATION-B)."""
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()), source=trial_source())
    uid = built.job._ctx.uid
    await seal_r6(built)
    await pick(built)
    await run_first(built)
    assert (await steps(built)).state == "done"
    page = await built.service.page(uid, "pg_card_c01", None)
    assert [s.id for s in page.sections] == ["plain", "example", "how", "costs", "fails", "code"]
    assert page.sections[1].heading == EXAMPLE_MARK
    index = TRIAL_FACTS.index
    for ref in page.sections[-1].refs:
        assert ref in index.paths
    for s in page.sections:
        assert not FACT_PLACEHOLDER.search(s.text)
        if s.id not in ("example", "code"):
            assert not [c for c in s.text if c.isdigit()] or s.id == "how"
    how = next(s for s in page.sections if s.id == "how").text
    assert "3 times" in how and "(5 by default)" in how  # filled from the facts, never typed
    meta = page.meta
    assert meta is not None and (meta.brain, meta.tier) == ("anthropic", "balanced")
    assert meta.model == write.model_of(claude) and meta.release == TRIAL_FACTS.release.id  # type: ignore[union-attr]

    real = write.write_text
    for wrong in ({"tier": ModelTier.FAST}, {"model": "offline-model", "provider": "offline"}):

        async def answered(router: Any, *, _wrong: Any = wrong, **kw: Any) -> Any:
            got = await real(router, **kw)
            return write.Written(**{**got.__dict__, **_wrong})

        monkeypatch.setattr(write, "write_text", answered)
        fresh = service(brains=registry(claude_like(), gemini_like()), source=trial_source())
        await seal_r6(fresh)
        await pick(fresh)
        await run_first(fresh)
        await steps(fresh)
        kept = await fresh.service.page(uid, "pg_card_c01", None)
        assert kept.meta is None and NOT_WRITTEN in kept.sections[0].text, wrong
    monkeypatch.setattr(write, "write_text", real)


# ---- 23 Nov · the trial (his cap of Rs 100) ------------------------------------------------
async def test_the_trial_spends_nothing_before_yes_and_stops_at_its_cap() -> None:
    claude, gemini = claude_like(), gemini_like()
    built = service(brains=registry(claude, gemini))
    svc, uid = built.service, built.job._ctx.uid
    est = await svc.estimate(uid, "trial")
    await svc.view(uid)
    for _ in range(5):
        await built.job.run((uid,))
    assert (await svc.step(uid)).state == "none" and _calls(claude, gemini) == 0
    for typed in ("yes", "Yes", "YES!", " ye s"):
        await _refused("not_yes", svc.start_trial(uid, TrialIn(typed=typed, estimate_id=est.id)))
    await _refused(
        "estimate_changed", svc.start_trial(uid, TrialIn(typed="YES", estimate_id="we_" + "0" * 12))
    )
    assert _calls(claude, gemini) == 0
    await svc.start_trial(uid, TrialIn(typed=" YES ", estimate_id=est.id))
    assert (await steps(built)).state == "done"
    rows = (await svc.trial_rows(uid)).rows
    assert len(rows) == 10 and {r.brain for r in rows} == {"anthropic", "gemini"}
    assert all(r.state == "first" and r.checks == () for r in rows)
    assert _calls(claude) == 5 and _calls(gemini) == 5
    one = await svc.trial_page(uid, rows[0].nn)
    assert one.page.meta is not None and one.page.meta.tier == "balanced"

    # every Claude call settles at its hold (Rs 16.71 a full pack since hotfix 1; Rs 11.84 and 8
    # calls before): 5 calls fit Rs 100, the 6th is refused before it is sent
    payer = hold_payer(*([FAKE_PATH_DRAFT] * 10))
    capped = service(brains=registry(payer, gemini_like()), source=trial_source(big=True))
    s2 = capped.service
    est2 = await s2.estimate(uid, "trial")
    assert est2.hold == pytest.approx(16.71, abs=0.02) and est2.cap == 100  # 11.84 before hotfix 1
    await s2.start_trial(uid, TrialIn(typed="YES", estimate_id=est2.id))
    view = await steps(capped)
    assert _calls(payer) == 5 and view.state == "stopped" and "cap" in view.why.lower()
    assert 83.0 <= view.inr <= 84.0  # five holds of about Rs 16.7: a sixth would pass Rs 100

    # a call billed above its hold stops the trial at once (M1)
    over = hold_payer(over=5_000)
    o = service(brains=registry(over, gemini_like()), source=trial_source(big=True))
    est3 = await o.service.estimate(uid, "trial")
    await o.service.start_trial(uid, TrialIn(typed="YES", estimate_id=est3.id))
    stopped = await steps(o)
    assert _calls(over) == 1 and stopped.state == "stopped" and "worst case" in stopped.why


# ---- 23 Nov · the pick ---------------------------------------------------------------------------
async def test_the_first_write_needs_the_pick_and_a_second_yes_on_the_estimate_shown() -> None:
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()))
    svc, uid = built.service, built.job._ctx.uid
    await seal_r6(built)
    est = await svc.estimate(uid, "first")
    await _refused("pick_needed", svc.first(uid, RunIn(typed="YES", estimate_id=est.id)))
    await pick(built, first=1_200)
    est = await svc.estimate(uid, "first")
    await _refused("not_yes", svc.first(uid, RunIn(typed="yes", estimate_id=est.id)))
    await _refused(
        "estimate_changed", svc.first(uid, RunIn(typed="YES", estimate_id="we_" + "9" * 12))
    )
    assert _calls(claude) == 0
    run = await svc.first(uid, RunIn(typed="YES", estimate_id=est.id))
    assert run.kind == "first" and run.cap_inr == 1_200 and run.state == "queued"
    await _refused("running", svc.first(uid, RunIn(typed="YES", estimate_id=est.id)))


# ---- 23 Nov · the deploy -------------------------------------------------------------------------
async def test_nothing_spends_by_itself_after_a_deploy() -> None:
    claude = claude_like()
    src = MovableSource(TRIAL_FACTS, zipped=trial_source().read("source"))
    built = service(brains=registry(claude, gemini_like()), source=src)
    svc, uid = built.service, built.job._ctx.uid
    await seal_r6(built)
    await pick(built)
    await run_first(built)
    assert (await steps(built)).state == "done"
    written = _calls(claude)
    tree = files({"src/jarvis/demo/store.py": '"""The demo store, changed."""\n\nKEEP_DAYS = 30\n'})
    new = src.deploy("70" * 20, tree, TRIAL_FACTS)
    await seal_r6(built)
    for _ in range(50):
        await built.job.run((uid,))
    assert _calls(claude) == written  # no brain call by itself
    view = await svc.view(uid)
    ready = view.update_ready
    assert ready is not None and ready.release == new.id and ready.inr_mid > 0
    assert set(ready.pages) == {"pg_card_c02", "pg_chapter_example", "pg_module_demo"}
    carried = await svc.page(uid, "pg_card_c01", new.id)
    assert carried.meta is not None and carried.meta.release == TRIAL_FACTS.release.id  # type: ignore[union-attr]
    waiting = await svc.page(uid, "pg_card_c02", new.id)
    assert waiting.changed and waiting.meta is None
    await _refused("not_yes", svc.update(uid, RunIn(typed="ok", estimate_id=ready.estimate_id)))
    await svc.update(uid, RunIn(typed="YES", estimate_id=ready.estimate_id))
    assert (await steps(built)).state == "done"
    assert _calls(claude) == written + 3  # the changed pages only
    assert (await svc.page(uid, "pg_card_c02", new.id)).meta is not None
    assert (await svc.view(uid)).update_ready is None


async def test_spending_authority_needs_a_typed_yes() -> None:
    built = service(brains=registry(claude_like(), gemini_like()))
    svc, uid = built.service, built.job._ctx.uid

    async def asks(body: PickIn) -> str:
        no = await _refused("yes_needed", svc.pick(uid, body))
        assert no.extra["words"] and all("$" not in w for w in no.extra["words"])
        assert (await svc.view(uid)).pick == before
        return str(no.extra["terms_id"])

    before = (await svc.view(uid)).pick
    first = PickIn(brain="anthropic", caps=Caps())
    terms = await asks(first)  # the first pick
    await _refused(
        "not_yes", svc.pick(uid, first.model_copy(update={"typed": "yes", "terms_id": terms}))
    )
    stale = first.model_copy(update={"typed": "YES", "terms_id": "wt_" + "0" * 12})
    await _refused("terms_changed", svc.pick(uid, stale))
    saved = await svc.pick(uid, first.model_copy(update={"typed": "YES", "terms_id": terms}))
    assert saved.brain == "anthropic" and saved.confirmed.caps == Caps()
    before = saved
    for body in (
        PickIn(brain="anthropic", caps=Caps(release=800)),  # a cap raised
        PickIn(brain="anthropic", caps=Caps(limit_pct=90)),  # the % line raised
        PickIn(brain="anthropic", caps=Caps(), auto_update=True),  # update by itself
        PickIn(brain="gemini", caps=Caps()),  # a brain that trains on what it reads
    ):
        await asks(body)
    lower = await svc.pick(uid, PickIn(brain="anthropic", caps=Caps(release=300)))
    assert lower.caps.release == 300 and lower.confirmed.caps.release == 300  # instant
    before = lower
    gem = PickIn(brain="gemini", caps=Caps(release=300))
    t = await asks(gem)
    await svc.pick(uid, gem.model_copy(update={"typed": "YES", "terms_id": t}))
    before = (await svc.view(uid)).pick
    await asks(PickIn(brain="anthropic", caps=Caps(release=300)))  # back to a paid brain


async def test_row380_the_update_estimate_counts_a_new_card() -> None:
    claude = claude_like()
    src = MovableSource(TRIAL_FACTS, zipped=trial_source().read("source"))
    built = service(brains=registry(claude, gemini_like()), source=src)
    svc, uid = built.service, built.job._ctx.uid
    await seal_r6(built)
    await pick(built)
    await run_first(built)
    await steps(built)
    c74 = IndexedPage(
        id="pg_card_c74", kind="card", title="Demo voice", part="parts", chapter="demo",
        refs=("src/jarvis/demo/router.py",), sources=("C74",),
    )  # fmt: skip
    grown = TRIAL_FACTS.model_copy(
        update={
            "pages": (*TRIAL_FACTS.pages, c74),
            "cards": (*TRIAL_FACTS.cards, CardFact(id="C74", title="Demo voice", module="demo")),
        }
    )
    new = src.deploy("74" * 20, files(), grown)
    await seal_r6(built)
    await built.job.run((uid,))
    ready = (await svc.view(uid)).update_ready
    assert ready is not None and ready.release == new.id and ready.pages == ("pg_card_c74",)
    est = await svc.estimate(uid, "update")
    assert est.pages == 1 and est.id == ready.estimate_id and est.mid >= 0


# ---- the brain's rules (D1, M2) and the job's (D5) ----------------------------------------
async def test_no_laptop_call_with_a_ready_fallback_and_no_tier_change() -> None:
    laptop = RecordingLaptop()
    claude = claude_like(down(), down(), down())
    built = service(brains=registry(claude, gemini_like(), laptop=laptop))
    svc, uid = built.service, built.job._ctx.uid
    est = await svc.estimate(uid, "trial")
    await svc.start_trial(uid, TrialIn(typed="YES", estimate_id=est.id))
    await svc.step(uid)
    assert laptop.calls == 0
    assert {c.model for c in provider_of(claude).calls} <= {write.model_of(claude)}


async def test_a_paid_tier_gemini_and_an_unpriced_brain_are_not_offered() -> None:
    from r63_fake_brains import custom_brain

    built = service(brains=registry(claude_like(), paid_gemini(), custom_brain()))
    view = await built.service.view(built.job._ctx.uid)
    offered = {b.id: b.offered for b in view.brains}
    assert offered == {"anthropic": True, "gemini": False, "openai_compat": False}
    await _refused(
        "not_offered",
        built.service.pick(built.job._ctx.uid, PickIn(brain="gemini", caps=Caps())),
    )


async def test_the_clocks_start_no_call_before_a_measured_one_and_the_step_does() -> None:
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()))
    svc, uid = built.service, built.job._ctx.uid
    est = await svc.estimate(uid, "trial")
    await svc.start_trial(uid, TrialIn(typed="YES", estimate_id=est.id))
    for _ in range(3):
        await built.job.run((uid,))
    assert _calls(claude) == 0  # no measured call: the clocks start none (H7)
    await svc.step(uid)
    assert _calls(claude) == 5


async def test_an_unreadable_meter_refuses_and_nothing_is_sent() -> None:
    billing = FakeBilling()
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()), billing=billing)
    svc, uid = built.service, built.job._ctx.uid
    est = await svc.estimate(uid, "trial")
    await svc.start_trial(uid, TrialIn(typed="YES", estimate_id=est.id))
    billing.broken = True
    view = await svc.step(uid)
    assert _calls(claude) == 0 and view.state in ("stopped", "paused")
    assert NOW.year == 2026 and GOOD_DRAFT and FIXTURE_FACTS
