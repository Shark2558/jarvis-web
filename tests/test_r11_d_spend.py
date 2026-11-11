# tests/test_r11_d_spend.py -- R11 Part D (plan D15, item 15): grocery spend a month from his
# e-mailed receipts. The daily `grocery_spend` job reads Gmail like the parcels reader, obeys his
# permission rows (fail closed), keeps totals per month only (sealed, purpose `spend`), never a
# card number, and audits a kind-only line.
from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from r11_fakes import UID
from r11_fakes_d import CARD_DIGITS, MailBox, Rules, connector, kctx

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


async def _rig(
    names: tuple[str, ...] = ALL, *, on: bool = True, rules: Rules | None = None, **kw: Any
) -> tuple[SpendService, GrocerySpendJob, MailBox, Any, Any]:
    box = MailBox(names)
    conn = await connector(box.client())
    c, _, docs, _ = kctx(google=conn, rules=rules or Rules(effect=None), **kw)
    store = SpendStore(docs, c.keyring, now=c.now, tz=c.tz)
    svc = SpendService(store, google=c.google, now=c.now, tz=c.tz)
    if on and c.keyring is not None:
        await svc.set_on(UID, True)
    job = GrocerySpendJob(svc, owners=c.owners, permissions=c.permissions, audit=c.audit)
    return svc, job, box, docs, c


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
    assert (entry.agent, entry.tool, entry.outcome) == ("helpers", "grocery_spend", "executed")
    assert entry.detail.startswith("mails=") and "₹" not in entry.detail


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


async def test_without_permission_rows_wired_the_job_fails_closed() -> None:
    box = MailBox(ALL)
    conn = await connector(box.client())
    c, _, docs, _ = kctx(google=conn)
    svc = SpendService(SpendStore(docs, c.keyring, now=c.now, tz=c.tz), google=conn, now=c.now)
    await svc.set_on(UID, True)
    counts = await GrocerySpendJob(
        svc, owners=c.owners, permissions=c.permissions, audit=c.audit
    ).run([])
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
