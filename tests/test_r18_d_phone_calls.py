# tests/test_r18_d_phone_calls.py -- R18 builder D (docs/plans/r18-calls/BUILD-BRIEF.md, "Phone <->
# cloud"): the cloud's half of the phone's call commands and call events, `jarvis.phone.calls`.
# Commands are signed by the cloud and handed out on the phone's own signed door (`calls`), with
# Web Push only as the doorbell; a dial needs a live approval; events are checked for shape,
# freshness, repeats and rate before the calls engine sees them; an incoming number reaches the
# engine only while answering missed calls is on, and no log line carries a full number.
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.calls.models import CallCard
from jarvis.calls.protocol import CallAnswer, CallDial, CallEnd, CallRoute, CallStateEvent
from jarvis.mobile import contract
from jarvis.mobile.ports import PhoneRequest
from jarvis.phone import calls as pc
from jarvis.phone import calls_wire as w
from jarvis.phone.store import Phone

UID = "u_owner"
C1, C2, K1 = "call_000000000001", "call_000000000002", "cc_000000000001"
PHONE = "ph_0123456789ab"
OTHER = "ph_ba9876543210"
NUMBER = "+919000000001"
T0 = 1_800_000_000.0
VECTORS = Path(__file__).resolve().parent / "fixtures" / "r18" / "phone_calls_vectors.json"


def _phone(device: str, *, last_seen: float | None = None) -> Phone:
    return Phone(
        id=device,
        model="phone",
        public_key="04" + "ab" * 64,
        package="io.github.shark2558.jarvis",
        fingerprint="cd" * 32,
        linked_at=T0 - 86_400,
        last_seen=last_seen,
        app_version="18.0.0",
    )


class Clock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class Directory:
    phones: list[Phone] = field(default_factory=lambda: [_phone(PHONE, last_seen=T0 - 60)])

    async def linked(self, uid: str) -> list[Phone]:
        return list(self.phones) if uid == UID else []


@dataclass
class Approvals:
    live: dict[str, float] = field(default_factory=lambda: {"ap_live_000001": T0 + 300})
    asked: list[tuple[str, str, str, str]] = field(default_factory=list)

    async def live_until(
        self, uid: str, approval_id: str, call_id: str, number_e164: str
    ) -> float | None:
        self.asked.append((uid, approval_id, call_id, number_e164))
        return self.live.get(approval_id) if number_e164 == NUMBER else None


@dataclass
class Bell:
    rang: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    async def ring(self, uid: str, kind: str, text: str) -> int:
        if self.fail:
            raise RuntimeError("push down")
        self.rang.append((uid, kind, text))
        return 1


@dataclass
class Sink:
    states: list[CallStateEvent] = field(default_factory=list)
    results: list[pc.PhoneCommandResult] = field(default_factory=list)
    fail_once: bool = False

    async def phone_state(self, uid: str, event: CallStateEvent) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("engine busy")
        self.states.append(event)

    async def phone_result(self, uid: str, result: pc.PhoneCommandResult) -> None:
        self.results.append(result)


@dataclass
class Cards:
    seen: list[tuple[str, str, str]] = field(default_factory=list)
    outcome: pc.CardOutcome = "approved"

    async def decide(
        self, uid: str, card_id: str, decision: w.CardDecision, device_id: str
    ) -> pc.CardOutcome:
        self.seen.append((card_id, decision, device_id))
        return self.outcome


@dataclass
class Answering:
    on: bool = False

    async def rule(self, uid: str) -> pc.AnsweringRule:
        return pc.AnsweringRule(on=self.on, after_rings=5)


@dataclass
class Audit:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def append(self, **row: Any) -> None:
        self.rows.append(row)


@dataclass
class Rig:
    calls: pc.PhoneCalls
    clock: Clock
    approvals: Approvals
    bell: Bell
    sink: Sink
    cards: Cards
    answering: Answering
    audit: Audit
    directory: Directory


SECRET = bytes(range(48))


def rig(**over: Any) -> Rig:
    clock, approvals, bell = Clock(), Approvals(), Bell()
    sink, cards, answering, audit, directory = Sink(), Cards(), Answering(), Audit(), Directory()
    calls = pc.PhoneCalls(
        phones=over.pop("phones", directory),
        signer=w.CommandSigner.from_secret(SECRET),
        approvals=approvals,
        doorbell=over.pop("doorbell", bell),
        sink=sink,
        cards=over.pop("cards", cards),
        answering=answering,
        audit=audit,
        clock=clock,
        **over,
    )
    return Rig(calls, clock, approvals, bell, sink, cards, answering, audit, directory)


def can(**over: bool) -> dict[str, bool]:
    base = {"place": True, "answer": True, "state": True, "number": False, "notify": True}
    return {**base, **over}


def body(
    events: list[dict[str, Any]] | None = None,
    acks: list[str] | None = None,
    wait: int = 0,
    **over: Any,
) -> bytes:
    data = {
        "v": 1,
        "app_version": "18.0.0",
        "can": can(),
        "events": events or [],
        "acks": acks or [],
        "wait": wait,
    }
    data.update(over)
    return contract.canonical_json(data)


def req(raw: bytes, at: float = T0, device: str = PHONE) -> PhoneRequest:
    return PhoneRequest(route="calls", device_id=device, uid=UID, body=raw, at=at)


_EID = iter(range(1, 10_000))


def state_event(state: str, **over: Any) -> dict[str, Any]:
    ev = {
        "id": f"pe_{next(_EID):016x}",
        "type": "call.state",
        "call_id": C1,
        "state": state,
        "number_e164": None,
        "rings": 0,
        "at": int(T0),
    }
    ev.update(over)
    return ev


async def answer(r: Rig, raw: bytes, **kw: Any) -> tuple[int, dict[str, Any]]:
    reply = await r.calls.door(req(raw, **kw))
    return reply.status, dict(reply.body)


def dial() -> w.Dial:
    return w.Dial(call_id=C1, number=NUMBER, approval_id="ap_live_000001", label="Laundry")


# ---- the signer --------------------------------------------------------------------------------
def test_the_signer_is_the_same_key_on_every_start_and_signs_what_it_says() -> None:
    a, b = w.CommandSigner.from_secret(SECRET), w.CommandSigner.from_secret(SECRET)
    assert a.public_key_hex == b.public_key_hex
    assert len(a.public_key_hex) == 130 and a.public_key_hex.startswith("04")
    text = '{"v":1}'
    sig = a.sign(text)
    assert w.verify_command(a.public_key_hex, text, sig)
    assert not w.verify_command(a.public_key_hex, text + " ", sig)
    other = w.CommandSigner.from_secret(bytes(reversed(SECRET)))
    assert not w.verify_command(other.public_key_hex, text, sig)
    assert "hidden" in repr(a)


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(ValueError):
        w.CommandSigner.from_secret(b"short")


def test_the_shared_vectors_verify_and_their_bad_cases_do_not() -> None:
    v = json.loads(VECTORS.read_text(encoding="utf-8"))
    key = v["public_key"]
    for case in v["good"]:
        assert w.verify_command(key, case["body"], case["sig"]), case["name"]
        parsed = json.loads(case["body"])
        assert contract.canonical_json(parsed).decode("utf-8") == case["body"], case["name"]
        assert parsed["d"] == v["device_id"]
    for case in v["bad_signature"]:
        assert not w.verify_command(key, case["body"], case["sig"]), case["name"]


def test_the_shared_door_body_is_accepted_and_the_refused_vectors_are_what_they_say() -> None:
    v = json.loads(VECTORS.read_text(encoding="utf-8"))
    parsed = w.parse_body(v["door_body"].encode("utf-8"))
    assert parsed is not None and len(parsed.events) == 3 and parsed.wait == 8
    for case in v["refused"]:
        assert w.verify_command(v["public_key"], case["body"], case["sig"]), case["name"]
        cmd = json.loads(case["body"])
        now = case.get("now", v["now"])
        assert cmd["d"] != v["device_id"] or cmd["exp"] <= now, case["name"]


def test_a_command_body_is_the_one_json_form_with_its_fields_in_order() -> None:
    signer = w.CommandSigner.from_secret(SECRET)
    sealed = w.seal(
        signer, dial(), device_id=PHONE, now=T0, exp=T0 + 120, command_id="pc_" + "1" * 16
    )
    assert sealed.body == (
        '{"v":1,"id":"pc_1111111111111111","d":"ph_0123456789ab","type":"call.dial",'
        '"iat":1800000000,"exp":1800000120,"call_id":"call_000000000001",'
        '"number":"+919000000001","approval_id":"ap_live_000001","label":"Laundry"}'
    )
    assert w.verify_command(signer.public_key_hex, sealed.body, sealed.sig)


# ---- sending -------------------------------------------------------------------------------------
async def test_a_dial_with_a_live_approval_is_queued_signed_and_rings_the_doorbell() -> None:
    r = rig()
    out = await r.calls.send(UID, dial())
    assert out.status == "queued" and out.device_id == PHONE and out.rang
    assert r.approvals.asked == [(UID, "ap_live_000001", C1, NUMBER)]
    assert r.bell.rang and r.bell.rang[0][1] == pc.DOORBELL_KIND
    assert NUMBER not in r.bell.rang[0][2] and "Laundry" not in r.bell.rang[0][2]
    status, got = await answer(r, body())
    assert status == 200
    (cmd,) = got["commands"]
    assert w.verify_command(got["key"], cmd["body"], cmd["sig"])
    sent = json.loads(cmd["body"])
    assert sent["type"] == "call.dial" and sent["d"] == PHONE and sent["number"] == NUMBER
    assert sent["exp"] == int(T0 + 300)  # the approval's own expiry, under the 10-minute cap


@pytest.mark.parametrize("approval", ["ap_gone_000001", "ap_live_000001"])
async def test_a_dial_without_a_live_approval_for_that_number_is_refused(approval: str) -> None:
    r = rig()
    number = "+919000000002" if approval == "ap_live_000001" else NUMBER
    out = await r.calls.send(
        UID, w.Dial(call_id=C1, number=number, approval_id=approval, label="X")
    )
    assert out.status == "refused" and out.code == "approval"
    assert r.bell.rang == []
    _, got = await answer(r, body())
    assert got["commands"] == []


async def test_an_expired_approval_is_refused_and_a_long_one_is_capped() -> None:
    r = rig()
    r.approvals.live["ap_live_000001"] = T0 - 1
    assert (await r.calls.send(UID, dial())).status == "refused"
    r.approvals.live["ap_live_000001"] = T0 + 86_400
    assert (await r.calls.send(UID, dial())).status == "queued"
    _, got = await answer(r, body())
    assert json.loads(got["commands"][0]["body"])["exp"] == int(T0 + pc.DIAL_MAX_S)


async def test_an_approval_check_that_fails_refuses_the_dial() -> None:
    r = rig()

    async def broken(*_: Any) -> float | None:
        raise RuntimeError("store down")

    r.approvals.live_until = broken  # type: ignore[method-assign,assignment]
    out = await r.calls.send(UID, dial())
    assert out.status == "refused" and out.code == "approval"


@pytest.mark.parametrize(
    "bad",
    [
        {"number": "112"},
        {"number": "+11234567890"},
        {"number": "+9119001234567"},
        {"number": "9000000001"},
        {"approval_id": ""},
        {"call_id": "a b"},
        {"label": "x" * 41},
    ],
)
def test_a_dial_of_the_wrong_shape_cannot_be_made(bad: dict[str, str]) -> None:
    fields = {"call_id": C1, "number": NUMBER, "approval_id": "ap_live_000001"}
    with pytest.raises(ValueError):
        w.Dial.model_validate({**fields, "label": "", **bad})


async def test_answer_end_route_and_card_need_no_approval_and_expire_soon() -> None:
    r = rig()
    for command in (
        w.Answer(call_id=C1),
        w.End(call_id=C1),
        w.RouteTo(call_id=C1, to="phone"),
        w.Card(card_id=K1, label="Laundry", purpose="Pickup tomorrow", passkey=True),
    ):
        assert (await r.calls.send(UID, command)).status == "queued"
    _, got = await answer(r, body())
    kinds = [json.loads(c["body"]) for c in got["commands"]]
    assert [k["type"] for k in kinds] == ["call.answer", "call.end", "call.route", "call.card"]
    assert all(k["exp"] - k["iat"] <= pc.DIAL_MAX_S for k in kinds)
    assert kinds[0]["exp"] - kinds[0]["iat"] == pc.TTL_S["call.answer"]
    assert kinds[2]["to"] == "phone" and kinds[3]["passkey"] is True


async def test_no_linked_phone_means_nothing_is_queued() -> None:
    r = rig(phones=Directory(phones=[]))
    out = await r.calls.send(UID, w.End(call_id=C1))
    assert out.status == "no_phone" and r.bell.rang == []


async def test_a_doorbell_that_fails_still_queues_the_command() -> None:
    r = rig(doorbell=Bell(fail=True))
    out = await r.calls.send(UID, w.End(call_id=C1))
    assert out.status == "queued" and not out.rang
    _, got = await answer(r, body())
    assert len(got["commands"]) == 1


async def test_the_phone_that_checked_in_able_to_place_calls_gets_the_command() -> None:
    d = Directory(phones=[_phone(PHONE, last_seen=T0 - 10), _phone(OTHER, last_seen=T0 - 5)])
    r = rig(phones=d)
    await answer(r, body(can=can(place=False)), device=OTHER)
    await answer(r, body(), device=PHONE)
    out = await r.calls.send(UID, w.End(call_id=C1))
    assert out.device_id == PHONE
    _, other = await answer(r, body(), device=OTHER)
    assert other["commands"] == []


async def test_acked_and_expired_commands_are_not_handed_out_again() -> None:
    r = rig()
    await r.calls.send(UID, w.End(call_id=C1))
    _, got = await answer(r, body())
    cid = json.loads(got["commands"][0]["body"])["id"]
    _, again = await answer(r, body())
    assert len(again["commands"]) == 1  # not acked yet: handed out again, the phone dedupes
    _, acked = await answer(r, body(acks=[cid]))
    assert acked["commands"] == []
    await r.calls.send(UID, w.Answer(call_id=C1))
    r.clock.now += pc.TTL_S["call.answer"] + 1
    _, late = await answer(r, body())
    assert late["commands"] == []


async def test_the_outbox_is_bounded_per_phone() -> None:
    r = rig()
    for i in range(pc.OUTBOX_MAX + 5):
        await r.calls.send(UID, w.End(call_id=f"call_{i:012x}"))
    _, got = await answer(r, body())
    assert len(got["commands"]) == pc.OUTBOX_MAX
    assert json.loads(got["commands"][-1]["body"])["call_id"] == f"call_{pc.OUTBOX_MAX + 4:012x}"


async def test_a_waiting_phone_gets_a_command_sent_while_it_waits() -> None:
    r = rig()

    async def later() -> None:
        await asyncio.sleep(0.05)
        await r.calls.send(UID, w.End(call_id=C1))

    task = asyncio.create_task(later())
    status, got = await answer(r, body(wait=2))
    await task
    assert status == 200 and len(got["commands"]) == 1


async def test_a_wait_with_nothing_to_send_ends_on_time() -> None:
    r = rig(max_wait_s=0.05)
    status, got = await answer(r, body(wait=25))
    assert status == 200 and got["commands"] == []


# ---- events ------------------------------------------------------------------------------------
async def test_call_states_reach_the_engine_once_each() -> None:
    r = rig()
    evs = [state_event("dialing"), state_event("active"), state_event("ended")]
    status, _ = await answer(r, body(evs))
    assert status == 200
    assert [s.state for s in r.sink.states] == ["dialing", "active", "ended"]
    assert r.calls.last_state(C1) is not None
    assert r.calls.last_state(C1).state == "ended"  # type: ignore[union-attr]
    await answer(r, body(evs))  # the phone retried the same batch
    assert len(r.sink.states) == 3


async def test_an_incoming_number_reaches_the_engine_only_while_answering_is_on() -> None:
    r = rig()
    ring = state_event("ringing", call_id=None, number_e164=NUMBER, rings=1)
    _, got = await answer(r, body([ring]))
    assert r.sink.states[-1].number_e164 is None
    assert got["answering"] == {"on": False, "after_rings": 5, "number": False}
    r.answering.on = True
    ring = state_event("ringing", call_id=None, number_e164=NUMBER, rings=5)
    _, got = await answer(r, body([ring], can=can(number=True)))
    assert r.sink.states[-1].number_e164 == NUMBER and r.sink.states[-1].rings == 5
    assert got["answering"] == {"on": True, "after_rings": 5, "number": True}


async def test_a_number_on_anything_but_a_ringing_call_is_refused() -> None:
    r = rig()
    status, _ = await answer(r, body([state_event("active", number_e164=NUMBER)]))
    assert status == 422 and r.sink.states == []


async def test_stale_and_future_events_are_dropped_but_answered() -> None:
    r = rig()
    old = state_event("ended", at=int(T0 - pc.EVENT_MAX_AGE_S - 1))
    ahead = state_event("ended", at=int(T0 + 600))
    status, got = await answer(r, body([old, ahead]))
    assert status == 200 and r.sink.states == [] and got["took"] == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"v":1}',
        b"not json",
        b'{"v": 1, "app_version": "18.0.0"}',
        "body_with_spaces",
        "nine_events",
        "unknown_kind",
        "extra_field",
        "bool_rings",
    ],
)
async def test_a_body_of_the_wrong_shape_is_refused(raw: Any) -> None:
    r = rig()
    if raw == "body_with_spaces":
        raw = body().replace(b",", b", ")
    elif raw == "nine_events":
        raw = body([state_event("active") for _ in range(w.EVENTS_MAX + 1)])
    elif raw == "unknown_kind":
        raw = body([{**state_event("active"), "type": "call.record"}])
    elif raw == "extra_field":
        raw = body([{**state_event("active"), "audio": "x"}])
    elif raw == "bool_rings":
        raw = body([{**state_event("ringing"), "rings": True}])
    status, got = await answer(r, raw)
    assert status == 422 and got == {"error": "input_rejected"}
    assert r.sink.states == []


async def test_events_past_the_rate_are_refused_with_429() -> None:
    r = rig()
    sent = 0
    status = 200
    while status == 200 and sent < 200:
        status, _ = await answer(r, body([state_event("active") for _ in range(w.EVENTS_MAX)]))
        sent += w.EVENTS_MAX
    assert status == 429
    assert len(r.sink.states) <= pc.EVENTS_PER_MINUTE


async def test_an_engine_failure_answers_503_and_the_retry_is_delivered() -> None:
    r = rig()
    r.sink.fail_once = True
    ev = state_event("active")
    status, _ = await answer(r, body([ev]))
    assert status == 503
    status, _ = await answer(r, body([ev]))
    assert status == 200 and [s.state for s in r.sink.states] == ["active"]


async def test_command_results_reach_the_engine() -> None:
    r = rig()
    ev = {
        "id": "pe_00000000000000aa",
        "type": "call.result",
        "command_id": "pc_" + "2" * 16,
        "call_id": C1,
        "command": "call.route",
        "ok": False,
        "code": "route_refused",
        "at": int(T0),
    }
    status, _ = await answer(r, body([ev]))
    assert status == 200
    (res,) = r.sink.results
    assert res.command == "call.route" and not res.ok and res.code == "route_refused"


async def test_a_card_decision_goes_to_the_cards_and_its_outcome_comes_back() -> None:
    r = rig()
    r.cards.outcome = "passkey_needed"
    ev = {
        "id": "pe_00000000000000bb",
        "type": "card.decision",
        "card_id": K1,
        "decision": "approve",
        "at": int(T0),
    }
    status, got = await answer(r, body([ev]))
    assert status == 200
    assert r.cards.seen == [(K1, "approve", PHONE)]
    assert got["decisions"] == [{"card_id": K1, "outcome": "passkey_needed"}]


async def test_without_a_card_desk_a_decision_is_unavailable() -> None:
    r = rig(cards=None)
    ev = {
        "id": "pe_00000000000000cc",
        "type": "card.decision",
        "card_id": K1,
        "decision": "decline",
        "at": int(T0),
    }
    _, got = await answer(r, body([ev]))
    assert got["decisions"] == [{"card_id": K1, "outcome": "unavailable"}]


# ---- readiness, audit and logs -----------------------------------------------------------------
async def test_readiness_names_what_is_missing() -> None:
    r = rig()
    ready = await r.calls.readiness(UID)
    assert ready.device_id == PHONE and ready.ready and "not_checked_in" in ready.problems
    await answer(r, body(can=can(place=False, notify=False)))
    ready = await r.calls.readiness(UID)
    assert not ready.ready and {"cannot_place", "no_notifications"} <= set(ready.problems)
    none = await rig(phones=Directory(phones=[])).calls.readiness(UID)
    assert not none.ready and none.problems == ("no_phone",)


async def test_every_command_and_event_is_audited_without_a_full_number() -> None:
    r = rig()
    r.answering.on = True
    await r.calls.send(UID, dial())
    await answer(r, body([state_event("ringing", call_id=None, number_e164=NUMBER, rings=1)]))
    tools = [row["tool"] for row in r.audit.rows]
    assert tools == ["calls_phone_command", "calls_phone_event"]
    assert NUMBER not in json.dumps(r.audit.rows)
    assert r.audit.rows[0]["args"]["number"] == w.mask_number(NUMBER)


async def test_no_log_line_carries_a_full_number(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="jarvis")
    r = rig()
    r.answering.on = True
    await r.calls.send(UID, dial())
    other = w.Dial(call_id=C2, number="+919000000002", approval_id="x" * 8)
    await r.calls.send(UID, other)
    await answer(r, body([state_event("ringing", call_id=None, number_e164=NUMBER, rings=1)]))
    await answer(r, body([state_event("active", number_e164=NUMBER)]))
    text = " ".join(f"{rec.getMessage()} {rec.__dict__}" for rec in caplog.records)
    assert NUMBER not in text and "9000000001" not in text and "9000000002" not in text


def test_the_mask_keeps_only_the_country_code_and_the_last_two_digits() -> None:
    assert w.mask_number(NUMBER) == "+91********01"
    assert w.mask_number(None) == ""
    assert w.mask_number("12") == "**"


async def test_the_door_handler_is_offered_for_the_calls_route() -> None:
    r = rig()
    door = r.calls.door_handlers()
    assert set(door) == {pc.DOOR_ROUTE}
    reply = await door[pc.DOOR_ROUTE](req(body()))
    assert reply.status == 200


# ---- I0's seams ----------------------------------------------------------------------------------
async def test_the_owner_link_is_i0s_phone_link_and_raises_when_nothing_was_queued() -> None:
    r = rig()
    link = pc.OwnerPhoneLink(r.calls, UID)
    await link.send(CallDial(call_id=C1, number=NUMBER, approval_id="ap_live_000001"))
    await link.send(CallAnswer(call_id=C1))
    await link.send(CallRoute(call_id=C1, to="bluetooth"))
    await link.send(CallEnd(call_id=C1))
    _, got = await answer(r, body())
    assert [json.loads(c["body"])["type"] for c in got["commands"]] == [
        "call.dial",
        "call.answer",
        "call.route",
        "call.end",
    ]
    with pytest.raises(pc.PhoneCommandRefused) as refused:
        await link.send(CallDial(call_id=C2, number=NUMBER, approval_id="ap_gone_000001"))
    assert refused.value.code == "approval"
    await answer(r, body([state_event("active")]))
    last = link.last_state()
    assert isinstance(last, CallStateEvent) and last.state == "active" and last.call_id == C1


async def test_an_international_number_from_the_protocol_is_refused_before_any_check() -> None:
    r = rig()
    out = await r.calls.send(UID, CallDial(call_id=C1, number="+14155550100", approval_id="a" * 8))
    assert out.status == "refused" and out.code == "number" and r.approvals.asked == []


async def test_the_engine_gets_i0s_call_state_with_an_aware_time() -> None:
    r = rig()
    await answer(r, body([state_event("dialing")]))
    (got,) = r.sink.states
    assert isinstance(got, CallStateEvent)
    assert got.at.tzinfo is not None and int(got.at.timestamp()) == int(T0)


def test_a_card_notice_comes_from_i0s_call_card() -> None:
    card = CallCard(
        number_e164=NUMBER, contact_name="Laundry\u200b", purpose="Pickup", new_number=True
    )
    notice = w.Card.for_card(card)
    assert notice.card_id == card.id and notice.label == "Laundry" and notice.passkey
    nameless = w.Card.for_card(CallCard(number_e164=NUMBER, purpose="Pickup"))
    assert nameless.label == "your call" and not nameless.passkey
