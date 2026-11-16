# tests/test_r62_book_hold.py -- R6.2 round 3 (review 3): the free-only HOLD on the shared free
# allowance. The rule, in one place (`VoiceService._engine`): a hold is given back when Google
# billed nothing (a clean 429, a rejection, an error before the request left) and is kept when it
# is unclear (a timeout after the request went out, a cancel, an unexpected error): over-counting
# the free allowance is the safe side for the owner's money. Made-up words only, fixed clocks.
from __future__ import annotations

from typing import Any

import pytest
from billing_fakes import NOW, UID, billing, registry
from billing_fakes import Clock as BillClock
from book_hear_fakes import wav
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.ports import Transcript, VoiceBusy, VoiceError, VoiceRejected, VoiceUnavailable
from jarvis.voice.service import SpeakRequest, VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsStore

STEP = 15.0


def _svc(stt: Any, tts: Any, docs: MemoryDocs | None = None) -> VoiceService:
    docs = docs or MemoryDocs()
    return VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing(registry(), docs=docs, clock=BillClock(NOW)),
        prices=PriceList.from_settings(Settings(_env_file=None)),
        engines=VoiceEngines(tts=tts, stt=stt, tokens=FakeTokens()),
        language="en-IN",
        honorific="Sir",
    )


async def _stt_used(svc: VoiceService) -> float:
    key = svc.prices.stt.key
    return (await svc.billing.allowance((key,))).used(key)


async def _tts_used(svc: VoiceService) -> float:
    keys = (svc.prices.chirp3_hd.key, svc.prices.studio.key)
    allow = await svc.billing.allowance(keys)
    return sum(allow.used(k) for k in keys)


async def _ask(svc: VoiceService, **kw: Any) -> None:
    await svc.transcribe(UID, wav(1.0), free_only=True, **kw)


async def test_a_clean_429_gives_the_listening_hold_back() -> None:
    svc = _svc(FakeSTT(fail=VoiceBusy()), FakeTTS())
    with pytest.raises(VoiceBusy):
        await _ask(svc, owner_phrases=False)
    assert await _stt_used(svc) == 0.0


async def test_a_rejected_narration_gives_the_hold_back() -> None:
    svc = _svc(FakeSTT(), FakeTTS(fail=VoiceRejected("no")))
    with pytest.raises(VoiceRejected):
        await svc.speak(UID, SpeakRequest(text="Welcome to the tour."), free_only=True)
    assert await _tts_used(svc) == 0.0


async def test_a_busy_narration_gives_the_hold_back() -> None:
    svc = _svc(FakeSTT(), FakeTTS(fail=VoiceBusy()))
    with pytest.raises(VoiceBusy):
        await svc.speak(UID, SpeakRequest(text="Welcome to the tour."), free_only=True)
    assert await _tts_used(svc) == 0.0


async def test_a_hold_is_given_back_to_the_count_before_it_not_to_zero() -> None:
    stt = FakeSTT()
    svc = _svc(stt, FakeTTS())
    await _ask(svc, owner_phrases=False)  # one good call: 15 s counted
    stt.fail = VoiceBusy()
    with pytest.raises(VoiceBusy):
        await _ask(svc, owner_phrases=False)
    assert await _stt_used(svc) == STEP


class _Script:
    """An STT that fails with each given error in turn, then answers."""

    def __init__(self, *errors: Exception) -> None:
        self.errors, self.calls = list(errors), 0

    async def recognize(self, pcm: bytes, **kw: Any) -> Transcript:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return Transcript("hello", 0.9, 1.0, "en-in")


@pytest.mark.parametrize(
    ("errors", "counted"),
    [
        ((VoiceRejected("a"), VoiceBusy()), 0.0),  # the retry with the base hints met a 429
        ((VoiceRejected("a"), VoiceRejected("b")), 0.0),
        ((VoiceBusy(),), 0.0),  # no retry on a 429; the hold is back at once
        ((VoiceRejected("a"), VoiceUnavailable("timeout", maybe_billed=True)), STEP),
    ],
)
async def test_the_owner_words_retry_gives_back_or_keeps_by_the_same_rule(
    errors: tuple[VoiceError, ...], counted: float
) -> None:
    stt = _Script(*errors)
    svc = _svc(stt, FakeTTS())
    with pytest.raises(VoiceError):
        await _ask(svc, turn_hints=("zebra",))  # a turn hint counts as owner's words: retry
    assert await _stt_used(svc) == counted


async def test_a_rejected_first_try_keeps_the_hold_for_the_retry_that_follows() -> None:
    stt = _Script(VoiceRejected("a"))
    svc = _svc(stt, FakeTTS())
    await _ask(svc, turn_hints=("zebra",))
    assert stt.calls == 2 and await _stt_used(svc) == STEP  # one hold, counted once


@pytest.mark.parametrize(
    "error",
    [VoiceUnavailable("timeout", maybe_billed=True), RuntimeError("unexpected")],
)
async def test_when_it_is_unclear_whether_google_billed_the_hold_is_kept(
    error: Exception,
) -> None:
    svc = _svc(FakeSTT(fail=error), FakeTTS())
    with pytest.raises(type(error)):
        await _ask(svc, owner_phrases=False)
    assert await _stt_used(svc) == STEP


async def test_an_unexpected_narration_error_keeps_the_hold() -> None:
    svc = _svc(FakeSTT(), FakeTTS(fail=RuntimeError("unexpected")))
    with pytest.raises(RuntimeError):
        await svc.speak(UID, SpeakRequest(text="Welcome to the tour."), free_only=True)
    assert await _tts_used(svc) > 0.0


async def test_an_owners_own_call_has_no_hold_to_give_back() -> None:
    svc = _svc(FakeSTT(fail=VoiceBusy()), FakeTTS())
    with pytest.raises(VoiceBusy):
        await svc.transcribe(UID, wav(1.0), owner_phrases=False)  # free_only=False
    assert await _stt_used(svc) == 0.0
