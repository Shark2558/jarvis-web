# tests/test_r11_i1_paused.py -- R11 integrated review M2: a helper his permission rows pause says
# so. A morning job reads on "Allow" only (jarvis.tools.background); when one he switched on can't
# read because of a row, he sees ONE fixed-template line (jarvis.helpers.paused), never anyone
# else's words: in that part's Helpers tab (GET /v1/helpers parts[].paused), in the brief (one
# line at most in all, folded across parts) and in breach_status. Each part's check is shown:
# on + "Ask first" = a line; off, or "Allow" = none; his to-dos say nothing on "Never".
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from r11_fakes import NO_ROWS, UID, Clock, ctx, reads_over

from jarvis.helpers.brief import MAX_SECTION_LINES, HelpersBrief
from jarvis.helpers.paused import Pause, PauseCheck, fold, lines, pause_of, row_word
from jarvis.tools.audit import AuditLog
from jarvis.tools.background import BackgroundReads, Verdict
from jarvis.tools.policy import Effect, PolicyRule

NOON = datetime(2026, 11, 12, 6, 30, tzinfo=UTC)
ASK_EMAIL = "Breach watching paused: your Email permission is set to Ask first."


class Rows:
    """His rows: `effect` on every tool matching `pattern`."""

    def __init__(self, pattern: str, effect: Effect) -> None:
        self.pattern, self.effect = pattern, effect

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern=self.pattern, effect=self.effect, source="owner:test")]


def _reads(rows: object) -> BackgroundReads:
    return reads_over(lambda: rows, AuditLog(), now=Clock(NOON))  # type: ignore[arg-type,return-value]


async def _on(uid: str) -> bool:
    return True


# ---- the lines ---------------------------------------------------------------------------------
def test_the_lines_are_fixed_templates_naming_the_row_by_its_section() -> None:
    assert row_word("gmail_search") == "Email" and row_word("contacts_birthdays") == "Contacts"
    assert row_word("tasks_list") == "To-do list" and row_word("breach_status") == (
        "Weather and alerts"
    )
    ask = pause_of("Breach watching", Verdict("ask_first", "gmail_search", "ask first"))
    assert ask is not None and ask.line == (f"{ASK_EMAIL} Set it to Allow to let it run by itself.")
    never = pause_of("Grocery spend", Verdict("denied", "spend_month", "never"))
    assert never is not None
    assert never.line == "Grocery spend paused: your Kitchen permission is set to Never."
    gone = pause_of("Birthdays", Verdict("unreadable", "", "permissions unreadable"))
    assert gone is not None and gone.line == (
        "Birthdays paused: JARVIS couldn't read your permissions just now."
    )
    assert pause_of("Birthdays", Verdict("allowed")) is None


def test_the_brief_folds_every_pause_into_one_line() -> None:
    a = Pause("Breach watching", "Email", "ask_first")
    b = Pause("Grocery spend", "Email", "ask_first")
    c = Pause("Birthdays", "Contacts", "denied")
    assert fold([]) is None and fold([a]) == a.line
    assert fold([a, b, c]) == (
        "Paused: 3 helpers wait on your permissions (Email, Contacts); see Helpers."
    )


async def test_a_check_speaks_only_when_the_helper_is_on_and_a_row_stops_it() -> None:
    async def off(uid: str) -> bool:
        return False

    async def broken(uid: str) -> bool:
        raise RuntimeError("the switch can't be read")

    ask = _reads(Rows("gmail_*", Effect.ASK))
    tools = ("gmail_search", "breach_status")
    assert await PauseCheck(ask, what="Breach watching", tools=tools, on=off).pause(UID) is None
    assert await PauseCheck(ask, what="Breach watching", tools=tools, on=broken).pause(UID) is None
    allowed = PauseCheck(_reads(NO_ROWS), what="Breach watching", tools=tools, on=_on)
    assert await allowed.pause(UID) is None
    got = await PauseCheck(ask, what="Breach watching", tools=tools, on=_on).pause(UID)
    assert got is not None and got.line.startswith(ASK_EMAIL)
    unwired = await PauseCheck(None, what="Birthdays", tools=("contacts_birthdays",), on=_on).pause(
        UID
    )
    assert unwired is not None and unwired.reason == "unreadable"
    no_service = PauseCheck(_reads(None), what="Birthdays", tools=("contacts_birthdays",), on=_on)
    assert (await no_service.pause(UID)) == unwired  # no permission service: unreadable too


async def test_a_status_check_writes_no_audit_line() -> None:
    audit = AuditLog()
    reads = reads_over(lambda: Rows("gmail_*", Effect.ASK), audit)  # type: ignore[arg-type,return-value]
    check = PauseCheck(reads, what="Breach watching", tools=("gmail_search",), on=_on)
    for _ in range(3):
        assert await check.pause(UID) is not None
    assert (await audit.tail(10)).entries == []  # the morning job's own refusal is the line


# ---- each part's check -------------------------------------------------------------------------
async def test_part_a_birthdays_he_switched_on_and_his_todos_on_ask_first() -> None:
    from r11_fakes_a import FakePeople, connector, today_ctx

    from jarvis.helpers.today import part as today_part

    google = await connector(FakePeople())
    c, _, _, _ = today_ctx(google=google, rules=Rows("contacts_*", Effect.ASK))
    part = today_part.build(c)
    assert await lines(part.paused, UID) == []  # birthdays off; the to-do row is Allow
    await part.services["bills"].set_prefs(UID, birthdays_on=True)
    (line,) = await lines(part.paused, UID)
    assert line.startswith("Birthdays paused: your Contacts permission is set to Ask first.")
    c2, _, _, _ = today_ctx(google=google, rules=Rows("tasks_*", Effect.ASK))
    (todo,) = await lines(today_part.build(c2).paused, UID)
    assert todo.startswith("To-dos in your top priority paused: your To-do list permission")
    c3, _, _, _ = today_ctx(google=google, rules=Rows("tasks_*", Effect.DENY))
    assert await lines(today_part.build(c3).paused, UID) == []  # his own "don't read my to-dos"
    unlinked, _, _, _ = today_ctx(rules=Rows("*", Effect.ASK))
    assert today_part.build(unlinked).paused == ()  # no Google: nothing reads at all


async def test_part_a_todays_tab_points_at_the_paused_line() -> None:
    from r11_fakes_a import FakePeople, connector, today_ctx

    from jarvis.helpers.today import part as today_part
    from jarvis.helpers.today.views import SEE_ABOVE, today_view

    c, _, _, _ = today_ctx(
        google=await connector(FakePeople()), rules=Rows("contacts_*", Effect.ASK)
    )
    part = today_part.build(c)
    await part.services["bills"].set_prefs(UID, birthdays_on=True)
    view = await today_view(part.services, UID, NOON)
    assert view["birthdays"]["state"] == "denied" and view["birthdays"]["note"] == SEE_ABOVE


async def test_part_b_breach_watching_and_breach_status_say_it_is_paused() -> None:
    from r11_fakes_b import gmail_with, house_ctx

    from jarvis.helpers.house import part as house_part
    from jarvis.tools.context import tool_context

    hc, _, _, _ = house_ctx(google=gmail_with("b_gmail_hibp.json"))
    hc = replace(hc, reads=_reads(Rows("gmail_*", Effect.ASK)))
    part = house_part.build(hc)
    svc = part.services["house"]
    assert await lines(part.paused, UID) == []  # not switched on yet
    await svc.outside.change(UID, lambda o: o.model_copy(update={"breach_on": True}))
    (line,) = await lines(part.paused, UID)
    assert line.startswith(ASK_EMAIL)
    tool = next(t for t in part.tools if t.name == "breach_status")
    with tool_context(f"{UID}:s1"):
        got = await tool.run({})
    assert got["paused"] == line and got["on"] is True
    hc2 = replace(hc, reads=_reads(NO_ROWS))
    with tool_context(f"{UID}:s1"):
        fine = await next(t for t in house_part.build(hc2).tools if t.name == "breach_status").run(
            {}
        )
    assert "paused" not in fine


async def test_part_c_calendar_nudges_he_switched_on() -> None:
    from r11_fakes_c import part as nudges_rig

    from jarvis.helpers.nudges import part as nudges_part
    from jarvis.helpers.nudges import standup

    rig = nudges_rig()
    c = replace(rig.ctx, reads=_reads(Rows("calendar_*", Effect.ASK)))
    built = nudges_part.build(c, calendar=rig.calendar, rain=rig.rain)
    assert await lines(built.paused, UID) == []  # no calendar nudge on
    svc = built.services["service"]
    await svc.store.change(UID, lambda s: s.changed(standup.KIND, {"meeting": True}))
    (line,) = await lines(built.paused, UID)
    assert line.startswith("Calendar nudges paused: your Calendar permission is set to Ask first.")


async def test_part_d_grocery_spend_he_switched_on() -> None:
    from r11_fakes_d import MailBox, connector, kctx

    from jarvis.helpers.kitchen import part as kitchen_part

    conn = await connector(MailBox(("d_receipt_blinkit_nov.eml",)).client())
    c, _, _, _ = kctx(google=conn, rules=None)
    c = replace(c, reads=_reads(Rows("spend_*", Effect.DENY)))
    built = kitchen_part.build(c)
    assert await lines(built.paused, UID) == []
    await built.services["kitchen"].spend.set_on(UID, True)
    assert await lines(built.paused, UID) == [
        "Grocery spend paused: your Kitchen permission is set to Never."
    ]


# ---- the surfaces ------------------------------------------------------------------------------
class Fixed:
    def __init__(self, pause: Pause | None) -> None:
        self._pause = pause

    async def pause(self, uid: str) -> Pause | None:
        return self._pause


class Lines:
    name = "x"

    def __init__(self, n: int) -> None:
        self.n = n

    async def lines(self, uid: str, tz: Any, day: date) -> list[str]:
        return [f"Line {i}" for i in range(self.n)][:3]


async def test_the_brief_holds_one_paused_line_last_and_keeps_its_room() -> None:
    a = Pause("Breach watching", "Email", "ask_first")
    b = Pause("Birthdays", "Contacts", "denied")
    many = [Lines(3), Lines(3), Lines(3)]
    brief = HelpersBrief(lambda: many, pauses=lambda: [Fixed(a), Fixed(None), Fixed(b)])
    got = await brief.section(UID, UTC, date(2026, 11, 12))
    assert got is not None and len(got.lines) == MAX_SECTION_LINES
    assert (
        got.lines[-1]
        == "Paused: 2 helpers wait on your permissions (Email, Contacts); see Helpers."
    )
    assert sum(1 for x in got.lines if "aused" in x) == 1
    only = HelpersBrief(lambda: [], pauses=lambda: [Fixed(a)])
    alone = await only.section(UID, UTC, date(2026, 11, 12))
    assert alone is not None and alone.lines == (a.line,)
    quiet = HelpersBrief(lambda: [], pauses=lambda: [Fixed(None)])
    assert await quiet.section(UID, UTC, date(2026, 11, 12)) is None


async def test_get_helpers_carries_each_parts_paused_lines(settings: Any) -> None:
    from httpx import ASGITransport, AsyncClient

    from jarvis.api import create_app
    from jarvis.helpers.ports import HelperPart
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.memory.inmemory import InMemorySessionStore

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    pause = Pause("Breach watching", "Email", "ask_first")
    async with app.router.lifespan_context(app):
        app.state.r11_parts["house"] = HelperPart(name="house", paused=(Fixed(pause),))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/v1/helpers")
    assert r.status_code == 200, r.text
    by = {p["name"]: p["paused"] for p in r.json()["parts"]}
    assert by == {"today": [], "house": [pause.line], "nudges": [], "kitchen": []}


def test_the_fake_context_has_a_permission_service() -> None:
    c, _, _, _ = ctx("today")
    assert isinstance(c.reads, BackgroundReads)
