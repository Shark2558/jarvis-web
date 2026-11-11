# tests/test_r11_a_part.py -- R11 Part A's plug-in against I0's contract (D2, D16, D17):
# `build(ctx)` passes `r11_wiring.check_part` (only Part A's tool families, job names and privacy
# ids), its R3 tools are exactly the two the plan names, the privacy rows list, export and delete,
# the brief gives at most 3 fixed lines, and No-AI mode runs a phrase end to end through the
# gateway with no model anywhere.
from __future__ import annotations

import json
from datetime import date
from zoneinfo import ZoneInfo

from r11_fakes import UID, Clock
from r11_fakes_a import (
    FAKE_UPI,
    FakePeople,
    at,
    connector,
    every_text,
    gateway_rig,
    person,
    today_ctx,
)

from jarvis.api.r11_wiring import check_part
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.kinds import CLOCK_JOBS, PRIVACY_IDS
from jarvis.helpers.today import part as today_part
from jarvis.helpers.today.part import READY_NO_KEY
from jarvis.offline.no_ai import run_no_ai

IST = ZoneInfo("Asia/Kolkata")


def test_the_part_keeps_to_its_names() -> None:
    c, _, _, _ = today_ctx()
    part = check_part("today", today_part.build(c))
    assert {j.name for j in part.clock_jobs} == set(CLOCK_JOBS["today"])
    assert {p.id for p in part.privacy} == set(PRIVACY_IDS["today"])
    assert part.daily_jobs == ()
    r3 = {t.name for t in part.tools if t.risk is ActionRisk.IRREVERSIBLE}
    assert r3 == {"bill_pay_prepare", "bill_payee_set"}
    assert {t.name for t in part.tools} == {
        "bill_list",
        "bill_add",
        "bill_paid",
        "bill_payee_set",
        "bill_pay_prepare",
        "focus_now",
        "pending_list",
        "contacts_birthdays",
    }
    assert len(part.brief) == 1 and part.phrases


def test_without_a_keyring_it_says_bills_are_off() -> None:
    c, _, _, _ = today_ctx(keys=False)
    assert today_part.build(c).ready == READY_NO_KEY


async def test_privacy_rows_list_export_and_delete() -> None:
    clock = Clock(at(2026, 11, 10, 9, 0))
    c, _, docs, _ = today_ctx(clock=clock)
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)
    await part.clock_jobs[0].run(())  # one reminder sent: one claim
    rows = {p.id: p for p in part.privacy}
    view = await rows["helpers_bills"].describe(UID)
    assert view.count == 1 and view.delete == "passkey" and view.encrypted_by_jarvis
    exported = await rows["helpers_bills"].export(UID)
    assert exported is not None and exported["bills"][0]["upi_id"] == FAKE_UPI
    assert exported["bills"][0]["amount"] == "₹1,240" and len(exported["reminders_sent_at"]) == 1
    assert "upi://" not in json.dumps(exported)
    assert await rows["helpers_bills"].delete(UID) == 2
    assert "Electricity" not in every_text(docs) and "bills_told" not in every_text(docs)
    bday = await rows["helpers_birthdays"].describe(UID)
    assert bday.count == 0 and bday.delete == "none"  # nothing to delete


async def test_the_brief_gives_at_most_three_fixed_lines() -> None:
    clock = Clock(at(2026, 11, 12, 7, 0))
    fake = FakePeople([person("c1", "Asha Example", 11, 12, 1988)])
    c, _, _, _ = today_ctx(clock=clock, google=await connector(fake))
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", upi=FAKE_UPI, amount="1240", day=13)
    await svc.add(UID, label="Water", amount="300", day=12)
    await svc.add(UID, label="Gas", amount="900", day=13)
    await svc.set_prefs(UID, birthdays_on=True)
    lines = await part.brief[0].lines(UID, IST, date(2026, 11, 12))
    assert lines == [
        "Bills: Water ₹300 due today; Electricity ₹1,240 due tomorrow and 1 more",
        "Birthdays today: Asha Example",
    ]
    assert all("1988" not in x for x in lines)


async def test_no_ai_runs_a_phrase_through_the_gateway() -> None:
    c, _, _, _ = today_ctx()
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)
    rig = gateway_rig(part)
    now = c.now().astimezone(IST)
    got = await run_no_ai(
        rig.gateway, "pay the electricity bill", now, scope=rig.scope, extra=part.phrases
    )
    assert got.tool_calls == 1 and len(got.pending) == 1  # the R3 card, no model anywhere
    assert "₹1,240.00 to Power Co (test@okfake)" in got.pending[0].summary
    focus = await run_no_ai(
        rig.gateway, "what's my top priority?", now, scope=rig.scope, extra=part.phrases
    )
    assert focus.reply.startswith("Top priority now, Sir: Electricity ₹1,240")
    listed = await run_no_ai(rig.gateway, "show my bills", now, scope=rig.scope, extra=part.phrases)
    assert listed.reply == "1 bill kept, Sir."
