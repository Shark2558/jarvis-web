# tests/test_r62_book_hear.py -- R6.2 Part 1 (Phase A findings 4.3-4.5; gaps G1, G12, G13): a spoken
# question in the build book's show, through the real app with a fake recogniser (book_hear_fakes).
# The answer carries {text, heard, changed, no_speech}; the console's free R11.1 rules
# (understand.rules.apply) correct the words with no model call, against the book's own words (and
# the owner's "Words to recognise" for an owner session ONLY: R6 D1). Each failure is said in plain
# words by reason, and a guest never sees setup or admin text (no Cloud Shell command, no "Vitals",
# no rupees). A limit that can't be read is a 503, not "the limit is reached" (G12). Fixed clocks.
# Owner decision 4: this is the cloud path, behind the owner's switch (Listening: Cloud); the
# browser default and its negative controls are in test_r62_book_listening.py.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from billing_fakes import NOW, UID, billing, registry
from billing_fakes import Clock as BillClock
from book_app_fakes import book, book_app, open_book, owner_uid, register_passkey, sign_in
from book_hear_fakes import Ears, wav
from book_show_fakes import Clock, FixtureSource
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.billing.service import BudgetReached, BudgetUnavailable
from jarvis.buildbook import hear
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.ports import BadAudio, VoiceBusy, VoiceRejected, VoiceUnavailable
from jarvis.voice.service import VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore, clean_phrase

# words a guest must never be shown in the Book: setup steps, admin places, money
ADMIN = ("gcloud", "Cloud Shell", "Vitals", "₹", "JARVIS_", "browser's voice", "Run the")
NOT_FOR_THE_BOOK = ("gcloud", "Cloud Shell", "browser's voice", "₹")  # nobody, in the Book
# narration: the browser's voice really does read the line there (console-book-voice.js)
SETUP = ("gcloud", "Cloud Shell", "Vitals", "₹", "JARVIS_", "Run the")
SPENDING = ("spending", "limit", "charged", "minutes", "rupee")  # the owner's billing state


async def _hear(
    settings: Settings,
    voice: Any,
    audience: str,
    *,
    body: bytes | None = None,
    prepare: Callable[[Any], Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """One spoken question in a fresh app: (status, JSON answer)."""
    got: list[tuple[int, dict[str, Any]]] = []
    async for app in book_app(settings):
        app.state.book_clock = Clock()  # never today's date
        app.state.voice = voice
        app.state.book_prefs.values["listening"] = "cloud"  # decision 4: the cloud, switched on
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            h = {**book((await open_book(c, auth, audience))["token"]), "Content-Type": "audio/wav"}
            if prepare is not None:
                await prepare(app)
            r = await c.post("/v1/book/show/hear", content=body or wav(1.0), headers=h)
            got.append((r.status_code, r.json()))
    return got[0]


# ---- the words, corrected for free -------------------------------------------------------------
async def test_the_owner_gets_the_consoles_corrections_with_his_own_words(
    settings: Settings,
) -> None:
    ears = Ears(heard="javis what is the trivandram office", phrases=("Trivandrum",))
    code, body = await _hear(settings, ears, "owner")
    assert code == 200
    assert body == {
        "text": "JARVIS what is the trivandrum office",
        "heard": "javis what is the trivandram office",
        "changed": True,
        "no_speech": False,
    }
    assert ears.settings_reads == [owner_uid()]
    (asked,) = ears.asked
    assert asked["owner_phrases"] is True
    assert "Firestore" in asked["public_hints"]  # the book's fixed words
    assert "Telegram" in asked["public_hints"]  # and the names in this release's book


async def test_a_guest_is_never_biased_toward_the_owners_words(settings: Settings) -> None:
    ears = Ears(heard="javis what is the trivandram office", phrases=("Trivandrum",))
    code, body = await _hear(settings, ears, "guest")
    assert code == 200
    assert body["text"] == "JARVIS what is the trivandram office"  # the free rule, not his word
    assert body["changed"] is True and body["heard"] == "javis what is the trivandram office"
    assert ears.settings_reads == []  # his words are never even read for a guest (D1)
    (asked,) = ears.asked
    assert asked["owner_phrases"] is False and asked["turn_hints"] == ()
    assert "Trivandrum" not in asked["public_hints"] and "Firestore" in asked["public_hints"]


async def test_words_heard_right_come_back_unchanged(settings: Settings) -> None:
    code, body = await _hear(settings, Ears(heard="how does the vault work"), "owner")
    assert code == 200
    assert body == {
        "text": "how does the vault work",
        "heard": "how does the vault work",
        "changed": False,
        "no_speech": False,
    }


@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_nothing_heard_is_said_as_no_speech(settings: Settings, audience: str) -> None:
    code, body = await _hear(settings, Ears(heard=""), audience)
    assert code == 200
    assert body == {"text": "", "heard": "", "changed": False, "no_speech": True}


async def test_the_owner_is_told_when_a_question_was_charged(settings: Settings) -> None:
    """G13: past the free minutes listening is charged until the monthly limit: said truthfully."""
    code, body = await _hear(settings, Ears(heard="how", cost_inr=0.57), "owner")
    assert code == 200 and body["charged"] is True
    code, body = await _hear(settings, Ears(heard="how", cost_inr=0.0), "owner")
    assert code == 200 and "charged" not in body


async def test_a_guest_never_hears_about_charges(settings: Settings) -> None:
    code, body = await _hear(settings, Ears(heard="how", cost_inr=0.57), "guest")
    assert code == 200 and "charged" not in body  # the guest view hides costs


# ---- each failure in plain words ----------------------------------------------------------------
FAILURES = [
    (VoiceUnavailable("not_configured"), 503, "voice_unavailable", "not_configured"),
    (VoiceUnavailable("api_disabled"), 503, "voice_unavailable", "api_disabled"),
    (VoiceUnavailable("upstream_error"), 503, "voice_unavailable", "upstream_error"),
    (VoiceUnavailable("timeout"), 503, "voice_unavailable", "timeout"),
    (BudgetUnavailable(), 503, "voice_unavailable", "budget_unreadable"),  # G12: not a 402
    (
        BudgetReached(
            limit_inr=500,
            used_inr=512.0,
            free_brain=False,
            detail="This month's limit of ₹500 is used up; raise the limit in Vitals.",
        ),
        402,
        "budget_reached",
        "budget_reached",
    ),
    (VoiceBusy(), 429, "voice_busy", "busy"),
    (VoiceRejected("refused"), 422, "input_rejected", "rejected"),
]


@pytest.mark.parametrize("audience", ["guest", "owner"])
@pytest.mark.parametrize(("error", "status", "code", "reason"), FAILURES)
async def test_each_failure_is_said_in_the_books_own_words(
    settings: Settings, audience: str, error: Exception, status: int, code: str, reason: str
) -> None:
    got, body = await _hear(settings, Ears(error=error), audience)
    assert got == status and body["error"] == code
    if status == 503:
        assert body["reason"] == reason
    assert body["detail"] == hear.words(reason, owner=audience == "owner")
    leaks = ADMIN if audience == "guest" else NOT_FOR_THE_BOOK
    assert [w for w in leaks if w in body["detail"]] == [], body["detail"]


def test_the_monthly_limit_is_said_truthfully() -> None:
    guest, owner = (
        hear.words("budget_reached", owner=False),
        hear.words("budget_reached", owner=True),
    )
    assert "free listening minutes" in owner and "limit" in owner
    assert "Vitals" in owner  # the owner is told where to raise it
    assert guest == "JARVIS can't listen right now. Type your question."  # L1: neutral for a guest


async def test_a_recording_too_short_says_so(settings: Settings) -> None:
    short = BadAudio("That recording is too short to hear anything.")
    got, body = await _hear(settings, Ears(error=short), "guest")
    assert got == 422 and body["error"] == "bad_audio"
    assert body["detail"] == "That recording is too short to hear anything."


@pytest.mark.parametrize("audience", ["guest", "owner"])
async def test_without_cloud_listening_nobody_is_told_the_browser_listens(
    settings: Settings, audience: str
) -> None:
    """Phase A case 7: "the browser's voice is used" was wrong for hearing (nothing listens)."""
    got, body = await _hear(settings, None, audience)
    assert got == 503 and body["reason"] == "not_configured"
    assert body["detail"] == hear.words("not_configured", owner=audience == "owner")
    assert "browser" not in body["detail"]


async def test_the_sessions_spoken_questions_used_up_say_so(settings: Settings) -> None:
    async def spend(app: Any) -> None:
        live = await app.state.book_sessions.live(owner_uid(), now=app.state.book_clock())
        while app.state.book_service.allow_hearing(live.session_id):
            pass

    got, body = await _hear(settings, Ears(), "guest", prepare=spend)
    assert got == 503 and body["reason"] == "budget"
    assert body["detail"] == hear.words("session_budget", owner=False)


# ---- the narration route gives no setup text either ---------------------------------------------
class Mouth(Ears):
    async def speak(self, uid: str, req: Any) -> Any:
        assert self.error is not None
        raise self.error


@pytest.mark.parametrize("audience", ["guest", "owner"])
async def test_a_narration_failure_never_carries_setup_text(
    settings: Settings, audience: str
) -> None:
    got: list[tuple[int, dict[str, Any]]] = []
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        app.state.voice = Mouth(error=VoiceUnavailable("api_disabled"))
        app.state.book_prefs.values["show_voice"] = "cloud"  # decision 4: the cloud, switched on
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, audience))["token"])
            r = await c.post("/v1/book/show/speak", json={"line_id": "ask"}, headers=h)
            got.append((r.status_code, r.json()))
    status, body = got[0]
    assert status == 503 and body["error"] == "voice_unavailable"
    assert body["detail"] == hear.SPEAK_OFF
    assert [w for w in SETUP if w in body["detail"]] == []


# ---- the voice service: the book's words go along for a guest too, his never ---------------------
def _voice(stt: FakeSTT) -> VoiceService:
    docs = MemoryDocs()
    return VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=BillClock(NOW)),
        prices=PriceList.from_settings(Settings(_env_file=None)),
        engines=VoiceEngines(tts=FakeTTS(), stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )


async def test_public_hints_reach_the_recogniser_for_a_guest_and_his_words_never() -> None:
    stt = FakeSTT()
    svc = _voice(stt)
    await svc.update_settings(UID, VoiceSettingsPatch.model_validate({"phrases": ["Kochi"]}))
    await svc.transcribe(
        UID, wav(1.0), owner_phrases=False, public_hints=("Firestore",), turn_hints=("Kerala",)
    )
    guest = stt.calls[-1]["phrases"]
    assert "Firestore" in guest and "Kochi" not in guest and "Kerala" not in guest
    await svc.transcribe(UID, wav(1.0), public_hints=("Firestore",), turn_hints=("Kerala",))
    owner = stt.calls[-1]["phrases"]
    assert owner.index("Firestore") < owner.index("Kerala") < owner.index("Kochi")


async def test_a_refused_public_hint_is_retried_with_the_base_list_only() -> None:
    """One bad word never stops a guest's question (as the owner's words today)."""
    stt = FakeSTT()
    svc = _voice(stt)
    calls: list[tuple[str, ...]] = []
    real = stt.recognize

    async def first_refused(pcm: bytes, **kw: Any) -> Any:
        calls.append(kw["phrases"])
        if len(calls) == 1:
            raise VoiceRejected("refused")
        return await real(pcm, **kw)

    stt.recognize = first_refused  # type: ignore[method-assign]
    view = await svc.transcribe(UID, wav(1.0), owner_phrases=False, public_hints=("Firestore",))
    assert view.text and "Firestore" in calls[0] and "Firestore" not in calls[1]


# ---- the module itself ---------------------------------------------------------------------------
def test_the_vocabulary_is_public_names_only_unique_and_capped() -> None:
    plain = hear.vocabulary(None)
    assert plain == hear.vocabulary(None)  # deterministic
    assert "JARVIS" in plain and "Firestore" in plain
    full = hear.vocabulary(FixtureSource().book())
    assert "Telegram" in full and set(plain) <= set(full)
    for words in (plain, full):
        assert len(words) <= hear.MAX_VOCABULARY
        assert len({w.casefold() for w in words}) == len(words)
        assert all(clean_phrase(w) == w for w in words), words


class CountingSource(FixtureSource):
    def __init__(self, *, broken: bool = False, present: bool = True) -> None:
        super().__init__(present=present)
        self.reads, self.broken = 0, broken

    def book(self) -> Any:
        self.reads += 1
        if self.broken:
            raise ValueError("unreadable")
        return super().book()


def test_the_books_words_are_read_once_a_release() -> None:
    src = CountingSource()
    words = hear.BookWords(src)
    assert words() == words() == hear.vocabulary(FixtureSource().book())
    assert src.reads == 1


def test_a_book_that_cant_be_read_gives_the_fixed_words_and_is_asked_again() -> None:
    src = CountingSource(broken=True)
    words = hear.BookWords(src)
    assert words() == hear.vocabulary(None) and words() == hear.vocabulary(None)
    assert src.reads == 2  # never cached as if it were the book's
    absent = CountingSource(present=False)
    assert hear.BookWords(absent)() == hear.vocabulary(None) and absent.reads == 0


def test_understood_uses_the_free_rules_only() -> None:
    got = hear.understood("javis how does the calender work", ())
    assert got == hear.Understood(
        text="JARVIS how does the calendar work",
        heard="javis how does the calender work",
        changed=True,
    )
    assert hear.understood("  ", ()) == hear.Understood(text="", heard="", changed=False)
    assert hear.understood("firestor keeps it", ("Firestore",)).text == "firestore keeps it"


@pytest.mark.parametrize("reason", hear.REASONS)
def test_every_reason_has_plain_words_and_a_guest_gets_no_admin_text(reason: str) -> None:
    guest, owner = hear.words(reason, owner=False), hear.words(reason, owner=True)
    assert guest and guest.endswith(".")
    neutral = reason in ("budget_reached", "budget_unreadable")  # a guest's own line (L1)
    assert owner.startswith(guest) is not neutral, (guest, owner)
    assert [w for w in ADMIN if w in guest] == [], guest
    # security review 1, L1: a guest is never told about the owner's spending, in any words
    assert [w for w in SPENDING if w in guest.lower()] == [], guest
    assert [w for w in NOT_FOR_THE_BOOK if w in owner] == [], owner


def test_an_unknown_reason_still_gets_plain_words() -> None:
    assert hear.words("no_such_reason", owner=False) == hear.words("upstream_error", owner=False)
