# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_r52_v5_voiceprint.py -- R5.2 V5 (row 84, docs/plans/r5-2-voice.md 3.5, D6): the speaker
# check in a real Chromium. Its three scripts are linked the way I1 will link them (after console-voice-barge.js);
# the model is the stand-in from r52_v5_fakes (the slot ships no real one yet) and every voice is synthetic
# (tests/fixtures/r52_v5/voices.js). Covered: the Voice -> Speaker check section in both surfaces and on a phone,
# with no model and with one; enrolment from the voice session's clips and from a reading on the microphone; the
# print encrypted in IndexedDB with a key that cannot be exported, nothing sent; owner / other / short in the page;
# the per-device switch across a reload; Forget asks first. The barge-in hook with the real voice loop: another
# voice no longer stops JARVIS in "speech" mode and is dropped unsent in "name" mode, his voice still does, no print
# is today's behaviour, and his verified voice saying "approve" approves nothing.
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from r52_v5_fakes import STATIC, VOICES_JS, sha256, tiny_speaker_model
from test_brief import CONTRAST_JS, SETTLE_JS
from test_console import PHONE, Console
from test_voice import FakeVoice
from test_voice_barge import RECORD_BARGE, _route, _start
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    TONE_MIC,
    _count,
    _mic_file,
    _playwright,
    _until,
    browser,
    make,
)

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

OWN = ("console-voiceprint-math.js", "console-voiceprint.js", "console-voiceprint-panel.js")
ANCHOR = '<script src="/static/console-voice-barge.js" defer></script>'
MODEL = tiny_speaker_model()
TINY = {"sha256": sha256(MODEL), "threshold": 0.85}
SHOTS = Path("/tmp/r52-v5-shots")
# The microphone hears a synthetic voice (window.__micSpeaker, default the owner) on a loop.
VOICE_MIC = """
(() => {
  navigator.mediaDevices.getUserMedia = async () => {
    const V = window.JarvisTestVoices, pcm = V.utter(window.__micSpeaker || 'owner', 20, 5);
    const ac = new AudioContext();
    try { await ac.resume(); } catch (_) {}
    const buf = ac.createBuffer(1, pcm.length, 16000), ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ac.createBufferSource(); src.buffer = buf; src.loop = true;
    const d = ac.createMediaStreamDestination(); src.connect(d); src.start();
    return d.stream;
  };
})();
"""
# For the barge-in hook alone: a stand-in speaker check whose verdict the test sets.
STUB = """
window.__vp = { active: true, verdict: 'other', calls: 0 };
window.JarvisVoicePrint = Object.freeze({
  active: () => window.__vp.active,
  verify: async (frames) => { window.__vp.calls++; await new Promise((r) => setTimeout(r, 60)); return window.__vp.verdict; },
  CHECK_MS: 1200,
});
"""
OUR_IDB = """async () => {
  const db = await new Promise((res, rej) => { const q = indexedDB.open('jarvis-voiceprint'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
  const get = (k) => new Promise((res) => { const q = db.transaction('v').objectStore('v').get(k); q.onsuccess = () => res(q.result); });
  const key = await get('key'), print = await get('print');
  let exported = 'refused';
  try { await crypto.subtle.exportKey('raw', key); exported = 'exported'; } catch (_) {}
  db.close();
  return { key: key && { type: key.type, extractable: key.extractable, alg: key.algorithm.name, usages: key.usages },
           print: print && { fields: Object.keys(print).sort(), iv: print.iv.length, data: print.data.byteLength,
                             clear: JSON.stringify(print).includes('vector') }, exported };
}"""


def _link(route: Any) -> None:
    resp = route.fetch()
    html = resp.text()
    assert ANCHOR in html
    tags = "".join(f'\n<script src="/static/{n}" defer></script>' for n in OWN)
    route.fulfill(response=resp, body=html.replace(ANCHOR, ANCHOR + tags))


def _script(body: str) -> Callable[[Any], None]:
    return lambda r: r.fulfill(status=200, content_type="application/javascript", body=body)


def wire(c: Console, *, model: bool = True, slot: dict[str, Any] | None = TINY, hooks: dict[str, Any] | None = None) -> list[str]:
    """What I1 will do (serve the scripts, link them), plus a model file and the test hook; -> the model GETs."""
    for name in OWN:
        c.page.route(f"**/static/{name}", _script((STATIC / name).read_text(encoding="utf-8")))
    c.page.route(lambda u: urlsplit(u).path == "/", _link)
    gets: list[str] = []

    def serve(r: Any) -> None:
        gets.append(r.request.method + " " + urlsplit(r.request.url).path)
        if model:
            r.fulfill(status=200, content_type="application/octet-stream", body=MODEL)
        else:
            r.fulfill(status=404, body="not found")

    c.page.route("**/static/vendor/speaker/**", serve)
    c.page.add_init_script(path=str(VOICES_JS))
    if slot is not None or hooks:
        c.page.add_init_script(f"window.__jarvisVoicePrintTest = {json.dumps({'model': slot or {}, **(hooks or {})})};")
    return gets


def _panel(c: Console) -> Any:
    c.open_panel("voice")
    c.page.locator("#vPrintT").wait_for(state="visible")
    return c.page.locator("#vPrint")


def _state(c: Console) -> str:
    return str(c.page.evaluate("JarvisVoicePrint.state()"))


def _enrol_from_session(c: Console, seconds: int = 36) -> dict[str, Any]:
    """The voice session (V3) offers its clips; the owner then taps "Use my voice session"."""
    c.page.evaluate(f"JarvisVoicePrint.offerSessionClip(JarvisTestVoices.utter('owner', {seconds}, 11))")
    _until(c, "JarvisVoicePrint.sessionCount() >= JarvisVoicePrint.ENROL_MIN", 30)
    c.page.locator("#vPrintSession").wait_for(state="visible")
    c.page.locator("#vPrintSession").click()
    _until(c, "JarvisVoicePrint.state() === 'ready'", 20)
    return dict(c.page.evaluate("JarvisVoicePrint.info()"))


def _measure(c: Console, speaker: str, seconds: float, seed: int) -> dict[str, Any]:
    js = f"JarvisVoicePrint.measure(JarvisTestVoices.frames(JarvisTestVoices.utter('{speaker}', {seconds}, {seed})))"
    return dict(c.page.evaluate(js))


# ================================================================== the section
def test_without_a_print_the_section_says_so_and_nothing_is_loaded(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    gets = wire(c)
    c.open()
    sec = _panel(c)
    assert _state(c) == "none" and c.page.evaluate("JarvisVoicePrint.active()") is False
    assert "Not set up on this device" in str(sec.locator("#vPrintStatus").text_content())
    assert sec.locator("#vPrintOn").is_hidden() and sec.locator("#vPrintForget").is_hidden()
    assert sec.locator("#vPrintSession").is_hidden()  # no voice session in this tab
    assert sec.locator("#vPrintRecord").is_enabled() and sec.locator("#vPrintRecord").text_content() == "Record 1 minute"
    assert "never approves" in str(sec.text_content())
    # it sits right after "Words to recognise" in the Voice panel
    assert c.page.evaluate("document.getElementById('vSlotPhrases').nextElementSibling.id") == "vSlotSpeaker"
    assert gets == []  # no print: the model is not fetched
    assert c.errors == [] and c.csp_violations() == []


def test_with_the_slot_still_empty_it_says_no_model_and_fetches_nothing(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    gets = wire(c, slot=None)  # the shipped SLOT: sha256 null
    c.open()
    sec = _panel(c)
    assert _state(c) == "no_model"
    assert "isn't installed on JARVIS yet" in str(sec.locator("#vPrintStatus").text_content())
    assert sec.locator("#vPrintRecord").is_disabled()
    assert c.page.evaluate("JarvisVoicePrint.offerSessionClip(JarvisTestVoices.utter('owner', 4, 1))") is False
    assert c.page.evaluate("JarvisVoicePrint.verify([new Int16Array(1280)])") == "skip"
    assert gets == [] and c.errors == []


@pytest.mark.parametrize("surface", ["night", "day"])
def test_the_section_reads_clearly_in_both_surfaces(make: Callable[..., Console], surface: str) -> None:
    c = make(scripts=(f"localStorage.setItem('jarvis_surface', '{surface}');",))
    FakeVoice(c.page)
    wire(c)
    c.open()
    sec = _panel(c)
    _enrol_from_session(c)
    sec.scroll_into_view_if_needed()
    c.page.evaluate(SETTLE_JS, "#vPrint")
    found = c.page.evaluate(CONTRAST_JS, "#vPrint")
    assert len(found) >= 6
    assert [f for f in found if f["ratio"] < 4.5] == []
    SHOTS.mkdir(parents=True, exist_ok=True)
    sec.screenshot(path=str(SHOTS / f"speaker-check-{surface}.png"))
    c.page.locator("#vPrintForget").click()
    sec.screenshot(path=str(SHOTS / f"speaker-check-{surface}-forget.png"))
    assert c.errors == []


def test_on_a_phone_the_section_fits_and_its_buttons_are_reachable(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        FakeVoice(c.page)
        wire(c)
        c.open()
        sec = _panel(c)
        sec.scroll_into_view_if_needed()
        widths = c.page.evaluate("[document.getElementById('p-voice').scrollWidth, document.getElementById('p-voice').clientWidth]")
        assert widths[0] <= widths[1] + 1, widths
        box = sec.locator("#vPrintRecord").bounding_box()
        assert box and box["width"] >= 44 and box["height"] >= 32
        SHOTS.mkdir(parents=True, exist_ok=True)
        sec.screenshot(path=str(SHOTS / "speaker-check-phone.png"))
        assert c.errors == []
    finally:
        c.close()


# ================================================================== the print
def test_the_session_clips_make_an_encrypted_print_that_never_leaves_the_browser(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    gets = wire(c)
    sent: list[str] = []
    c.page.on("request", lambda r: sent.append(r.method + " " + urlsplit(r.url).path) if r.method != "GET" else None)
    c.open()
    _panel(c)
    before = list(sent)
    info = _enrol_from_session(c)
    assert info == {"saved": True, "made": info["made"], "count": 12, "quality": "good", "source": "session"}
    assert c.page.evaluate("JarvisVoicePrint.sessionCount()") == 0  # the embeddings are used up, the audio was never kept
    stored = c.page.evaluate(OUR_IDB)
    assert stored["key"] == {"type": "secret", "extractable": False, "alg": "AES-GCM", "usages": ["encrypt", "decrypt"]}
    assert stored["print"] == {"fields": ["data", "iv", "v"], "iv": 12, "data": stored["print"]["data"], "clear": False}
    assert stored["exported"] == "refused"
    assert gets == ["GET /static/vendor/speaker/spk-1/wespeaker-voxceleb-campplus.onnx"]
    assert sent == before  # nothing was posted while the print was made
    keys = c.page.evaluate("Object.keys(localStorage).filter((k) => /print|speaker/i.test(k))")
    assert keys == []  # on by default: not even the switch is written
    status = str(c.page.locator("#vPrintStatus").text_content())
    assert status.startswith("On. Only your voice can interrupt JARVIS on this device") and "your voice session" in status
    assert c.page.locator("#vPrintNote").text_content() == "Voice print saved on this device."
    assert c.errors == []


def test_the_print_tells_the_owner_from_another_voice(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    wire(c)
    c.open()
    _panel(c)
    _enrol_from_session(c)
    assert c.page.evaluate("JarvisVoicePrint.active()") is True
    for seed in (21, 22, 23):
        assert _measure(c, "owner", 1.5, seed)["verdict"] == "owner"
        assert _measure(c, "other", 1.5, seed)["verdict"] == "other"
        assert _measure(c, "tv", 1.5, seed)["verdict"] == "other"
    assert _measure(c, "owner", 0.3, 9)["verdict"] == "short"
    assert c.page.evaluate("JarvisVoicePrint.verify(JarvisTestVoices.frames(JarvisTestVoices.utter('owner', 1.5, 30)))") == "owner"
    assert c.errors == []


def test_a_reading_on_the_microphone_makes_a_print_and_too_little_says_why(make: Callable[..., Console]) -> None:
    c = make(scripts=(VOICE_MIC,))
    FakeVoice(c.page)
    wire(c, hooks={"readMs": 7000, "enrolMin": 2})
    c.open()
    sec = _panel(c)
    sec.locator("#vPrintRecord").click()
    sec.locator("#vPrintReading").wait_for(state="visible")
    assert "Read this aloud" in str(sec.locator("#vPrintReading").text_content())
    assert sec.locator("#vPrintRecord").is_hidden()
    _until(c, "/seconds of your voice so far/.test(document.getElementById('vPrintProgress').textContent)", 10)
    SHOTS.mkdir(parents=True, exist_ok=True)
    sec.screenshot(path=str(SHOTS / "speaker-check-reading.png"))
    _until(c, "JarvisVoicePrint.state() === 'ready'", 25)
    assert c.page.evaluate("JarvisVoicePrint.info().source") == "reading"
    assert sec.locator("#vPrintReading").is_hidden() and sec.locator("#vPrintRecord").text_content() == "Record again"
    # Stop at once: too little voice; the print made before stays
    sec.locator("#vPrintRecord").click()
    sec.locator("#vPrintStop").click()
    _until(c, "/wasn't enough of your voice/.test(document.getElementById('vPrintNote').textContent)", 15)
    assert _state(c) == "ready" and c.page.evaluate("JarvisVoicePrint.info().source") == "reading"
    assert c.errors == []


def test_the_switch_is_this_devices_and_forget_asks_first(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    wire(c)
    c.open()
    sec = _panel(c)
    _enrol_from_session(c)
    sw = sec.locator("#vPrintOn")
    assert sw.get_attribute("aria-pressed") == "true"
    sw.click()
    assert _state(c) == "off" and c.page.evaluate("JarvisVoicePrint.active()") is False
    assert c.page.evaluate("localStorage.getItem('jarvis_voiceprint_off_v1')") == "1"
    c.page.reload()
    c.page.locator("#welcome").wait_for()
    sec = _panel(c)
    _until(c, "JarvisVoicePrint.state() === 'off'", 10)  # still off, and the print is still here
    assert "Off on this device" in str(sec.locator("#vPrintStatus").text_content())
    sec.locator("#vPrintOn").click()
    _until(c, "JarvisVoicePrint.state() === 'ready'", 15)
    # Forget: the safe choice has the focus; Keep it keeps it
    sec.locator("#vPrintForget").click()
    assert sec.locator("#vPrintConfirm").is_visible() and c.page.evaluate("document.activeElement.id") == "vPrintKeep"
    sec.locator("#vPrintKeep").click()
    assert _state(c) == "ready" and sec.locator("#vPrintConfirm").is_hidden()
    sec.locator("#vPrintForget").click()
    sec.locator("#vPrintForgetYes").click()
    _until(c, "JarvisVoicePrint.state() === 'none'", 10)
    assert c.page.locator("#vPrintNote").text_content() == "Voice print forgotten on this device."
    assert c.page.evaluate("indexedDB.databases().then((d) => d.map((x) => x.name))") == []
    assert c.errors == []


# ================================================================== the barge-in hook, with the real voice loop
def _barge(make: Callable[..., Console], by: str, scripts: tuple[str, ...] = (STUB,)) -> tuple[Console, FakeVoice]:
    c = make(device={"interruptBy": by, "speak": "always", "keepListening": True}, scripts=(TONE_MIC, RECORD_BARGE, *scripts), barge=True)
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    c.page.evaluate("window.__kind = 'headphones'")
    _start(c, fake)
    return c, fake


def test_in_speech_mode_another_voice_no_longer_stops_him(make: Callable[..., Console]) -> None:
    c, fake = _barge(make, "speech")
    before = _count(fake, "/v1/voice/transcribe")
    c.page.evaluate("window.__burst(1500)")
    _until(c, "window.__vp.calls >= 1", 8)
    _until(c, "JarvisVoice.speaker.volume() > 0.99", 8)  # ducked while the clip was judged, then back
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True
    assert c.page.evaluate("window.__barges") == []
    assert _count(fake, "/v1/voice/transcribe") == before  # the check sent nothing
    assert c.errors == []


def test_in_speech_mode_his_voice_still_stops_him(make: Callable[..., Console]) -> None:
    c, _fake = _barge(make, "speech")
    c.page.evaluate("window.__vp.verdict = 'owner'")
    c.page.evaluate("window.__burst(1500)")
    _until(c, "!JarvisVoice.speaker.speaking()", 8)
    barge = c.page.evaluate("window.__barges")
    assert barge and barge[0]["how"] == "speech" and c.page.evaluate("window.__vp.calls") == 1
    _until(c, "document.getElementById('micBtn').dataset.state === 'listening'", 5)
    assert c.errors == []


def test_without_a_print_it_is_todays_barge_in(make: Callable[..., Console]) -> None:
    c, _fake = _barge(make, "speech", scripts=(STUB, "window.__vp.active = false;"))  # decided when he starts a reply
    c.page.evaluate("window.__burst(1500)")
    _until(c, "!JarvisVoice.speaker.speaking()", 5)
    assert c.page.evaluate("window.__barges")[0]["how"] == "speech"
    assert c.page.evaluate("window.__vp.calls") == 0  # never asked
    assert c.errors == []


def test_in_name_mode_another_voice_is_dropped_unsent(make: Callable[..., Console]) -> None:
    c, fake = _barge(make, "name")
    before = _count(fake, "/v1/voice/transcribe")
    fake.transcript["text"] = "stop"
    c.page.evaluate("window.__burst(1200)")
    _until(c, "window.__vp.calls >= 1", 8)
    c.page.wait_for_timeout(800)
    assert _count(fake, "/v1/voice/transcribe") == before  # not sent to Google: not his voice
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True and c.page.evaluate("window.__barges") == []
    c.page.evaluate("window.__vp.verdict = 'owner'")
    c.page.wait_for_timeout(3200)  # the hook's gap between clips
    c.page.evaluate("window.__burst(1200)")
    _until(c, "!JarvisVoice.speaker.speaking()", 10)
    assert _count(fake, "/v1/voice/transcribe") == before + 1 and c.page.evaluate("window.__barges")[0]["how"] == "stop"
    assert c.errors == []


def test_his_verified_voice_saying_approve_approves_nothing(make: Callable[..., Console]) -> None:
    c, fake = _barge(make, "speech")
    asked: list[str] = []
    c.page.on("request", lambda r: asked.append(urlsplit(r.url).path) if "approv" in r.url else None)
    c.page.evaluate("window.__vp.verdict = 'owner'")
    fake.transcript["text"] = "Approve it. Yes, approve all of them."
    c.page.evaluate("window.__burst(1500)")
    _until(c, "!JarvisVoice.speaker.speaking()", 8)
    c.page.evaluate("window.__talk(false)")
    _until(c, "[...document.querySelectorAll('.row.user')].some((r) => /approve all of them/i.test(r.textContent))", 20)
    c.page.wait_for_timeout(500)
    assert [p for p in asked if "/approve" in p] == []  # his words became a message; nothing was approved
    assert c.errors == []
