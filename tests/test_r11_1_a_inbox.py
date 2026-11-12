# tests/test_r11_1_a_inbox.py -- R11.1 Part A, O12 (plan D20): the whole inbox. The unread count
# is the INBOX label's own; every category is read, grouped, within a fixed number of reads; a
# one-time code or a bank message is withheld; the tool and the brief's background read obey the
# "Search and read email" row ("Never" means no read at all).
from __future__ import annotations

import json
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r11_1_fakes_a import GM, UID, PlanGoogle, connector, letter

from jarvis.brief import collect
from jarvis.brief.collect import INBOX_QUERY, Collector
from jarvis.brief.models import BriefData, InboxItem, InboxSection
from jarvis.brief.render import render_text
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools import gmail_digest as gd
from jarvis.tools.audit import AuditLog
from jarvis.tools.background import BackgroundReads
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 12)
SCOPE = f"{UID}:sess_1"
CODE = "482913"


def inbox() -> list[dict[str, Any]]:
    """Ten unread: two from people, three bills and orders, two other updates (one a code), two
    promotions and one social."""
    return [
        letter("m01", "Priya Menon <priya@example.com>", "Budget review on Friday"),
        letter("m02", "Arun <arun@example.org>", "Lunch?", snippet="Are you free at one"),
        letter(
            "m03", "Power Board <billing@power.example>", "Your bill is ready", category="UPDATES"
        ),
        letter("m04", "Shop <orders@shop.example>", "Your order has shipped", category="UPDATES"),
        letter(
            "m05", "Net <no-reply@net.example>", "Payment receipt for November", category="UPDATES"
        ),
        letter("m06", "Forum <news@forum.example>", "Weekly digest", category="UPDATES"),
        letter(
            "m07",
            "Bank <alerts@bank.example>",
            f"{CODE} is your one-time password",
            category="UPDATES",
            snippet=f"Use OTP {CODE} to sign in. Do not share it.",
        ),
        letter("m08", "Deals <deals@shop.example>", "50% off today", category="PROMOTIONS"),
        letter("m09", "Travel <offers@travel.example>", "Fly for less", category="PROMOTIONS"),
        letter(
            "m10", "Network <notify@social.example>", "You have a new follower", category="SOCIAL"
        ),
    ]


class Rig:
    def __init__(self, fake: PlanGoogle, conn: Any, *, effect: Effect | None = None) -> None:
        self.fake, self.conn = fake, conn
        reg = ToolRegistry()
        for t in gd.inbox_tools(lambda: conn, max_reads=30):
            reg.register(t)
        rules = [PolicyRule(tool_pattern="gmail_*", effect=effect)] if effect else []
        self.gw = Gateway(
            registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=AuditLog()
        )

    async def summary(self) -> Any:
        call = ToolCall(id="c", name=gd.SUMMARY_TOOL, arguments={})
        return await self.gw.execute(call, scope=SCOPE)


async def _rig(mails: list[dict[str, Any]] | None = None, **kw: Any) -> Rig:
    fake = PlanGoogle(mails=inbox() if mails is None else mails, unread=132)
    return Rig(fake, await connector(fake), **kw)


# ---- the tool ----------------------------------------------------------------------------------
async def test_the_count_is_the_label_s_and_every_category_is_counted() -> None:
    rig = await _rig()
    out = await rig.summary()
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    res = out.result
    assert res["unread"] == 132  # Gmail's own number, not an estimate of one tab
    assert res["read"] == 10
    groups = res["groups"]
    assert {k: g["unread"] for k, g in groups.items()} == {
        "people": 2,
        "bills": 3,
        "updates": 1,
        "promotions": 2,
        "social": 1,
    }
    assert [g["label"] for g in groups.values()] == [
        "People",
        "Bills and orders",
        "Updates",
        "Promotions",
        "Social and forums",
    ]
    assert len(groups["people"]["items"]) == 2 and len(groups["bills"]["items"]) == 3
    assert "items" not in groups["promotions"] and "items" not in groups["social"]  # count only
    first = groups["people"]["items"][0]
    assert "Priya Menon" in first["from"] and "Budget review" in first["subject"]
    assert first["from"].startswith("<<EXTERNAL CONTENT")  # other people's words: fenced
    assert out.trusted is False


async def test_a_one_time_code_is_withheld_and_never_reaches_the_model() -> None:
    out = await (await _rig()).summary()
    res = out.result
    assert res["withheld"] == 1 and "code or bank" in res["withheld_note"]
    said = json.dumps(res) + out.for_model()
    assert CODE not in said and "one-time password" not in said and "bank.example" not in said


async def test_what_is_kept_is_masked_for_the_ear() -> None:
    mails = [
        letter(
            "m1",
            "Shop <orders@shop.example>",
            "Order 99812734 total Rs. 4,999 see https://shop.example/track",
            category="UPDATES",
        )
    ]
    res = (await (await _rig(mails)).summary()).result
    said = json.dumps(res)
    assert "99812734" not in said and "4,999" not in said and "https://" not in said
    assert "orders@shop.example" not in said  # a bare address is never repeated


async def test_the_reads_are_bounded_and_the_query_is_the_whole_inbox() -> None:
    many = [letter(f"m{i:03d}", f"S{i} <s{i}@example.com>", f"Subject {i}") for i in range(100)]
    rig = await _rig(many)
    res = (await rig.summary()).result
    reads = rig.fake.gmail_reads()
    assert len(reads) <= 32  # the label, one listing, at most thirty messages
    assert res["read"] == 30 and res["unread"] == 132
    assert "30 most recent" in res["note"]
    listing = next(r for r in reads if r.url.path == f"{GM}/messages")
    assert listing.url.params["q"] == gd.INBOX_QUERY == "is:unread in:inbox newer_than:7d"
    assert "category" not in listing.url.params["q"] and listing.url.params["maxResults"] == "30"
    assert all(r.method == "GET" for r in reads)
    metas = [r for r in reads if r.url.path.startswith(f"{GM}/messages/")]
    assert all(r.url.params["format"] == "metadata" for r in metas)  # never a body


async def test_never_on_the_mail_row_means_no_read_at_all() -> None:
    rig = await _rig(effect=Effect.DENY)
    out = await rig.summary()
    assert out.outcome is GatewayOutcome.DENIED and rig.fake.gmail_reads() == []


async def test_an_empty_inbox_and_a_missing_link_are_said_plainly() -> None:
    fake = PlanGoogle(mails=[], unread=0)
    res = (await Rig(fake, await connector(fake)).summary()).result
    assert res["unread"] == 0 and res["note"] == "No unread mail in your inbox, Sir."
    off = Rig(PlanGoogle(), None)
    out = await off.summary()
    assert out.result["unavailable"] is True and "Google is not linked" in out.result["message"]


async def test_when_the_label_cannot_be_read_the_count_says_so() -> None:
    rig = await _rig()
    rig.fake.fail[f"GET {GM}/labels/INBOX"] = 403
    res = (await rig.summary()).result
    assert res["unread"] is None and res["read"] == 10
    assert "exact count" in res["note"]


@pytest.mark.parametrize(
    ("sender", "subject", "want"),
    [
        ("Power Board <billing@power.example>", "Your bill is ready", "bills"),
        ("Shop <auto-confirm@shop.example>", "Your order has shipped", "bills"),
        ("Clinic <hello@clinic.example>", "Invoice 12 attached", "bills"),
        ("Forum <news@forum.example>", "Weekly digest", "updates"),
        ("Dev <notifications@code.example>", "Build finished", "updates"),
    ],
)
def test_bills_and_orders_are_a_fixed_check_on_the_sender_and_subject(
    sender: str, subject: str, want: str
) -> None:
    m = letter("m", sender, subject, category="UPDATES")
    assert gd.read_letter(m).group == want


def test_the_category_decides_the_group() -> None:
    assert gd.read_letter(
        letter("a", "A <a@example.com>", "Bill", category="PROMOTIONS")
    ).group == ("promotions")
    assert (
        gd.read_letter(letter("a", "A <a@example.com>", "x", category="FORUMS")).group == "social"
    )
    plain = letter("a", "A <a@example.com>", "x")
    plain["labelIds"] = ["UNREAD", "INBOX"]  # an account without tabs
    assert gd.read_letter(plain).group == "people"


# ---- the brief ---------------------------------------------------------------------------------
async def _collect(fake: PlanGoogle, **kw: Any) -> Any:
    return await Collector(await connector(fake), None, **kw).collect(UID, IST, DAY)


async def test_the_brief_counts_the_whole_inbox_and_lists_people_first() -> None:
    fake = PlanGoogle(mails=list(reversed(inbox())), unread=132)
    got = await _collect(fake)
    box = got.data.inbox
    assert got.data.sections_status.inbox == "ok" and box.total == 132
    subjects = [i.subject for i in box.items]
    assert subjects[:2] == ["Lunch?", "Budget review on Friday"]  # people before bills
    assert "Your bill is ready" in subjects and "Weekly digest" in subjects
    assert "50% off today" not in subjects and "You have a new follower" not in subjects
    assert not any(CODE in s for s in subjects)  # the code is not on the brief
    assert len(got.snippets) == len(box.items) and not any(CODE in s for s in got.snippets)
    listing = next(r for r in fake.gmail_reads() if r.url.path == f"{GM}/messages")
    assert listing.url.params["q"] == INBOX_QUERY == gd.INBOX_QUERY
    assert len(fake.gmail_reads()) <= 32


async def test_the_groups_are_read_once_and_light_up_a_wider_inbox_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = PlanGoogle(mails=inbox(), unread=132)
    read = await gd.read_inbox(await connector(fake), UID, max_reads=30)
    assert read.unread == 132 and read.withheld == 1
    assert read.counts == {"people": 2, "bills": 3, "updates": 1, "promotions": 2, "social": 1}

    class Wider(InboxSection):  # what I1's InboxSection will hold (INTEGRATION-A.md, Needs I1)
        groups: tuple[dict[str, Any], ...] = ()
        withheld: int = 0
        exact: bool = False

    monkeypatch.setattr(collect, "InboxSection", Wider)
    got = await _collect(PlanGoogle(mails=inbox(), unread=132))
    box = got.data.inbox
    assert (box.withheld, box.exact) == (1, True)
    assert [(g["label"], g["unread"]) for g in box.groups] == [
        ("People", 2),
        ("Bills and orders", 3),
        ("Updates", 1),
        ("Promotions", 2),
        ("Social and forums", 1),
    ]
    text = render_text(got.data)
    assert "2 from people · 3 bills and orders · 1 update · 2 promotions · 1 social" in text
    assert "1 more looks like a code or a bank message: open it in Gmail." in text


def _gateway(conn: Any, effect: Effect | None) -> Gateway:
    reg = ToolRegistry()
    for t in gd.inbox_tools(lambda: conn, max_reads=30):
        reg.register(t)
    rules = [PolicyRule(tool_pattern="gmail_*", effect=effect, source="owner")] if effect else []

    class Rows:
        async def rules_for(self, user_id: str) -> list[PolicyRule]:
            return rules

    return Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=Rows()
    )


@pytest.mark.parametrize("effect", [Effect.DENY, Effect.ASK])
async def test_the_brief_s_background_read_obeys_the_mail_row(effect: Effect) -> None:
    fake = PlanGoogle(mails=inbox(), unread=132)
    conn = await connector(fake)
    gw = _gateway(conn, effect)
    got = await Collector(conn, None, reads=BackgroundReads.of(gw)).collect(UID, IST, DAY)
    assert fake.gmail_reads() == []  # nobody is there to ask at 07:00: no read
    assert got.data.sections_status.inbox == "unavailable" and got.data.inbox.items == ()
    assert got.data.sections_status.calendar == "ok"  # the other sections are untouched
    last = (await gw.audit.tail(5)).entries[-1]
    assert (last.agent, last.tool, last.outcome) == ("helpers", gd.SUMMARY_TOOL, "denied")
    assert last.detail.startswith("brief")


async def test_an_allowed_background_read_leaves_one_kind_only_audit_line() -> None:
    fake = PlanGoogle(mails=inbox(), unread=132)
    conn = await connector(fake)
    gw = _gateway(conn, Effect.ALLOW)
    got = await Collector(conn, None, reads=BackgroundReads.of(gw)).collect(UID, IST, DAY)
    assert got.data.inbox.total == 132
    lines = [e for e in (await gw.audit.tail(10)).entries if e.agent == "helpers"]
    assert [(e.tool, e.outcome, e.detail) for e in lines] == [
        (gd.SUMMARY_TOOL, "executed", "brief")
    ]


def _brief(total: int, items: tuple[InboxItem, ...] = ()) -> BriefData:
    return BriefData(
        date="2026-11-12", tz="Asia/Kolkata", inbox=InboxSection(total=total, items=items)
    )


def test_the_brief_text_says_the_whole_count() -> None:
    item = InboxItem(
        from_name="Priya Menon",
        from_address="priya@example.com",
        subject="Budget review",
        date="",
        when="07:42",
    )
    text = render_text(_brief(132, (item,)))
    assert "INBOX · 132 unread (showing 1)" in text and "in the last day" not in text
    assert "No unread mail in your inbox." in render_text(_brief(0))
    only_ads = render_text(_brief(40))
    assert "INBOX · 40 unread" in only_ads
    assert "None of them is from a person, a bill or an update of the last 7 days." in only_ads


# ---- reads that failed are counted and said (silent-failure review H2) -------------------------
async def test_messages_that_could_not_be_read_are_counted_and_said(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = await _rig()
    for mid in ("m01", "m02", "m03"):
        rig.fake.fail[f"GET {GM}/messages/{mid}"] = 500
    res = (await rig.summary()).result
    assert res["read"] == 7 and res["failed"] == 3 and res["unread"] == 132
    assert "couldn't read 3 of the 10 newest unread messages just now" in res["note"]
    logged = [r for r in caplog.records if "could not be read" in r.getMessage()]
    assert logged and "Budget review" not in caplog.text and "priya" not in caplog.text


async def test_when_every_read_failed_the_tool_never_says_the_inbox_is_quiet() -> None:
    rig = await _rig()
    for m in inbox():
        rig.fake.fail[f"GET {GM}/messages/{m['id']}"] = 503
    res = (await rig.summary()).result
    assert res["read"] == 0 and res["failed"] == 10
    assert "couldn't read any of the 10 newest unread messages just now" in res["note"]
    assert "No unread mail" not in res["note"]


async def test_an_unread_count_that_could_not_be_read_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = await _rig()
    rig.fake.fail[f"GET {GM}/labels/INBOX"] = 500
    await rig.summary()
    assert any("unread count could not be read" in r.getMessage() for r in caplog.records)


class Widest(InboxSection):  # I1's InboxSection (INTEGRATION-A.md 3.4, a merge gate)
    groups: tuple[dict[str, Any], ...] = ()
    withheld: int = 0
    exact: bool = True
    failed: int = 0
    listed: int = 0


async def test_when_no_message_could_be_read_the_brief_never_says_none_is_from_a_person() -> None:
    """On today's model (before INTEGRATION-A 3.4) the section says the inbox could not be read;
    with I1's fields it says "I couldn't read any of the 10". Never "none of them is from a
    person"."""
    reads_down = PlanGoogle(mails=inbox(), unread=132)
    for m in inbox():
        reads_down.fail[f"GET {GM}/messages/{m['id']}"] = 503
    got = await _collect(reads_down)
    text = render_text(got.data)
    assert "None of them is from a person" not in text
    if "failed" in InboxSection.model_fields:  # I1 has widened the brief's inbox section
        assert "I couldn't read any of the 10 newest unread messages just now." in text
    else:
        assert got.data.sections_status.inbox == "unavailable" and "could not be read" in text


async def test_the_brief_says_about_n_when_gmail_s_count_could_not_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collect, "InboxSection", Widest)
    fake = PlanGoogle(mails=inbox(), unread=132)
    fake.fail[f"GET {GM}/labels/INBOX"] = 500
    got = await _collect(fake)
    assert got.data.inbox.exact is False
    text = render_text(got.data)
    assert "INBOX · about 10 unread" in text and "INBOX · 10 unread" not in text
    assert "Gmail didn't give its own count just now: the number is an estimate." in text
    assert "could not be read" not in text  # that wording is the brief's for a failed section


async def test_the_brief_says_how_many_it_could_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect, "InboxSection", Widest)
    some = PlanGoogle(mails=inbox(), unread=132)
    for mid in ("m01", "m02"):
        some.fail[f"GET {GM}/messages/{mid}"] = 500
    text = render_text((await _collect(some)).data)
    assert "INBOX · 132 unread" in text
    assert "I couldn't read 2 of the 10 newest unread messages just now." in text
    every = PlanGoogle(mails=inbox(), unread=132)
    for m in inbox():
        every.fail[f"GET {GM}/messages/{m['id']}"] = 500
    text = render_text((await _collect(every)).data)
    assert "I couldn't read any of the 10 newest unread messages just now." in text
    assert "None of them is from a person" not in text


# ---- codes and bank mail are withheld in every category (security review MEDIUM-2) -------------
async def test_a_code_in_primary_is_withheld_on_the_brief_and_never_reaches_the_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collect, "InboxSection", Widest)
    mails = [
        *inbox(),
        letter(
            "m11",
            "Asha <asha@example.com>",
            "Your login code",
            snippet=f"Your code is {CODE}. It expires in 10 minutes.",
        ),
    ]
    got = await _collect(PlanGoogle(mails=mails, unread=133))
    box = got.data.inbox
    assert box.withheld == 2  # the code in Primary and the one in Updates: counted
    assert "Your login code" not in [i.subject for i in box.items]
    assert not any(CODE in s or "login code" in s for s in got.snippets)
    assert [g["unread"] for g in box.groups if g["key"] == "people"] == [2]
    text = render_text(got.data)
    assert "2 more look like codes or bank messages: open them in Gmail." in text
    assert CODE not in text
