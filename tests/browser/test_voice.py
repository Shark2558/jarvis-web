# tests/browser/test_voice.py — slice 9 voice in a real browser (docs/plans/phase1-slice9-voice.md).
# /v1/voice* is faked with page.route exactly as §3 describes it (no network, no Google); the chat
# itself is the real app with the mock brain. Chromium runs with a fake microphone that plays a
# generated, speech-like WAV (a burst of voiced "syllables", then silence, looped), so the whole
# capture pipeline (AudioWorklet → 16 kHz Int16 frames → VAD → WAV) runs for real.
# Covers: the speech chunker, the worklet's resampling, live capture frames, the WAV header, the
# VAD, mic → transcribe → message sent with channel "voice" → reply spoken in order, conversation
# mode, barge-in, the browser-voice fallback on 503, the fixed approval line (D11), the Voice panel
# (voices, preview, speed, wit, device settings, debounced + serialized saves, allowance in ₹,
# cloud status), the "Hey Jarvis" switch with and without window.JarvisWake, mic-blocked help,
# phone layout, contrast on Night and Day, 0 JS errors, 0 CSP violations and no "$" on the page.
from __future__ import annotations

import copy
import json
import math
import random
import re
import struct
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_brief import CONTRAST_JS, SETTLE_JS  # same directory (pytest prepend import)
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

VOICE_URL = re.compile(r".*/v1/voice(?:/[^?]*)?(?:\?.*)?$")
APPROVAL_LINE = "That one needs your approval on screen, Sir."
ALLOWANCE = "This month: 12,340 of 900,000 free characters · 3 of 54 free minutes · ≈ ₹0.00"


def _voice(
    name: str, style: str, kind: str = "chirp3-hd", available: bool = True
) -> dict[str, Any]:
    vid = "en-GB-Studio-B" if kind == "studio" else f"en-GB-Chirp3-HD-{name}"
    return {"id": vid, "label": name, "style": style, "type": kind, "available": available}


VOICES = [
    _voice("Algieba", "smooth"),
    _voice("Sadaltager", "knowledgeable"),
    _voice("Charon", "informative, deeper"),
    _voice("Iapetus", "clear", available=False),
    _voice("Studio-B", "formal, crisp", kind="studio"),
]
WIT = [
    {"id": "measured", "label": "Measured", "description": "Light: the odd dry remark."},
    {"id": "film", "label": "Film", "description": "Dry British wit; at most one light quip."},
    {"id": "extra", "label": "Extra", "description": "Drier, more often; gentle teasing allowed."},
]

# Collected before any script runs: chunks as they start playing, the voice states, and the bytes
# the page uploads (Chromium leaves large bodies out of intercepted requests).
RECORDER = """
window.__voice = { speech: [], states: [] };
document.addEventListener('jarvis:speech', (e) => window.__voice.speech.push(e.detail));
document.addEventListener('jarvis:state', (e) => {
  window.__voice.states.push(e.detail.voice || null);
});
window.__sent = [];
(() => {
  const real = window.fetch;
  window.fetch = function (path, opts) {
    const b = opts && opts.body;
    if (b instanceof ArrayBuffer) {
      const head = Array.from(new Uint8Array(b.slice(0, 44)));
      window.__sent.push({ path: String(path), size: b.byteLength, head });
    }
    return real.apply(this, arguments);
  };
})();
"""
# The browser voice, faked so headless Chromium's silent speechSynthesis can be observed.
FAKE_SYNTH = """
(() => {
  window.__synth = [];
  class U { constructor(t) { this.text = t; this.onend = null; this.onerror = null; } }
  const voices = [{ name: 'Google UK English Female', lang: 'en-GB' },
    { name: 'Daniel', lang: 'en-GB' }];
  const fake = {
    speak(u) { window.__synth.push(u.text); setTimeout(() => { if (u.onend) u.onend({}); }, 40); },
    cancel() {}, getVoices() { return voices; }, speaking: false, pending: false,
  };
  Object.defineProperty(window, 'speechSynthesis', { value: fake, configurable: true });
  window.SpeechSynthesisUtterance = U;
})();
"""
# The browser's own recognition, faked: interim words, then a final result, then end. stop() is
# what a browser does on "tap again": the words heard so far as a final result, then end.
# window.__recEndMs: when the browser ends by itself (a pause in speech); window.__recSilent: nobody
# speaks (no result until stop() / abort()).
FAKE_RECOGNITION = """
(() => {
  window.__rec = [];
  window.__said = 'Remind me about the review.';
  window.__recEndMs = 1200;
  window.__recSilent = false;
  const result = (transcript, isFinal) => ({ resultIndex: 0,
    results: [Object.assign([{ transcript }], { isFinal })] });
  class R {
    constructor() {
      window.__rec.push(this); this.aborted = false; this.stopped = false; this.done = false;
    }
    start() {
      this.silent = window.__recSilent;
      if (this.silent) return;
      const first = window.__said.split(' ')[0];
      this.t1 = setTimeout(() => this.onresult && this.onresult(result(first, false)), 60);
      this.t2 = setTimeout(() => this.finish(), window.__recEndMs);
    }
    finish() {
      if (this.done) return;
      this.done = true; clearTimeout(this.t1); clearTimeout(this.t2);
      if (!this.silent && this.onresult) this.onresult(result(window.__said, true));
      if (this.onend) this.onend();
    }
    stop() { this.stopped = true; setTimeout(() => this.finish(), 30); }
    abort() {
      if (this.done) return;
      this.done = true; this.aborted = true; clearTimeout(this.t1); clearTimeout(this.t2);
      if (this.onerror) this.onerror({ error: 'aborted' });
      if (this.onend) this.onend();
    }
  }
  window.SpeechRecognition = R; window.webkitSpeechRecognition = R;
})();
"""
# A stand-in for console-wakeword.js (window.JarvisWake), recording what the console gives it. Like
# the real module it has a `state` and pause() / resume(); frames count only while it listens.
FAKE_WAKE = """
window.__wake = { started: 0, stopped: 0, loaded: 0, frames: 0, len: 0, rate: 0, paused: 0,
  resumed: 0, pausedAt: 0, resumedAt: 0 };
window.JarvisWake = {
  state: 'idle',
  supported: () => true,
  load() { window.__wake.loaded++; return Promise.resolve(); },
  start(opts, onWake) {
    const w = window.__wake, W = window.JarvisWake;
    w.started++; w.rate = opts.sampleRate; w.fire = onWake;
    W.state = 'listening';
    const off = opts.subscribe((f) => {
      if (W.state !== 'listening') return;
      w.frames++; w.len = f.length; w.int16 = f instanceof Int16Array;
    });
    return { stop() { w.stopped++; W.state = 'idle'; off(); } };
  },
  pause() {
    if (this.state !== 'listening') return;
    this.state = 'paused'; window.__wake.paused++; window.__wake.pausedAt = performance.now();
  },
  resume() {
    if (this.state !== 'paused') return;
    this.state = 'listening'; window.__wake.resumed++; window.__wake.resumedAt = performance.now();
  },
  stop() { window.__wake.stopped++; this.state = 'idle'; },
};
"""


def voice_view(**over: Any) -> dict[str, Any]:
    """GET /v1/voice (§3)."""
    view: dict[str, Any] = {
        "cloud": {"tts": "ready", "stt": "ready", "reason": None},
        "settings": {"voice": "en-GB-Chirp3-HD-Algieba", "rate": 1.0, "wit": "film"},
        "voices": VOICES,
        "wit_levels": WIT,
        "allowance": {
            "tts": {
                "type": "chirp3-hd",
                "used_chars": 12340,
                "free_chars": 900000,
                "by_type": {
                    "chirp3-hd": {"used": 12340, "free": 900000},
                    "studio": {"used": 0, "free": 900000},
                },
            },
            "stt": {"used_seconds": 150, "free_seconds": 3240},
            "month": "2026-11",
            "resets_at": "2026-12-01T00:00:00-08:00",
            "scope": "deployment",
        },
        "month": {"month": "2026-11", "voice_inr": 0.0},
        "language": "en-IN",
    }
    view.update(over)
    return view


def wav_bytes(seconds: float = 0.3, rate: int = 16000, freq: float = 330.0) -> bytes:
    """A small valid WAV the fake /v1/voice/speak answers with (decodeAudioData reads it)."""
    n = int(seconds * rate)
    pcm = b"".join(
        struct.pack("<h", int(6000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )
    head = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    head += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data"
    return head + struct.pack("<I", len(pcm)) + pcm


SPEECH_WAV = wav_bytes()


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeVoice:
    """Answers /v1/voice* for one page the way §3 says; records every request."""

    def __init__(self, page: Any, view: dict[str, Any] | None = None) -> None:
        self.view = copy.deepcopy(view if view is not None else voice_view())
        self.calls: list[dict[str, Any]] = []
        self.speak_status = 200
        self.speak_code = "voice_unavailable"
        self.transcribe_status = 200
        self.transcribe_code = "voice_unavailable"
        self.speak_audio = SPEECH_WAV
        self.transcript: dict[str, Any] = {
            "text": "Turn on the lights. Then dim them to half.",
            "confidence": 0.93,
            "seconds": 2.1,
            "cost_inr": 0.0,
            "language": "en-IN",
            "no_speech": False,
        }
        self.hold_puts = False
        self.held: list[Any] = []
        self.get_status, self.get_code = 200, "rate_limited"
        self.put_status, self.put_code = 200, "rate_limited"
        self.hold_transcribe = False
        self.held_transcribe: list[Any] = []
        page.route(VOICE_URL, self._handle)

    def to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def spoken(self) -> list[str]:
        return [c["body"].get("text", "") for c in self.to("POST", "/v1/voice/speak")]

    def _handle(self, route: Any) -> None:
        req = route.request
        path = urlsplit(req.url).path
        raw = req.post_data_buffer or b""
        body: Any = None
        if path != "/v1/voice/transcribe" and raw:
            body = json.loads(raw)
        call = {
            "method": req.method,
            "path": path,
            "body": body,
            "raw": raw,
            "headers": dict(req.headers),
        }
        self.calls.append(call)
        if path == "/v1/voice" and req.method == "GET":
            if self.get_status != 200:
                return self._refuse(route, self.get_status, self.get_code)
            return _json(route, 200, self.view)
        if path == "/v1/voice/settings" and req.method == "PUT":
            if self.put_status != 200:
                status, self.put_status = self.put_status, 200  # once
                return self._refuse(route, status, self.put_code)
            if self.hold_puts:
                self.held.append((route, body))
                return None
            return self._put(route, body)
        if path == "/v1/voice/speak" and req.method == "POST":
            if self.speak_status != 200:
                return self._refuse(route, self.speak_status, self.speak_code)
            return route.fulfill(
                status=200,
                content_type="audio/mpeg",
                body=self.speak_audio,
                headers={
                    "X-Jarvis-Chars": str(len((body or {}).get("text", ""))),
                    "X-Jarvis-Cost-Inr": "0",
                },
            )
        if path == "/v1/voice/transcribe" and req.method == "POST":
            if self.hold_transcribe:
                self.held_transcribe.append(route)
                return None
            if self.transcribe_status != 200:
                return self._refuse(route, self.transcribe_status, self.transcribe_code)
            return _json(route, 200, self.transcript)
        return _json(route, 404, {"error": "not_found", "detail": "Not found."})

    def _refuse(self, route: Any, status: int, code: str) -> None:
        """The app's error shape: {error, detail}; a 503 adds reason, a 429 adds Retry-After."""
        body: dict[str, Any] = {"error": code, "detail": "Cloud voice is not available right now."}
        headers = {}
        if status == 503:
            body["reason"] = "api_disabled"
        if status == 429:
            headers["Retry-After"] = "10"
        route.fulfill(
            status=status, content_type="application/json", body=json.dumps(body), headers=headers
        )

    def _put(self, route: Any, body: dict[str, Any]) -> None:
        s = self.view["settings"]
        ids = {v["id"] for v in self.view["voices"] if v["available"]}
        wits = {w["id"] for w in self.view["wit_levels"]}
        if (
            ("voice" in body and body["voice"] not in ids)
            or ("wit" in body and body["wit"] not in wits)
            or ("rate" in body and not 0.8 <= body["rate"] <= 1.25)
        ):
            return _json(
                route,
                422,
                {"error": "input_rejected", "detail": "That setting isn't one JARVIS knows."},
            )
        s.update({k: body[k] for k in ("voice", "rate", "wit") if k in body})
        return _json(route, 200, s)

    def release(self) -> None:
        held, self.held = self.held, []
        for route, body in held:
            self._put(route, body)

    def release_transcribe(self) -> None:
        held, self.held_transcribe = self.held_transcribe, []
        for route in held:
            _json(route, 200, self.transcript)


def speechlike_wav(path: Path, rate: int = 48000) -> None:
    """0.6 s near-silence, 1.6 s of voiced "syllables" (harmonics under a 4 Hz envelope), 3 s
    silence. Chromium loops it as the fake microphone."""
    rnd = random.Random(7)
    samples: list[int] = []
    for _ in range(int(0.6 * rate)):
        samples.append(int(rnd.uniform(-30, 30)))
    phase = 0.0
    for i in range(int(1.6 * rate)):
        t = i / rate
        f0 = 150 + 25 * math.sin(2 * math.pi * 0.8 * t)
        phase += 2 * math.pi * f0 / rate
        env = 0.5 - 0.5 * math.cos(2 * math.pi * 4 * t)
        s = sum(math.sin(h * phase) / h for h in range(1, 9))
        samples.append(int(9000 * env * s))
    for _ in range(int(3.0 * rate)):
        samples.append(int(rnd.uniform(-30, 30)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mic = tmp_path_factory.mktemp("voice") / "speech.wav"
    speechlike_wav(mic)
    args = [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={mic}",
        "--autoplay-policy=no-user-gesture-required",
    ]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(
        viewport: dict[str, int] = DESKTOP,
        device: dict[str, Any] | None = None,
        scripts: tuple[str, ...] = (),
        real_wake: bool = False,
        barge: bool = False,
    ) -> Console:
        c = Console(browser, server_url, token, viewport)
        if not real_wake:  # the real module is tested on its own; these tests use FAKE_WAKE or none
            c.page.route(
                "**/static/console-wakeword.js",
                lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
            )
        c.page.add_init_script(RECORDER)
        # R5: the fake microphones talk constantly, so tests that are not about interrupting pin
        # "Tapping only" (docs/plans/r5-voice.md I0 item 9) unless they ask for barge-in.
        pinned = dict(device or {})
        if not barge:
            pinned.setdefault("interruptBy", "tap")
        if pinned:  # this device's voice settings, set before any script runs
            # only the pin alone must not undo what the page saved before a reload
            keep = (
                ""
                if device is not None
                else "localStorage.getItem('jarvis_voice_device_v1') === null && "
            )
            c.page.add_init_script(
                f"{keep}localStorage.setItem('jarvis_voice_device_v1', "
                f"{json.dumps(json.dumps(pinned))});"
            )
        for s in scripts:
            c.page.add_init_script(s)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _quiet(c: Console) -> list[str]:
    """Page errors other than the refusals a test provokes on purpose (e.g. a 503 from speak)."""
    return [e for e in c.errors if "status of" not in e]


def _speech(c: Console) -> list[str]:
    return [d["text"] for d in c.page.evaluate("window.__voice.speech")]


def _wait(c: Console, js: str, timeout: int = 15000) -> None:
    c.page.wait_for_function(js, timeout=timeout)


def _mic_state(c: Console) -> str:
    return str(c.page.locator("#micBtn").get_attribute("data-state"))


def _voice_panel(c: Console) -> Any:
    c.open_panel("voice")
    c.page.locator("#vVoiceT").wait_for(state="visible")
    return c.page.locator("#p-voice")


# ================================================================== pure pieces (in the page)
@pytest.fixture(scope="module")
def pure(browser: Any, server_url: str) -> Iterator[Any]:
    """One console page, never signed in, for the pure helpers (chunker, WAV, VAD): no /v1 calls,
    so these many quick cases don't spend the app's per-IP rate limit the other tests need."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.route(re.compile(r".*/(v1|auth|connect|internal)/.*"), lambda r: r.abort())
    page.goto(server_url + "/")
    page.wait_for_function("() => !!(window.JarvisSpeechChunker && window.JarvisVad)")
    yield page
    ctx.close()


CHUNK_JS = """([text, deltas]) => {
  const c = window.JarvisSpeechChunker.create({ honorific: 'Sir' });
  let out = [];
  if (deltas) { for (const ch of text) out = out.concat(c.push(ch)); }
  else out = out.concat(c.push(text));
  return out.concat(c.end());
}"""


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello, Sir. All systems are ready.", ["Hello, Sir.", "All systems are ready."]),
        (
            "Mr. Sharma called at 9 a.m. today. He wants the report.",
            ["Mr. Sharma called at 9 a.m. today.", "He wants the report."],
        ),
        (
            "Bring snacks, e.g. fruit and nuts. Thanks.",
            ["Bring snacks, e.g. fruit and nuts.", "Thanks."],
        ),
        (
            "The total is ₹1,234.50. Shall I pay it?",
            ["The total is ₹1,234.50.", "Shall I pay it?"],
        ),
        (
            "See https://example.com/docs/a.b?x=1 for more. That is all.",
            ["See https://example.com/docs/a.b?x=1 for more.", "That is all."],
        ),
        (
            "Here is the script:\n```python\nprint('hi. there')\nx = 1\n```\nRun it once.",
            ["Here is the script:", "The details are on screen, Sir.", "Run it once."],
        ),
        (
            "Your week:\n| Day | Meetings |\n|---|---|\n| Mon | 3 |\n"
            "A calm week. Two code blocks:\n```\na\n```\n```\nb\n```",
            ["Your week:", "The details are on screen, Sir.", "A calm week. Two code blocks:"],
        ),
        (
            "Name | Role\n--- | ---\nPriya | Manager\nDone.",
            ["The details are on screen, Sir.", "Done."],
        ),
        # list items: one sentence each, without the markers (as the server's speakable() does)
        ("1. Buy milk\n2. Call Priya", ["Buy milk.", "Call Priya."]),
        ("1. Yes\n2. No", ["Yes.", "No."]),
        ("Options:\n1. Yes\n2. No\nPick one.", ["Options:", "Yes. No. Pick one."]),
        ("- Eggs\n- Bread\n* Milk!\n+ Tea\n• Jam", ["Eggs.", "Bread. Milk! Tea. Jam."]),
        ("1) Plan\n    - pick a date\n2) Book", ["Plan.", "pick a date. Book."]),
        ("1.5 million came. 2023 was busy.", ["1.5 million came.", "2023 was busy."]),
        # 4-space / tab indented code is never spoken
        (
            "Run this:\n    rm -rf build\n    make\nThen rebuild.",
            ["Run this:", "The details are on screen, Sir.", "Then rebuild."],
        ),
        (
            "Steps:\n\n\tmake build\n\tmake test\n\nDone.",
            ["Steps:", "The details are on screen, Sir.", "Done."],
        ),
        ("Well... then. Wait… really? Yes!", ["Well... then.", "Wait… really? Yes!"]),
        ("```\nonly code\n```", ["The details are on screen, Sir."]),
        ("**Bold** move, J. K. Rowling said.", ["**Bold** move, J. K. Rowling said."]),
    ],
)
def test_chunker_splits_speakable_sentences(pure: Any, text: str, expected: list[str]) -> None:
    assert pure.evaluate(CHUNK_JS, [text, False]) == expected
    assert pure.evaluate(CHUNK_JS, [text, True]) == expected  # streamed char by char: the same


def test_chunker_gives_the_first_sentence_at_once_and_packs_the_rest(pure: Any) -> None:
    got = pure.evaluate(
        """() => {
      const c = window.JarvisSpeechChunker.create({ honorific: 'Ma\\'am' });
      const first = c.push('Good evening. S');
      const long = Array.from({ length: 30 }, (_, i) => `Sentence number ${i + 1} is here.`)
        .join(' ');
      const mid = c.push(long.slice(1) + ' ');
      const end = c.end();
      const other = window.JarvisSpeechChunker.create({ honorific: 'Ma\\'am' });
      return { first, mid, end, notice: other.push('```\\nx\\n```\\n') };
    }"""
    )
    assert got["first"] == ["Good evening."]  # spoken while the rest is still arriving
    rest = got["mid"] + got["end"]
    assert len(rest) >= 2 and all(len(x) <= 400 for x in rest)
    assert " ".join(rest).startswith("Sentence number 1 is here.")
    assert " ".join(rest).endswith("Sentence number 30 is here.")
    assert got["notice"] == ["The details are on screen, Ma'am."]


def test_wav_header_is_pcm16_mono_16k(pure: Any) -> None:
    data = pure.evaluate(
        """() => {
      const a = new Int16Array(1280).map((_, i) => i - 640), b = new Int16Array(1280).fill(-32768);
      return Array.from(new Uint8Array(window.JarvisWav.encode([a, b])));
    }"""
    )
    raw = bytes(data)
    assert raw[:4] == b"RIFF" and raw[8:16] == b"WAVEfmt "
    (size,) = struct.unpack("<I", raw[4:8])
    fmt = struct.unpack("<IHHIIHH", raw[16:36])
    assert fmt == (16, 1, 1, 16000, 32000, 2, 16)  # PCM, mono, 16 kHz, byte rate, align, bits
    assert raw[36:40] == b"data"
    (n,) = struct.unpack("<I", raw[40:44])
    assert n == 2560 * 2 and size == 36 + n and len(raw) == 44 + n
    samples = struct.unpack("<2560h", raw[44:])
    assert samples[0] == -640 and samples[1279] == 639 and samples[1280] == -32768


VAD_JS = """([pattern]) => {
  const vad = window.JarvisVad.create();
  const loud = () => Int16Array.from({ length: 1280 }, (_, i) => 8000 * Math.sin(i / 3));
  const quiet = () => Int16Array.from({ length: 1280 }, (_, i) => (i % 7) - 3);
  const out = [];
  let i = 0;
  for (const [kind, n] of pattern) {
    for (let k = 0; k < n; k++, i++) {
      const ev = vad.push(kind === 'loud' ? loud() : quiet());
      if (ev) out.push({ at: i, type: ev.type, frames: ev.frames ? ev.frames.length : null });
    }
  }
  return out;
}"""


def test_vad_start_end_timeout_and_max(pure: Any) -> None:
    # speech after 1 s: starts on its 2nd loud frame, ends after 1.2 s (15 frames) of silence
    got = pure.evaluate(VAD_JS, [[["quiet", 12], ["loud", 20], ["quiet", 30]]])
    assert [e["type"] for e in got] == ["start", "end"]
    assert got[0]["at"] == 13 and got[1]["at"] == 12 + 20 + 15 - 1
    assert 20 + 4 <= got[1]["frames"] <= 20 + 4 + 2 + 5 + 1  # pre-roll + speech + a short tail
    # nobody speaks: 6 s → timeout (75 frames of 80 ms)
    got = pure.evaluate(VAD_JS, [[["quiet", 100]]])
    assert got == [{"at": 74, "type": "timeout", "frames": None}]
    # someone never stops: 30 s cap (375 frames)
    got = pure.evaluate(VAD_JS, [[["loud", 400]]])
    assert [e["type"] for e in got] == ["start", "max"] and got[1]["at"] == 374


WORKLET_JS = """async ([freq, rate]) => {
  const ctx = new OfflineAudioContext(1, rate * 2, rate);
  await ctx.audioWorklet.addModule('/static/voice-capture-worklet.js');
  const node = new AudioWorkletNode(ctx, 'jarvis-capture',
    { channelCount: 1, channelCountMode: 'explicit' });
  const frames = [];
  node.port.onmessage = (e) => frames.push(e.data);
  const osc = ctx.createOscillator(); osc.frequency.value = freq;
  const g = ctx.createGain(); g.gain.value = 0.5;
  osc.connect(g); g.connect(node); node.connect(ctx.destination); osc.start();
  await ctx.startRendering();
  await new Promise(r => setTimeout(r, 300));
  const all = frames.flatMap(f => Array.from(f));
  const body = all.slice(1600);  // skip the filter's warm-up
  let sum = 0, crossings = 0;
  for (let i = 0; i < body.length; i++) {
    sum += (body[i] / 32768) ** 2;
    if (i && (body[i - 1] < 0) !== (body[i] < 0)) crossings++;
  }
  return { n: frames.length, lens: [...new Set(frames.map(f => f.length))],
    int16: frames.every(f => f instanceof Int16Array),
    rms: Math.sqrt(sum / body.length), hz: crossings / 2 / (body.length / 16000) };
}"""


@pytest.mark.parametrize("rate", [48000, 44100])
def test_worklet_resamples_to_16k_int16_frames_of_1280_with_anti_aliasing(
    make: Callable[..., Console], rate: int
) -> None:
    c = make()
    c.open()
    tone = c.page.evaluate(WORKLET_JS, [1000, rate])
    assert tone["int16"] and tone["lens"] == [1280]
    assert tone["n"] == 2 * 16000 // 1280  # 2 s → 25 frames of 80 ms
    assert abs(tone["hz"] - 1000) < 15  # the tone keeps its pitch at 16 kHz
    assert 0.3 < tone["rms"] < 0.4  # 0.5 amplitude sine ≈ 0.354 RMS: passband intact
    alias = c.page.evaluate(WORKLET_JS, [12000, rate])  # above the new Nyquist (8 kHz)
    assert alias["rms"] < 0.05 * tone["rms"]  # filtered away (> 26 dB down), not folded to 4 kHz


def test_live_capture_frames_are_1280_sample_int16_at_16k(make: Callable[..., Console]) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const A = window.JarvisAudio;
      await A.open();
      const seen = [];
      const off = A.subscribe((f) => seen.push({ len: f.length, int16: f instanceof Int16Array }));
      await new Promise(r => setTimeout(r, 1000));  // warm-up: the first callbacks come in bursts
      const n0 = seen.length, t0 = performance.now();
      await new Promise(r => setTimeout(r, 3000));
      const perSecond = (seen.length - n0) / ((performance.now() - t0) / 1000);
      off();
      const level = A.level(), open = A.isOpen();
      A.close();
      return { seen, perSecond, level, open, closed: !A.isOpen(), rate: A.SAMPLE_RATE,
        frame: A.FRAME };
    }"""
    )
    seen = got["seen"]
    assert got["open"] and got["closed"] and got["rate"] == 16000 and got["frame"] == 1280
    assert seen and all(f["len"] == 1280 and f["int16"] for f in seen)
    assert abs(got["perSecond"] - 12.5) < 2.5, got["perSecond"]  # 16000 / 1280 = 12.5 a second
    assert c.errors == [] and c.csp_violations() == []


# ================================================================== the spoken turn
def test_mic_to_transcribe_to_voice_message_to_reply_spoken_in_order(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": True})
    fake = FakeVoice(c.page)
    chats: list[dict[str, Any]] = []

    def chat(route: Any) -> None:
        chats.append(json.loads(route.request.post_data or "{}"))
        route.continue_()

    c.page.route("**/v1/chat", chat)
    c.open()
    mic = c.page.locator("#micBtn")
    assert mic.is_visible() and mic.get_attribute("aria-pressed") == "false"
    mic.click()
    assert _mic_state(c) == "listening" and mic.get_attribute("aria-pressed") == "true"
    assert c.page.locator("#statusText").text_content() == "Listening"
    assert c.page.locator("#voiceLive").text_content() in {"Listening", "Hearing you"}
    # the fake microphone's burst of speech, then silence: the VAD ends it, the WAV goes up
    _wait(c, "() => document.querySelectorAll('.row.user').length === 1", 20000)
    up = fake.to("POST", "/v1/voice/transcribe")
    assert len(up) == 1
    assert up[0]["headers"]["content-type"] == "audio/wav"
    assert up[0]["headers"]["x-requested-with"] == "JARVIS"
    assert up[0]["headers"]["authorization"] == "Bearer " + c.token
    # (Chromium leaves bodies this large out of intercepted requests: the page-side copy is used)
    sent = c.page.evaluate("window.__sent.find(s => s.path === '/v1/voice/transcribe')")
    wav = bytes(sent["head"])
    assert wav[:4] == b"RIFF" and struct.unpack("<HII", wav[22:32]) == (1, 16000, 32000)
    assert struct.unpack("<I", wav[40:44])[0] == sent["size"] - 44
    seconds = (sent["size"] - 44) / 32000
    assert 1.0 < seconds < 6.0, seconds  # speech + pre-roll + a short tail, never the silence
    # the transcript went to the chat as a spoken message
    assert (
        chats
        and chats[-1]["message"] == fake.transcript["text"]
        and chats[-1]["channel"] == "voice"
    )
    assert "Spoken" in str(c.page.locator(".row.user .meta").text_content())
    # the reply is spoken chunk by chunk, in order
    _wait(c, "() => window.__voice.speech.length >= 2")
    spoken = _speech(c)
    assert spoken == ["Certainly, Sir.", "You said: Turn on the lights. Then dim them to half."]
    assert fake.spoken() == spoken  # fetched in the same order
    assert all(
        b["body"].get("voice") == "en-GB-Chirp3-HD-Algieba"
        for b in fake.to("POST", "/v1/voice/speak")
    )
    assert "speaking" in c.page.evaluate("window.__voice.states")
    # conversation mode: JARVIS listens again after a spoken reply; Esc cancels it
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'listening'", 8000)
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    assert c.page.locator("#statusText").text_content() == "Online"
    assert c.errors == [] and c.csp_violations() == []


def test_browser_engine_shows_interim_words_and_sends_with_channel_voice(
    make: Callable[..., Console],
) -> None:
    c = make(device={"engine": "browser", "keepListening": False}, scripts=(FAKE_RECOGNITION,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()
    c.page.wait_for_function("() => document.getElementById('input').value === 'Remind'")
    assert "interim" in str(c.page.locator("#input").get_attribute("class"))
    c.page.locator(".row.user .bubble", has_text="Remind me about the review.").wait_for()
    assert c.page.evaluate("window.__rec[0].lang") == "en-IN"  # from GET /v1/voice
    assert c.page.locator("#input").input_value() == ""
    assert fake.to("POST", "/v1/voice/transcribe") == []  # the browser did the listening
    _wait(c, "() => window.__voice.speech.length >= 2")
    assert c.errors == [] and c.csp_violations() == []


def test_send_straight_away_off_leaves_the_words_to_check(make: Callable[..., Console]) -> None:
    c = make(
        device={"engine": "browser", "autoSend": False, "keepListening": False},
        scripts=(FAKE_RECOGNITION,),
    )
    FakeVoice(c.page)
    chats: list[dict[str, Any]] = []
    c.page.route(
        "**/v1/chat", lambda r: (chats.append(json.loads(r.request.post_data)), r.continue_())
    )
    c.open()
    c.page.locator("#micBtn").click()
    c.page.wait_for_function(
        "() => document.getElementById('input').value === 'Remind me about the review.'"
    )
    assert _mic_state(c) == "idle" and chats == []
    assert "Press Enter" in str(
        c.page.locator("#voiceLine").text_content()
    ) or "press Enter" in str(c.page.locator("#voiceLine").text_content())
    c.page.locator("#input").press("End")
    c.page.keyboard.type(" Tomorrow.")
    c.page.keyboard.press("Enter")
    c.page.locator(".row.user .bubble", has_text="Tomorrow.").wait_for()
    assert chats[-1]["channel"] == "voice"  # dictated, checked, still a spoken message
    assert c.errors == []


def test_barge_in_stops_speech_and_listens(make: Callable[..., Console]) -> None:
    c = make(device={"speak": "always", "keepListening": False})
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=4.0)  # long enough to interrupt
    c.open()
    c.send("One. " + "This sentence is long enough to be part of a chunk of its own. " * 14)
    _wait(c, "() => window.__voice.speech.length >= 1")
    assert _mic_state(c) == "speaking"
    assert c.page.locator("#statusText").text_content() == "Speaking"
    assert c.page.locator("#coreState").text_content() == "Speaking"
    assert c.page.evaluate("window.JarvisVoice.speaker.speaking()") is True
    c.page.wait_for_timeout(300)
    asked = len(fake.to("POST", "/v1/voice/speak"))
    assert asked == 2  # the chunk playing and the next one, fetched ahead; no more
    c.page.locator("#micBtn").click()  # barge-in: stop speaking, listen
    assert c.page.evaluate("window.JarvisVoice.speaker.speaking()") is False
    assert _mic_state(c) == "listening"
    c.page.wait_for_timeout(800)
    assert len(_speech(c)) == 1  # nothing else was played
    assert len(fake.to("POST", "/v1/voice/speak")) == asked  # and nothing more was fetched
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    assert c.errors == []


def test_escape_stops_speech_and_a_new_conversation_silences_it(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always"})
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=4.0)
    c.open()
    c.send("Read me something long.")  # typed, spoken because "Speak replies: Always"
    _wait(c, "() => window.__voice.speech.length >= 1")
    assert _mic_state(c) == "speaking"
    c.page.locator("#scroll").click()
    c.page.keyboard.press("Escape")
    assert (
        c.page.evaluate("window.JarvisVoice.speaker.speaking()") is False
        and _mic_state(c) == "idle"
    )
    c.send("Again, please.")
    _wait(c, "() => window.JarvisVoice.speaker.speaking()")
    c.page.locator("#newBtn").click()  # another conversation: all audio stops
    assert (
        c.page.evaluate("window.JarvisVoice.speaker.speaking()") is False
        and _mic_state(c) == "idle"
    )
    assert fake.to("GET", "/v1/voice")  # loaded once "Always" was set on this device
    assert c.errors == []


def test_speak_503_falls_back_to_the_browser_voice_with_one_note(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"engine": "browser", "keepListening": False}, scripts=(FAKE_RECOGNITION, FAKE_SYNTH)
    )
    fake = FakeVoice(c.page)
    fake.speak_status = 503
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__synth.length >= 2")
    assert c.page.evaluate("window.__synth") == [
        "Certainly, Sir.",
        "You said: Remind me about the review.",
    ]
    assert len(fake.to("POST", "/v1/voice/speak")) <= 2  # the rest never went to the cloud
    note = c.page.locator("#voiceLine")
    assert "browser's voice" in str(note.text_content())
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'idle'")
    # the next reply: still the browser voice (cloud marked down), and no second note
    c.page.evaluate("document.getElementById('voiceLine').textContent = ''")
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__synth.length >= 4")
    calls = len(fake.to("POST", "/v1/voice/speak"))
    assert calls <= 2 and note.text_content() == ""
    assert _quiet(c) == []


def test_speak_voice_busy_429_falls_back_and_402_says_the_limit(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"engine": "browser", "keepListening": False}, scripts=(FAKE_RECOGNITION, FAKE_SYNTH)
    )
    fake = FakeVoice(c.page)
    fake.speak_status, fake.speak_code = 402, "budget_reached"
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__synth.length >= 2")
    assert "voice limit is reached" in str(c.page.locator("#voiceLine").text_content())
    # voice_busy: Google throttled us; the browser speaks this reply, the cloud is asked again soon
    fake2 = make(
        device={"engine": "browser", "keepListening": False}, scripts=(FAKE_RECOGNITION, FAKE_SYNTH)
    )
    busy = FakeVoice(fake2.page)
    busy.speak_status, busy.speak_code = 429, "voice_busy"
    fake2.open()
    fake2.page.locator("#micBtn").click()
    _wait(fake2, "() => window.__synth.length >= 2")
    assert fake2.page.evaluate("window.JarvisVoice.outputEngine()") == "browser"  # for Retry-After
    assert _quiet(c) == [] and _quiet(fake2) == []


def test_transcribe_503_hands_listening_to_the_browser_recognition(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(FAKE_RECOGNITION,))
    fake = FakeVoice(c.page)
    fake.transcribe_status = 503
    c.open()
    c.page.locator("#micBtn").click()  # Automatic: the cloud listens first (the fake microphone)
    _wait(c, "() => window.__rec.length === 1", 20000)  # refused → this browser listens instead
    assert len(fake.to("POST", "/v1/voice/transcribe")) == 1
    assert "Say that again" in str(c.page.locator("#voiceLine").text_content())
    c.page.locator(".row.user .bubble", has_text="Remind me about the review.").wait_for()
    assert c.page.evaluate("window.JarvisVoice.inputEngine()") == "browser"
    assert _quiet(c) == []


def test_chosen_cloud_engine_is_never_swapped_for_the_browser(make: Callable[..., Console]) -> None:
    c = make(device={"engine": "cloud"}, scripts=(FAKE_RECOGNITION,))
    FakeVoice(
        c.page, voice_view(cloud={"tts": "ready", "stt": "unavailable", "reason": "api_disabled"})
    )
    c.open()
    c.page.locator("#micBtn").click()
    help_ = c.page.locator("#micHelp")
    help_.wait_for(state="visible")
    assert "Speech engine to Automatic" in str(help_.text_content())
    assert c.page.evaluate("window.__rec.length") == 0  # no audio went to the browser's maker
    assert _mic_state(c) == "idle" and c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_an_approval_after_a_spoken_turn_is_said_with_the_fixed_line(
    make: Callable[..., Console],
) -> None:
    c = make(device={"engine": "browser"}, scripts=(FAKE_RECOGNITION,))
    fake = FakeVoice(c.page)
    approvals: list[str] = []
    pending = {
        "id": "ap1",
        "tool": "gmail_send",
        "summary": "Send the email to Priya",
        "arguments": {"to": "priya@example.com"},
        "risk": "R3",
        "expires_at": "2026-11-01T12:00:00Z",
        "session_id": "s-voice",
    }
    reply = {
        "session_id": "s-voice",
        "reply": "Done, Sir. Rather efficient of me, I must say. It is ready to send.",
        "tool_calls": 1,
        "pending_approvals": [pending],
        "trace_id": "t1",
        "model": "mock",
        "brain": "mock",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "cost_usd": 0,
        "cost_inr": 0,
        "total_cost_usd": 0,
        "total_cost_inr": 0,
        "latency_ms": 5,
        "turn_count": 2,
        "memory_used": [],
    }
    c.page.route("**/v1/chat", lambda r: _json(r, 200, reply))
    c.page.route(
        "**/v1/approvals/**", lambda r: (approvals.append(r.request.url), _json(r, 500, {}))
    )
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__voice.speech.length >= 1")
    c.page.wait_for_timeout(800)
    assert _speech(c) == [APPROVAL_LINE]
    assert fake.spoken() == [APPROVAL_LINE]  # never the reply's own (witty) words
    assert approvals == []  # nothing is approved by voice
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'idle'")
    c.page.wait_for_timeout(800)
    assert _mic_state(c) == "idle"  # no conversation-mode re-listen after an approval
    assert c.errors == []


def test_mic_blocked_shows_help(make: Callable[..., Console]) -> None:
    blocked = """
    navigator.mediaDevices.getUserMedia = () =>
      Promise.reject(new DOMException('denied', 'NotAllowedError'));
    """
    c = make(scripts=(blocked,))
    FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()
    help_ = c.page.locator("#micHelp")
    help_.wait_for(state="visible")
    assert "blocked" in str(help_.text_content()) and "tap the mic again" in str(
        help_.text_content()
    )
    assert _mic_state(c) == "idle"
    assert c.errors == []


def test_ctrl_space_toggles_listening_and_escape_cancels_without_sending(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False})
    fake = FakeVoice(c.page)
    c.open()
    c.page.locator("#input").focus()
    c.page.keyboard.press("Control+Space")
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'listening'")
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    assert c.page.locator(
        "#p-chat"
    ).is_visible()  # Esc cancelled listening, it did not close the panel
    c.page.wait_for_timeout(3500)
    assert fake.to("POST", "/v1/voice/transcribe") == []
    assert c.errors == []


# ================================================================== the Voice panel
def test_voice_panel_lists_available_voices_and_saves_settings(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    labels = panel.locator("#vVoiceT ~ .vlist .vlab b").all_text_contents()
    assert labels == ["Algieba", "Sadaltager", "Charon", "Studio-B"]  # Iapetus is not available
    assert (
        panel.locator("input[name='vVoice']:checked").get_attribute("value")
        == "en-GB-Chirp3-HD-Algieba"
    )
    assert panel.locator("#vAllow").text_content() == ALLOWANCE
    assert "Cloud voice ready" in str(panel.locator("#voiceStatus").text_content())
    assert c.page.locator("#voiceMeta").text_content() == "Cloud voice"
    wits = panel.locator("#vWitT ~ .vlist .vlab").all_text_contents()
    assert any("at most one light quip" in w for w in wits) and len(wits) == 3
    # debounced: quick changes → one PUT carrying all of them (three slider steps, a voice, a wit)
    c.page.locator("#vRate").focus()
    for _ in range(3):
        c.page.keyboard.press("ArrowRight")
    assert c.page.locator("#vRateOut").text_content() == "1.15×"
    c.page.evaluate(
        "() => ['vVoice-2', 'vWit-2']"
        ".forEach(id => document.querySelector(`label[for=${id}]`).click())"
    )
    c.page.locator("#voiceNote.ok").wait_for()
    puts = fake.to("PUT", "/v1/voice/settings")
    assert len(puts) == 1
    assert puts[0]["body"] == {"voice": "en-GB-Chirp3-HD-Charon", "wit": "extra", "rate": 1.15}
    assert puts[0]["headers"]["x-requested-with"] == "JARVIS"
    assert c.page.locator("#vRateOut").text_content() == "1.15×"
    assert c.page.locator("#vRate").get_attribute("aria-valuetext") == "1.15×"
    # serialized: a change made while a save is in flight waits for it
    fake.hold_puts = True
    panel.locator("label", has_text="Measured").click()
    c.page.wait_for_timeout(700)
    panel.locator("label", has_text="Film").click()
    c.page.wait_for_timeout(900)
    assert len(fake.to("PUT", "/v1/voice/settings")) == 2  # the second change is still waiting
    fake.hold_puts = False
    fake.release()
    for _ in range(40):
        if len(fake.to("PUT", "/v1/voice/settings")) == 3:
            break
        c.page.wait_for_timeout(100)
    bodies = [p["body"] for p in fake.to("PUT", "/v1/voice/settings")]
    assert bodies[1:] == [{"wit": "measured"}, {"wit": "film"}]
    # ▶ Preview: the server's fixed sample in that voice
    panel.locator("#vPrev-1").click()
    _wait(c, "() => window.__voice.speech.length >= 1")
    prev = fake.to("POST", "/v1/voice/speak")[-1]["body"]
    assert prev == {"preview": True, "voice": "en-GB-Chirp3-HD-Sadaltager"}  # exactly this
    assert c.errors == [] and c.csp_violations() == []


def test_voice_panel_device_settings_are_kept_on_this_device(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    auto, keep = panel.locator("#vAuto"), panel.locator("#vKeep")
    assert (
        auto.get_attribute("aria-pressed") == "true"
        and keep.get_attribute("aria-pressed") == "true"
    )
    auto.click()
    c.page.locator("#vSpeak").select_option("always")
    c.page.locator("#vEngine").select_option("browser")
    c.page.locator("#vFinish").select_option("clean")
    saved = json.loads(c.page.evaluate("localStorage.getItem('jarvis_voice_device_v1')"))
    assert saved == {
        "engine": "browser",
        "finish": "clean",
        "speak": "always",
        "autoSend": False,
        "keepListening": True,
        "wake": False,
        "interruptBy": "tap",  # pinned by the factory (R5 I0)
        "followUpS": 8,
        "longPauseS": 20,
        "endSilenceMs": 1200,
        "checkIn": True,
        "cues": True,
    }
    c.page.reload()
    c.open()
    _voice_panel(c)
    assert c.page.locator("#vAuto").get_attribute("aria-pressed") == "false"
    assert c.page.locator("#vSpeak").input_value() == "always"
    assert c.errors == []


def test_voice_panel_rejected_setting_explains_and_reloads(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVoice(c.page)
    fake.view["voices"] = [
        *VOICES,
        {**VOICES[3], "id": "en-GB-Gone", "label": "Gone", "available": True},
    ]
    c.open()
    panel = _voice_panel(c)
    fake.view["voices"] = VOICES  # the server dropped it meanwhile: 422 input_rejected
    panel.locator("label", has_text="Gone").click()
    c.page.locator("#voiceNote.bad").wait_for()
    assert "isn't one JARVIS knows" in str(c.page.locator("#voiceNote").text_content())
    _wait(
        c,
        "() => ![...document.querySelectorAll('#p-voice .vlab b')]"
        ".some(b => b.textContent === 'Gone')",
    )
    assert len(fake.to("GET", "/v1/voice")) >= 2
    assert _quiet(c) == []


@pytest.mark.parametrize(
    "cloud, words",
    [
        (
            {"tts": "unavailable", "stt": "unavailable", "reason": "api_disabled"},
            "gcloud services enable texttospeech.googleapis.com speech.googleapis.com",
        ),
        (
            {"tts": "unavailable", "stt": "unavailable", "reason": "not_configured"},
            "no Google Cloud credentials",
        ),
        ({"tts": "off", "stt": "off", "reason": None}, "switched off on this server"),
        ({"tts": "unavailable", "stt": "ready", "reason": "timeout"}, "isn't answering right now"),
    ],
)
def test_voice_panel_cloud_status_has_a_plain_fix(
    make: Callable[..., Console], cloud: dict[str, Any], words: str
) -> None:
    c = make()
    FakeVoice(c.page, voice_view(cloud=cloud))
    c.open()
    panel = _voice_panel(c)
    assert words in str(panel.locator("#voiceStatus").text_content())
    assert c.page.locator("#voiceMeta").text_content() == "Browser voice"
    assert "this browser" in str(panel.locator("#vSpeakD").text_content())
    assert c.errors == []


def test_voice_panel_not_available_when_the_route_is_missing(make: Callable[..., Console]) -> None:
    c = make()
    c.page.route(VOICE_URL, lambda r: _json(r, 404, {"detail": "Not Found"}))
    c.open()
    c.open_panel("voice")
    c.page.locator("#voiceStatus", has_text="Not available in this setup").wait_for()
    assert c.page.locator("#vVoiceT").is_hidden() and c.page.locator("#vDevT").is_visible()
    assert c.page.locator("#voiceMeta").text_content() == "Not available"


# ================================================================== "Hey Jarvis"
def test_wake_switch_is_hidden_without_the_wake_word_module(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    assert c.page.evaluate("typeof window.JarvisWake") == "undefined"
    assert c.page.locator("#vWakeRow").is_hidden()
    assert c.errors == []


def test_wake_switch_is_offered_with_the_real_wake_word_module(
    make: Callable[..., Console],
) -> None:
    c = make(real_wake=True)
    FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    assert c.page.evaluate("typeof window.JarvisWake.supported") == "function"
    assert panel.locator("#vWakeRow").is_visible()
    assert panel.locator("#vWake").get_attribute("aria-pressed") == "false"  # off by default
    assert c.errors == []


def test_wake_switch_feeds_the_wake_word_module_and_wakes_the_mic(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(FAKE_WAKE,))
    FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    row = panel.locator("#vWakeRow")
    assert row.is_visible()
    assert "openWakeWord (CC BY-NC-SA 4.0), personal use" in str(row.text_content())
    sw = panel.locator("#vWake")
    assert sw.get_attribute("aria-pressed") == "false"  # off by default
    sw.click()
    _wait(c, "() => window.__wake.frames >= 5")
    w = c.page.evaluate("({ ...window.__wake, fire: undefined })")
    assert w["loaded"] == 1 and w["started"] == 1 and w["rate"] == 16000
    assert w["len"] == 1280 and w["int16"] is True
    assert panel.locator("#vWakeChip").text_content() == "Listening for ‘Hey Jarvis’"
    assert (
        json.loads(c.page.evaluate("localStorage.getItem('jarvis_voice_device_v1')"))["wake"]
        is True
    )
    # the wake word fires: JARVIS listens; the wake detector gets no frames meanwhile
    c.page.evaluate("window.__wake.fire()")
    assert _mic_state(c) == "listening"
    before = c.page.evaluate("window.__wake.frames")
    c.page.wait_for_timeout(500)
    assert c.page.evaluate("window.__wake.frames") == before  # gated while JARVIS listens
    assert panel.locator("#vWakeChip").text_content() == "Paused while JARVIS speaks or listens"
    c.page.keyboard.press("Escape")
    c.page.wait_for_timeout(1000)  # resumed ~0.4 s after the mic went idle
    assert c.page.evaluate("window.__wake.frames") > before  # listening for the wake word again
    sw.click()  # off: the module is stopped and the microphone closed
    assert c.page.evaluate("window.__wake.stopped") == 1
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.errors == []


# ================================================================== layout, a11y, text
def test_phone_layout_mic_in_composer_voice_behind_more(make: Callable[..., Console]) -> None:
    c = make(viewport=PHONE)
    FakeVoice(c.page)
    c.open()
    mic = c.page.locator("#micBtn")
    assert mic.is_visible()
    box = mic.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44  # touch target
    tabs = c.page.locator("#dock .dk:visible")
    assert tabs.count() <= 8
    assert c.page.locator('.dk[data-open="voice"]').is_hidden()
    c.open_panel("voice")  # through the More sheet
    c.page.locator("#vVoiceT").wait_for(state="visible")
    c.page.wait_for_timeout(300)
    widths = c.page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth,"
        " document.getElementById('p-voice').scrollWidth,"
        " document.getElementById('p-voice').clientWidth]"
    )
    assert widths[0] <= widths[2] and widths[1] <= widths[2], widths
    assert widths[3] <= widths[4] + 1, widths  # nothing in the panel scrolls sideways
    assert c.errors == []


@pytest.mark.parametrize("surface", ["night", "day"])
def test_voice_panel_and_mic_contrast(make: Callable[..., Console], surface: str) -> None:
    c = make(scripts=(FAKE_WAKE, f"localStorage.setItem('jarvis_surface', '{surface}');"))
    FakeVoice(
        c.page, voice_view(cloud={"tts": "unavailable", "stt": "ready", "reason": "api_disabled"})
    )
    c.open()
    _voice_panel(c)
    c.page.evaluate(SETTLE_JS, "#p-voice")
    found = c.page.evaluate(CONTRAST_JS, "#p-voice")
    assert len(found) > 25
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low
    c.page.evaluate(
        "document.getElementById('voiceLine').textContent ="
        " 'The cloud voice is not available: speaking with this browser voice.'"
    )
    found = c.page.evaluate(CONTRAST_JS, ".composer-wrap")
    low = [f for f in found if f["ratio"] < 4.5]
    assert low == [], low


def test_page_has_no_dollar_sign_zero_errors_and_zero_csp_reports(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(FAKE_WAKE,))
    FakeVoice(c.page, voice_view(month={"voice_inr": 12.5}))
    c.open()
    _voice_panel(c)
    assert "≈ ₹12.50" in str(c.page.locator("#vAllow").text_content())
    text = c.page.evaluate("document.body.innerText")
    assert "$" not in text
    c.page.wait_for_timeout(500)
    assert c.errors == [] and c.csp_violations() == []
