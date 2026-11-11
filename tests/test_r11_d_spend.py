# tests/test_r11_d_spend.py -- R11 Part D (plan D15, item 15): grocery spend a month from his
# e-mailed receipts. The daily `grocery_spend` job reads Gmail like the parcels reader, obeys his
# permission rows (fail closed), keeps totals per month only (sealed, purpose `spend`), never a
# card number, and audits a kind-only line.
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from r11_fakes import UID
from r11_fakes_d import CARD_DIGITS, GMAIL, MailBox, Rules, connector, kctx

from jarvis.helpers.kitchen.spend import OFF_LINE, GrocerySpendJob, SpendService
from jarvis.helpers.kitchen.store import SpendStore
from jarvis.tools.policy import Effect

ALL = (
    "d_receipt_bigbasket_nov.eml",
    "d_receipt_bigbasket_delivered.eml",
    "d_receipt_blinkit_nov.eml",
    "d_receipt_zepto_oct.eml",
    "d_receipt_zepto_nov.eml",
    "d_receipt_zepto_cancelled.eml",
    "d_receipt_instamart_nov.eml",
    "d_receipt_swiggy_food.eml",
    "d_receipt_unknown_sender.eml",
    "d_receipt_unaligned.eml",
    "d_receipt_injected.eml",
    "d_receipt_bigbasket_promo.eml",
)


class Ticker:
    """A monotonic clock the test moves (the job's time budget)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _rig(
    names: tuple[str, ...] = ALL,
    *,
    on: bool = True,
    rules: Rules | None = None,
    box: MailBox | None = None,
    clock: Ticker | None = None,
    **kw: Any,
) -> tuple[SpendService, GrocerySpendJob, MailBox, Any, Any]:
    box = box or MailBox(names)
    conn = await connector(box.client())
    c, _, docs, _ = kctx(google=conn, rules=rules or Rules(effect=None), **kw)
    svc, job = _service(docs, c, clock or Ticker())
    if on and c.keyring is not None:
        await svc.set_on(UID, True)
    return svc, job, box, docs, c


def _service(docs: Any, c: Any, clock: Ticker) -> tuple[SpendService, GrocerySpendJob]:
    """A new service and job over `docs` (as after a restart)."""
    store = SpendStore(docs, c.keyring, now=c.now, tz=c.tz)
    svc = SpendService(store, google=c.google, now=c.now, tz=c.tz, clock=clock)
    job = GrocerySpendJob(svc, owners=c.owners, reads=c.reads)
    return svc, job


async def _months(svc: SpendService) -> dict[str, str]:
    return {m["month"]: m["total"] for m in await svc.totals(UID)}


WANT = {"2026-11": "₹2,140.50", "2026-10": "₹789"}


async def test_the_job_totals_each_month_from_aligned_grocery_receipts_only() -> None:
    svc, job, _, _, _ = await _rig()
    counts = await job.run(["someone_else"])  # the composite's list is ignored: ctx.owners
    assert counts["owners"] == 1 and counts["failed"] == 0
    months = {m["month"]: m for m in await svc.totals(UID)}
    assert months["2026-11"]["total"] == "₹2,140.50" and months["2026-11"]["orders"] == 4
    assert months["2026-10"]["total"] == "₹789" and months["2026-10"]["orders"] == 1
    assert set(months["2026-11"]["by_merchant"]) == {"BigBasket", "Blinkit", "Swiggy Instamart"}


async def test_a_second_run_reads_no_mail_twice_and_counts_nothing_twice() -> None:
    svc, job, box, _, _ = await _rig()
    await job.run([])
    first = box.reads()
    await job.run([])
    assert box.reads() == first  # every message id was already seen (keyed hashes)
    months = {m["month"]: m for m in await svc.totals(UID)}
    assert months["2026-11"]["total"] == "₹2,140.50"


async def test_a_planted_card_number_is_never_stored_logged_or_audited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, job, _, docs, c = await _rig()
    await job.run([])
    stored = json.dumps(docs._data)  # noqa: SLF001 - every document, raw
    assert CARD_DIGITS not in stored and "4111 1111" not in stored
    audit = json.dumps([e.model_dump(mode="json") for e in (await c.audit.tail(50)).entries])
    assert CARD_DIGITS not in audit and "BigBasket" not in audit and "2,140" not in audit
    assert CARD_DIGITS not in caplog.text and "4111 1111" not in caplog.text
    assert "BigBasket" not in caplog.text


async def test_the_audit_line_is_kind_only() -> None:
    _, job, _, _, c = await _rig()
    await job.run([])
    entry = (await c.audit.tail(5)).entries[-1]
    got = (entry.agent, entry.tool, entry.outcome, entry.detail)
    assert got == ("helpers", "gmail_search", "executed", "grocery_spend")  # I1: kind only


@pytest.mark.parametrize(
    "rules",
    [
        Rules("gmail_*", Effect.DENY),  # his "Search and read email" row is Never
        Rules("gmail_*", Effect.ASK),  # a background reader can't ask: skipped
        Rules("spend_*", Effect.DENY),  # the Kitchen row is Never
        Rules(fail=True),  # the rows can't be read: fail closed
    ],
)
async def test_his_permission_rows_stop_the_job_before_any_mail_is_read(rules: Rules) -> None:
    svc, job, box, _, _ = await _rig(rules=rules)
    counts = await job.run([])
    assert counts["skipped"] == 1 and box.requests == []
    assert await svc.totals(UID) == []


async def test_without_the_governed_path_the_job_fails_closed() -> None:
    box = MailBox(ALL)
    conn = await connector(box.client())
    c, _, docs, _ = kctx(google=conn)
    svc = SpendService(SpendStore(docs, c.keyring, now=c.now, tz=c.tz), google=conn, now=c.now)
    await svc.set_on(UID, True)
    counts = await GrocerySpendJob(svc, owners=c.owners, reads=None).run([])
    assert counts["skipped"] == 1 and box.requests == []


async def test_receipts_are_off_until_he_switches_them_on() -> None:
    svc, job, box, _, _ = await _rig(on=False)
    assert (await job.run([]))["off"] == 1 and box.requests == []
    assert (await svc.month(UID, None))["message"] == OFF_LINE


async def test_without_a_keyring_nothing_is_read_or_kept() -> None:
    svc, job, box, docs, _ = await _rig(sealed=False)
    assert (await job.run([]))["off"] == 1 and box.requests == [] and docs.sets == 0
    assert "token key" in (await svc.month(UID, None))["message"]


async def test_a_gmail_failure_counts_as_failed_and_keeps_what_was_there() -> None:
    svc, job, box, _, _ = await _rig()
    await job.run([])
    box.fail_list = 500
    box.mails.clear()
    state = await svc.store.scan(UID)
    await svc.store.set_scan(UID, lambda s: s.model_copy(update={"seen": ()}))
    assert (await job.run([]))["failed"] == 1
    assert {m["month"] for m in await svc.totals(UID)} == {"2026-10", "2026-11"}
    assert state.on is True


async def test_the_month_answer_is_a_fixed_template() -> None:
    svc, job, _, _, _ = await _rig()
    await job.run([])
    out = await svc.month(UID, "2026-11")
    assert out["message"] == (
        "Groceries in November 2026: about ₹2,140.50 from 4 orders "
        "(from your e-mailed receipts: BigBasket, Blinkit, Swiggy Instamart)."
    )
    empty = await svc.month(UID, "2026-09")
    assert empty["message"] == "No grocery receipts found for September 2026, Sir."
    with pytest.raises(ValueError):
        await svc.month(UID, "2026-13")


async def test_every_page_is_read_and_only_then_the_last_scan_moves() -> None:  # code M1
    svc, job, box, _, _ = await _rig(box=MailBox(ALL, page=3))
    await job.run([])
    assert box.lists() == 4 and box.reads() == len(ALL)
    assert await _months(svc) == WANT
    assert (await svc.store.scan(UID)).last_at is not None


def _read_log(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    rec = [r for r in caplog.records if r.getMessage() == "grocery receipts read"][-1]
    return {
        k: getattr(rec, k) for k in ("mails", "read", "orders", "ignored", "flagged", "complete")
    }


async def test_out_of_time_while_listing_keeps_the_last_scan_and_the_next_run_finishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    clock = Ticker()

    def slow(request: httpx.Request) -> None:
        if request.url.path == GMAIL and request.url.params.get("pageToken"):
            clock.t += 60  # the second page arrives after the budget

    box = MailBox(ALL, page=4, on_request=slow)
    svc, job, _, _, c = await _rig(box=box, clock=clock)
    await job.run([])
    assert box.lists() == 2 and box.reads() == 0  # out of time after the second page
    assert (await svc.store.scan(UID)).last_at is None  # the window wasn't covered
    assert not _read_log(caplog)["complete"]  # the counts go to the log (I1), not the audit
    box.on_request = None
    await job.run([])
    assert await _months(svc) == WANT and (await svc.store.scan(UID)).last_at is not None


async def test_out_of_time_while_reading_continues_on_the_next_run_without_counting_twice() -> None:
    clock = Ticker()

    def slow(request: httpx.Request) -> None:
        if request.url.path.startswith(GMAIL + "/"):
            clock.t += 4  # every read takes 4 s of the 11 s budget

    box = MailBox(ALL, on_request=slow)
    svc, job, _, _, _ = await _rig(box=box, clock=clock)
    await job.run([])
    first = box.reads()
    assert 0 < first < len(ALL) and (await svc.store.scan(UID)).last_at is None
    box.on_request = None
    await job.run([])
    assert box.reads() == len(ALL)  # the rest, once each
    assert await _months(svc) == WANT and (await svc.store.scan(UID)).last_at is not None


async def test_a_mail_that_failed_to_read_is_read_next_time_and_keeps_the_last_scan() -> None:
    box = MailBox(ALL, fail_read={"d_receipt_blinkit_nov"})
    svc, job, _, _, _ = await _rig(box=box)
    await job.run([])
    assert (await svc.store.scan(UID)).last_at is None
    assert (await _months(svc))["2026-11"] == "₹1,684.50"  # without Blinkit's ₹456
    box.fail_read.clear()
    await job.run([])
    assert await _months(svc) == WANT and (await svc.store.scan(UID)).last_at is not None


async def test_a_restart_counts_nothing_twice() -> None:  # code M5
    _, job, box, docs, c = await _rig()
    await job.run([])
    svc2, job2 = _service(docs, c, Ticker())  # a new process over the same documents
    await job2.run([])
    assert await _months(svc2) == WANT
    await svc2.store.set_scan(UID, lambda s: s.model_copy(update={"seen": ()}))  # lost hashes
    await job2.run([])
    assert await _months(svc2) == WANT


async def test_a_receipt_just_after_midnight_in_his_zone_counts_in_his_month() -> None:
    svc, job, _, _, _ = await _rig(("d_receipt_blinkit_month_edge.eml",))
    await job.run([])
    assert await _months(svc) == {"2026-11": "₹120"}


async def test_a_total_too_large_for_groceries_is_flagged_not_added(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    svc, job, _, _, c = await _rig(("d_receipt_bigbasket_bulk.eml", "d_receipt_blinkit_nov.eml"))
    await job.run([])
    out = await svc.month(UID, "2026-11")
    assert out["total"] == "₹456" and out["flagged"] == 1
    assert "1 receipt over ₹25,000 wasn't counted" in out["message"]
    assert _read_log(caplog)["flagged"] == 1
