# tests/test_r131_c_money.py -- R13.1 Part C: what the money path does when the store blips after
# Google answered (docs/plans/r13-1-try-on.md D13.6, D15; review C-1 findings 5 and 12). A settle
# or a release is tried three times; one that still fails is kept for the next press and the
# daily job, which close it as it was meant (a release is never turned into spend); his usage
# month always hears a billed call; the daily job records nothing (pinned). Fixed clocks only;
# nothing reaches Google. Written first and run red.
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from r131_fake_tryon import Step
from r131_fakes import NOW, UID, FixedClock, T
from r131_fakes_c import FakeBilling, SlowProvider, StrictTryOn, ask, ready_world

from jarvis.llm.tryon import TryOnMaybeBilled, TryOnNotBilled
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.wardrobe.seeme import cap as capmod
from jarvis.wardrobe.seeme.cap import TryonCap
from jarvis.wardrobe.seeme.texts import SeeMeRefused


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capmod, "CLOSE_WAITS_S", (0.0, 0.0))  # three tries, no real waits


class FlakyDocs(MemoryDocs):
    """A transaction that writes the spend fails while `left` > 0 (a store blip)."""

    def __init__(self) -> None:
        super().__init__()
        self.left = 0

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        async def checked(tx: Any) -> Any:
            out = await fn(tx)
            if self.left > 0 and any("tryon_spend/" in op.path for op in tx.ops):
                self.left -= 1
                raise RuntimeError("store blip")
            return out

        return await super().transaction(checked)


class BlipsAfter(SlowProvider):
    """p, and the store's next `n` spend writes fail once Google has answered."""

    def __init__(self, p: Any, docs: FlakyDocs, n: int) -> None:
        super().__init__(p)
        self.docs, self.n = docs, n

    async def make(self, a: Any) -> Any:
        try:
            return await self.p.make(a)
        finally:
            self.docs.left = self.n


def _priced(*steps: Step) -> StrictTryOn:
    return StrictTryOn(max_garments=3, model="gemini-3.1-flash-image", script=list(steps))


def rid(n: int) -> str:
    return f"tq_{n:016x}"


async def _refused(coro: Awaitable[Any]) -> SeeMeRefused:
    with pytest.raises(SeeMeRefused) as err:
        await coro
    return err.value


# ---- the cap -----------------------------------------------------------------------------------
async def test_a_close_that_blips_once_is_tried_again_and_closes() -> None:
    docs = FlakyDocs()
    cap = TryonCap(docs, "jarvis_", tz="Asia/Kolkata", now=FixedClock(NOW))
    hold = await cap.reserve(UID, rid(1), 11.22, 300)
    docs.left = 2  # two blips: the third try closes it
    await cap.release(hold, outcome={"error": "provider_unavailable"})
    month = await cap.month(UID)
    assert (month.held_inr, month.spent_inr, month.holds) == (0.0, 0.0, {})


async def test_a_release_that_still_fails_is_kept_and_the_daily_job_releases_it() -> None:
    docs, clock = FlakyDocs(), FixedClock(NOW)
    cap = TryonCap(docs, "jarvis_", tz="Asia/Kolkata", now=clock)
    hold = await cap.reserve(UID, rid(1), 11.22, 300)
    docs.left = 3
    with pytest.raises(RuntimeError):
        await cap.release(hold, outcome={"error": "provider_unavailable"})
    assert hold.released is False and rid(1) in cap.pending
    clock.set(NOW + timedelta(hours=2))  # the morning tick, after the hour
    await cap.settle_old(UID)
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr) == (0.0, 0.0)  # released, never spend at the hold
    assert month.done[rid(1)] == {"error": "provider_unavailable"} and not cap.pending


async def test_the_next_press_closes_a_kept_close_first_so_it_isnt_busy() -> None:
    docs = FlakyDocs()
    cap = TryonCap(docs, "jarvis_", tz="Asia/Kolkata", now=FixedClock(NOW))
    hold = await cap.reserve(UID, rid(1), 11.22, 300)
    docs.left = 3
    with pytest.raises(RuntimeError):
        await cap.settle(hold, 8.52, outcome={"picture": "tp_000000000001"}, picture=True)
    second = await cap.reserve(UID, rid(2), 11.22, 300)  # within 10 minutes: not busy
    assert isinstance(second, capmod.CapHold) and not cap.pending
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.pictures) == (8.52, 11.22, 1)


class LostReplyDocs(MemoryDocs):
    """The next spend write commits, then its reply is lost (the caller sees an error)."""

    def __init__(self) -> None:
        super().__init__()
        self.lose = 0

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        out = await super().transaction(fn)
        if self.lose > 0:
            self.lose -= 1
            raise RuntimeError("the commit's reply was lost")
        return out


@pytest.mark.parametrize("blocked", [False, True])
async def test_a_close_retried_after_a_lost_reply_counts_once(blocked: bool) -> None:
    docs = LostReplyDocs()
    cap = TryonCap(docs, "jarvis_", tz="Asia/Kolkata", now=FixedClock(NOW))
    hold = await cap.reserve(UID, rid(1), 11.22, 300)
    docs.lose = 1  # committed; the cap doesn't know, and tries again
    await cap.settle(hold, 11.22, outcome={"error": "x"}, picture=not blocked, blocked=blocked)
    month = await cap.month(UID)
    assert (month.spent_inr, month.held_inr) == (11.22, 0.0)
    assert (month.pictures, month.blocked) == ((0, 1) if blocked else (1, 0))


# ---- the press ---------------------------------------------------------------------------------
async def test_a_429_whose_release_fails_says_nothing_was_charged_and_is_released_later() -> None:
    docs = FlakyDocs()
    p = BlipsAfter(_priced(Step(error=TryOnNotBilled("status_429"))), docs, 3)
    sw, svc, g = await ready_world(provider=p, docs=docs)
    err = await _refused(svc.press(UID, ask(g.id, (), inr=9.0)))
    assert (err.status, err.code) == (503, "provider_unavailable") and "Nothing" in err.words
    sw.w.clock.set(sw.w.clock() + timedelta(hours=2))
    await svc.kit.cap.settle_old(UID)
    assert (await svc.kit.cap.month(UID)).spent_inr == 0.0


async def test_a_made_picture_whose_settle_fails_is_shown_his_month_hears_it_and_once() -> None:
    docs, billing = FlakyDocs(), FakeBilling()
    sw, svc, g = await ready_world(provider=BlipsAfter(_priced(), docs, 3), docs=docs,
                                   billing=billing)  # fmt: skip
    body = ask(g.id, (T.trousers,), inr=(await svc.estimate(UID, g.id, [T.trousers])).typical_inr)
    pic = await svc.press(UID, body)  # made and kept: never "can't be reached"
    assert await svc.picture(UID, pic.id) is not None
    assert [(u, label) for u, label, _ in billing.recorded] == [(UID, "tryon")]
    again = await svc.press(UID, body)  # his retry: the kept close goes first, then `done`
    assert again.id == pic.id and len(billing.recorded) == 1
    month = await svc.kit.cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.pictures) == (8.52, 0.0, 1)


@pytest.mark.parametrize(
    ("step", "status", "code"),
    [(Step(blocked="safety"), 502, "blocked"),
     (Step(error=TryOnMaybeBilled("timeout")), 503, "provider_unavailable")],
)  # fmt: skip
async def test_a_billed_refusal_whose_settle_fails_keeps_its_words_and_records_his_month(
    step: Step, status: int, code: str
) -> None:
    docs, billing = FlakyDocs(), FakeBilling()
    sw, svc, g = await ready_world(provider=BlipsAfter(_priced(step), docs, 3), docs=docs,
                                   billing=billing)  # fmt: skip
    err = await _refused(svc.press(UID, ask(g.id, (), inr=9.0)))
    assert (err.status, err.code) == (status, code) and "may still be charged" in err.words
    worst = svc.kit.provider().estimate(3)[1]
    assert billing.recorded == [(UID, "tryon", worst)]


# ---- what his usage month hears (pins) ---------------------------------------------------------
@pytest.mark.parametrize(
    ("step", "records"),
    [(Step(blocked="safety"), True), (Step(error=TryOnMaybeBilled("cut")), True),
     (Step(error=TryOnNotBilled("status_500")), False)],
)  # fmt: skip
async def test_a_billed_call_records_the_worst_case_and_a_released_one_nothing(
    step: Step, records: bool
) -> None:
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=_priced(step), billing=billing)
    await _refused(svc.press(UID, ask(g.id, (), inr=9.0)))
    worst = svc.kit.provider().estimate(3)[1]
    assert billing.recorded == ([(UID, "tryon", worst)] if records else [])


async def test_the_daily_job_settles_an_old_hold_and_records_nothing_in_his_month() -> None:
    billing = FakeBilling()
    sw, svc, g = await ready_world(billing=billing)
    await svc.kit.cap.reserve(UID, rid(9), 11.22, 300)  # a press cut off by a crash
    sw.w.clock.set(sw.w.clock() + timedelta(hours=2))
    assert await svc.kit.cap.settle_old(UID) == 1
    assert (await svc.kit.cap.month(UID)).spent_inr == 11.22 and billing.recorded == []
