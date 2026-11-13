# tests/test_r7_d_fixes_sos.py -- R7 Part D's review follow-ups for the SOS service and store
# (docs/plans/r7-integration/INTEGRATION-D.md "Review follow-ups"): a failed SOS always leaves the
# owner the SMS screen and 112; the state told is honest; the budget gives back a press that
# reached nobody and never runs unbounded; a locked phone sees no contact label; a repeated
# press is answered once; the side channels never hold the answer; joins are counted per chat.
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from r7_fakes_d import ASHA, MEERA, RAVI, UID, BrokenDocs, Notes
from test_r7_d_sos_send import HERE, World

import jarvis.sos.service as service_mod
from jarvis.notify.ports import Delivery, Signal
from jarvis.sos.store import WRONG_GLOBAL_PER_HOUR, WRONG_PER_CHAT, Budget, SosStore
from jarvis.storage.docs import MemoryDocs


class Held(Notes):
    """A notifier whose policy holds or drops the notice instead of delivering it."""

    def __init__(self, action: str) -> None:
        super().__init__()
        self.action = action

    async def notify(self, uid: str, signal: Signal, message: str, **kw: Any) -> Delivery:
        return Delivery(action=self.action, reason="quiet")  # type: ignore[arg-type]


class Hangs(Notes):
    async def notify(self, uid: str, signal: Signal, message: str, **kw: Any) -> Delivery:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


# ---- honest state ----
async def test_an_unreadable_book_shows_a_warning_on_the_sheet_never_a_normal_empty_list() -> None:
    w = World(docs=BrokenDocs())
    sheet = await w.svc.sheet(UID)
    assert sheet["unreadable"] is True and sheet["numbers"] == []
    assert "112" in sheet["warning"] and "Sir" in sheet["warning"]
    ok = await World().svc.sheet(UID)
    assert ok["unreadable"] is False and "warning" not in ok


@pytest.mark.parametrize("action", ["hold", "drop"])
async def test_told_is_true_only_for_a_real_delivery(action: str) -> None:
    w = World(notes=Held(action))  # type: ignore[arg-type]
    await w.contact(ASHA)
    res = await w.svc.send(UID, "real", None, via="web")
    assert res.outcome == "sent" and res.told is False and res.view()["told"] is False


async def test_a_delivery_that_rang_is_told_and_one_that_reached_no_device_is_not() -> None:
    w = World()
    await w.contact(ASHA)
    assert (await w.svc.send(UID, "real", None, via="web")).told is True

    class Nowhere(Notes):
        async def notify(self, uid: str, signal: Signal, message: str, **kw: Any) -> Delivery:
            return Delivery(action="ring", reason="x")  # rang nowhere: no Telegram, no push

    w2 = World(notes=Nowhere())
    await w2.contact(ASHA)
    assert (await w2.svc.send(UID, "real", None, via="web")).told is False


async def test_a_missing_notifier_is_logged_and_the_answer_says_not_told(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = World()
    w.svc._notifier = lambda: None  # noqa: SLF001
    await w.contact(ASHA)
    with caplog.at_level(logging.WARNING):
        res = await w.svc.send(UID, "real", None, via="web")
    assert res.told is False and "no notifier" in caplog.text


async def test_a_log_that_fails_is_said_in_the_answer(caplog: pytest.LogCaptureFixture) -> None:
    w = World()
    await w.contact(ASHA)

    async def boom(uid: str, entry: Any) -> None:
        raise ValueError("no")

    w.store.log = boom  # type: ignore[method-assign]
    res = await w.svc.send(UID, "real", None, via="web")
    assert res.outcome == "sent" and res.view()["logged"] is False
    assert (await World().svc.send(UID, "real", None, via="web")).view()["logged"] is True


async def test_a_corrupt_budget_is_logged_not_silently_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        b = Budget.of({"real": "nope", "test": [1.0, "x", True]}, 100.0)
    assert b == Budget(real=(), test=(1.0,)) and "budget" in caplog.text.lower()


async def test_two_contacts_in_one_chat_both_show_a_row_and_count_once() -> None:
    w = World()
    await w.contact(ASHA)
    await w.contact((ASHA[0] + " again", "+10000000009", ASHA[2]))
    w.bot.calls.clear()
    res = await w.svc.send(UID, "real", None, via="web")
    assert len(w.bot.to(ASHA[2])) == 1 and (res.reached, res.joined) == (1, 1)
    assert [r.status for r in res.results] == ["sent", "sent"] and res.outcome == "sent"


# ---- the budget ----
async def test_a_real_press_that_reached_nobody_gives_its_slot_back() -> None:
    w = World()
    await w.three()
    w.bot.fail.add("sendMessage")
    for _ in range(4):  # more than the 3 an hour: none of them reached anyone
        assert (await w.svc.send(UID, "real", HERE, via="web")).outcome == "failed"
    w.bot.fail.clear()
    ok = await w.svc.send(UID, "real", HERE, via="web")
    assert ok.outcome == "sent"  # never refused as a rate limit while in danger
    assert (await w.svc.view(UID))["left"]["real_hour"] == 2


async def test_none_joined_and_unavailable_give_the_slot_back_too() -> None:
    w = World()
    await w.svc.add_contact(UID, *ASHA[:2])  # not joined
    for _ in range(5):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "none_joined"
    assert (await w.svc.view(UID))["left"]["real_hour"] == 3


async def test_a_delivered_press_keeps_its_slot() -> None:
    w = World()
    await w.contact(ASHA)
    await w.svc.send(UID, "real", None, via="web")
    assert (await w.svc.view(UID))["left"]["real_hour"] == 2


async def test_the_fallback_counter_holds_three_an_hour_and_ten_a_day() -> None:
    docs = MemoryDocs()
    w = World(docs=docs)
    await w.contact(ASHA)
    flaky = {"down": False}
    real_tx = docs.transaction

    async def tx(fn: Callable[[Any], Awaitable[Any]]) -> Any:
        if flaky["down"]:
            raise RuntimeError("transactions down")
        return await real_tx(fn)

    docs.transaction = tx  # type: ignore[method-assign]
    flaky["down"] = True
    for _ in range(3):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "sent"
    w.bot.calls.clear()
    fourth = await w.svc.send(UID, "real", None, via="web")
    assert fourth.outcome == "refused" and fourth.reason == "hour" and w.bot.calls == []
    assert "112" in fourth.words
    w.clock.move(minutes=61)  # the hour passes; the day cap (10) is the next bound
    for _ in range(3):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "sent"
        w.clock.move(minutes=61)
    for _ in range(4):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "sent"
        w.clock.move(minutes=61)
    tenth = await w.svc.send(UID, "real", None, via="web")
    assert tenth.outcome == "refused" and tenth.reason == "day"
    # a test is refused outright while the limits cannot be read
    assert (await w.svc.send(UID, "test", None, via="web")).reason == "unreadable"


async def test_a_press_that_reached_nobody_does_not_use_the_fallback_slot_either() -> None:
    docs = MemoryDocs()
    w = World(docs=docs)
    await w.contact(ASHA)

    async def tx(fn: Callable[[Any], Awaitable[Any]]) -> Any:
        raise RuntimeError("down")

    docs.transaction = tx  # type: ignore[method-assign]
    w.bot.fail.add("sendMessage")
    for _ in range(5):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "failed"
    w.bot.fail.clear()
    assert (await w.svc.send(UID, "real", None, via="web")).outcome == "sent"


async def test_privacy_delete_never_resets_the_send_limits() -> None:
    w = World()
    await w.three()
    for _ in range(3):
        assert (await w.svc.send(UID, "real", None, via="web")).outcome == "sent"
    assert await w.store.delete_all(UID) >= 3
    assert (await w.store.budget(UID, w.clock().timestamp())).real  # the times are still there
    await w.three()
    assert (await w.svc.send(UID, "real", None, via="web")).outcome == "refused"


async def test_delete_all_deletes_even_when_the_book_will_not_open() -> None:
    w = World()
    await w.contact(ASHA)
    await w.svc.send(UID, "real", None, via="web")
    path = w.store._book_path(UID)  # noqa: SLF001
    w.docs._data[path] = {"v": 1, "kid": "x", "blob": "garbage"}
    gone = await w.store.delete_all(UID)
    assert gone >= 1 and path not in w.docs._data
    assert not [p for p in w.docs._data if "sos_log/" in p and not p.endswith("_budget")]


async def test_six_presses_at_once_send_three_and_refuse_three() -> None:
    w = World()
    await w.contact(ASHA)
    w.bot.calls.clear()
    got = await asyncio.gather(*(w.svc.send(UID, "real", None, via="web") for _ in range(6)))
    assert sorted(r.outcome for r in got) == ["refused"] * 3 + ["sent"] * 3
    assert len(w.bot.to(ASHA[2])) == 3  # the contact got exactly the allowed ones
    assert (await w.store.budget(UID, w.clock().timestamp())).real.__len__() == 3


# ---- one press, one send ----
PRESS = "A1b2C3d4E5f6G7h8"


async def test_a_repeated_press_id_answers_the_first_result_without_sending_again() -> None:
    w = World()
    await w.contact(ASHA)
    w.bot.calls.clear()
    first = await w.svc.send(UID, "real", HERE, via="web", press_id=PRESS)
    again = await w.svc.send(UID, "real", HERE, via="phone", press_id=PRESS)
    assert again.view() == first.view() and len(w.bot.to(ASHA[2])) == 1
    assert (await w.svc.view(UID))["left"]["real_hour"] == 2
    other = await w.svc.send(UID, "real", HERE, via="web", press_id=PRESS + "x")
    assert other.outcome == "sent" and len(w.bot.to(ASHA[2])) == 2


async def test_two_requests_for_one_press_at_the_same_moment_send_once() -> None:
    w = World()
    await w.contact(ASHA)
    w.bot.calls.clear()
    got = await asyncio.gather(
        *(w.svc.send(UID, "real", None, via="web", press_id=PRESS) for _ in range(4))
    )
    assert len(w.bot.to(ASHA[2])) == 1 and len({json.dumps(r.view()) for r in got}) == 1


async def test_a_press_id_is_forgotten_after_an_hour() -> None:
    w = World()
    await w.contact(ASHA)
    await w.svc.send(UID, "real", None, via="web", press_id=PRESS)
    w.clock.move(minutes=61)
    w.bot.calls.clear()
    await w.svc.send(UID, "real", None, via="web", press_id=PRESS)
    assert len(w.bot.to(ASHA[2])) == 1


@pytest.mark.parametrize(
    "bad", ["short", "x" * 65, "has a space 1234567", "semi;colon;1234567", ""]
)
async def test_a_badly_shaped_press_id_is_ignored_and_the_sos_still_goes(bad: str) -> None:
    w = World()
    await w.contact(ASHA)
    w.bot.calls.clear()
    await w.svc.send(UID, "real", None, via="web", press_id=bad)
    await w.svc.send(UID, "real", None, via="web", press_id=bad)
    assert len(w.bot.to(ASHA[2])) == 2


# ---- a locked phone ----
async def test_locked_answers_carry_no_contact_label() -> None:
    w = World()
    await w.three()
    w.bot.refuse_text.add(RAVI[2])
    res = await w.svc.send(UID, "real", None, via="web", locked=True)
    said = json.dumps(res.view())
    for name in (ASHA[0], RAVI[0], MEERA[0]):
        assert name not in said
    assert sorted(r.label for r in res.results) == ["Contact 1", "Contact 2", "Contact 3"]
    assert "Contact" in said and res.reached == 2


async def test_the_locked_sheet_has_the_numbers_for_the_sms_link_and_nothing_else() -> None:
    w = World()
    await w.three()
    sheet = await w.svc.sheet(UID, locked=True)
    assert sheet["numbers"] == [ASHA[1], RAVI[1], MEERA[1]] and sheet["locked"] is True
    assert sheet["first"] is None and "label" not in sheet
    unlocked = await w.svc.sheet(UID)
    assert unlocked["label"] == "Kiran Example" and unlocked["locked"] is False


# ---- the side channels never hold the answer ----
async def test_a_hanging_notice_does_not_hold_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "AFTER_S", 0.05)
    w = World(notes=Hangs())
    await w.contact(ASHA)
    res = await asyncio.wait_for(w.svc.send(UID, "real", None, via="web"), 2)
    assert res.outcome == "sent" and res.reached == 1 and res.told is False


async def test_a_hanging_log_and_audit_do_not_hold_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_mod, "AFTER_S", 0.05)
    w = World()
    await w.contact(ASHA)

    async def hang(*a: Any, **k: Any) -> None:
        await asyncio.Event().wait()

    w.store.log = hang  # type: ignore[method-assign]
    w.svc._audit.append = hang  # type: ignore[union-attr,method-assign]  # noqa: SLF001
    res = await asyncio.wait_for(w.svc.send(UID, "real", None, via="web"), 2)
    assert res.outcome == "sent" and res.view()["logged"] is False


async def test_a_book_that_hangs_gives_the_sms_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "STORE_S", 0.05)
    w = World()

    async def hang(uid: str) -> Any:
        await asyncio.Event().wait()

    w.store.book = hang  # type: ignore[method-assign]
    res = await asyncio.wait_for(w.svc.send(UID, "real", None, via="web"), 2)
    assert res.outcome == "unavailable" and res.reason == "unreadable" and "112" in res.words


async def test_a_budget_that_hangs_lets_a_real_sos_go(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "STORE_S", 0.05)
    docs = MemoryDocs()
    w = World(docs=docs)
    await w.contact(ASHA)

    async def hang(fn: Any) -> Any:
        await asyncio.Event().wait()

    docs.transaction = hang  # type: ignore[method-assign]
    res = await asyncio.wait_for(w.svc.send(UID, "real", None, via="web"), 2)
    assert res.outcome == "sent"


async def test_the_location_that_was_dropped_is_said_in_the_answer() -> None:
    w = World()
    await w.contact(ASHA)
    res = await w.svc.send(UID, "real", None, via="phone", location_dropped=True)
    assert res.outcome == "sent" and "sent without your location" in res.words


# ---- joins counted per chat ----
WORD = "sos-" + "x" * 30


async def test_wrong_words_are_counted_per_chat_with_a_high_global_cap() -> None:
    w = World()
    await w.contact(ASHA, join=False)
    now = w.clock().timestamp()
    for _ in range(WRONG_PER_CHAT):
        await w.svc.join(WORD, tg_user_id=1, chat_id=111)
    assert await w.store.wrong_blocked(now, 111) is True
    assert await w.store.wrong_blocked(now, 222) is False  # a stranger cannot shut other chats
    link = await w.svc.join_link(UID, (await w.svc.view(UID))["contacts"][0]["id"])
    word = link["link"].split("start=", 1)[1]
    assert (
        await w.svc.join(word, tg_user_id=2, chat_id=222) is not None
    )  # the owner's contact joins
    assert await w.svc.join(word, tg_user_id=1, chat_id=111) is None  # the blocked chat is held


async def test_the_global_cap_still_stops_a_flood_from_many_chats() -> None:
    w = World()
    now = w.clock().timestamp()
    for chat in range(WRONG_GLOBAL_PER_HOUR):
        await w.store.count_wrong(now, chat)
    assert await w.store.wrong_blocked(now, 99_999) is True


def test_the_store_keeps_its_old_signature_names() -> None:
    assert hasattr(SosStore, "wrong_blocked") and hasattr(SosStore, "count_wrong")
