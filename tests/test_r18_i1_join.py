# tests/test_r18_i1_join.py -- R18 I1: the join of the calls parts (docs/plans/r18-integration/
# I1-NOTES.md). The wired app (every slot, the tools, the door route, the retention job), the
# adapters between the parts (dial gate, the phone's look at a dial, slots, records in the vault,
# answering, the phone's card decisions, phone results), metering in one place, the speech
# choice, English before its first check, the language check in the background, and the image
# carrying the call desk's kit. No network, no audio device, no real call.
from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from calls_a1_fakes import NUMBER, UID, known, rig
from calls_a1_fakes import api as a1_api
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.calls_console import ConsoleCardsApi
from jarvis.api.r18_wiring import R18Parts
from jarvis.calls.approvals import GrantBook
from jarvis.calls.brain import Line
from jarvis.calls.cards import offered, provisional
from jarvis.calls.join import (
    BookingSlots,
    GrantGate,
    HubAnswering,
    HubPhoneSink,
    PhoneApprovals,
    PhoneCardDesk,
    VaultRecords,
)
from jarvis.calls.join_speech import CallSpeech, CallSpend, CallTally, LanguageCheckJob
from jarvis.calls.models import (
    Booking,
    CallCard,
    CallRecord,
    CallSettings,
    LanguageResult,
    SpeechOption,
    TimeWindow,
)
from jarvis.calls.ports import CallsRefused, SpeechUnavailable
from jarvis.calls.protocol import CallStateEvent
from jarvis.calls.records import RecordKeeper, SealedBlobs
from jarvis.calls.speech.build import SpeechOptions
from jarvis.calls.store import MemoryCallStore
from jarvis.calls.summary import CallSummary
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.mobile.contract import signing_string
from jarvis.mobile.ports import DOOR_CAPS, DOOR_OWNER, DOOR_ROUTES
from jarvis.vault.crypto import VaultCrypto

ROOT = Path(__file__).resolve().parents[1]
KEY = SecretStr(base64.b64encode(bytes(range(1, 33))).decode())
H = {"X-Requested-With": "JARVIS"}
NOW = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)  # 12:00 IST


# ---- the wired app -------------------------------------------------------------------------------
@pytest.fixture
async def wired(settings: Any) -> AsyncIterator[Any]:
    s = settings.model_copy(update={"token_key": KEY, "tools_enabled": True})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        yield app


async def test_the_app_wires_every_calls_slot_tool_route_and_job(wired: Any) -> None:
    st = wired.state
    assert isinstance(st.r18_parts, R18Parts) and isinstance(st.calls_api, ConsoleCardsApi)
    assert st.calls_sockets is not None and st.calls_desk_door is not None
    names = {x.name for x in st.gateway.registry.specs()}
    assert {"calls_place", "calls_answer_mode"} <= names
    assert "calls_retention" in [j.name for j in st.tick_jobs]
    phone = st.r7_parts["phone"].services["phone_calls"]
    assert st.r18_parts.phone is phone
    assert phone.approvals is not None and phone.sink is not None and phone.cards is not None
    assert "calls" in st.r7_parts["phone"].services["door"]
    async with AsyncClient(transport=ASGITransport(app=wired), base_url="http://test") as c:
        status = (await c.get("/v1/calls/status", headers=H)).json()
        langs = (await c.get("/v1/calls/languages", headers=H)).json()
    assert status["desk"]["connected"] is False and status["phone"]["linked"] is False
    assert status["month"]["cap_inr"] == 200 and status["today"]["max"] == 10
    english = next(r for r in langs["languages"] if r["lang"] == "en-IN")
    assert english["offered"] is True and english["checked"] is False  # "not yet checked"
    assert langs["check"]["running"] is False


async def test_without_the_token_key_nothing_is_wired_and_the_routes_say_so(settings: Any) -> None:
    app = create_app(
        settings.model_copy(update={"tools_enabled": True}),
        provider=MockProvider(),
        store=InMemorySessionStore(),
    )
    async with app.router.lifespan_context(app):
        assert app.state.r18_parts is None and getattr(app.state, "calls_api", None) is None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            got = await c.get("/v1/calls/status", headers=H)
    assert got.status_code == 501 and got.json()["error"] == "not_built"


def test_the_phone_door_has_the_calls_route() -> None:
    assert "calls" in DOOR_ROUTES and DOOR_OWNER["calls"] == "phone"
    assert DOOR_CAPS["calls"] == 16 * 1024
    signing_string("d", 1, "n", "POST", "/phone/v1/calls", b"{}")  # the door signs this path


def test_the_image_carries_the_call_desk_kit() -> None:
    assert "COPY deploy/calldesk ./deploy/calldesk" in (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "!deploy/calldesk" in ignore and ignore.index("!deploy/calldesk") > ignore.index(
        "deploy"
    )


def test_the_mock_evals_run_the_calls_language_suite() -> None:
    assert '"calls_language" / "run.py"' in (ROOT / "evals" / "run_all_mock.py").read_text()


# ---- the dial: A2's gate on A1's grant, D's look at it -------------------------------------------
async def _approved(r: Any) -> tuple[CallCard, str]:
    await known(r.store)
    api = a1_api(r)
    made = await api.create_card(UID, {"number": NUMBER, "purpose": "Book a pickup"})
    done = await api.approve(UID, made["id"], {})
    assert done["status"] == "placing"
    _, card_id, approval_id = r.starter.started[-1]
    card = await r.store.get_card(UID, card_id)
    assert card is not None
    return card, approval_id


async def test_the_dial_gate_spends_the_grant_for_this_call_and_the_phone_sees_it() -> None:
    r = await rig()
    card, approval = await _approved(r)
    gate, phone = GrantGate(r.service), PhoneApprovals(r.service.grants)
    call_id = "call_0000000000aa"
    assert await phone.live_until(UID, approval, call_id, NUMBER) is None  # not dialled yet
    assert await gate.before_dial(UID, card, approval, call_id) is None
    until = await phone.live_until(UID, approval, call_id, NUMBER)
    assert until is not None and until > r.clock().timestamp()
    assert await phone.live_until(UID, approval, call_id, NUMBER) == until  # spends nothing
    assert await phone.live_until(UID, approval, "call_0000000000bb", NUMBER) is None
    assert await phone.live_until(UID, approval, call_id, "+919000000002") is None
    assert await phone.live_until("u_someone_else", approval, call_id, NUMBER) is None
    again = await gate.before_dial(UID, card, approval, "call_0000000000bb")
    assert again is not None and "Approve it again" in again  # one use
    r.clock.advance(seconds=180)
    assert await phone.live_until(UID, approval, call_id, NUMBER) is None  # 2 minutes at most


async def test_a_changed_card_is_not_dialled() -> None:
    r = await rig()
    card, approval = await _approved(r)
    edited = card.model_copy(update={"purpose": "Something else"})
    words = await GrantGate(r.service).before_dial(UID, edited, approval, "call_0000000000aa")
    assert words is not None and "changed" in words


async def test_the_grant_book_peek_needs_a_taken_grant() -> None:
    book = GrantBook(lambda: NOW)
    card = CallCard(number_e164=NUMBER, purpose="x")
    grant = await book.issue(UID, card)
    assert await book.live_until(UID, grant.id, "call_0000000000aa", NUMBER) is None


# ---- a booking's slot ----------------------------------------------------------------------------
def test_the_engine_slot_check_is_a1s_rule() -> None:
    day = date(2026, 11, 28)
    b = Booking(
        windows=(TimeWindow(day=day, start=time(10), end=time(12)),),
        give_name="Sam",
        reason="Laundry pickup",
    )
    slots = BookingSlots(lambda: NOW)
    assert slots.within(b, day, time(10, 30), time(11, 0))
    assert not slots.within(b, day, time(11, 45), time(12, 30))  # ends outside
    assert not slots.within(b, day, time(11, 0), time(10, 0))  # ends before it starts
    assert not slots.within(b, date(2026, 11, 26), time(10, 30), None)  # in the past


# ---- records in the vault ------------------------------------------------------------------------
def _keeper(store: MemoryCallStore) -> RecordKeeper:
    blobs = SealedBlobs(store.docs, VaultCrypto(Keyring(bytes(range(32)))), prefix="t_")
    return RecordKeeper(store, blobs)


def _frames(n: int) -> bytes:
    return (1000).to_bytes(2, "little", signed=True) * 320 * n


LINES = [
    Line(
        who="jarvis", lang="en-IN", text="Hello, this is JARVIS.", english="Hello, this is JARVIS."
    ),
    Line(who="them", lang="ml-IN", text="നമസ്കാരം", english="Hello"),
]


async def test_the_call_is_sealed_at_its_end_audio_transcript_and_summary() -> None:
    store = MemoryCallStore()
    keeper = _keeper(store)
    sink = VaultRecords(keeper)
    rec = CallRecord(number_e164=NUMBER, started_at=NOW, recorded=True, cost_inr=1.5)
    for _ in range(3):
        await sink.audio(UID, rec.id, _frames(50))  # three seconds, 16 kHz
    summary = CallSummary(text="Pickup booked.", agreed=["Saturday 10:00"])
    done = await sink.finish(UID, rec, card=None, summary=summary, lines=LINES, booked=None)
    assert done.audio_ref and done.transcript_ref and done.summary_ref
    audio, media = await keeper.audio(UID, rec.id)
    assert media == "audio/wav" and audio[:4] == b"RIFF"
    assert int.from_bytes(audio[24:28], "little") == 8_000  # kept at the phone line's rate
    assert len(audio) - 44 == 3 * 8_000 * 2
    kept = await keeper.transcript(UID, rec.id)
    assert kept is not None and [ln.who.value for ln in kept.lines] == ["jarvis", "them"]
    assert kept.lines[0].english == ""  # spoken in English: no translation kept
    told = await keeper.summary(UID, rec.id)
    assert told is not None and told.english == "Pickup booked." and told.cost_inr == 1.5


async def test_an_objection_keeps_no_audio_and_no_transcript() -> None:
    store = MemoryCallStore()
    keeper = _keeper(store)
    sink = VaultRecords(keeper)
    rec = CallRecord(number_e164=NUMBER, started_at=NOW, recorded=True)
    await sink.audio(UID, rec.id, _frames(50))
    await sink.objection(UID, rec.id)
    await sink.audio(UID, rec.id, _frames(50))  # nothing more is held
    gone = rec.model_copy(update={"recorded": False, "objected": True})
    done = await sink.finish(
        UID, gone, card=None, summary=CallSummary(text="Notes."), lines=LINES, booked=None
    )
    assert done.audio_ref is None and done.transcript_ref is None and done.summary_ref


async def test_a_failing_part_never_loses_the_others() -> None:
    store = MemoryCallStore()
    keeper = _keeper(store)
    await store.save_settings(UID, {"record_audio": False})  # the audio is refused
    sink = VaultRecords(keeper)
    rec = CallRecord(number_e164=NUMBER, started_at=NOW, recorded=True)
    await sink.audio(UID, rec.id, _frames(50))
    done = await sink.finish(
        UID, rec, card=None, summary=CallSummary(text="Done."), lines=LINES, booked=None
    )
    assert done.audio_ref is None and done.transcript_ref and done.summary_ref


# ---- answering, the phone's card decisions and results -------------------------------------------
class _Decision:
    def __init__(self, answer: bool) -> None:
        self.answer = answer


class _Policy:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.events: list[CallStateEvent] = []

    async def should_answer(self, uid: str, event: CallStateEvent) -> _Decision:
        self.events.append(event)
        return _Decision(self.answer)


async def test_the_hub_asks_a1s_answering_policy_with_the_ringing_event() -> None:
    policy = _Policy(True)
    yes = await HubAnswering(policy, lambda: NOW).should_answer(UID, NUMBER, 6, CallSettings())
    ev = policy.events[0]
    assert yes and ev.state == "ringing" and ev.call_id is None and ev.number_e164 == NUMBER
    assert ev.rings == 6


class _Cards:
    def __init__(self, approve: Any = None, refuse: CallsRefused | None = None) -> None:
        self.out, self.refuse = approve or {"status": "placing"}, refuse
        self.calls: list[tuple[str, str]] = []

    async def approve(self, uid: str, card_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("approve", card_id))
        if self.refuse is not None:
            raise self.refuse
        return dict(self.out)

    async def cancel(self, uid: str, card_id: str) -> dict[str, Any]:
        self.calls.append(("cancel", card_id))
        return {}


async def test_the_phones_approve_is_his_press_and_a_new_number_needs_the_console() -> None:
    store = MemoryCallStore()
    old = CallCard(number_e164=NUMBER, purpose="x")
    new = CallCard(number_e164=NUMBER, purpose="y", new_number=True)
    await store.put_card(UID, old)
    await store.put_card(UID, new)
    cards = _Cards()
    desk = PhoneCardDesk(lambda: cards, store)
    assert await desk.decide(UID, old.id, "approve", "d1") == "approved"
    assert await desk.decide(UID, new.id, "approve", "d1") == "passkey_needed"
    assert ("approve", new.id) not in cards.calls  # never pressed for a never-called number
    assert await desk.decide(UID, old.id, "decline", "d1") == "declined"
    assert await desk.decide(UID, "cc_000000000000", "approve", "d1") == "gone"
    passkey = PhoneCardDesk(lambda: _Cards({"status": "needs_passkey"}), store)
    assert await passkey.decide(UID, old.id, "approve", "d1") == "passkey_needed"
    spent = _Cards(refuse=CallsRefused(409, "gone", "spent"))
    assert await PhoneCardDesk(lambda: spent, store).decide(UID, old.id, "approve", "d") == "gone"
    assert await PhoneCardDesk(lambda: None, store).decide(UID, old.id, "approve", "d") == (
        "unavailable"
    )


class _Hub:
    def __init__(self) -> None:
        self.events: list[CallStateEvent] = []

    async def phone_event(self, uid: str, ev: CallStateEvent) -> None:
        self.events.append(ev)


class _Result:
    def __init__(self, command: str, ok: bool, code: str, call_id: str | None) -> None:
        self.command, self.ok, self.code, self.call_id = command, ok, code, call_id


async def test_phone_events_reach_the_hub_and_a_dial_the_phone_refused_ends_the_call() -> None:
    hub, refreshed = _Hub(), list[tuple[str, Any]]()

    async def refresh(uid: str, langs: Any) -> None:
        refreshed.append((uid, langs))

    sink = HubPhoneSink(hub, refresh, lambda: NOW)
    ringing = CallStateEvent(state="ringing", number_e164=NUMBER, rings=5, at=NOW)
    await sink.phone_state(UID, ringing)
    assert hub.events == [ringing] and refreshed == [(UID, None)]
    await sink.phone_result(UID, _Result("call.dial", False, "needs_tap", "call_0000000000aa"))
    assert len(hub.events) == 1  # he taps the notification: the call still goes on
    await sink.phone_result(UID, _Result("call.dial", False, "no_permission", "call_0000000000aa"))
    assert hub.events[-1].state == "ended" and hub.events[-1].call_id == "call_0000000000aa"


# ---- metering in one place -----------------------------------------------------------------------
class _Base:
    def __init__(self) -> None:
        self.models = 0

    async def model(self, uid: str, brain_id: str, completion: Any) -> float:
        self.models += 1
        return 0.25

    async def allowed(self, uid: str) -> bool:
        return True


def _prices(rate: float) -> Any:
    from jarvis.calls.prices import SpeechPrice

    return {SpeechOption.GOOGLE: SpeechPrice(SpeechOption.GOOGLE, 2.0, 3.0)}


async def _rate() -> float:
    return 95.0


async def test_speech_rupees_come_from_bs_meter_once_and_an_unknown_price_is_never_zero() -> None:
    tally, base = CallTally(), _Base()
    spend = CallSpend(base, tally, _prices, _rate)  # type: ignore[arg-type]
    tally("hearing", 0.5)  # B charged this hearing (Google past its free allowance)
    assert await spend.speech(UID, "google", "hear", 12.0) == 0.5
    assert await spend.speech(UID, "google", "hear", 12.0) == 0.0  # never counted twice
    tally("voice", 0.0)  # inside the free allowance
    assert await spend.speech(UID, "google", "voice", 80) == 0.0
    tally("hearing", None)  # Bhashini: no known price
    stand_in = await spend.speech(UID, "bhashini", "hear", 30.0)
    assert stand_in == pytest.approx(1.0)  # Google's ₹2 a minute for 30 s, not ₹0
    assert await spend.model(UID, "b", object()) == 0.25 and base.models == 1


# ---- the speech of a call ------------------------------------------------------------------------
class _Hear:
    def __init__(self, name: str) -> None:
        self.name = name

    async def transcribe(self, pcm16k: bytes, languages: Any) -> Any:
        raise AssertionError("not called here")


class _Say:
    def __init__(self, name: str) -> None:
        self.name = name

    async def speak(self, text: str, lang: str) -> bytes:
        return b""


def _options(*names: str) -> SpeechOptions:
    out = SpeechOptions()
    for n in names:
        out.hearing[n], out.voices[n] = _Hear(n), _Say(n)
    return out


async def test_the_check_chooses_and_english_falls_back_to_the_cloud() -> None:
    kit = CallSpeech(_options("google", "azure"), {"ml-IN": "azure"}, frozenset({"ml-IN"}))
    assert kit.hearing("ml-IN").name == "azure" and kit.voice("ml-IN").name == "azure"
    assert kit.hearing("en-IN").name == "google"  # English, not yet checked: Google first
    assert kit.voice("hi-IN").name == "google"  # the "unsupported" line's Hindi half
    assert kit.needs_balanced("ml-IN") and not kit.needs_balanced("en-IN")
    assert kit.detector() is None  # one language
    gone = CallSpeech(_options("google"), {"ml-IN": "azure"})  # Azure's key was taken away
    with pytest.raises(SpeechUnavailable):  # never Google, which Malayalam did not pass on
        await gone.hearing("ml-IN").transcribe(b"", ["ml-IN"])
    nothing = CallSpeech(_options(), {})
    with pytest.raises(SpeechUnavailable):
        await nothing.hearing("en-IN").transcribe(b"", ["en-IN"])
    with pytest.raises(SpeechUnavailable):
        await nothing.voice("en-IN").speak("hi", "en-IN")


def test_google_detects_inside_its_hearing_and_azure_tries_each() -> None:
    google = CallSpeech(_options("google"), {}, languages=("en-IN", "ml-IN"))
    assert google.detector() is None  # alternatives in one request, not a second one
    azure = CallSpeech(_options("azure"), {"en-IN": "azure"}, languages=("en-IN", "ta-IN"))
    assert type(azure.detector()).__name__ == "TryEachDetector"


def test_english_is_offered_not_yet_checked_until_its_first_result() -> None:
    s = CallSettings()
    first = offered([], s)
    assert "en-IN" in first and provisional(first["en-IN"])
    failed = LanguageResult(lang="en-IN", option=SpeechOption.GOOGLE, checked_at=NOW, passed=False)
    assert "en-IN" not in offered([failed], s)  # once checked, the check decides
    hindi = LanguageResult(lang="hi-IN", option=SpeechOption.GOOGLE, checked_at=NOW)
    assert "hi-IN" not in offered([hindi], s)  # every Indian language still needs a pass


# ---- the language check in the background --------------------------------------------------------
class _Plan:
    def __init__(self) -> None:
        from jarvis.calls.langcheck.runner import CheckPlan, PairPlan

        self.plan = CheckPlan((PairPlan("ml-IN", "google", True, True, inr=0.0),))


class _Check:
    def __init__(self, store: MemoryCallStore, gate: asyncio.Event) -> None:
        self.store, self.gate, self.runs = store, gate, 0

    async def plan(self, langs: Any, options: Any = None) -> Any:
        return _Plan().plan

    async def run(self, plan: Any, *, accept_inr: float, accept_unknown: bool) -> Any:
        from jarvis.calls.langcheck.runner import CheckReport

        self.runs += 1
        await self.gate.wait()
        await self.store.put_language_result(
            LanguageResult(
                lang="ml-IN",
                option=SpeechOption.GOOGLE,
                checked_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        )
        return CheckReport()


async def test_a_language_check_runs_in_the_background_with_its_progress() -> None:
    store, gate = MemoryCallStore(), asyncio.Event()
    check = _Check(store, gate)

    async def make(uid: str, settings: CallSettings) -> Any:
        return check

    job = LanguageCheckJob(make, store)
    est = await job.handle(UID, {})
    assert est["plan"]["total_inr"] == 0 and check.runs == 0  # the default is the estimate
    started = await job.handle(UID, {"estimate_only": False, "languages": ["ml-IN"]})
    assert started["check"]["running"] is True and started["check"]["total"] == 1
    with pytest.raises(CallsRefused) as busy:
        await job.handle(UID, {"estimate_only": False, "languages": ["ml-IN"]})
    assert busy.value.status == 409 and busy.value.code == "check_running"
    gate.set()
    for _ in range(50):
        await asyncio.sleep(0)
        if not job.progress.running:
            break
    view = await job.view()
    assert view["running"] is False and view["done"] == 1 and view["error"] is None
    with pytest.raises(CallsRefused) as bad:
        await job.handle(UID, {"languages": ["xx-IN"]})
    assert bad.value.status == 422


# ---- the console's names (E's console-calls-shapes.js) -----------------------------------------
def _console(r: Any) -> ConsoleCardsApi:
    base = a1_api(r)
    return ConsoleCardsApi(
        store=base.store,
        builder=base.builder,
        service=base.service,
        gateway=base.gateway,
        keeper=base.keeper,
        booking=base.booking,
        passkeys=r.passkeys,
        audit=r.audit,
    )


async def test_a_passkey_card_takes_a1s_two_presses() -> None:
    r = await rig(passkey=True)
    api = _console(r)
    card = await api.create_card(UID, {"number": NUMBER, "purpose": "Book a pickup"})
    assert card["new_number"] is True and card["needs_passkey"] is True
    first = await api.approve(UID, card["id"], {})  # A1's first press: the approval to prove
    assert first["status"] == "needs_passkey" and first["approval_id"]


async def test_the_console_reads_a_sealed_record_settings_and_the_language_table() -> None:
    r = await rig(languages=())
    api = _console(r)
    rec = CallRecord(number_e164=NUMBER, started_at=NOW, recorded=False)
    await r.store.put_record(UID, rec)
    sink = VaultRecords(api.keeper)
    await sink.finish(
        UID, rec, card=None, summary=CallSummary(text="Booked."), lines=LINES, booked=None
    )
    one = await api.get_record(UID, rec.id)  # A1's own view, as the console reads it
    assert one["summary"]["english"] == "Booked."
    assert [ln["who"] for ln in one["transcript"]["lines"]] == ["jarvis", "them"]
    settings = await api.get_settings(UID)
    assert settings["azure_status"] == "off" and settings["templates"]
    langs = await api.languages(UID)
    english = [x for x in langs["results"] if x["lang"] == "en-IN"]
    assert english and english[0]["passed"] is True and english[0]["not_checked"] is True


async def test_the_console_runs_the_check_with_the_rupees_it_showed() -> None:
    store, gate = MemoryCallStore(), asyncio.Event()
    check = _Check(store, gate)

    async def make(uid: str, settings: CallSettings) -> Any:
        return check

    job = LanguageCheckJob(make, store)
    est = await job.handle(UID, {"confirm": False})
    assert est["estimate_inr"] == 0 and est["languages"] == 1 and check.runs == 0
    gate.set()
    ran = await job.handle(UID, {"confirm": True, "estimate_inr": 0})
    assert ran["check"]["running"] is True


async def test_a_confirmed_settings_change_from_the_console_raises_the_cap(wired: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=wired), base_url="http://test") as c:
        refused = await c.put("/v1/calls/settings", json={"month_cap_inr": 400}, headers=H)
        assert refused.status_code == 422 and refused.json()["error"] == "confirm_raise"
        done = await c.put("/v1/calls/settings?confirm=1", json={"month_cap_inr": 400}, headers=H)
    assert done.status_code == 200 and done.json()["month_cap_inr"] == 400


# ---- the dial reaches the phone only after the gate (A2 -> A1 -> D) ------------------------------
class _Directory:
    def __init__(self, at: float) -> None:
        from jarvis.phone.store import Phone

        self.phones = [
            Phone(
                id="ph_0123456789ab",
                model="phone",
                public_key="04" + "ab" * 64,
                package="io.github.shark2558.jarvis",
                fingerprint="cd" * 32,
                linked_at=at - 86_400,
                last_seen=at - 60,
                app_version="18.0.0",
            )
        ]

    async def linked(self, uid: str) -> list[Any]:
        return list(self.phones) if uid == UID else []


async def test_a_dial_is_queued_for_the_phone_only_for_the_call_the_gate_let_through() -> None:
    from jarvis.calls.protocol import CallDial
    from jarvis.phone.calls import OwnerPhoneLink, PhoneCalls, PhoneCommandRefused
    from jarvis.phone.calls_wire import CommandSigner

    r = await rig()
    card, approval = await _approved(r)
    now = lambda: r.clock().timestamp()  # noqa: E731 - one clock for both sides
    phone = PhoneCalls(
        phones=_Directory(now()),
        signer=CommandSigner.ephemeral(),
        approvals=PhoneApprovals(r.service.grants),
        clock=now,
    )
    link = OwnerPhoneLink(phone, UID)
    dial = CallDial(call_id="call_0000000000aa", number=NUMBER, approval_id=approval)
    with pytest.raises(PhoneCommandRefused) as early:
        await link.send(dial)  # the gate has not spent the grant for this call yet
    assert early.value.code == "approval"
    assert await GrantGate(r.service).before_dial(UID, card, approval, dial.call_id) is None
    await link.send(dial)  # queued for the phone, signed
    other = dial.model_copy(update={"call_id": "call_0000000000bb"})
    with pytest.raises(PhoneCommandRefused):
        await link.send(other)


async def test_the_call_speaks_with_the_option_its_card_was_estimated_with() -> None:
    from jarvis.calls.join_speech import SpeechChoices

    store = MemoryCallStore()
    for option, inr in ((SpeechOption.GOOGLE, 1.2), (SpeechOption.AZURE, 0.0)):
        await store.put_language_result(
            LanguageResult(
                lang="ml-IN", option=option, checked_at=NOW, passed=True, inr_per_minute=inr
            )
        )
    choices = SpeechChoices(store)
    await choices.refresh(UID, ("en-IN", "ml-IN"))
    chosen, balanced, langs = choices.snapshot(UID)
    assert chosen == {"ml-IN": "azure"}  # A1's cheapest; English "not yet checked": the fallback
    assert langs == ("en-IN", "ml-IN") and balanced == frozenset()
    await choices.refresh(UID, None)  # an answered call: his default languages
    assert choices.snapshot(UID)[2] == ("en-IN",)


# ---- the chat's call card (E draws `call_card`; A1's press either way, once) ---------------------
async def test_a_chat_proposal_shows_its_card_and_either_approval_uses_it_once() -> None:
    from jarvis.llm.base import ToolCall
    from jarvis.tools.gateway import GatewayOutcome
    from jarvis.tools.reply_cards import CallReplyCard, collecting_cards
    from jarvis.tools.taint import context_trust

    r = await rig()
    await known(r.store)
    api = a1_api(r)
    chat = f"{UID}:session1"
    args = {"number": NUMBER, "purpose": "Book a laundry pickup"}
    cards: list[Any] = []
    with context_trust(untrusted=False), collecting_cards(cards):
        asked = await r.gateway.execute(
            ToolCall(id="t1", name="calls_place", arguments=args), scope=chat
        )
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending is not None
    (shown,) = cards
    assert isinstance(shown, CallReplyCard) and shown.kind == "call_card"
    assert shown.number_masked.endswith("0001") and shown.estimate_inr is not None
    stored = await r.store.get_card(UID, shown.id)
    assert stored is not None and stored.status.value == "draft"
    # his Call under the reply: the panel's press; the chat's own approval card is withdrawn
    done = await api.approve(UID, shown.id, {})
    assert done["status"] == "placing" and done["card_id"] == shown.id
    assert not [p for p in await r.gateway.pending() if p.scope == chat]
    with context_trust(untrusted=False):
        late = await r.gateway.execute(
            ToolCall(id="t1", name="calls_place", arguments=args),
            confirmation_id=asked.pending.id,
            scope=chat,
        )
    assert late.outcome is not GatewayOutcome.EXECUTED  # never a second call
    assert len(r.starter.started) == 1


async def test_approving_the_chats_own_card_uses_the_card_shown_under_it() -> None:
    from jarvis.llm.base import ToolCall
    from jarvis.tools.gateway import GatewayOutcome
    from jarvis.tools.reply_cards import collecting_cards
    from jarvis.tools.taint import context_trust

    r = await rig()
    await known(r.store)
    api = a1_api(r)
    chat = f"{UID}:session1"
    call = ToolCall(id="t1", name="calls_place", arguments={"number": NUMBER, "purpose": "Ask"})
    cards: list[Any] = []
    with context_trust(untrusted=False), collecting_cards(cards):
        asked = await r.gateway.execute(call, scope=chat)
        assert asked.pending is not None
        done = await r.gateway.execute(call, confirmation_id=asked.pending.id, scope=chat)
    assert done.outcome is GatewayOutcome.EXECUTED and done.result["card_id"] == cards[0].id
    with pytest.raises(CallsRefused) as again:  # the card under the reply is used
        await api.approve(UID, cards[0].id, {})
    assert again.value.code == "not_waiting"
