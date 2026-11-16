# tests/test_r62_book_listening.py -- R6.2 owner decision 4 (15 Nov 2026, 20:29 IST): the Book's
# voice costs nothing by default. Listening ("Ask by voice") and the show voice both default to the
# BROWSER; an owner-only switch in Book settings sets each to Browser (free) or Cloud, and a switch
# to Cloud needs the cost confirmed (`confirm_cost`, as the budget's `confirm_raise`), is saved per
# owner and audited without content; a guest can never set it. With a setting on the browser, no
# cloud STT or TTS call happens (negative controls through the real VoiceService and fake engines).
# The browser's words get the console's free R11.1 corrections through POST /v1/book/show/heard
# (text only, the same caps, rate limit and guest rule as /hear). A guest's cloud listening stays
# inside the free allowance and is never charged. Fixed clocks; made-up words only.
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from billing_fakes import NOW, UID, billing, registry
from billing_fakes import Clock as BillClock
from book_app_fakes import CSRF, book, book_app, open_book, owner_uid, register_passkey, sign_in
from book_hear_fakes import Ears, wav
from book_show_fakes import Clock
from pydantic import ValidationError
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.billing.service import BudgetUnavailable, FreeAllowanceUsed
from jarvis.buildbook import hear
from jarvis.buildbook.owner import (
    VOICE_RULE,
    BookSettings,
    BookSettingsPatch,
    BookSettingsStore,
    CostNotConfirmed,
    SettingsRejected,
)
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import Price, PriceList
from jarvis.voice.service import SpeakRequest, VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsStore

PATH = f"jarvis_book_settings/{UID}"
HOW_BROWSER = "Use the browser's voice."
MONEY = ("₹", "rupee", "charged", "spending", "limit", "minutes")  # never in a guest's words


# ---- the setting: browser by default, cloud only with the cost confirmed -------------------------
async def test_both_voices_default_to_the_browser() -> None:
    s = await BookSettingsStore(MemoryDocs()).get(UID)
    assert (s.listening, s.show_voice) == ("browser", "browser")
    assert BookSettings().listening == "browser" and BookSettings().show_voice == "browser"


@pytest.mark.parametrize("field", ["listening", "show_voice"])
async def test_a_switch_to_the_cloud_without_the_cost_confirmed_writes_nothing(field: str) -> None:
    docs = MemoryDocs()
    with pytest.raises(CostNotConfirmed) as err:
        await BookSettingsStore(docs).update(
            UID, BookSettingsPatch.model_validate({field: "cloud"})
        )
    assert isinstance(err.value, SettingsRejected) and docs.sets == 0
    assert "free" in str(err.value) and "confirm" in str(err.value).lower()


@pytest.mark.parametrize("field", ["listening", "show_voice"])
async def test_a_confirmed_switch_is_saved_and_the_confirmation_is_never_stored(field: str) -> None:
    docs = MemoryDocs()
    store = BookSettingsStore(docs)
    patch = BookSettingsPatch.model_validate({field: "cloud", "confirm_cost": True})
    got = await store.update(UID, patch)
    assert getattr(got, field) == "cloud" and await BookSettingsStore(docs).get(UID) == got
    stored = docs._data[PATH]
    assert stored[field] == "cloud" and stored["voice_rule"] == VOICE_RULE
    assert "confirm_cost" not in stored and "confirm_cost" not in got.model_dump()


async def test_back_to_the_browser_needs_no_confirmation() -> None:
    store = BookSettingsStore(MemoryDocs())
    await store.update(UID, BookSettingsPatch(listening="cloud", confirm_cost=True))
    got = await store.update(UID, BookSettingsPatch(listening="browser"))
    assert got.listening == "browser"


async def test_a_cloud_voice_saved_before_the_decision_reads_as_the_browser() -> None:
    """Before R6.2 every save wrote the old default ("cloud") whether he chose it or not, so a
    stored "cloud" without the R6.2 rule mark was never confirmed: it reads as the free browser."""
    docs = MemoryDocs()
    docs._data[PATH] = {"creator_name": "", "show_voice": "cloud", "talk_on": True}
    assert (await BookSettingsStore(docs).get(UID)).show_voice == "browser"
    docs._data[PATH] = {"show_voice": "cloud", "listening": "cloud", "voice_rule": VOICE_RULE}
    got = await BookSettingsStore(docs).get(UID)
    assert (got.show_voice, got.listening) == ("cloud", "cloud")
    docs._data[PATH] = {"listening": "robot", "voice_rule": VOICE_RULE}
    assert (await BookSettingsStore(docs).get(UID)).listening == "browser"


async def test_any_later_save_keeps_the_unconfirmed_cloud_off() -> None:
    docs = MemoryDocs()
    docs._data[PATH] = {"show_voice": "cloud"}  # an old document
    got = await BookSettingsStore(docs).update(UID, BookSettingsPatch(talk_on=False))
    assert got.show_voice == "browser" and docs._data[PATH]["voice_rule"] == VOICE_RULE


def test_the_new_fields_take_strict_types() -> None:
    for bad in ({"listening": "robot"}, {"listening": 1}, {"confirm_cost": "yes"}):
        with pytest.raises(ValidationError):
            BookSettingsPatch.model_validate(bad)


# ---- the owner's switch over HTTP: confirmed, saved, audited without content; never a guest's ----
async def _settings_app(settings: Settings, run: Callable[[Any, Any], Awaitable[None]]) -> None:
    async for app in book_app(settings, real_prefs=True):
        app.state.book_clock = Clock()
        async with sign_in(app) as c:
            await run(app, c)


def _audited(app: Any) -> list[dict[str, Any]]:
    """What each audit entry was asked to record (the chain itself keeps a hash of `args` only)."""
    rows: list[dict[str, Any]] = []
    audit = app.state.gateway.audit
    real = audit.append

    async def append(**kw: Any) -> Any:
        rows.append(kw)
        return await real(**kw)

    audit.append = append
    return rows


async def test_the_owner_switches_listening_to_the_cloud_only_with_the_cost_confirmed(
    settings: Settings,
) -> None:
    async def run(app: Any, c: Any) -> None:
        audited = _audited(app)
        r = await c.get("/v1/book/settings")
        assert r.status_code == 200 and r.json()["listening"] == "browser"
        assert r.json()["show_voice"] == "browser"
        r = await c.put("/v1/book/settings", json={"listening": "cloud"}, headers=CSRF)
        assert (r.status_code, r.json()["error"]) == (422, "confirm_needed")
        assert (await c.get("/v1/book/settings")).json()["listening"] == "browser"
        body = {"listening": "cloud", "confirm_cost": True}
        r = await c.put("/v1/book/settings", json=body, headers=CSRF)
        assert r.status_code == 200 and r.json()["listening"] == "cloud", r.text
        assert "confirm_cost" not in r.json()
        rows = [e for e in audited if e["tool"] == "book_settings"]
        assert rows[-1]["args"] == {"fields": ["listening"], "cost_confirmed": True}
        r = await c.put("/v1/book/settings", json={"show_voice": "browser"}, headers=CSRF)
        assert r.status_code == 200
        rows = [e for e in audited if e["tool"] == "book_settings"]
        assert rows[-1]["args"] == {"fields": ["show_voice"]}  # content-free: names, never values
        assert len(rows) == 2  # the refused, unconfirmed switch changed nothing and left no line

    await _settings_app(settings, run)


async def test_a_guest_browser_can_never_read_or_set_the_switch(settings: Settings) -> None:
    async def run(app: Any, c: Any) -> None:
        auth = await register_passkey(c)
        await open_book(c, auth, "guest")  # this browser is the guest's now (show-only, SEC-4)
        body = {"listening": "cloud", "show_voice": "cloud", "confirm_cost": True}
        r = await c.put("/v1/book/settings", json=body, headers=CSRF)
        assert r.status_code in (401, 423) and "listening" not in r.text, r.text
        assert (await c.get("/v1/book/settings")).status_code in (401, 423)
        saved = await app.state.book_settings.get(owner_uid())
        assert (saved.listening, saved.show_voice) == ("browser", "browser")

    await _settings_app(settings, run)


# ---- the script: the owner's saved choice, for both audiences ------------------------------------
async def _script(settings: Settings, audience: str, **prefs: str) -> dict[str, Any]:
    got: list[dict[str, Any]] = []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.book_prefs.values.update(prefs)
        async with sign_in(app) as c:
            h = book((await open_book(c, await register_passkey(c), audience))["token"])
            got.append((await c.get("/v1/book/show/script", headers=h)).json())
    return got[0]


@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_the_script_says_browser_for_both_by_default(
    settings: Settings, audience: str
) -> None:
    sc = await _script(settings, audience)
    assert (sc["voice"], sc["listening"]) == ("browser", "browser")


@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_a_guest_show_uses_the_owners_saved_choice(settings: Settings, audience: str) -> None:
    sc = await _script(settings, audience, show_voice="cloud", listening="cloud")
    assert (sc["voice"], sc["listening"]) == ("cloud", "cloud")


# ---- negative controls: on the browser, no cloud speech call at all ------------------------------
def _voice(stt: FakeSTT, tts: FakeTTS, docs: MemoryDocs | None = None) -> VoiceService:
    docs = docs or MemoryDocs()
    return VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=BillClock(NOW)),
        prices=PriceList.from_settings(Settings(_env_file=None)),
        engines=VoiceEngines(tts=tts, stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )


async def _speech(
    settings: Settings, audience: str, **prefs: str
) -> tuple[FakeSTT, FakeTTS, list[tuple[int, dict[str, Any]]]]:
    stt, tts, got = FakeSTT(), FakeTTS(), []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.voice = _voice(stt, tts)
        app.state.book_prefs.values.update(prefs)
        async with sign_in(app) as c:
            h = book((await open_book(c, await register_passkey(c), audience))["token"])
            r = await c.post(
                "/v1/book/show/hear", content=wav(1.0), headers={**h, "Content-Type": "audio/wav"}
            )
            got.append((r.status_code, r.json()))
            r = await c.post("/v1/book/show/speak", json={"line_id": "ask"}, headers=h)
            got.append((r.status_code, r.json() if r.status_code != 200 else {}))
    return stt, tts, got


@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_on_the_browser_no_cloud_speech_call_happens(
    settings: Settings, audience: str
) -> None:
    stt, tts, ((hear_code, heard), (speak_code, spoke)) = await _speech(settings, audience)
    assert stt.calls == [] and tts.calls == []  # the negative control: no STT, no TTS
    assert (hear_code, heard["error"]) == (409, "listening_browser")
    assert heard["detail"] == hear.words("listening_browser", owner=audience == "owner")
    assert (speak_code, spoke["reason"]) == (503, "browser")


async def test_switched_to_the_cloud_the_same_calls_do_reach_the_engines(
    settings: Settings,
) -> None:
    """The positive control: the negative one above would catch a call if there were one."""
    stt, tts, ((hear_code, _), (speak_code, _)) = await _speech(
        settings, "owner", listening="cloud", show_voice="cloud"
    )
    assert (hear_code, speak_code) == (200, 200)
    assert len(stt.calls) == 1 and len(tts.calls) == 1


# ---- a guest's narration (security review 2, LOW-1): inside the free allowance only --------------
async def _use_up_tts(svc: VoiceService) -> None:
    for price in (svc.prices.chirp3_hd, svc.prices.studio):
        await _used(svc, price.free_units, price)


async def test_free_only_narration_never_reaches_google_once_the_allowance_is_used() -> None:
    stt, tts = FakeSTT(), FakeTTS()
    svc = _voice(stt, tts)
    await _use_up_tts(svc)
    before = (await svc.billing.month(UID)).inr_total
    with pytest.raises(FreeAllowanceUsed):
        await svc.speak(UID, SpeakRequest(text="Welcome to the tour."), free_only=True)
    assert tts.calls == [] and (await svc.billing.month(UID)).inr_total == before


async def test_free_only_narration_inside_the_allowance_goes_ahead_free() -> None:
    tts = FakeTTS()
    svc = _voice(FakeSTT(), tts)
    out = await svc.speak(UID, SpeakRequest(text="Welcome to the tour."), free_only=True)
    assert len(tts.calls) == 1 and out.cost_inr == 0


async def _narrate(
    settings: Settings, audience: str, *, used_up: bool
) -> tuple[FakeTTS, int, dict[str, Any]]:
    tts, got = FakeTTS(), []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.voice = svc = _voice(FakeSTT(), tts)
        app.state.book_prefs.values.update(show_voice="cloud")
        if used_up:
            await _use_up_tts(svc)
        async with sign_in(app) as c:
            h = book((await open_book(c, await register_passkey(c), audience))["token"])
            r = await c.post("/v1/book/show/speak", json={"line_id": "ask"}, headers=h)
            got.append((r.status_code, r.json() if r.status_code != 200 else {}))
    return tts, got[0][0], got[0][1]


async def test_a_guests_narration_past_the_free_allowance_is_the_browsers_voice(
    settings: Settings,
) -> None:
    tts, code, body = await _narrate(settings, "guest", used_up=True)
    assert (code, body["error"], body["detail"]) == (503, "voice_unavailable", HOW_BROWSER)
    assert tts.calls == [] and [w for w in MONEY if w in body["detail"].lower()] == []


async def test_a_guests_narration_inside_the_free_allowance_is_the_cloud_voice(
    settings: Settings,
) -> None:
    tts, code, _ = await _narrate(settings, "guest", used_up=False)
    assert code == 200 and len(tts.calls) == 1


async def test_the_owners_own_narration_is_not_cut_at_the_free_allowance(
    settings: Settings,
) -> None:
    """He chose and confirmed Cloud: past the free allowance his own show goes on, priced."""
    tts, code, _ = await _narrate(settings, "owner", used_up=True)
    assert code == 200 and len(tts.calls) == 1


# ---- a guest's cloud listening: inside the free allowance only, never charged --------------------
async def _hear(settings: Settings, ears: Ears, audience: str) -> tuple[int, dict[str, Any]]:
    got: list[tuple[int, dict[str, Any]]] = []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.voice = ears
        app.state.book_prefs.values["listening"] = "cloud"
        async with sign_in(app) as c:
            h = book((await open_book(c, await register_passkey(c), audience))["token"])
            r = await c.post(
                "/v1/book/show/hear", content=wav(1.0), headers={**h, "Content-Type": "audio/wav"}
            )
            got.append((r.status_code, r.json()))
    return got[0]


@pytest.mark.parametrize(("audience", "free_only"), [("guest", True), ("owner", False)])
async def test_only_a_guests_cloud_listening_is_free_only(
    settings: Settings, audience: str, free_only: bool
) -> None:
    ears = Ears(heard="how does the vault work")
    code, _ = await _hear(settings, ears, audience)
    assert code == 200 and ears.asked[0]["free_only"] is free_only


async def test_a_guest_past_the_free_allowance_is_told_plainly(settings: Settings) -> None:
    code, body = await _hear(settings, Ears(error=FreeAllowanceUsed()), "guest")
    assert (code, body["error"], body["reason"]) == (503, "voice_unavailable", "free_used")
    assert body["detail"] == hear.words("free_used", owner=False)
    assert [w for w in MONEY if w in body["detail"].lower()] == [], body["detail"]


async def _used(svc: VoiceService, units: float, price: Price | None = None) -> None:
    p = price or svc.prices.stt
    await svc.billing.record_units(
        UID,
        key=p.key,
        units=units,
        free_units=p.free_units,
        usd_per_unit=p.usd_per_unit,
        label="x",
    )


async def test_a_free_only_question_never_reaches_google_once_the_allowance_is_used() -> None:
    stt, tts = FakeSTT(), FakeTTS()
    svc = _voice(stt, tts)
    await _used(svc, svc.prices.stt.free_units)
    before = (await svc.billing.month(UID)).inr_total
    with pytest.raises(FreeAllowanceUsed):
        await svc.transcribe(UID, wav(1.0), owner_phrases=False, free_only=True)
    assert stt.calls == [] and (await svc.billing.month(UID)).inr_total == before
    await svc.transcribe(UID, wav(1.0), owner_phrases=False)  # not free-only: no limit, so priced
    assert len(stt.calls) == 1


async def test_a_free_only_question_needs_a_whole_billing_step_left() -> None:
    """Google may bill a request in 15-second steps: 10 s left is not enough for a 1 s question."""
    stt = FakeSTT()
    svc = _voice(stt, FakeTTS())
    await _used(svc, svc.prices.stt.free_units - 10)
    with pytest.raises(FreeAllowanceUsed):
        await svc.transcribe(UID, wav(1.0), owner_phrases=False, free_only=True)
    assert stt.calls == []


async def test_a_free_only_question_inside_the_allowance_goes_ahead_free() -> None:
    stt = FakeSTT()
    svc = _voice(stt, FakeTTS())
    view = await svc.transcribe(UID, wav(1.0), owner_phrases=False, free_only=True)
    assert len(stt.calls) == 1 and view.cost_inr == 0


async def test_an_unreadable_allowance_fails_closed_for_free_only() -> None:
    svc = _voice(FakeSTT(), FakeTTS())

    async def broken(month: str) -> Any:
        raise RuntimeError("down")

    svc.billing.meter.allowance = broken  # type: ignore[method-assign]
    with pytest.raises(BudgetUnavailable):
        await svc.billing.ensure_free(key=svc.prices.stt.key, units=1.0, free_units=3240.0)


# ---- POST /v1/book/show/heard: the browser's words, corrected for free ---------------------------
async def _heard(
    settings: Settings,
    audience: str,
    bodies: list[Any],
    *,
    voice: Any = None,
    prepare: Callable[[Any], Awaitable[None]] | None = None,
    token: bool = True,
) -> list[tuple[int, dict[str, Any]]]:
    got: list[tuple[int, dict[str, Any]]] = []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.voice = voice
        async with sign_in(app) as c:
            h = book((await open_book(c, await register_passkey(c), audience))["token"])
            if not token:
                h = {**h, "X-Jarvis-Book": "b" * 43}
            if prepare is not None:
                await prepare(app)
            for body in bodies:
                r = await c.post("/v1/book/show/heard", json=body, headers=h)
                got.append((r.status_code, r.json()))
    return got


async def test_the_owner_gets_the_free_corrections_with_his_own_words(settings: Settings) -> None:
    ears = Ears(phrases=("Brightwater",))
    ((code, body),) = await _heard(
        settings, "owner", [{"text": "javis what is the brightwatter office"}], voice=ears
    )
    assert code == 200
    assert body == {
        "text": "JARVIS what is the brightwater office",
        "heard": "javis what is the brightwatter office",
        "changed": True,
        "no_speech": False,
    }
    assert ears.settings_reads == [owner_uid()] and ears.asked == []  # no STT call: text only


async def test_a_guests_words_are_never_biased_toward_the_owners(settings: Settings) -> None:
    ears = Ears(phrases=("Brightwater",))
    ((code, body),) = await _heard(
        settings, "guest", [{"text": "javis what is the brightwatter office"}], voice=ears
    )
    assert code == 200 and body["text"] == "JARVIS what is the brightwatter office"
    assert ears.settings_reads == [] and ears.asked == []  # his words are never even read (D1)


async def test_the_heard_route_needs_no_cloud_voice_and_corrects_with_the_books_words(
    settings: Settings,
) -> None:
    ((code, body),) = await _heard(settings, "guest", [{"text": "where is firestor used"}])
    assert code == 200 and body["text"] == "where is firestore used" and body["changed"] is True


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        ({"text": "x" * 501}, 422, "too_long"),
        ({"text": 5}, 422, "input_rejected"),
        ({}, 422, "input_rejected"),
        ({"text": "y" * 5000}, 422, "input_rejected"),
    ],
)
async def test_the_heard_route_keeps_its_caps(
    settings: Settings, body: Any, status: int, error: str
) -> None:
    ((code, got),) = await _heard(settings, "guest", [body])
    assert (code, got["error"]) == (status, error)
    assert "x" * 20 not in got["detail"] and "y" * 20 not in got["detail"]  # never echoed


async def test_nothing_heard_is_no_speech(settings: Settings) -> None:
    ((code, body),) = await _heard(settings, "owner", [{"text": "   "}])
    assert code == 200 and body == {"text": "", "heard": "", "changed": False, "no_speech": True}


async def test_the_heard_route_has_the_same_rate_limit_as_hear(settings: Settings) -> None:
    got = await _heard(settings, "guest", [{"text": "how"}] * 11)
    assert [c for c, _ in got] == [200] * 10 + [429]


async def test_the_heard_route_counts_against_the_sessions_spoken_questions(
    settings: Settings,
) -> None:
    async def spend(app: Any) -> None:
        live = await app.state.book_sessions.live(owner_uid(), now=app.state.book_clock())
        while app.state.book_service.allow_hearing(live.session_id):
            pass

    ((code, body),) = await _heard(settings, "guest", [{"text": "how"}], prepare=spend)
    assert (code, body["reason"]) == (503, "budget")
    assert body["detail"] == hear.words("session_budget", owner=False)


async def test_the_heard_route_needs_the_live_session(settings: Settings) -> None:
    ((code, body),) = await _heard(settings, "owner", [{"text": "how"}], token=False)
    assert (code, body["error"]) == (401, "session_gone")


async def test_the_heard_route_never_logs_the_words(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    await _heard(settings, "guest", [{"text": "NEEDLE7319 how does it work"}])
    assert "NEEDLE7319" not in caplog.text


# ---- the words: plain, and no money for a guest --------------------------------------------------
@pytest.mark.parametrize("reason", ["free_used", "listening_browser"])
def test_the_new_reasons_have_plain_words(reason: str) -> None:
    guest, owner = hear.words(reason, owner=False), hear.words(reason, owner=True)
    assert guest.endswith(".") and owner.startswith(guest) and "type your question" in guest.lower()
    assert [w for w in MONEY if w in guest.lower()] == [], guest
