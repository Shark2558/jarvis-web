# tests/test_r63_b_cases.py -- R6.3 part B: the `writer` suite's other cases (docs/plans/
# r6-3-book-content.md "Tests and evals"), each a test here and an eval case of the same name in
# evals/r6_3/writer.py: a 429 released with no retry inside (M1), a cut call settled at its usage
# plus the margin (H7), a length stop refused before the checks (L10), one lease holder, the same
# pack to both brains with no tools, No-AI pauses, the storage line, a first write continued with a
# new YES (H3), three seals without an Update, use_first, a run across a deploy (M5), "update by
# itself" only within its cap, a slow brain on the clocks (H7), Privacy -> Delete (D13), a pack
# that never reads tests/ or .claude/ (M8). Fixed clocks, scripted brains only.
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from r63_fake_brains import (
    FAKE_PATH_DRAFT,
    GOOD_DRAFT,
    Step,
    busy,
    claude_like,
    cut,
    gemini_like,
    length_stop,
    provider_of,
    registry,
    slow,
)
from r63_fakes import FakeBilling, source_zip
from r63_fakes_b import (
    TRIAL_FACTS,
    MovableSource,
    files,
    pick,
    run_first,
    seal_r6,
    service,
    steps,
    trial_source,
)

from jarvis.buildbook.model import MIB
from jarvis.buildbook.writer import model as wmodel
from jarvis.buildbook.writer import packs
from jarvis.buildbook.writer.http import PickIn, RunIn, TrialIn
from jarvis.buildbook.writer.model import NOT_WRITTEN, Caps
from jarvis.buildbook.writer.texts import WriterRefused
from jarvis.notify.ports import Delivery


def _calls(*specs: Any) -> int:
    return sum(len(provider_of(s).calls) for s in specs)


async def _trial(built: Any) -> None:
    svc, uid = built.service, built.job._ctx.uid
    est = await svc.estimate(uid, "trial")
    await svc.start_trial(uid, TrialIn(typed="YES", estimate_id=est.id))


class Told:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def notify(self, uid: str, signal: Any, message: str, **kw: Any) -> Delivery:
        self.sent.append((signal.kind, message))
        return Delivery(action="ring", reason="sent", push=1)


# ---- the call (D1, D8, H7, L10) ------------------------------------------------------------
async def test_a_429_is_released_with_no_retry_inside_the_call() -> None:
    claude = claude_like(busy())
    built = service(brains=registry(claude, gemini_like()))
    uid = built.job._ctx.uid
    await _trial(built)
    view = await built.service.step(uid)
    calls = provider_of(claude).calls
    assert len(calls) == 1 and calls[0].retries_off and view.inr == 0.0
    month = await built.service.ledger.month(uid)
    assert month.held_inr == 0.0 and month.holds == {} and "answering" in view.why


async def test_a_cut_call_is_settled_at_its_usage_plus_the_margin_never_its_hold() -> None:
    billing = FakeBilling()
    claude = claude_like(cut(GOOD_DRAFT), Step(text=GOOD_DRAFT))
    built = service(brains=registry(claude, gemini_like()), source=trial_source(big=True),
                    billing=billing)  # fmt: skip
    await _trial(built)
    await built.service.step(built.job._ctx.uid)
    first_inr = billing.recorded[0][2] * billing.rate
    assert 0.5 < first_inr < 11.84 - 5  # usage + a 200-token margin, far under the Rs 11.84 hold
    rows = (await built.service.trial_rows(built.job._ctx.uid)).rows
    assert rows[0].state == "redrafted" and rows[0].checks == ("incomplete",)


async def test_a_length_stop_is_refused_before_the_checks() -> None:
    claude = claude_like(length_stop(GOOD_DRAFT), Step(text=GOOD_DRAFT))
    built = service(brains=registry(claude, gemini_like()))
    await _trial(built)
    await built.service.step(built.job._ctx.uid)
    row = (await built.service.trial_rows(built.job._ctx.uid)).rows[0]
    assert (row.state, row.checks) == ("redrafted", ("incomplete",))


async def test_ten_steps_at_once_have_one_lease_holder_and_the_rest_are_busy() -> None:
    claude = claude_like(*[slow(GOOD_DRAFT, 0.05) for _ in range(5)])
    built = service(brains=registry(claude, gemini_like()))
    svc, uid = built.service, built.job._ctx.uid
    await _trial(built)
    got = await asyncio.gather(*(svc.step(uid) for _ in range(10)), return_exceptions=True)
    busy_ones = [g for g in got if isinstance(g, WriterRefused) and g.code == "busy"]
    assert len(busy_ones) == 9 and _calls(claude) == 5


async def test_the_free_brain_gets_the_same_pack_and_no_tools() -> None:
    claude, gemini = claude_like(), gemini_like()
    built = service(brains=registry(claude, gemini))
    await _trial(built)
    await built.service.step(built.job._ctx.uid)
    a, b = provider_of(claude).calls, provider_of(gemini).calls
    assert [c.messages[0].text() for c in a] == [c.messages[0].text() for c in b]
    assert (
        a[0].system == b[0].system and a[0].max_tokens == 4_000
    )  # tools: never (the fake asserts)


async def test_no_ai_pauses_the_run_and_nothing_is_sent() -> None:
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()))
    await _trial(built)
    router = built.job._ctx.brains.router_for("anthropic")

    async def off() -> bool:
        return True

    router.blocked_now = off  # type: ignore[method-assign]
    view = await built.service.step(built.job._ctx.uid)
    assert view.state == "paused" and _calls(claude) == 0


async def test_the_80_percent_storage_line_is_shown_and_told_once() -> None:
    told = Told()
    built = service(notifier=told, limit_mb=10)
    ctx, uid = built.job._ctx, built.job._ctx.uid
    await seal_r6(built)

    async def used(_: str) -> int:
        return int(8.5 * MIB)

    ctx.vault.used_bytes = used  # type: ignore[method-assign]
    assert (await built.service.view(uid)).storage.warn is True
    for _ in range(3):
        await built.job.run((uid,))
    assert [k for k, _ in told.sent] == ["book_sealed"] and "of 10 MiB" in told.sent[0][1]


# ---- the pages files across releases (D11, D12, H3, M5) ------------------------------------------
async def test_a_first_write_stopped_at_its_cap_and_continued_with_a_new_yes_replaces_it() -> None:
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()), source=trial_source(big=True))
    svc, uid = built.service, built.job._ctx.uid
    await seal_r6(built)
    await pick(built, first=30)
    await run_first(built)
    stopped = await steps(built)
    assert stopped.state == "stopped" and "cap" in stopped.why.lower()
    part = (await svc.pages_view(uid, None)).parts
    first_written = sum(1 for p in part for c in p.chapters for r in c.pages if r.written)
    assert 0 < first_written < len(TRIAL_FACTS.pages)
    await pick(built, first=1_500)
    await run_first(built)
    assert (await steps(built)).state == "done"
    part = (await svc.pages_view(uid, None)).parts
    assert all(r.written for p in part for c in p.chapters for r in c.pages)
    assert len((await built.service.vault.index(uid)).files) == 1


async def _deployed(*, big: bool = False, auto: bool = False, **caps: int) -> Any:
    claude = claude_like()
    src = MovableSource(TRIAL_FACTS, zipped=trial_source(big=big).read("source"))
    built = service(brains=registry(claude, gemini_like()), source=src)
    await seal_r6(built)
    if auto:
        built_pick = PickIn(brain="anthropic", caps=Caps(**caps), auto_update=True)
        try:
            await built.service.pick(built.job._ctx.uid, built_pick)
        except WriterRefused as no:
            yes = built_pick.model_copy(update={"typed": "YES", "terms_id": no.extra["terms_id"]})
            await built.service.pick(built.job._ctx.uid, yes)
    else:
        await pick(built, **caps)
    await run_first(built)
    await steps(built)
    return built, src, claude


def _changed(big: bool = False) -> dict[str, str]:
    return files({"src/jarvis/demo/store.py": '"""The store, changed."""\n'}, big=big)


async def test_three_seals_without_an_update_keep_every_unchanged_ai_page() -> None:
    built, src, claude = await _deployed()
    uid, before = built.job._ctx.uid, _calls(claude)
    for n, tree in enumerate((_changed(), _changed(), _changed())):
        rel = src.deploy(f"{n + 7}{n + 7}" * 20, tree, TRIAL_FACTS)
        await seal_r6(built)
        await built.job.run((uid,))
    page = await built.service.page(uid, "pg_card_c01", rel.id)
    assert page.meta is not None and _calls(claude) == before
    waiting = await built.service.page(uid, "pg_card_c02", rel.id)
    assert waiting.meta is None and waiting.changed


async def test_an_update_over_the_release_cap_or_with_nothing_to_carry_is_use_first() -> None:
    built, src, _ = await _deployed(big=True)
    svc, uid = built.service, built.job._ctx.uid
    src.deploy("71" * 20, _changed(big=True), TRIAL_FACTS)
    await seal_r6(built)
    await built.job.run((uid,))
    await svc.pick(uid, PickIn(brain="anthropic", caps=Caps(release=1)))  # lowering: instant
    est = await svc.estimate(uid, "update")
    with pytest.raises(WriterRefused) as no:
        await svc.update(uid, RunIn(typed="YES", estimate_id=est.id))
    assert no.value.code == "use_first" and est.mid > 1
    await svc.pick(uid, PickIn(brain="anthropic", caps=Caps(release=1)))
    await built.service.vault.drop(uid, [src.current().id])  # type: ignore[union-attr]
    with pytest.raises(WriterRefused) as nothing:
        await svc.update(uid, RunIn(typed="YES", estimate_id=est.id))
    assert nothing.value.code == "use_first"


async def test_a_run_across_a_deploy_stops_seals_its_own_file_and_its_yes_is_not_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude = claude_like(*[slow(GOOD_DRAFT, 0.3) for _ in range(10)])
    src = MovableSource(TRIAL_FACTS, zipped=trial_source().read("source"))
    built = service(brains=registry(claude, gemini_like()), source=src)
    svc, uid = built.service, built.job._ctx.uid
    await seal_r6(built)
    await pick(built)
    await run_first(built)
    seed = (3.0,) * 20
    timed = {"anthropic": seed}
    await svc.store.change(uid, lambda d: (d.model_copy(update={"seconds": timed}), None))
    monkeypatch.setattr(wmodel, "STEP_BUDGET_S", 8.1)  # one call fits, a second doesn't
    await svc.step(uid)
    assert _calls(claude) == 1
    r1 = src.current().id  # type: ignore[union-attr]
    new = src.deploy("72" * 20, files(), TRIAL_FACTS)
    await seal_r6(built)
    view = await svc.step(uid)
    assert view.state == "stopped" and "new release" in view.why and _calls(claude) == 1
    assert (await built.service.vault.index(uid)).find(r1) is not None
    for _ in range(5):
        await built.job.run((uid,))
    ready = (await svc.view(uid)).update_ready
    assert _calls(claude) == 1 and ready is not None and ready.release == new.id
    assert len(ready.pages) == len(TRIAL_FACTS.pages) - 1  # the pages left join its estimate


async def test_update_by_itself_runs_only_within_the_release_cap() -> None:
    built, src, claude = await _deployed(big=True, auto=True)
    uid, before = built.job._ctx.uid, _calls(claude)
    src.deploy("73" * 20, _changed(big=True), TRIAL_FACTS)
    await seal_r6(built)
    for _ in range(4):
        await built.job.run((uid,))
    assert _calls(claude) == before + 3 and (await built.service.view(uid)).update_ready is None
    capped, src2, claude2 = await _deployed(big=True, auto=True, release=1)
    uid2, before2 = capped.job._ctx.uid, _calls(claude2)
    src2.deploy("74" * 20, _changed(big=True), TRIAL_FACTS)
    await seal_r6(capped)
    for _ in range(4):
        await capped.job.run((uid2,))
    assert _calls(claude2) == before2  # over its cap: it waits for his Update (or a full write)


async def test_a_slow_brain_starts_no_clock_call_and_the_step_finishes_it() -> None:
    claude = claude_like()
    built = service(brains=registry(claude, gemini_like()))
    uid = built.job._ctx.uid
    await _trial(built)
    seed = {"anthropic": (50.0,) * 20, "gemini": (50.0,) * 20}
    await built.service.store.change(uid, lambda d: (d.model_copy(update={"seconds": seed}), None))
    await built.job.run((uid,))
    waiting = (await built.service.view(uid)).run
    assert _calls(claude) == 0 and "clock allows" in waiting.why
    await built.service.step(uid)
    assert _calls(claude) >= 1


async def test_privacy_delete_stops_a_run_and_removes_the_writers_data() -> None:
    built, _, _ = await _deployed()
    uid = built.job._ctx.uid
    row = built.privacy[0]
    assert (await row.describe(uid)).count > 0 and (await row.describe(uid)).delete == "passkey"
    exported = await row.export(uid)
    assert (
        exported is not None and "pages_files" in exported and GOOD_DRAFT[:20] not in str(exported)
    )
    assert await row.delete(uid) > 0
    assert (await built.service.vault.index(uid)).files == ()
    assert (await built.service.view(uid)).pick.brain is None
    assert (await built.service.ledger.month(uid)).spent_inr > 0  # the ledger stays 13 months
    page = await built.service.page(uid, "pg_card_c01", None)
    assert page.meta is None and NOT_WRITTEN in page.sections[0].text


async def test_a_pack_never_reads_tests_or_claude_files() -> None:
    planted = {
        "tests/test_demo.py": "NEEDLE_TESTS = 'Quimbledorf Works'\n",
        ".claude/agents/x.md": "NEEDLE_CLAUDE\n",
        "evals/demo/cases.jsonl": '{"NEEDLE_EVALS": 1}\n',
        "deploy/bridge.env.example": "NEEDLE_ENV=1\n",
    }
    tree = packs.read_source(source_zip({**files(), **planted}))
    page = TRIAL_FACTS.page("pg_card_c01")
    assert page is not None
    widened = page.model_copy(update={"refs": (*page.refs, *planted)})
    from jarvis.buildbook.gen.scrub import default_scrubber

    body = packs.build(widened, TRIAL_FACTS, tree, default_scrubber()).body
    assert not [
        n for n in ("NEEDLE_TESTS", "NEEDLE_CLAUDE", "NEEDLE_EVALS", "NEEDLE_ENV") if n in body
    ]
    assert FAKE_PATH_DRAFT


async def test_a_trial_stopped_at_the_monthly_line_names_the_line_it_used() -> None:
    """R6.3 hotfix 1 (v6.3.1; the owner's trial of 24 Nov, 00:52 IST): with no writer picked, the
    gate holds a trial at the default 80 % of his monthly limit, but the stop's words read the
    unpicked pick's floor and said "10 %". The words name the line the gate used."""
    billing = FakeBilling(limit_inr=1_500)
    built = service(billing=billing)
    uid = built.job._ctx.uid
    billing.recorded.append((uid, "anthropic", 1_404.79 / billing.rate))  # 94 % used, as his
    await _trial(built)
    view = await built.service.step(uid)
    assert view.state == "stopped" and view.done == 0 and view.inr == 0.0
    assert f"{Caps().limit_pct} % of your monthly limit" in view.why
    assert "10 %" not in view.why


async def test_a_page_counted_denser_than_the_old_worst_case_is_kept_not_stopped() -> None:
    """R6.3 hotfix 1 (v6.3.1; the owner's trial of 24 Nov, 01:00 IST): Claude counted the first
    sample page's pack denser than 2.5 bytes a token, so its bill (Rs 11.83) passed its hold and the
    safety stop ended the trial with no page kept. The hold now assumes 1.5 bytes a token: a page
    counted at 1.8 with every output token used settles inside its hold and is kept."""
    claude = claude_like(Step(text=GOOD_DRAFT, bytes_per_token=1.8, output_tokens=4_000))
    built = service(brains=registry(claude, gemini_like()), source=trial_source(big=True))
    uid = built.job._ctx.uid
    await _trial(built)
    view = await built.service.step(uid)
    sent = sum(len(m.text().encode("utf-8")) for m in provider_of(claude).calls[0].messages)
    assert sent > 60_000  # a full-size pack, as his (the cap is 96,000)
    assert "worst case" not in view.why and view.state in ("running", "queued", "done")
    assert view.done >= 1 and view.inr > 0
    month = await built.service.ledger.month(uid)
    assert month.held_inr == 0.0 and month.holds == {}  # settled, nothing left held
