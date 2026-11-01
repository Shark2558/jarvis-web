# tests/browser/test_wakeword.py — the on-device "Hey Jarvis" wake word (slice 9, D12) in real
# Chromium under the console's own CSP: per-frame scores match Python openWakeWord within 0.02
# (tests/fixtures/wakeword/reference_scores.json), positives wake exactly once, negatives never,
# 2-frame rule, 2 s cooldown, pause/resume/stop, overload, load failures, real-time speed, and no
# worker, CSP violation or network request while listening.
from __future__ import annotations

import base64
import json
import statistics
import urllib.request
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/wakeword"
REFERENCE = json.loads((FIXTURES / "reference_scores.json").read_text(encoding="utf-8"))
TOLERANCE = 0.02
FRAME = REFERENCE["frame_samples"]
PAD = REFERENCE["pad_samples"]
POSITIVES = sorted(k for k, v in REFERENCE["clips"].items() if v["kind"] == "positive")
NEGATIVES = sorted(k for k, v in REFERENCE["clips"].items() if v["kind"] == "negative")
ORT_PREFIX = "/static/vendor/ort-1.30.0/"
MODEL_PREFIX = "/static/wakeword/oww-0.5.1/"
# A page the app never serves: Playwright answers it with the console's real CSP header, so the
# module runs under exactly the production policy without any test route in the app.
TEST_PAGE = "/__wakeword_test__"
PAGE_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>wake word</title>'
    '<script src="/static/console-wakeword.js"></script></head><body></body></html>'
)
SPIES = """
window.__jarvisWakeTest = {};
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || ''));
});
window.__workers = 0;
for (const name of ['Worker', 'SharedWorker']) {
  const Real = window[name];
  if (Real) window[name] = function (...args) { window.__workers += 1; return new Real(...args); };
}
// little-endian 16-bit PCM, base64 → Int16Array; and a fake 16 kHz capture source
window.__pcm = (b64) => new Int16Array(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer);
window.__fakeSource = () => {
  const subs = new Set();
  const subscribe = (fn) => { subs.add(fn); return () => subs.delete(fn); };
  return { subs, source: { sampleRate: 16000, subscribe } };
};
"""
# Feeds a clip through JarvisWake.start() from a fake 16 kHz source, one frame per "80 ms" of a
# test clock, waiting for inference between frames like a real-time stream.
FEED = """
async ({ b64, jumpAfterWake }) => {
  const pcm = window.__pcm(b64);
  const hook = window.__jarvisWakeTest;
  let t = 0;
  hook.now = () => t;
  const { subs, source } = window.__fakeSource();
  const wakes = [];
  let frame = 0;
  JarvisWake.start(source, (e) => {
    wakes.push({ score: e.score, frame });
    if (jumpAfterWake) t += jumpAfterWake;
  });
  for (; (frame + 1) * 1280 <= pcm.length; frame++) {
    const view = pcm.subarray(frame * 1280, (frame + 1) * 1280);
    subs.forEach((fn) => fn(view));
    t += 80;
    await hook.idle();
  }
  const state = JarvisWake.state;
  JarvisWake.stop();
  return { wakes, state, after: JarvisWake.state, subscribers: subs.size };
}
"""


def _pcm(name: str, pad: int = PAD) -> bytes:
    with wave.open(str(FIXTURES / REFERENCE["clips"][name]["file"]), "rb") as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (16000, 1, 2)
        data = f.readframes(f.getnframes())
    silence = b"\0\0" * pad
    return silence + data + silence


def _b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def _console_csp(url: str) -> str:
    with urllib.request.urlopen(url + "/", timeout=10) as r:
        return str(r.headers["content-security-policy"])


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class WakePage:
    """The wake-word module alone on a page with the console's CSP, plus error/request spies."""

    def __init__(self, browser: Any, url: str, init: str = "") -> None:
        self.url = url
        self.ctx = browser.new_context()
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.requests: list[str] = []
        csp = _console_csp(url)
        self.page.route(
            url + TEST_PAGE,
            lambda route: route.fulfill(
                status=200,
                headers={"content-type": "text/html", "content-security-policy": csp},
                body=PAGE_HTML,
            ),
        )
        self.page.add_init_script(SPIES + init)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on(
            "console",
            lambda m: (
                self.errors.append(f"console.{m.type}: {m.text}")
                if m.type in ("error", "warning")
                else None
            ),
        )
        self.page.on("request", lambda r: self.requests.append(r.url))
        self.page.goto(url + TEST_PAGE)

    def js(self, script: str, arg: Any = None) -> Any:
        return self.page.evaluate(script, arg)

    def load(self) -> float:
        """Loads the module's runtime and models; returns how long load() took, in ms."""
        ms = self.js(
            "async () => { const t = performance.now(); await JarvisWake.load(); "
            "return performance.now() - t; }"
        )
        assert self.js("() => JarvisWake.state") == "idle"
        return float(ms)

    def close(self) -> None:
        self.ctx.close()


@pytest.fixture(scope="module")
def wake(browser: Any, server_url: str) -> Iterator[WakePage]:
    page = WakePage(browser, server_url)
    print(f"\nfirst load() incl. 18 MB download from localhost: {page.load():.0f} ms")
    yield page
    page.close()


# ---- loading under the real CSP ------------------------------------------------------------------
def test_loads_under_the_console_csp_with_no_worker_violation_or_stray_request(
    wake: WakePage,
) -> None:
    assert wake.js("() => JarvisWake.supported()") is True
    assert wake.js("() => window.__csp") == []
    assert wake.js("() => window.__workers") == 0
    assert wake.errors == []
    paths = {u.removeprefix(wake.url) for u in wake.requests}
    assert paths == {
        TEST_PAGE,
        "/static/console-wakeword.js",
        ORT_PREFIX + "ort.wasm.min.mjs",
        ORT_PREFIX + "ort-wasm-simd-threaded.mjs",
        ORT_PREFIX + "ort-wasm-simd-threaded.wasm",
        MODEL_PREFIX + "melspectrogram.onnx",
        MODEL_PREFIX + "embedding_model.onnx",
        MODEL_PREFIX + "hey_jarvis_v0.1.onnx",
    }
    # idempotent: a second load() makes no request and resolves at once
    before = len(wake.requests)
    wake.load()
    assert len(wake.requests) == before


def test_loads_on_the_real_console_page(browser: Any, server_url: str) -> None:
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        page.add_init_script(SPIES)
        page.goto(server_url + "/")
        page.add_script_tag(url="/static/console-wakeword.js")
        page.evaluate("() => JarvisWake.load()")
        assert page.evaluate("() => JarvisWake.state") == "idle"
        assert page.evaluate("() => window.__csp") == []
        assert page.evaluate("() => window.__workers") == 0
    finally:
        ctx.close()


# ---- parity with Python openWakeWord -------------------------------------------------------------
PARITY = """
async ({ b64 }) => {
  const pcm = window.__pcm(b64);
  const hook = window.__jarvisWakeTest;
  hook.reset();
  const scores = [], ms = [];
  for (let i = 0; (i + 1) * 1280 <= pcm.length; i++) {
    const t0 = performance.now();
    scores.push(await hook.process(pcm.subarray(i * 1280, (i + 1) * 1280)));
    ms.push(performance.now() - t0);
  }
  return { scores, ms };
}
"""


@pytest.fixture(scope="module")
def parity(wake: WakePage) -> dict[str, dict[str, list[float]]]:
    out: dict[str, dict[str, list[float]]] = {}
    for name in REFERENCE["clips"]:
        out[name] = wake.js(PARITY, {"b64": _b64(_pcm(name))})
    return out


def test_seed_noise_is_the_reference_noise(wake: WakePage) -> None:
    head = wake.js("() => window.__jarvisWakeTest.stats().noiseHead")
    assert head == REFERENCE["init_noise"]["head"]


@pytest.mark.parametrize("name", sorted(REFERENCE["clips"]))
def test_every_frame_score_matches_python_openwakeword(
    parity: dict[str, dict[str, list[float]]], name: str
) -> None:
    ref = REFERENCE["clips"][name]["scores"]
    got = parity[name]["scores"]
    assert len(got) == len(ref) == REFERENCE["clips"][name]["frames"]
    worst = max(abs(a - b) for a, b in zip(got, ref, strict=True))
    print(f"\n{name}: frames={len(ref)} max|js-py|={worst:.6f} js_max={max(got):.4f}")
    assert worst <= TOLERANCE, (name, worst)


def test_inference_keeps_up_in_real_time(parity: dict[str, dict[str, list[float]]]) -> None:
    """Typical frames meet the < 20 ms desktop target; nearly all fit the 80 ms real-time budget
    even on a busy CI runner (an idle 2-vCPU box measures a median of about 4-5 ms)."""
    ms = sorted(t for clip in parity.values() for t in clip["ms"])
    median = statistics.median(ms)
    p95 = ms[int(len(ms) * 0.95)]
    print(f"\nper-frame ms ({len(ms)} frames): median={median:.2f} p95={p95:.2f} max={ms[-1]:.2f}")
    assert median < 20
    assert p95 < 80


# ---- detection through the public API ------------------------------------------------------------
@pytest.mark.parametrize("name", POSITIVES)
def test_each_positive_clip_wakes_exactly_once(wake: WakePage, name: str) -> None:
    res = wake.js(FEED, {"b64": _b64(_pcm(name)), "jumpAfterWake": 0})
    assert len(res["wakes"]) == 1, res
    assert res["wakes"][0]["score"] >= 0.5
    assert res["state"] == "listening" and res["after"] == "idle" and res["subscribers"] == 0


@pytest.mark.parametrize("name", NEGATIVES)
def test_negative_clips_never_wake(wake: WakePage, name: str) -> None:
    res = wake.js(FEED, {"b64": _b64(_pcm(name)), "jumpAfterWake": 0})
    assert res["wakes"] == [], res


def test_a_single_frame_above_threshold_is_not_a_wake() -> None:
    """The near miss ("Hey Travis…") has exactly one frame ≥ 0.5 in the reference."""
    scores = REFERENCE["clips"]["neg_awb_travis"]["scores"]
    assert sum(s >= 0.5 for s in scores) == 1


def test_listening_sends_nothing_over_the_network(wake: WakePage) -> None:
    before = len(wake.requests)
    for name in (POSITIVES[0], NEGATIVES[0]):
        wake.js(FEED, {"b64": _b64(_pcm(name)), "jumpAfterWake": 0})
    assert wake.requests[before:] == []
    assert wake.js("() => window.__csp") == [] and wake.js("() => window.__workers") == 0


def _two_utterances(gap_s: float) -> bytes:
    one = _pcm(POSITIVES[0], pad=0)
    return b"\0\0" * PAD + one + b"\0\0" * int(16000 * gap_s) + one + b"\0\0" * PAD


def test_a_second_wake_inside_the_cooldown_is_suppressed(wake: WakePage) -> None:
    audio = _b64(_two_utterances(gap_s=0.4))
    within = wake.js(FEED, {"b64": audio, "jumpAfterWake": 0})
    assert len(within["wakes"]) == 1, within
    # the same audio with the clock moved 2 s on at the first wake: the second one is detected,
    # so it was the cooldown (not the reset) that held it back
    after = wake.js(FEED, {"b64": audio, "jumpAfterWake": 2000})
    assert len(after["wakes"]) == 2, after
    assert after["wakes"][1]["frame"] - after["wakes"][0]["frame"] < 25  # < 2 s of audio apart


def test_threshold_is_respected_and_validated(wake: WakePage) -> None:
    assert wake.js("() => JarvisWake.threshold") == 0.5
    wake.js("() => { JarvisWake.threshold = 1.5; JarvisWake.threshold = NaN; }")
    assert wake.js("() => JarvisWake.threshold") == 0.5
    try:
        wake.js("() => { JarvisWake.threshold = 0.9999; }")
        res = wake.js(FEED, {"b64": _b64(_pcm(POSITIVES[0])), "jumpAfterWake": 0})
        assert res["wakes"] == []
    finally:
        wake.js("() => { JarvisWake.threshold = 0.5; }")


# ---- lifecycle -----------------------------------------------------------------------------------
LIFECYCLE = """
async ({ b64 }) => {
  const pcm = window.__pcm(b64);
  const hook = window.__jarvisWakeTest;
  const { subs, source } = window.__fakeSource();
  const wakes = [];
  const push = async (from, to) => {
    for (let i = from; i < to; i++) {
      subs.forEach((fn) => fn(pcm.subarray(i * 1280, (i + 1) * 1280)));
      await hook.idle();
    }
  };
  const seen = [];
  JarvisWake.start(source, (e) => wakes.push(e.score));
  seen.push(JarvisWake.state);
  await push(0, 10);
  const p0 = hook.stats().processed;
  JarvisWake.pause();
  seen.push(JarvisWake.state);
  await push(10, 40);  // the whole utterance arrives while paused (JARVIS is speaking)
  const p1 = hook.stats().processed;
  JarvisWake.resume();
  seen.push(JarvisWake.state);
  await push(40, 50);
  JarvisWake.stop();
  seen.push(JarvisWake.state);
  return { seen, wakes, ignoredWhilePaused: p1 === p0, subscribers: subs.size };
}
"""


def test_pause_ignores_audio_and_resume_and_stop_follow_the_contract(wake: WakePage) -> None:
    res = wake.js(LIFECYCLE, {"b64": _b64(_pcm(POSITIVES[0]))})
    assert res["seen"] == ["listening", "paused", "listening", "idle"]
    assert res["ignoredWhilePaused"] is True
    assert res["wakes"] == []  # the wake word was spoken only while paused
    assert res["subscribers"] == 0


def test_start_rejects_bad_arguments(wake: WakePage) -> None:
    codes = wake.js(
        """() => {
          const out = [];
          const cb = () => {};
          const ok = window.__fakeSource().source;
          const at48k = { sampleRate: 48000, subscribe: ok.subscribe };
          for (const [src, fn] of [[null, cb], [at48k, cb], [ok, null]]) {
            try { JarvisWake.start(src, fn); out.push('started'); } catch (e) { out.push(e.code); }
          }
          return out;
        }"""
    )
    assert codes == ["bad_source", "bad_source", "bad_callback"]
    assert wake.js("() => JarvisWake.state") == "idle"


OVERLOAD = """
async ({ b64, burst }) => {
  const pcm = window.__pcm(b64);
  const hook = window.__jarvisWakeTest;
  const { subs, source } = window.__fakeSource();
  JarvisWake.start(source, () => {});
  for (let i = 0; i < burst; i++) subs.forEach((fn) => fn(pcm.subarray(0, 1280)));  // no waiting
  await hook.idle();
  const out = { state: JarvisWake.state, stats: hook.stats(), subscribers: subs.size };
  JarvisWake.stop();
  return out;
}
"""


def test_a_backlog_is_dropped_and_a_device_that_cannot_keep_up_reports_error(
    wake: WakePage,
) -> None:
    clip = _b64(_pcm(NEGATIVES[0]))
    once = wake.js(OVERLOAD, {"b64": clip, "burst": 20})
    assert once["state"] == "listening" and once["stats"]["dropped"] >= 12
    again = wake.js(OVERLOAD, {"b64": clip, "burst": 60})
    assert again["state"] == "error" and again["stats"]["lastError"] == "too_slow"
    assert again["subscribers"] == 0
    assert wake.js("() => JarvisWake.state") == "idle"  # stop() clears the error


# ---- failures ------------------------------------------------------------------------------------
def test_load_failure_rejects_with_load_failed_and_can_be_retried(
    browser: Any, server_url: str
) -> None:
    page = WakePage(browser, server_url)
    try:
        blocked = server_url + MODEL_PREFIX + "hey_jarvis_v0.1.onnx"
        page.page.route(blocked, lambda route: route.fulfill(status=404, body="not found"))
        res = page.js(
            """async () => {
              let notLoaded;
              try { JarvisWake.start({ sampleRate: 16000, subscribe: () => () => {} }, () => {}); }
              catch (e) { notLoaded = e.code; }
              try { await JarvisWake.load(); return { notLoaded, code: 'resolved' }; }
              catch (e) { return { notLoaded, code: e.code, state: JarvisWake.state }; }
            }"""
        )
        assert res == {"notLoaded": "not_loaded", "code": "load_failed", "state": "error"}
        page.page.unroute(blocked)
        page.load()
        assert page.js("() => window.__csp") == []
    finally:
        page.close()


EAGER = """
async ({ b64 }) => {
  const pcm = window.__pcm(b64);
  const hook = window.__jarvisWakeTest;
  const first = JarvisWake.load();
  const second = JarvisWake.load();
  const shared = second === first;
  await second;  // then start at once: everything (sessions and seed history) must be ready
  const { subs, source } = window.__fakeSource();
  JarvisWake.start(source, () => {});
  subs.forEach((fn) => fn(pcm.subarray(0, 1280)));
  await hook.idle();
  const out = { shared, state: JarvisWake.state, stats: hook.stats() };
  JarvisWake.stop();
  return out;
}
"""


def test_concurrent_loads_share_one_attempt_and_resolve_ready(
    browser: Any, server_url: str
) -> None:
    page = WakePage(browser, server_url)
    try:
        res = page.js(EAGER, {"b64": _b64(_pcm(NEGATIVES[0]))})
        assert res["shared"] is True
        assert res["state"] == "listening", res
        assert res["stats"]["processed"] == 1 and res["stats"]["lastError"] is None
        assert sum(MODEL_PREFIX in u for u in page.requests) == 3  # one download each
        assert page.errors == []
    finally:
        page.close()


@pytest.mark.parametrize(
    "init",
    ["delete window.WebAssembly;", "delete window.AudioWorkletNode;"],
    ids=["no-wasm", "no-audioworklet"],
)
def test_unsupported_browsers_say_so_and_load_nothing(
    browser: Any, server_url: str, init: str
) -> None:
    page = WakePage(browser, server_url, init=init)
    try:
        res = page.js(
            """async () => {
              const supported = JarvisWake.supported();
              try { await JarvisWake.load(); return { supported, code: 'resolved' }; }
              catch (e) { return { supported, code: e.code, state: JarvisWake.state }; }
            }"""
        )
        assert res == {"supported": False, "code": "unsupported", "state": "error"}
        assert not any("/vendor/ort" in u or "/wakeword/" in u for u in page.requests)
    finally:
        page.close()
