# tests/browser/test_voice_pace.py - R5 workstream C (docs/plans/r5-voice.md D9, D15, D16): the
# short first chunk, the browser voice for audio that can't be decoded, the fixed-line
# cache, the sound cues, the timing line and the "Words to recognise" editor.
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import (  # same directory (pytest prepend import)
    FAKE_SYNTH,
    FakeVoice,
    _json,
    _voice_panel,
    _wait,
    browser,  # noqa: F401
    make,  # noqa: F401
    pure,  # noqa: F401
    voice_view,
)

pytestmark = pytest.mark.browser

LONG_FIRST = (
    "Your calendar today has a team review at ten, a call with the finance people at noon, "
    "a dentist appointment at four in the afternoon and a long dinner booked for eight tonight."
)
NO_BREAK = "x" * 10 + " " + " ".join(["wordwithoutanybreak"] * 10) + "."
CHUNK_JS = """([text, deltas]) => {
  const c = JarvisSpeechChunker.create({ honorific: 'Sir' });
  const out = [];
  (deltas || [text]).forEach(d => out.push(...c.push(d)));
  out.push(...c.end());
  return out;
}"""
SAY_JS = """async ([texts, meta]) => {
  const s = JarvisVoice.speaker;
  texts.forEach(t => s.say(t, meta));
  s.end();
  await new Promise(r => { const f = (d) => { if (!d.speaking) r(); }; s.on('state', f); });
}"""
TONES = """
window.__tones = [];
(() => {
  const arm = () => {
    const s = window.JarvisVoice && window.JarvisVoice.speaker;
    if (!s || s.__wrapped) return !!s;
    const real = s.tone;
    s.tone = (o) => { window.__tones.push(o.freq); return real(o); };
    s.__wrapped = true;
    return true;
  };
  window.__arm = arm;
})();
"""
TIMING = """
window.__timing = [];
document.addEventListener('jarvis:voice-timing', (e) => window.__timing.push(e.detail));
"""


# ============================================================== the short first chunk (D15)
def test_a_long_first_sentence_is_cut_at_a_clause_break_before_140(pure: Any) -> None:  # noqa: F811
    out = pure.evaluate(CHUNK_JS, [LONG_FIRST, None])
    assert len(out[0]) <= 140 and out[0].endswith(",")
    assert " ".join(out) == LONG_FIRST  # nothing is lost
    assert len(out) >= 2


def test_a_long_first_sentence_streamed_in_deltas_gives_the_same_short_start(pure: Any) -> None:  # noqa: F811
    deltas = [LONG_FIRST[i : i + 7] for i in range(0, len(LONG_FIRST), 7)]
    out = pure.evaluate(CHUNK_JS, [LONG_FIRST, deltas])
    assert len(out[0]) <= 140 and " ".join(out) == LONG_FIRST


def test_a_semicolon_or_dash_is_a_clause_break_too(pure: Any) -> None:  # noqa: F811
    semi = LONG_FIRST.replace(", a call", "; a call").replace(", a dentist", " and a dentist")
    first = pure.evaluate(CHUNK_JS, [semi, None])[0]
    assert len(first) <= 140 and first.endswith(";")
    dash = "Here is the long and detailed plan for the whole week ahead — " + "and " * 40 + "end."
    first = pure.evaluate(CHUNK_JS, [dash, None])[0]
    assert first == "Here is the long and detailed plan for the whole week ahead"


def test_short_and_break_less_first_sentences_are_left_alone(pure: Any) -> None:  # noqa: F811
    short = "The meeting is at ten, in the big room, with everyone from the team there."
    assert pure.evaluate(CHUNK_JS, [short, None]) == [short]
    out = pure.evaluate(CHUNK_JS, [NO_BREAK, None])
    assert out == [NO_BREAK]  # under the 400-character cap and nowhere to cut


def test_a_break_too_early_would_leave_a_tiny_first_chunk_so_it_is_not_used(pure: Any) -> None:  # noqa: F811
    text = "Well, " + "and then some more words follow without a pause " * 5 + "done."
    out = pure.evaluate(CHUNK_JS, [text, None])
    assert out[0].startswith("Well, and then")


def test_the_first_speak_request_carries_at_most_140_characters(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate(
        """(text) => { const ch = JarvisSpeechChunker.create({ honorific: 'Sir' });
          [...ch.push(text), ...ch.end()].forEach(x => JarvisVoice.speaker.say(x));
          JarvisVoice.speaker.end(); }""",
        LONG_FIRST,
    )
    _wait(c, "() => window.__voice.speech.length >= 2")
    sent = fake.spoken()
    assert len(sent[0]) <= 140 and len(sent) >= 2
    assert c.errors == []


# ============================================================== read it all (D9)
def test_a_chunk_whose_audio_cannot_be_decoded_is_said_by_the_browser_voice(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    fake.speak_audio = b"this is not audio at all, just text bytes"
    c.open()
    c.page.evaluate(SAY_JS, [["First part of the answer.", "Second part of the answer."], None])
    assert c.page.evaluate("window.__synth") == [
        "First part of the answer.",
        "Second part of the answer.",
    ]
    engines = [d["engine"] for d in c.page.evaluate("window.__voice.speech")]
    assert engines == ["browser", "browser"]
    assert c.page.evaluate("JarvisVoice.speaker.usingBrowser()") is False  # only those chunks
    assert c.errors == []


def test_only_the_broken_chunk_goes_to_the_browser_the_rest_stay_on_the_cloud(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    good = fake.speak_audio
    c.open()
    c.page.route(
        re.compile(r".*/v1/voice/speak$"),
        lambda r: r.fulfill(
            status=200,
            content_type="audio/mpeg",
            body=good if "second" not in (r.request.post_data or "").lower() else b"garbage",
        ),
    )
    c.page.evaluate(SAY_JS, [["First line.", "Second line.", "Third line."], None])
    engines = [d["engine"] for d in c.page.evaluate("window.__voice.speech")]
    assert engines == ["cloud", "browser", "cloud"]
    assert c.page.evaluate("window.__synth") == ["Second line."]


def test_nothing_to_say_is_still_skipped_not_spoken(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    fake.speak_status, fake.speak_code = 422, "nothing_to_say"
    c.open()
    c.page.evaluate(SAY_JS, [["..."], None])
    assert c.page.evaluate("window.__synth") == []
    assert c.page.evaluate("window.__voice.speech") == []


# ============================================================== fixed lines are kept (D15)
def test_a_fixed_line_is_fetched_once_and_then_played_from_the_cache(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    for _ in range(3):
        c.page.evaluate(SAY_JS, [["Microphone off, Sir."], {"fixed": True}])
    assert fake.spoken() == ["Microphone off, Sir."]
    assert c.page.evaluate("JarvisVoice.speaker.fixedCached()") == 1
    assert [d["engine"] for d in c.page.evaluate("window.__voice.speech")] == ["cloud"] * 3


def test_a_line_not_marked_fixed_is_never_cached(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    for _ in range(2):
        c.page.evaluate(SAY_JS, [["Just a reply."], None])
    assert len(fake.spoken()) == 2
    assert c.page.evaluate("JarvisVoice.speaker.fixedCached()") == 0


def test_the_cache_is_keyed_by_the_voice_and_speed_the_request_uses_and_holds_eight(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    line = "Switching to the keyboard, Sir."
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    assert len(fake.spoken()) == 1  # same voice and speed: a hit
    c.page.evaluate("JarvisVoice.updateSettings({ voice: 'en-GB-Chirp3-HD-Charon' })")
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    assert len(fake.spoken()) == 2  # another voice: fetched again
    c.page.evaluate("JarvisVoice.updateSettings({ rate: 1.1 })")
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    assert len(fake.spoken()) == 3  # another speed: fetched again, even with no setRate call
    bodies = [p["body"] for p in fake.to("POST", "/v1/voice/speak")]
    assert bodies[-1]["rate"] == 1.1 and bodies[1]["voice"] == "en-GB-Chirp3-HD-Charon"
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    assert len(fake.spoken()) == 3  # and kept under the new key
    for i in range(10):
        c.page.evaluate(SAY_JS, [[f"Fixed line number {i}."], {"fixed": True}])
    assert c.page.evaluate("JarvisVoice.speaker.fixedCached()") == 8
    before = len(fake.spoken())
    c.page.evaluate(SAY_JS, [[line], {"fixed": True}])
    assert len(fake.spoken()) == before + 1  # the oldest was pushed out
    c.page.evaluate(SAY_JS, [["Fixed line number 9."], {"fixed": True}])
    assert len(fake.spoken()) == before + 1  # the newest is still there


def test_a_meta_voice_that_synth_ignores_does_not_change_the_cache_key(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    line = "Microphone off, Sir."
    c.page.evaluate(SAY_JS, [[line], {"fixed": True, "voice": "en-GB-Studio-B"}])
    c.page.evaluate(SAY_JS, [[line], {"fixed": True, "voice": "en-GB-Chirp3-HD-Charon"}])
    assert len(fake.spoken()) == 1  # the request never carried meta.voice, so one entry


def test_a_cache_hit_plays_without_a_second_fetch_or_a_second_remember(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    fake = FakeVoice(c.page)
    c.open()
    for _ in range(4):
        c.page.evaluate(SAY_JS, [["Handing over, Sir."], {"fixed": True}])
    assert len(fake.spoken()) == 1 and c.page.evaluate("JarvisVoice.speaker.fixedCached()") == 1
    assert c.errors == []


# ============================================================== sound cues (D15)
def _arm(c: Console) -> None:
    c.page.evaluate("window.__arm()")


def test_cues_play_generated_tones_through_the_speaker_context(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    for name, expect in (("listen", 2), ("heard", 1), ("micoff", 2), ("handover", 3)):
        c.page.evaluate("window.__tones.length = 0")
        assert c.page.evaluate(f"JarvisVoicePace.cue('{name}')") is True, name
        assert len(c.page.evaluate("window.__tones")) == expect, name
    assert c.page.evaluate("JarvisVoicePace.cue('nonsense')") is False
    assert c.page.evaluate("JarvisVoicePace.cue('__proto__')") is False
    assert c.errors == []


def test_cues_are_skipped_while_jarvis_speaks(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(TONES, FAKE_SYNTH))
    fake = FakeVoice(c.page)
    fake.speak_audio = fake.speak_audio * 1  # the 0.3 s clip is long enough to check against
    c.open()
    _arm(c)
    ok = c.page.evaluate(
        """async () => { JarvisVoice.speaker.say('Hello there.');
          const r = await JarvisVoicePace.cue('listen'); return r; }"""
    )
    assert ok is False and c.page.evaluate("window.__tones") == []


def test_cues_can_be_switched_off(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(device={"cues": False}, scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    assert c.page.evaluate("JarvisVoicePace.cue('listen')") is False
    assert c.page.evaluate("window.__tones") == []


def test_the_same_cue_asked_twice_plays_once_and_both_callers_can_wait(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    res = c.page.evaluate(
        """async () => { const a = JarvisVoicePace.cue('listen'), b = JarvisVoicePace.cue('listen');
          return [await a, await b, window.__tones.length]; }"""
    )
    assert res == [True, True, 2]


def test_the_loop_events_play_the_cues(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])
    _wait(c, "() => window.__tones.length >= 2")
    c.page.evaluate("window.__tones.length = 0")
    c.page.wait_for_timeout(600)  # past the de-duplication window
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "handover"}])
    _wait(c, "() => window.__tones.length >= 3")
    c.page.evaluate("window.__tones.length = 0")
    # a lock from a reload or another tab is not announced; one the owner asked for is
    c.page.evaluate(fire, ["jarvis:mic-lock", {"locked": True, "by": "boot"}])
    c.page.evaluate(fire, ["jarvis:mic-lock", {"locked": True, "by": "storage"}])
    c.page.wait_for_timeout(300)
    assert c.page.evaluate("window.__tones") == []
    c.page.evaluate(fire, ["jarvis:mic-lock", {"locked": True, "by": "voice"}])
    _wait(c, "() => window.__tones.length >= 2")


# ---- fixer round: cues that cannot hang, suspended contexts, false triggers --------------------
STALLED_OSC = """
(() => {
  const real = AudioContext.prototype.createOscillator;
  AudioContext.prototype.createOscillator = function () {
    const o = real.call(this);
    o.start = () => {};          // never starts, so onended never fires
    return o;
  };
})();
"""
SUSPENDED = """
(() => {
  Object.defineProperty(AudioContext.prototype, 'state', { get: () => 'suspended' });
  AudioContext.prototype.resume = () => new Promise(() => {});   // the browser never lets it start
})();
"""


def test_a_cue_whose_tone_never_ends_still_settles_false_and_quickly(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(STALLED_OSC,))
    FakeVoice(c.page)
    c.open()
    res = c.page.evaluate(
        """async () => { const t0 = performance.now(); const ok = await JarvisVoicePace.cue('handover');
          return [ok, performance.now() - t0]; }"""
    )
    assert res[0] is False and res[1] < 1500


def test_a_speaker_tone_that_never_settles_cannot_hold_the_cue(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    res = c.page.evaluate(
        """async () => { JarvisVoice.speaker.tone = () => new Promise(() => {});
          const t0 = performance.now(); const ok = await JarvisVoicePace.cue('listen');
          return [ok, performance.now() - t0]; }"""
    )
    assert res[0] is False and res[1] < 3500


def test_a_suspended_context_costs_one_wait_not_one_per_step(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(SUSPENDED, TONES))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    res = c.page.evaluate(
        """async () => { const t0 = performance.now(); const ok = await JarvisVoicePace.cue('handover');
          return [ok, performance.now() - t0, window.__tones.length]; }"""
    )
    assert res[0] is False and res[1] < 2500 and res[2] == 1


def test_returning_to_listening_after_an_empty_transcript_plays_no_second_rise(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TONES,))
    FakeVoice(c.page)
    c.open()
    _arm(c)
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])
    _wait(c, "() => window.__tones.length >= 2")
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "thinking"}])
    _wait(c, "() => window.__tones.length >= 3")
    c.page.wait_for_timeout(600)  # past the de-duplication window
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])  # empty transcript
    c.page.wait_for_timeout(400)
    assert len(c.page.evaluate("window.__tones")) == 3
    # a real turn (words accepted) and then listening again does rise
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "thinking"}])  # tick (1 tone)
    c.page.evaluate(fire, ["jarvis:turn", {"channel": "voice"}])
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])  # rise (2 tones)
    _wait(c, "() => window.__tones.length >= 6")


def test_an_unknown_engine_is_reported_as_unknown_and_a_re_mark_clears_the_old_one(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    for stage in ("heard", "words", "answer", "voice"):
        c.page.evaluate(f"JarvisVoicePace.mark('{stage}')")
    assert c.page.evaluate("window.__timing[0].engine") == "unknown"
    _turn(c)
    _turn(c)
    assert c.page.evaluate("performance.getEntriesByName('jarvis:heard').length") == 1


@pytest.mark.parametrize(
    ("text", "head_len"),
    [
        ("x" * 139 + "," + " " + "tail words follow here to make it long enough", 140),
        ("ab " * 46 + "end", None),
    ],
)
def test_the_140_boundary_cases(pure: Any, text: str, head_len: int | None) -> None:  # noqa: F811
    out = pure.evaluate(CHUNK_JS, [text + ".", None])
    if head_len is None:
        assert out == [text + "."]  # 141 characters, nowhere to cut
    else:
        assert len(out[0]) == head_len and out[0].endswith(",")


def test_exactly_140_characters_is_left_whole(pure: Any) -> None:  # noqa: F811
    text = ("word " * 40)[:139] + "."
    assert len(text) == 140
    assert pure.evaluate(CHUNK_JS, [text, None]) == [text]


@pytest.mark.parametrize(
    ("mark", "gap"),
    [("،", " "), ("，", ""), ("।", " "), (": ", "")],
)
def test_arabic_fullwidth_devanagari_commas_and_colons_are_clause_breaks(
    pure: Any,  # noqa: F811
    mark: str,
    gap: str,
) -> None:
    body = "hello world " * 7
    text = body + mark + gap + "and then the rest of the very long line goes on " * 3 + "end."
    out = pure.evaluate(CHUNK_JS, [text, None])
    assert len(out) >= 2 and len(out[0]) <= 140 and out[0].rstrip().endswith(mark.strip())


def test_a_malayalam_and_a_hindi_sentence_are_cut_at_their_own_breaks(pure: Any) -> None:  # noqa: F811
    ml = ("ഇന്ന് തിരുവനന്തപുരത്തെ കാലാവസ്ഥ വളരെ നല്ലതാണ്, " * 5) + "നന്ദി."
    out = pure.evaluate(CHUNK_JS, [ml, None])
    assert len(out[0]) <= 140 and out[0].endswith(",") and len(out) >= 2
    hi2 = (
        "आज का दिन बहुत ही अच्छा है और मौसम भी साफ है । "
        + "बाकी बातें बाद में बताता हूँ और बहुत कुछ " * 3
        + "।"
    )
    out = pure.evaluate(CHUNK_JS, [hi2, None])
    assert len(out) >= 2 and len(out[0]) <= 140 and out[0].endswith("।")


# ============================================================== the timing line (D15)
def _turn(c: Console, *, spoke: bool = False, wait_ms: int = 30) -> None:
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    if spoke:
        c.page.evaluate("JarvisVoicePace.mark('spoke')")
        c.page.wait_for_timeout(wait_ms)
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "thinking"}])
    c.page.wait_for_timeout(wait_ms)
    c.page.evaluate(fire, ["jarvis:turn", {"channel": "voice"}])
    c.page.wait_for_timeout(wait_ms)
    c.page.evaluate(fire, ["jarvis:answer", {"channel": "voice", "text": "Done."}])
    c.page.wait_for_timeout(wait_ms)
    c.page.evaluate(fire, ["jarvis:speech", {"text": "Done.", "engine": "cloud"}])


def test_a_spoken_turn_gives_every_stage_and_the_panel_line(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(device={"endSilenceMs": 1600}, scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    assert c.page.locator("#vPaceLine").text_content().startswith("Last reply: nothing timed")
    _turn(c)
    _wait(c, "() => window.__timing.length >= 1")
    t = c.page.evaluate("window.__timing[0]")
    assert t["kind"] == "reply" and t["engine"] == "cloud"
    assert t["heard"] == 1600  # no VAD mark given: the pause the owner allowed is the estimate
    assert t["estimated"] is True
    for k in ("words", "answer", "voice"):
        assert 0 <= t[k] <= 2000, k
    assert t["total"] == t["heard"] + t["words"] + t["answer"] + t["voice"]
    assert c.page.evaluate("JarvisVoicePace.last()") == {k: t[k] for k in t if k != "kind"}
    line = c.page.locator("#vPaceLine").text_content()
    assert re.fullmatch(
        r"Last reply: \d+\.\d s \(listening ~1\.6 · words \d+\.\d · "
        r"answer \d+\.\d · voice \d+\.\d\)",
        line,
    ), line
    marks = c.page.evaluate("performance.getEntriesByType('mark').map(m => m.name)")
    for stage in ("heard", "words", "answer", "voice"):
        assert f"jarvis:{stage}" in marks
    assert c.errors == []


def test_a_spoke_mark_replaces_the_estimate_with_the_real_listening_time(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(device={"endSilenceMs": 2500}, scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    _turn(c, spoke=True, wait_ms=60)
    _wait(c, "() => window.__timing.length >= 1")
    t = c.page.evaluate("window.__timing[0]")
    assert 50 <= t["heard"] < 1500 and t["estimated"] is False
    assert "listening ~" not in c.page.locator("#vPaceLine").text_content()


def test_a_typed_message_or_an_unspoken_reply_gives_no_timing(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    c.page.evaluate(fire, ["jarvis:turn", {"channel": "text"}])
    c.page.evaluate(fire, ["jarvis:answer", {"channel": "text", "text": "Hi."}])
    c.page.evaluate(fire, ["jarvis:speech", {"text": "Hi.", "engine": "cloud"}])
    c.page.evaluate(fire, ["jarvis:answer", {"channel": "voice", "text": "Hi."}])  # no words yet
    c.page.evaluate(fire, ["jarvis:speech", {"text": "Hi.", "engine": "cloud"}])
    c.page.wait_for_timeout(150)
    assert c.page.evaluate("window.__timing") == []
    assert c.page.evaluate("JarvisVoicePace.last()") is None


def test_the_second_turn_replaces_the_first_and_later_chunks_do_not_re_time_it(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make(scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    _turn(c)
    c.page.evaluate(fire, ["jarvis:speech", {"text": "More.", "engine": "cloud"}])  # chunk two
    assert len(c.page.evaluate("window.__timing")) == 1
    _turn(c)
    assert len(c.page.evaluate("window.__timing")) == 2


def test_an_interruption_reports_its_delay(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:barge', "
        "{ detail: { how: 'speech', ms: 312.4 } }))"
    )
    assert c.page.evaluate("window.__timing") == [{"kind": "barge", "how": "speech", "ms": 312}]
    c.page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:barge', { detail: { how: 'tap' } }))"
    )
    assert len(c.page.evaluate("window.__timing")) == 1  # no delay given: nothing to report


def test_the_timing_never_carries_words(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make(scripts=(TIMING,))
    FakeVoice(c.page)
    c.open()
    fire = "(d) => document.dispatchEvent(new CustomEvent(d[0], { detail: d[1] }))"
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "listening"}])
    c.page.evaluate(fire, ["jarvis:voice-loop", {"state": "thinking"}])
    c.page.evaluate(fire, ["jarvis:turn", {"channel": "voice"}])
    c.page.evaluate(fire, ["jarvis:answer", {"channel": "voice", "text": "SECRETWORDS here"}])
    c.page.evaluate(fire, ["jarvis:speech", {"text": "SECRETWORDS here", "engine": "browser"}])
    assert "SECRETWORDS" not in json.dumps(c.page.evaluate("window.__timing"))
    assert c.page.evaluate("window.__timing[0].engine") == "browser"


# ============================================================== Words to recognise (D16)
class PhrasesVoice(FakeVoice):
    """FakeVoice whose PUT keeps `phrases` like the real server (the 422 rules are the server's)."""

    def _put(self, route: Any, body: dict[str, Any]) -> None:
        s = self.view["settings"]
        if "phrases" in body:
            s["phrases"] = list(body["phrases"])
        rest = {k: v for k, v in body.items() if k != "phrases"}
        if rest:
            return super()._put(route, rest)
        return _json(route, 200, s)


def _phrases(c: Console) -> Any:
    _voice_panel(c)
    c.page.locator("#vPhraseIn").wait_for(state="visible")
    return c.page.locator("#vSlotPhrases")


def _puts(fake: FakeVoice) -> list[Any]:
    return [p["body"] for p in fake.to("PUT", "/v1/voice/settings")]


def test_the_editor_adds_and_removes_words_and_saves_them_through_the_voice_settings(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make()
    fake = PhrasesVoice(c.page)
    c.open()
    slot = _phrases(c)
    assert "No words yet" in str(c.page.locator("#vPhraseCount").text_content())
    c.page.locator("#vPhraseIn").fill("  Trivandrum ")
    c.page.locator("#vPhraseAdd").click()
    c.page.locator("#vPhraseIn").fill("Thiruvananthapuram")
    c.page.keyboard.press("Enter")
    assert slot.locator("#vPhraseList .bl").all_text_contents() == [
        "Trivandrum",
        "Thiruvananthapuram",
    ]
    assert c.page.locator("#vPhraseCount").text_content() == "2 of 50 words."
    c.page.locator("#voiceNote.ok").wait_for()
    assert _puts(fake) == [{"phrases": ["Trivandrum", "Thiruvananthapuram"]}]  # one debounced PUT
    c.page.locator("#vPhraseRm-0").click()
    c.page.locator("#voiceNote.ok").wait_for()
    _wait(c, "() => document.querySelectorAll('#vPhraseList .bl').length === 1")
    for _ in range(40):
        if len(_puts(fake)) == 2:
            break
        c.page.wait_for_timeout(100)
    assert _puts(fake)[-1] == {"phrases": ["Thiruvananthapuram"]}
    assert c.errors == [] and c.csp_violations() == []


def test_saved_words_are_shown_after_a_reload(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    view = voice_view()
    view["settings"]["phrases"] = ["Kochi", "Zoë"]
    PhrasesVoice(c.page, view)
    c.open()
    _phrases(c)
    assert c.page.locator("#vPhraseList .bl").all_text_contents() == ["Kochi", "Zoë"]


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "<b>bold</b>", "12345", "semi;colon", "a" * 41, "emoji \U0001f600", "x@y"],
)
def test_a_word_the_server_would_refuse_is_not_sent(
    make: Callable[..., Console],  # noqa: F811
    bad: str,
) -> None:
    c = make()
    fake = PhrasesVoice(c.page)
    c.open()
    _phrases(c)
    c.page.locator("#vPhraseIn").fill(bad)
    c.page.locator("#vPhraseAdd").click()
    assert "at least one letter" in str(c.page.locator("#vPhraseNote").text_content())
    assert c.page.locator("#vPhraseNote").get_attribute("class") == "bnote bad"
    c.page.wait_for_timeout(700)
    assert _puts(fake) == []
    assert c.page.locator("#vPhraseList .bl").count() == 0


def test_a_duplicate_in_any_case_is_not_added_twice(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    view = voice_view()
    view["settings"]["phrases"] = ["Kochi"]
    fake = PhrasesVoice(c.page, view)
    c.open()
    _phrases(c)
    c.page.locator("#vPhraseIn").fill("KOCHI")
    c.page.locator("#vPhraseAdd").click()
    assert "already in the list" in str(c.page.locator("#vPhraseNote").text_content())
    c.page.wait_for_timeout(700)
    assert _puts(fake) == []


def test_the_limits_come_from_the_server_view(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    view = voice_view(phrase_limits={"items": 2, "chars": 8})
    view["settings"]["phrases"] = ["One", "Two"]
    fake = PhrasesVoice(c.page, view)
    c.open()
    _phrases(c)
    assert c.page.locator("#vPhraseCount").text_content() == "2 of 2 words."
    c.page.locator("#vPhraseIn").fill("Three")
    c.page.locator("#vPhraseAdd").click()
    assert "list is full (2 at most)" in str(c.page.locator("#vPhraseNote").text_content())
    c.page.locator("#vPhraseRm-0").click()
    c.page.locator("#vPhraseIn").fill("Much too long")
    c.page.locator("#vPhraseAdd").click()
    assert "1 to 8 characters" in str(c.page.locator("#vPhraseNote").text_content())
    c.page.locator("#vPhraseIn").fill("Fine")
    c.page.locator("#vPhraseAdd").click()
    _wait(c, "() => document.querySelectorAll('#vPhraseList .bl').length === 2")
    for _ in range(40):  # one debounced PUT, or two when the pause between clicks was long
        if _puts(fake) and _puts(fake)[-1] == {"phrases": ["Two", "Fine"]}:
            break
        c.page.wait_for_timeout(100)
    assert _puts(fake)[-1] == {"phrases": ["Two", "Fine"]}


def test_a_server_refusal_shows_what_the_server_holds(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    view = voice_view()
    view["settings"]["phrases"] = ["Kept"]
    fake = PhrasesVoice(c.page, view)
    fake.put_status, fake.put_code = 422, "input_rejected"
    c.open()
    _phrases(c)
    c.page.locator("#vPhraseIn").fill("Newcomer")
    c.page.locator("#vPhraseAdd").click()
    c.page.locator("#voiceNote.bad").wait_for()
    _wait(
        c,
        "() => [...document.querySelectorAll('#vPhraseList .bl')]"
        ".map(x => x.textContent).join() === 'Kept'",
    )


def test_the_words_are_never_written_to_the_event_log(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    PhrasesVoice(c.page)
    c.open()
    _phrases(c)
    c.page.evaluate(
        "window.__logs = []; document.addEventListener('jarvis:event', "
        "(e) => window.__logs.push(JSON.stringify(e.detail)))"
    )
    c.page.locator("#vPhraseIn").fill("Quillon")
    c.page.locator("#vPhraseAdd").click()
    c.page.locator("#voiceNote.ok").wait_for()
    assert not any("Quillon" in line for line in c.page.evaluate("window.__logs"))


def test_the_helper_cleans_like_the_server_and_offers_the_list_only_where_supported(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make()
    view = voice_view()
    view["settings"]["phrases"] = ["Kochi"]
    PhrasesVoice(c.page, view)
    c.open()
    clean = "(s) => JarvisVoicePhrases.clean(s)"
    assert c.page.evaluate(clean, "  Tri​van   drum ") == "Trivan drum"
    assert c.page.evaluate(clean, "O’Brien") == "O'Brien"
    assert c.page.evaluate(clean, "1234") is None
    assert c.page.evaluate(clean, "a" * 41) is None
    assert c.page.evaluate(clean, "തിരു") == "തിരു"
    _voice_panel(c)
    assert c.page.evaluate("JarvisVoicePhrases.apply({})") is False  # no biasing offered: no-op
    assert c.page.evaluate(
        """() => { window.SpeechRecognitionPhrase = class {
            constructor(p, b) { this.phrase = p; this.boost = b; } };
          const r = { phrases: [] }; return [JarvisVoicePhrases.apply(r), r.phrases.length]; }"""
    ) == [True, 1]


def test_file_separator_controls_become_spaces_like_the_server(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make()
    PhrasesVoice(c.page)
    c.open()
    clean = "(s) => JarvisVoicePhrases.clean(s)"
    for code in (0x1C, 0x1D, 0x1E, 0x1F):
        assert c.page.evaluate(clean, f"Tri{chr(code)}van") == "Tri van"
    assert c.page.evaluate(clean, "a" + "́" * 7) is None  # a stack of accents, as on the server
    assert c.page.evaluate(clean, "a" + "́" * 3) is not None


def test_a_server_refusal_is_also_shown_in_the_words_note(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make()
    fake = PhrasesVoice(c.page)
    fake.put_status, fake.put_code = 422, "input_rejected"
    c.open()
    _phrases(c)
    c.page.locator("#vPhraseIn").fill("Newcomer")
    c.page.locator("#vPhraseAdd").click()
    c.page.locator("#vPhraseNote.bad").wait_for()
    assert str(c.page.locator("#vPhraseNote").text_content()).startswith("Couldn't save")


def test_apply_is_safe_when_the_recogniser_has_no_phrase_support(
    make: Callable[..., Console],  # noqa: F811
) -> None:
    c = make()
    view = voice_view()
    view["settings"]["phrases"] = ["Kochi"]
    PhrasesVoice(c.page, view)
    c.open()
    assert c.page.evaluate("JarvisVoicePhrases.apply({ grammars: null })") is False
    assert c.page.evaluate("JarvisVoicePhrases.apply(null)") is False
    assert c.errors == []
