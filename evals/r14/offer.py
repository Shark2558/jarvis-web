# evals/r14/offer.py
"""R14 eval, Part C's suite (`offer`, docs/plans/r14-hardening.md "Per item" C): the turn's tools,
the window, the ledger and the history cache point, on fakes (no model, no network, ₹0).

- recall: 120 labelled messages, each with the tool it needs; a fresh offer per message (no
  sticky set, no history) over the fullest registry the fakes build; the needed tool is offered
  for >= 98 % of them;
- size: the average message is offered <= 30 tools;
- rounds: the set is the same in every round of a turn; `skills_open(skill)` adds that skill;
- fail_safe: a tool the register can't file is offered; an offer that raises gives every tool;
- window: a long tool session stays within `session_max_chars` once results count;
- ledger: the month's sums equal the calls' counts; the parts add up to the cost; no text;
- hint: with `cache_history` the Anthropic request carries two cache breakpoints.

Negative control (three, each must fail its own case): the words table emptied (no sticky, no
history) -> recall < 98 %; the window counting only `content` (before R14) -> the long tool
session exceeds `session_max_chars`; the hint off -> one breakpoint.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from r14_fakes_c import legacy_window, marks, session_turns  # noqa: E402

from jarvis.billing.ledger import TokenLedgerStore  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.core.window import build_window, message_chars  # noqa: E402
from jarvis.llm.base import ChatMessage, Completion, Role, ToolCall, ToolSpec, Usage  # noqa: E402
from jarvis.skills.offer import SkillOffer  # noqa: E402
from jarvis.skills.ports import BrainSlots, LedgerCall, OfferContext  # noqa: E402
from jarvis.skills.registry import Catalogue, SkillRegister, load_catalogue  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402

PART = "offer"
BUILT = True
RECALL_BAR = 0.98
SIZE_BAR = 30.0
SECRET = "EVAL-PLANTED-WORD"

# (what he says, the tool it needs): written as he would ask, English and Hinglish, every skill
LABELLED: tuple[tuple[str, str], ...] = (
    ("What's on my calendar tomorrow?", "calendar_list_events"),
    ("Schedule a meeting with Ravi on Friday at 3 pm", "calendar_create_event"),
    ("Move my dentist appointment to next Tuesday", "calendar_update_event"),
    ("Cancel the team sync on Monday", "calendar_delete_event"),
    ("Am I free on Thursday afternoon?", "calendar_free_slots"),
    ("Find a free slot for a 1-hour call next week", "calendar_free_slots"),
    ("Block two hours for deep work every morning this week", "calendar_create_events"),
    ("Undo the events you just added", "calendar_undo_events"),
    ("Remind me to call the bank at 5", "reminder_add"),
    ("What reminders do I have today?", "reminders_list"),
    ("Push my gym reminder to 7 pm", "reminder_update"),
    ("kal subah 6 baje uthne ka yaad dila dena", "reminder_add"),
    ("Add 'renew car insurance' to my to-do list", "task_add"),
    ("What's on my to-do list?", "tasks_list"),
    ("Mark the passport photo task as done", "task_complete"),
    ("Delete the task about the plumber", "task_delete"),
    ("Add milk, eggs and bread to the shopping list", "grocery_add"),
    ("What's on my grocery list?", "grocery_list"),
    ("Remove onions from the grocery list", "grocery_remove"),
    ("doodh aur atta list mein daal do", "grocery_add"),
    ("What's on the family calendar this weekend?", "family_calendar_events"),
    ("When are my wife and I both free on Saturday?", "family_free_slots"),
    ("Add the kids' school sports day to the family calendar", "family_event_add"),
    ("What chores are due this week?", "chore_list"),
    ("Add a chore: clean the balcony every Sunday", "chore_add"),
    ("I finished the laundry", "chore_done"),
    ("When is the AC service due?", "maint_list"),
    ("Add water purifier filter change every 6 months", "maint_add"),
    ("The geyser was serviced today", "maint_done"),
    ("What upkeep items should I track for a new flat?", "maint_starters"),
    ("What did I delete recently?", "deleted_list"),
    ("Bring back the reminder I deleted", "deleted_restore"),
    ("What should I focus on right now?", "focus_now"),
    ("What's pending for me?", "pending_list"),
    ("pehle kya karu, bahut kaam hai", "focus_now"),
    ("Search the web for the best budget laptops in 2026", "web_search"),
    ("Read this article: https://example.com/post", "web_read"),
    ("What's the latest news on the monsoon?", "web_search"),
    ("Who won the cricket match yesterday?", "web_search"),
    ("Find a pharmacy near me", "maps_search"),
    ("How long will it take to drive to the airport?", "maps_route"),
    ("Best South Indian restaurants in Indiranagar", "maps_search"),
    ("Research Sundar Pichai's background", "research_person"),
    ("Open the profiles you found", "people_open_profiles"),
    ("Remember that my blood group is O positive", "memory_save"),
    ("What do you remember about my car?", "memory_search"),
    ("Forget what I told you about my old address", "memory_forget"),
    ("Make a note: the guest wifi password is on the fridge", "kb_add_note"),
    ("Save this link for later: https://example.com/guide", "kb_save_link"),
    ("Find my notes about the tax filing", "kb_search"),
    ("Update my note on the car service with the new mileage", "kb_update"),
    ("Summarise the PDF I uploaded", "doc_read"),
    ("Search my Drive for the rental agreement", "drive_search"),
    ("List the files in my Projects folder", "drive_list"),
    ("Search inside my documents for the warranty card", "doc_search"),
    ("What is this in the picture I sent?", "picture_research"),
    ("Will it rain today?", "weather_now"),
    ("Any cyclone warnings for my district?", "disaster_status"),
    ("mausam kaisa hai aaj?", "weather_now"),
    ("Where did I keep my passport?", "belongings_where"),
    ("I put the spare keys in the second drawer", "belongings_put"),
    ("List the things you're tracking for me", "belongings_list"),
    ("Where has my laptop charger been over time?", "belongings_history"),
    ("Show my vitals", "vitals_show"),
    ("Add my OpenAI key to vitals, it expires next March", "vitals_set_key"),
    ("Run a systems check", "systems_check"),
    ("Is everything working okay with you?", "systems_check"),
    ("Connect my GitHub account", "connect_github"),
    ("What did I commit on GitHub this week?", "github_activity"),
    ("List my GitHub repos", "github_repos"),
    ("How is my YouTube channel doing?", "youtube_own_channel"),
    ("What can you do?", "skills_open"),
    ("Check my inbox for anything urgent", "gmail_inbox_summary"),
    ("Search my email for the flight booking", "gmail_search"),
    ("Draft a reply to Meera saying I'll join", "gmail_create_draft"),
    ("Send the draft to Arjun", "gmail_send"),
    ("Any unread mails from the school?", "gmail_unread_digest"),
    ("Where's my Amazon parcel?", "gmail_track_packages"),
    ("When will my Flipkart order be delivered?", "gmail_track_packages"),
    ("What's Priya's phone number?", "contacts_search"),
    ("Whose birthday is coming up this month?", "contacts_birthdays"),
    ("WhatsApp Rahul that I'm running late", "whatsapp_draft"),
    ("Message him that the meeting moved", "whatsapp_draft"),
    ("What bills are due this month?", "bill_list"),
    ("Add my broadband bill, Rs 999 due on the 5th", "bill_add"),
    ("I paid the electricity bill", "bill_paid"),
    ("Prepare the payment for the rent", "bill_pay_prepare"),
    ("Save the landlord's UPI ID for rent", "bill_payee_set"),
    ("How much did I spend on groceries this month?", "spend_month"),
    ("bijli ka bill kab due hai?", "bill_list"),
    ("How is my Python study plan going?", "series_list"),
    ("I skipped today's guitar session", "series_checkin"),
    ("Move my skipped Spanish lessons to next week", "series_reschedule"),
    ("I'm bored, what should I do?", "freetime_suggest"),
    ("Add 'learn to paint' to my free-time ideas", "freetime_add"),
    ("Show my free time list", "freetime_list"),
    ("Find a YouTube video on how to make filter coffee", "youtube_search"),
    ("Play my workout playlist", "youtube_my_playlists"),
    ("Show the songs in my road trip playlist", "youtube_playlist"),
    ("Is the house armed?", "home_status"),
    ("Arm the alarm, I'm leaving", "home_arm"),
    ("Disarm the alarm", "home_disarm"),
    ("Who came to the door today?", "camera_history"),
    ("Show the faces you know", "faces_list"),
    ("Group the faces from my photos", "faces_groups"),
    ("Import my Google Photos so you can learn faces", "photos_import"),
    ("Has my email been in a data breach?", "breach_status"),
    ("Which of my documents expire soon?", "vault_expiring"),
    ("Show my vault", "vault_list"),
    ("My passport expires in June 2030, update it", "vault_set_dates"),
    ("Turn off the living room lights", "home_control"),
    ("What devices are connected at home?", "home_devices"),
    ("fan band karo", "home_control"),
    ("I drank a glass of water", "nudge_water_log"),
    ("Nudge me to stand up every hour", "nudge_set"),
    ("Snooze the water nudge for an hour", "nudge_snooze"),
    ("How did I sleep last night?", "sleep_last_night"),
    ("How many steps today on my watch?", "watch_today"),
    ("What can I cook for dinner with what's in the pantry?", "recipe_suggest"),
    ("How much protein is in 100 g of paneer?", "nutrition_of"),
    ("Add tomatoes to the pantry", "pantry_add"),
    ("Is my SOS set up?", "sos_status"),
)


class Controls(NamedTuple):  # not a dataclass: run.py loads this file outside sys.modules
    no_words: bool = False
    content_only_window: bool = False
    hint_off: bool = False


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


def _register(c: Controls) -> SkillRegister:
    cat = load_catalogue()
    if c.no_words:
        skills = tuple(
            replace(s, groups=tuple(replace(g, words=()) for g in s.groups)) for s in cat.skills
        )
        cat = Catalogue(skills, cat.core, cat.telegram_open, cat.no_ai, cat.planned)
    return SkillRegister(cat)


async def _specs() -> list[ToolSpec]:
    from test_telegram_tool_guard import linked_gateway

    return (await linked_gateway()).registry.specs()


def _offered(register: SkillRegister, specs: list[ToolSpec], text: str) -> list[str]:
    offer = SkillOffer(register, sticky_s=0)
    got = offer(
        OfferContext("eval", text, (ChatMessage(role=Role.USER, content=text),), "t"), specs
    )
    return [s.name for s in got]


def _recall_and_size(c: Controls, specs: list[ToolSpec]) -> list[dict[str, Any]]:
    register = _register(c)
    names = {s.name for s in specs}
    misses, sizes, unknown = [], [], [t for _, t in LABELLED if t not in names]
    for text, tool in LABELLED:
        got = _offered(register, specs, text)
        sizes.append(len(got))
        if tool not in got:
            misses.append(f"{tool} <- {text!r}")
    recall = 1 - len(misses) / len(LABELLED)
    size = sum(sizes) / len(sizes)
    recall_fail = (
        [f"recall {recall:.1%} < {RECALL_BAR:.0%}"] + misses if recall < RECALL_BAR else []
    )
    return [
        _case(
            "labelled_120", [f"{len(LABELLED)} labelled, not 120+"] if len(LABELLED) < 120 else []
        ),
        _case("labelled_tools_exist", [f"not registered: {unknown}"] if unknown else []),
        _case("recall", recall_fail),
        _case("size", [f"average {size:.1f} tools > {SIZE_BAR:.0f}"] if size > SIZE_BAR else []),
    ]


def _rounds(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    offer, text = SkillOffer(_register(Controls()), sticky_s=300), "any new mail from the bank?"
    owner = ChatMessage(role=Role.USER, content=text)

    def at(*blocks: ToolCall) -> list[str]:
        msgs = [owner]
        for b in blocks:
            msgs += [ChatMessage(role=Role.ASSISTANT, content=[b])]
        return [s.name for s in offer(OfferContext("eval", text, tuple(msgs), "turn"), specs)]

    first = at()
    second = at(ToolCall(id="a", name="gmail_search", arguments={}))
    opened = at(ToolCall(id="b", name="skills_open", arguments={"skill": "finance"}))
    fails = [] if first == second else ["the set changed between rounds of one turn"]
    if not (set(first) < set(opened) and "bill_list" in opened):
        fails.append("skills_open(finance) did not add the finance tools")
    return [_case("rounds_constant", fails)]


def _fail_safe(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    odd = [ToolSpec(name="brand_new_tool", description="x", input_schema={}), *specs]
    fails = [] if "brand_new_tool" in _offered(_register(Controls()), odd, "hi") else ["hidden"]

    def boom(ctx: OfferContext, given: Any) -> list[ToolSpec]:
        raise RuntimeError("offer")

    if len(BrainSlots(offer=boom).tools(None, [], specs)) != len(specs):
        fails.append("a broken offer hid tools")
    return [_case("fail_safe", fails)]


def _window(c: Controls) -> list[dict[str, Any]]:
    s = Settings(_env_file=None)
    turns = session_turns(rounds=30, size=6_000)
    build = legacy_window if c.content_only_window else build_window
    win = build(turns, max_turns=s.session_max_turns, max_chars=s.session_max_chars)
    sent = sum(message_chars(m) for m in win)
    fails = (
        [f"{sent:,} characters sent > {s.session_max_chars:,}"]
        if sent > s.session_max_chars
        else []
    )
    return [_case("window_counts_blocks", fails)]


async def _ledger() -> list[dict[str, Any]]:
    docs = MemoryDocs()
    store = TokenLedgerStore(docs)
    costs = [0.003, 0.0045, 0.0021, 0.008, 0.0005]
    for n, cost in enumerate(costs):
        usage = Usage(input_tokens=1_000 + n, output_tokens=100, cache_read_tokens=n * 10)
        done = Completion(
            text=SECRET, model="claude-sonnet-5-5", provider="anthropic", usage=usage,
            latency_ms=1, cost_usd=cost,
        )  # fmt: skip
        msgs = (ChatMessage(role=Role.USER, content=f"tell me about {SECRET}"),)
        await store.record(LedgerCall("eval", "anthropic", SECRET, SECRET, msgs, (), done))
    month = await store.month("eval")
    fails = []
    if month.calls != len(costs) or month.tokens["input"] != sum(1_000 + n for n in range(5)):
        fails.append(f"counts {month.calls} calls, {month.tokens['input']} input tokens")
    if abs(month.usd_total - sum(costs)) > 1e-7:
        fails.append(f"parts add to {month.usd_total}, not {sum(costs)}")
    if any(
        SECRET in json.dumps(d, default=str) for _, d in await docs.query(store.query_for("eval"))
    ):
        fails.append("text reached the ledger")
    return [_case("ledger_sums", fails)]


async def _hint(c: Controls) -> list[dict[str, Any]]:
    got = await marks(cache_history=not c.hint_off)
    fails = [] if len(got) == 2 else [f"{len(got)} breakpoint(s): {got}"]
    return [_case("history_hint", fails)]


async def _cases(c: Controls) -> list[dict[str, Any]]:
    specs = await _specs()
    out = _recall_and_size(c, specs) + _rounds(specs) + _fail_safe(specs)
    return out + _window(c) + await _ledger() + await _hint(c)


async def cases() -> list[dict[str, Any]]:
    return await _cases(Controls())


async def control() -> dict[str, Any]:
    targets = {
        "no_words": (Controls(no_words=True), f"{PART}:recall"),
        "content_only_window": (Controls(content_only_window=True), f"{PART}:window_counts_blocks"),
        "hint_off": (Controls(hint_off=True), f"{PART}:history_hint"),
    }
    failed: list[str] = []
    each: dict[str, bool] = {}
    for name, (controls, case_id) in targets.items():
        results = await _cases(controls)
        bad = [r["id"] for r in results if not r["passed"]]
        each[name] = case_id in bad
        failed += [f"{name}: {i}" for i in bad]
    return {
        "name": "words emptied + content-only window + history hint off",
        "suite_failed": all(each.values()),
        "failed_cases": failed,
    }
