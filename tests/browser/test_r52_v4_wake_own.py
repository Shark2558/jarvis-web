# tests/browser/test_r52_v4_wake_own.py -- R5.2 V4 (row 83), real Chromium under the console's CSP:
# console-wakeword-own.js hands console-wakeword.js the owner's own model (an ONNX file written by
# jarvis.localspeech.wakeword.onnx_write, run by the vendored onnxruntime-web in place of
# hey_jarvis_v0.1) and his verifier (stage 1's JSON, the same rule as the kit's Python); a file
# with the wrong hash, or one the runtime refuses, leaves today's model; nothing is requested
# beyond the vendored files and the (stubbed) wake-word routes.
from __future__ import annotations

import array
import base64
import hashlib
import random
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from jarvis.localspeech.wakeword import formats
from jarvis.localspeech.wakeword.formats import VerifierFile
from jarvis.localspeech.wakeword.onnx_write import Dense, mlp_onnx

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

TEST_PAGE = "/__wakeword_own_test__"
PAGE_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>own wake word</title>'
    '<script src="/static/console-wakeword.js"></script>'
    '<script src="/static/console-wakeword-own.js"></script></head><body></body></html>'
)
BASE = "/v1/voice/profile/wakeword"
WAKE_FILE = "/static/wakeword/oww-0.5.1/hey_jarvis_v0.1.onnx"
# The console's transport, stubbed: the routes answer what each test puts in window.__own.
STUBS = """
window.__jarvisWakeTest = {};
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective));
window.__own = { status: null, files: {}, calls: [] };
const bytesOf = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
window.JarvisConsole = { api: async (path) => {
  window.__own.calls.push(path);
  if (path === '/v1/voice/profile/wakeword' && window.__own.status) return window.__own.status;
  throw Object.assign(new Error('refused'), { status: 409 });
} };
window.JarvisChat = { raw: async (path) => {
  window.__own.calls.push(path);
  const b64 = window.__own.files[path];
  return b64 ? new Response(bytesOf(b64), { status: 200 }) : new Response('', { status: 404 });
} };
"""
FEED = """
async ({ seconds }) => {
  const hook = window.__jarvisWakeTest;
  let t = 0;
  hook.now = () => t;
  const subs = new Set();
  const subscribe = (fn) => { subs.add(fn); return () => subs.delete(fn); };
  const source = { sampleRate: 16000, subscribe };
  let wakes = 0;
  JarvisWake.start(source, () => { wakes += 1; });
  const frame = new Int16Array(1280);
  for (let i = 0; i < Math.round(seconds * 12.5); i++) {
    subs.forEach((fn) => fn(frame));
    t += 80;
    await hook.idle();
  }
  JarvisWake.stop();
  return wakes;
}
"""
NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _always_model() -> bytes:
    """An owned model that scores ~1 on anything: proof that it, not today's, is running."""
    return mlp_onnx([Dense([0.0] * formats.FEATURES, [10.0], formats.FEATURES, 1, "sigmoid")])


def _verifier(bias: float, weights: tuple[float, ...] | None = None) -> VerifierFile:
    return VerifierFile(
        embedding_sha256=formats.console_pins()[formats.EMBEDDING_MODEL],
        weights=weights or tuple([0.0] * formats.FEATURES),
        bias=bias,
        trained_at=NOW,
        clips=25,
    )


def _status(model: bytes | None, verifier: bytes | None, *, announce: str | None = None) -> Any:
    def info(artifact: str, data: bytes) -> dict[str, Any]:
        return {
            "artifact": artifact,
            "sha256": announce or _sha(data),
            "size": len(data),
            "licence": "LicenseRef-Owner",
            "beats_current": True,
        }

    return {
        "available": True,
        "use_owned": model is not None,
        "use_verifier": verifier is not None,
        "owned": info("owned", model) if model else None,
        "verifier": info("verifier", verifier) if verifier else None,
    }


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class OwnPage:
    def __init__(self, browser: Any, url: str, status: Any, files: dict[str, bytes]) -> None:
        with urllib.request.urlopen(url + "/", timeout=10) as r:
            csp = str(r.headers["content-security-policy"])
        self.url = url
        self.ctx = browser.new_context()
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.requests: list[str] = []
        self.page.route(
            url + TEST_PAGE,
            lambda route: route.fulfill(
                status=200,
                headers={"content-type": "text/html", "content-security-policy": csp},
                body=PAGE_HTML,
            ),
        )
        self.page.add_init_script(STUBS)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.requests.append(r.url.removeprefix(url)))
        self.page.goto(url + TEST_PAGE)
        self.page.evaluate(
            "([s, f]) => { window.__own.status = s; window.__own.files = f; }",
            [status, {k: _b64(v) for k, v in files.items()}],
        )

    def js(self, script: str, arg: Any = None) -> Any:
        return self.page.evaluate(script, arg)

    def close(self) -> None:
        self.ctx.close()


@pytest.fixture
def page_with(browser: Any, server_url: str) -> Iterator[Any]:
    pages: list[OwnPage] = []

    def make(status: Any, files: dict[str, bytes]) -> OwnPage:
        pages.append(OwnPage(browser, server_url, status, files))
        return pages[-1]

    yield make
    for p in pages:
        p.close()


def test_the_verifier_rule_in_the_browser_is_the_kits(page_with: Any) -> None:
    rng = random.Random(7)
    v = _verifier(0.2, tuple(rng.uniform(-0.02, 0.02) for _ in range(formats.FEATURES)))
    page = page_with(None, {})
    cases = [(b, [rng.uniform(-3, 3) for _ in range(formats.FEATURES)]) for b in (0.05, 0.3, 0.9)]
    got = page.js(
        "([file, cases]) => { const r = JarvisWakeOwn.rescorer(file); "
        "return cases.map(([b, w]) => r.rescore(b, Float32Array.from(w))); }",
        [v.model_dump(mode="json"), cases],
    )
    for (base, window), score in zip(cases, got, strict=True):
        exact = list(array.array("f", window))  # float32, as the page holds them
        assert score == pytest.approx(v.score(base, exact), abs=1e-9)
    for bad in ({"licence": "CC-BY-NC-SA-4.0"}, {"embedding_sha256": "0" * 64}, {"weights": [1]}):
        assert page.js("(f) => JarvisWakeOwn.rescorer(f)", v.model_dump(mode="json") | bad) is None


def test_his_own_model_runs_in_place_of_todays(page_with: Any) -> None:
    model = _always_model()
    page = page_with(_status(model, None), {f"{BASE}/model": model})
    page.js("() => JarvisWake.load()")
    assert page.js("() => JarvisWake.state") == "idle"
    assert page.js("() => window.__jarvisWakeTest.stats().own") == {
        "model": True,
        "verifier": False,
    }
    assert WAKE_FILE not in page.requests  # today's model was never fetched
    assert page.js(FEED, {"seconds": 3}) >= 1  # silence wakes it: the owned model is running
    assert page.js("() => window.__csp") == [] and page.errors == []


def test_the_verifier_vetoes_after_the_score(page_with: Any) -> None:
    model, veto = _always_model(), _verifier(-20.0).to_bytes()
    page = page_with(_status(model, veto), {f"{BASE}/model": model, f"{BASE}/verifier": veto})
    page.js("() => JarvisWake.load()")
    assert page.js("() => window.__jarvisWakeTest.stats().own") == {"model": True, "verifier": True}
    assert page.js(FEED, {"seconds": 3}) == 0  # not him: the score is the verifier's


def test_a_file_with_another_hash_is_not_used(page_with: Any) -> None:
    model = _always_model()
    page = page_with(_status(model, None, announce="1" * 64), {f"{BASE}/model": model})
    page.js("() => JarvisWake.load()")
    assert page.js("() => window.__jarvisWakeTest.stats().own") == {
        "model": False,
        "verifier": False,
    }
    assert WAKE_FILE in page.requests and page.js(FEED, {"seconds": 3}) == 0


def test_a_model_the_runtime_refuses_falls_back_to_todays(page_with: Any) -> None:
    junk = b"\x08\x07 not really a model"
    page = page_with(_status(junk, None), {f"{BASE}/model": junk})
    page.js("() => JarvisWake.load()")
    assert page.js("() => JarvisWake.state") == "idle"
    assert page.js("() => window.__jarvisWakeTest.stats().own") == {
        "model": False,
        "verifier": False,
    }
    assert WAKE_FILE in page.requests


def test_without_his_files_it_is_exactly_as_before(page_with: Any) -> None:
    page = page_with(None, {})
    page.js("() => JarvisWake.load()")
    assert page.js("() => window.__jarvisWakeTest.stats().own") == {
        "model": False,
        "verifier": False,
    }
    assert WAKE_FILE in page.requests
    assert not [r for r in page.requests if r.startswith("/v1/")]  # the stubs answered, no network
