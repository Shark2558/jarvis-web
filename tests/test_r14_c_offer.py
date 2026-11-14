# tests/test_r14_c_offer.py -- R14 Part C, D9 "Offer only the tools a message needs" (plan
# docs/plans/r14-hardening.md): the turn's tools are the groups his words name, the groups of
# tools used in the last 3 turns, the previous turn's set while it is under `tool_offer_sticky_s`
# old, the core, and every tool a replayed tool_use names; fixed for the whole turn, in registry
# order, except that `skills_open(skill)` adds that skill from the next round. A tool the register
# can't file is always offered (fail safe).
from __future__ import annotations

from r14_fakes_c import Clock, called, ctx, later, names, owner, reply, specs

from jarvis.skills.offer import STICKY_MAX_TOOLS, SkillOffer, Words
from jarvis.skills.registry import SkillRegister, load_catalogue

REGISTRY = (
    "calendar_list_events", "calendar_create_event", "reminder_add", "reminders_list",
    "reminder_update", "tasks_list", "task_add", "grocery_list", "grocery_add", "gmail_search",
    "gmail_read", "gmail_send", "gmail_track_packages", "whatsapp_draft", "memory_search",
    "memory_save", "web_search", "web_read", "maps_search", "bill_list", "bill_pay_prepare",
    "spend_month", "home_status", "home_control", "home_devices", "vault_expiring",
    "nudge_water_log", "sleep_last_night", "recipe_suggest", "skills_open", "weather_now",
)  # fmt: skip
CORE = ["calendar_list_events", "reminder_add", "memory_search", "skills_open"]
SPECS = specs(*REGISTRY)
REGISTER = SkillRegister(load_catalogue())


def _offer(clock: Clock | None = None, *, sticky_s: float = 300) -> SkillOffer:
    return SkillOffer(REGISTER, sticky_s=sticky_s, clock=clock or Clock())


def test_a_message_with_no_words_gets_the_core_only() -> None:
    assert names(_offer()(ctx("thank you so much"), SPECS)) == CORE


def test_his_words_choose_their_groups_in_registry_order() -> None:
    got = names(_offer()(ctx("what's in my inbox from the bank?"), SPECS))
    assert got == [
        "calendar_list_events", "reminder_add", "gmail_search", "gmail_read", "gmail_send",
        "memory_search", "skills_open",
    ]  # fmt: skip
    assert "gmail_track_packages" not in got  # its own group: an exact name beats gmail_*


def test_hinglish_words_choose_their_groups_too() -> None:
    got = names(_offer()(ctx("kal subah saat baje yaad dila dena"), SPECS))
    assert {"reminders_list", "reminder_update"} <= set(got)
    assert {"grocery_add"} <= set(names(_offer()(ctx("doodh khatam ho gaya"), SPECS)))


def test_short_words_match_whole_words_only() -> None:
    offer = _offer()
    assert "home_control" in names(offer(ctx("switch the tv off"), SPECS))
    assert "home_control" not in names(_offer()(ctx("the tvs are fine"), SPECS))
    assert "bill_list" in names(_offer()(ctx("pay the rent"), SPECS))
    assert "bill_list" not in names(_offer()(ctx("payload of the request"), SPECS))


def test_a_tool_the_register_cannot_file_is_always_offered() -> None:
    odd = specs("brand_new_tool", *REGISTRY)
    assert names(_offer()(ctx("hello"), odd))[0] == "brand_new_tool"


def test_every_tool_a_replayed_call_names_is_offered() -> None:
    history = [owner("check the parcel"), *called("gmail_track_packages"), reply()]
    history += [owner("ok"), reply(), owner("fine"), reply(), owner("hmm"), reply()]
    got = names(_offer()(ctx("thanks", history), SPECS))
    assert "gmail_track_packages" in got  # named in the window: the provider must know it


def test_tools_used_in_the_last_three_turns_bring_their_group() -> None:
    old = [owner("search the web for x"), *called("web_search"), reply()]
    recent = [owner("read my mail"), *called("gmail_read"), reply()]
    filler = [owner("ok"), reply()]
    got = names(_offer()(ctx("and the next one?", [*old, *filler, *filler, *recent]), SPECS))
    assert {"gmail_search", "gmail_send"} <= set(got)  # gmail_read's group, used 1 turn ago
    assert "web_search" in got and "web_read" not in got  # 4 turns ago: the name only


def test_the_last_turns_set_stays_while_it_is_fresh() -> None:
    clock = Clock()
    offer = _offer(clock)
    first = names(offer(ctx("any new email?", turn="a"), SPECS))
    assert "gmail_send" in first
    clock.now += 120
    assert names(offer(ctx("thanks", turn="b"), SPECS)) == first  # sticky: the cache still hits
    clock.now += 301
    assert names(offer(ctx("thanks again", turn="c"), SPECS)) == CORE


def test_no_sticky_when_the_setting_is_zero_and_none_across_owners() -> None:
    offer = _offer(sticky_s=0)
    offer(ctx("any new email?", turn="a"), SPECS)
    assert names(offer(ctx("thanks", turn="b"), SPECS)) == CORE
    shared = _offer()
    shared(ctx("any new email?", uid="one", turn="a"), SPECS)
    assert names(shared(ctx("thanks", uid="two", turn="b"), SPECS)) == CORE


def test_the_sticky_set_is_dropped_when_it_grows_too_large() -> None:
    many = specs(*[f"gmail_x{i}" for i in range(STICKY_MAX_TOOLS + 5)], *REGISTRY)
    offer = _offer()
    offer(ctx("check my mail", turn="a"), many)
    assert names(offer(ctx("weather today?", turn="b"), many)) == [
        "calendar_list_events", "reminder_add", "memory_search", "skills_open", "weather_now",
    ]  # fmt: skip


def test_the_set_is_fixed_for_the_whole_turn() -> None:
    offer = _offer()
    first = offer(ctx("what's the weather?"), SPECS)
    again = offer(later("what's the weather?", called("weather_now")), SPECS)
    assert names(again) == names(first)
    stray = offer(later("what's the weather?", called("web_read")), SPECS)  # never offered
    assert names(stray) == sorted({*names(first), "web_read"}, key=REGISTRY.index)


def test_skills_open_adds_that_skill_from_the_next_round() -> None:
    offer = _offer()
    before = names(offer(ctx("sort out the money thing"), SPECS))
    assert "bill_list" not in before
    opened = called("skills_open", skill="finance")
    after = names(offer(later("sort out the money thing", opened), SPECS))
    assert {"bill_list", "bill_pay_prepare", "spend_month"} <= set(after)
    assert set(before) <= set(after)


def test_skills_open_with_an_unknown_skill_adds_nothing() -> None:
    offer = _offer()
    before = names(offer(ctx("hello"), SPECS))
    after = names(offer(later("hello", called("skills_open", skill="knowledge")), SPECS))
    assert after == before and "skills_open" in after


def test_a_new_owner_message_is_a_new_turn_even_without_a_trace_id() -> None:
    clock = Clock()
    offer = _offer(clock, sticky_s=0)
    offer(ctx("check my mail", turn="-"), SPECS)
    history = [owner("check my mail"), reply()]
    assert names(offer(ctx("the weather?", history, turn="-"), SPECS)) == [
        "calendar_list_events", "reminder_add", "memory_search", "skills_open", "weather_now",
    ]  # fmt: skip


def test_the_words_table_matches_word_starts() -> None:
    words = Words(("remind", "ac", "near me"))
    assert words.search("Please REMIND me") and words.search("reminders?")
    assert words.search("is the AC on") and not words.search("accurate")
    assert words.search("anything near   me") and not words.search("unremind")
    assert not Words(()).search("anything")
