# tests/browser/test_voice_devices.py — R5 workstream B: audio devices in a real browser
# ruff: noqa: E501  (embedded JavaScript lines)
# (docs/plans/r5-voice.md D13, D14). enumerateDevices, AudioContext.setSinkId and devicechange are
# stubbed; an Android case removes setSinkId. Nothing here opens the microphone for names.
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console
from test_voice import FakeVoice, _voice_panel, speechlike_wav

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

FAKE_MEDIA = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
ROUTE_KEY = "jarvis_audio_route_v1"
CTX = "{source: 'voice', state: 'idle', spoken: '', peak: 0}"

STUB = """
(() => {
  window.__gum = 0; window.__enum = 0; window.__sinks = [];
  window.__devs = [
    { kind: 'audiooutput', deviceId: 'default', label: 'Default - Speakers (Realtek(R) Audio)' },
    { kind: 'audiooutput', deviceId: 'communications', label: 'Communications - Speakers' },
    { kind: 'audiooutput', deviceId: 'spk-realtek', label: 'Speakers (Realtek(R) Audio)' },
    { kind: 'audiooutput', deviceId: 'buds-stereo', label: 'Headphones (Galaxy Buds2 Pro)' },
    { kind: 'audiooutput', deviceId: 'buds-hf',
      label: 'Headset (Galaxy Buds2 Pro Hands-Free AG Audio)' },
    { kind: 'audiooutput', deviceId: 'jbl', label: 'Speakers (JBL Flip 5)' },
    { kind: 'audioinput', deviceId: 'default', label: 'Default - Microphone Array (Realtek(R) Audio)' },
    { kind: 'audioinput', deviceId: 'mic-array', label: 'Microphone Array (Realtek(R) Audio)' },
    { kind: 'audioinput', deviceId: 'buds-mic',
      label: 'Headset (Galaxy Buds2 Pro Hands-Free AG Audio)' },
  ];
  const md = navigator.mediaDevices;
  md.enumerateDevices = () => {
    window.__enum++;
    if (window.__enumHang) return new Promise(() => {});
    if (window.__enumFail) { window.__enumFail--; return Promise.reject(new Error('boom')); }
    // before the mic permission Chrome returns empty ids and labels (window.__perm = false)
    const snap = window.__devs.map(d => (window.__perm === false ? { kind: d.kind, deviceId: '', label: '' } : { ...d }));
    return window.__enumDelay ? new Promise(r => setTimeout(() => r(snap), window.__enumDelay)) : Promise.resolve(snap);
  };
  const realGum = md.getUserMedia.bind(md);
  md.getUserMedia = (c) => { window.__gum++; return realGum(c); };
  if (window.__noSink) delete AudioContext.prototype.setSinkId;
  else AudioContext.prototype.setSinkId = function (id) {
    if (window.__sinkErr) { const e = new Error('sink'); e.name = window.__sinkErr; return Promise.reject(e); }
    window.__sinks.push(id);
    return Promise.resolve();
  };
})();
"""
NO_LABELS = "window.__noLabels = true;"
UNLABELLED = """
(() => { const e = navigator.mediaDevices.enumerateDevices;
  navigator.mediaDevices.enumerateDevices = () => e().then(l => l.map(d => ({ ...d, label: '' }))); })();
"""
ANDROID = """
Object.defineProperty(navigator, 'userAgent', { get: () => 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36' });
window.__noSink = true;
"""


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mic = tmp_path_factory.mktemp("r5dev") / "speech.wav"
    speechlike_wav(mic)
    args = [*FAKE_MEDIA, f"--use-file-for-fake-audio-capture={mic}"]
    with _pw.sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(scripts: tuple[str, ...] = (), *, route: dict[str, Any] | None = None) -> Console:
        c = Console(browser, server_url, token, DESKTOP)
        c.page.route(
            "**/static/console-wakeword.js",
            lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
        )
        dev = json.dumps(json.dumps({"interruptBy": "tap"}))
        c.page.add_init_script(
            f"localStorage.getItem('jarvis_voice_device_v1') === null && "
            f"localStorage.setItem('jarvis_voice_device_v1', {dev});"
        )
        for s in scripts:
            if s is ANDROID:
                c.page.add_init_script(s)
        c.page.add_init_script(STUB)  # console.html loads the matcher itself (I1)
        for s in scripts:
            if s is not ANDROID:
                c.page.add_init_script(s)
        if route is not None:
            c.page.add_init_script(
                f"localStorage.getItem('{ROUTE_KEY}') === null && "
                f"localStorage.setItem('{ROUTE_KEY}', {json.dumps(json.dumps(route))});"
            )
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def wf(c: Console, js: str) -> None:
    """Wait until a page expression is truthy (a bare string would be eval'd, which the CSP forbids)."""
    c.page.wait_for_function("() => (" + js + ")")


def ev(c: Console, js: str) -> Any:
    return c.page.evaluate(js)


def ready(c: Console) -> None:
    """Open the console and wait for the first device listing to land."""
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1 && JarvisAudioRoute.current !== undefined")
    ev(c, "JarvisAudioRoute.refresh()")


def say(c: Console, text: str, state: str = "listening") -> dict[str, Any]:
    ctx = CTX.replace("'idle'", f"'{state}'")
    return ev(c, f"JarvisVoiceCommands.handle({json.dumps(text)}, {ctx})")  # type: ignore[no-any-return]


def sink(c: Console) -> Any:
    return ev(c, "JarvisVoice.speaker.sink()")


def devchange(c: Console) -> None:
    ev(c, "navigator.mediaDevices.dispatchEvent(new Event('devicechange'))")


# ====================================================================== listing
def test_lists_real_devices_with_kinds_and_demotes_call_quality(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    res = ev(c, "JarvisAudioRoute.refresh()")
    assert [o["id"] for o in res["outputs"]] == ["spk-realtek", "buds-stereo", "jbl", "buds-hf"]
    kinds = {o["id"]: o["kind"] for o in res["outputs"]}
    assert kinds == {
        "spk-realtek": "speakers",
        "buds-stereo": "headphones",
        "jbl": "speakers",
        "buds-hf": "headphones",
    }
    hf = res["outputs"][-1]
    assert hf["callQuality"] is True and hf["label"].endswith("(call quality)")
    assert [i["id"] for i in res["inputs"]] == ["mic-array", "buds-mic"]
    assert ev(c, "JarvisAudioRoute.supported()") is True
    assert c.errors == [] and ev(c, "window.__gum") == 0  # never opens the mic for names


def test_the_default_output_decides_the_kind_until_one_is_chosen(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    assert ev(c, "JarvisAudioRoute.outputKind()") == "speakers"
    assert ev(c, "JarvisAudioRoute.current().output") is None
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    assert ev(c, "JarvisAudioRoute.outputKind()") == "headphones"
    ev(
        c,
        "JarvisAudioRoutePrefs.setKind('jbl', 'headphones'); JarvisAudioRoute.chooseOutput('jbl')",
    )
    assert ev(c, "JarvisAudioRoute.outputKind()") == "headphones"  # the owner's mark wins


def test_devicechange_bursts_are_debounced_into_one_listing(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    before = ev(c, "window.__enum")
    ev(
        c,
        "for (let i = 0; i < 5; i++) navigator.mediaDevices.dispatchEvent(new Event('devicechange'))",
    )
    wf(c, f"window.__enum > {before}")
    c.page.wait_for_timeout(900)
    assert ev(c, "window.__enum") == before + 1


# ====================================================================== choosing and remembering
def test_choosing_an_output_routes_remembers_and_survives_a_reload(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    assert ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')") == {"ok": True}
    assert sink(c) == "buds-stereo"
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["output"] == {"id": "buds-stereo", "label": "Headphones (Galaxy Buds2 Pro)"}
    c.open()  # reload
    wf(c, "JarvisVoice.speaker.sink() === 'buds-stereo'")
    assert ev(c, "JarvisAudioRoute.current().output.id") == "buds-stereo"


def test_a_changed_device_id_is_matched_again_by_its_label(make: Callable[..., Console]) -> None:
    stale = {"v": 1, "output": {"id": "old-id", "label": "Headphones (Galaxy Buds2 Pro)"}}
    c = make(route=stale)
    ready(c)
    wf(c, "JarvisVoice.speaker.sink() === 'buds-stereo'")
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["output"]["id"] == "buds-stereo"


def test_unknown_or_bad_choices_are_refused_and_the_old_sink_is_kept(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('jbl')")
    assert ev(c, "JarvisAudioRoute.chooseOutput('nope')") == {"ok": False, "reason": "not_found"}
    assert ev(c, "JarvisAudioRoute.chooseOutput(42)") == {"ok": False, "reason": "not_found"}
    assert sink(c) == "jbl"
    assert ev(c, "JarvisAudioRoute.chooseOutput(null)") == {"ok": True}
    assert sink(c) == ""
    assert ev(c, "JarvisAudioRoute.current().output") is None


def test_a_corrupt_saved_route_is_dropped_and_defaults_hold(make: Callable[..., Console]) -> None:
    c = make(route={"v": 9, "output": "x", "onConnect": "shout", "names": {"a": "x" * 99}})
    ready(c)
    assert ev(c, "JarvisAudioRoute.current()") == {"output": None, "input": None}
    assert ev(c, "JarvisAudioRoutePrefs.prefs().onConnect") == "ask"
    assert sink(c) in ("", None)


def test_the_input_is_chosen_with_a_headset_warning_and_defaults_to_the_laptop(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    assert ev(c, "JarvisAudio.inputId()") is None
    assert ev(c, "JarvisAudioRoute.chooseInput('mic-array')") == {"ok": True}
    assert ev(c, "JarvisAudio.inputId()") == "mic-array"
    res = ev(c, "JarvisAudioRoute.chooseInput('buds-mic')")
    assert res == {"ok": True, "warning": "call_quality"}
    assert ev(c, "JarvisAudio.inputId()") == "buds-mic"
    assert ev(c, "JarvisAudioRoute.chooseInput('gone')") == {"ok": False, "reason": "not_found"}
    assert ev(c, "JarvisAudioRoute.chooseInput(null)") == {"ok": True}
    assert ev(c, "JarvisAudio.inputId()") is None
    assert ev(c, "window.__gum") == 0


def test_moving_output_to_earphones_keeps_the_laptop_mic(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    assert ev(c, "JarvisAudio.inputId()") is None


def test_a_saved_input_is_applied_at_boot_and_a_missing_one_falls_back_to_default(
    make: Callable[..., Console],
) -> None:
    c = make(route={"v": 1, "input": {"id": "buds-mic", "label": "Headset"}})
    FakeVoice(c.page)
    c.open()
    wf(c, "JarvisAudio.inputId() === 'buds-mic'")
    ev(
        c,
        "document.dispatchEvent(new CustomEvent('jarvis:audio-route',"
        " { detail: { input: { id: 'buds-mic', label: '' }, reason: 'input_missing' } }))",
    )
    wf(c, "JarvisAudio.inputId() === null")
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["input"]["id"] == "buds-mic"  # remembered for when it comes back
    # a route change that merely has an output key is not an 'input missing' report
    ev(c, "JarvisAudioRoute.chooseInput('mic-array')")
    ev(
        c,
        "document.dispatchEvent(new CustomEvent('jarvis:audio-route',"
        " { detail: { output: null, input: null, reason: 'output_changed' } }))",
    )
    assert ev(c, "JarvisAudio.inputId()") == "mic-array"


# ====================================================================== connect / disconnect
def add_buds(c: Console) -> None:
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'pixel',"
        " label: 'Headphones (Pixel Buds)' })",
    )
    devchange(c)


def test_a_new_device_gets_an_offer_that_switches_only_when_accepted(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    add_buds(c)
    offer = c.page.locator("#voiceOffer")
    offer.locator("button", has_text="Use Headphones (Pixel Buds)").wait_for()
    assert "Headphones (Pixel Buds) connected." in str(offer.text_content())
    assert sink(c) in ("", None)
    offer.locator("button", has_text="Use Headphones (Pixel Buds)").click()
    assert sink(c) == "pixel"
    wf(
        c,
        "document.getElementById('voiceLine').textContent.includes('Switching to Headphones (Pixel Buds), Sir.')",
    )


def test_not_now_leaves_the_output_alone(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    add_buds(c)
    c.page.locator("#voiceOffer button", has_text="Not now").click()
    assert sink(c) in ("", None) and c.page.locator("#voiceOffer button").count() == 0


def test_switch_automatically_and_do_nothing_policies(make: Callable[..., Console]) -> None:
    c = make(route={"v": 1, "onConnect": "auto"})
    ready(c)
    add_buds(c)
    wf(c, "JarvisVoice.speaker.sink() === 'pixel'")
    assert "Switching to Headphones (Pixel Buds)" in str(
        c.page.locator("#voiceLine").text_content()
    )
    ev(c, "JarvisAudioRoutePrefs.setOnConnect('never'); JarvisAudioRoute.chooseOutput(null)")
    ev(c, "window.__devs.push({ kind: 'audiooutput', deviceId: 'z', label: 'Speakers (Zed)' })")
    devchange(c)
    wf(c, "window.__enum >= 3")
    c.page.wait_for_timeout(300)
    assert sink(c) == "" and c.page.locator("#voiceOffer button").count() == 0


def test_while_he_listens_the_offer_is_on_screen_only_and_a_yes_switches_nothing(
    make: Callable[..., Console],
) -> None:
    # SL1: mid-listening the loop cannot speak a question, so none is armed for a loose "yes"
    c = make()
    fv = FakeVoice(c.page)
    fv.hold_transcribe = True
    c.open()
    wf(c, "window.__enum >= 1")
    c.page.locator("#micBtn").click()
    wf(c, "JarvisVoiceLoop.inConversation()")
    add_buds(c)
    c.page.locator("#voiceOffer button").first.wait_for()
    assert ev(c, "JarvisVoiceCommands.pending()") is None
    ev(c, "JarvisVoiceCommands.handle('yes please', {source: 'voice', state: 'listening'})")
    c.page.wait_for_timeout(300)
    assert sink(c) in ("", None)
    c.page.locator("#voiceOffer button", has_text="Use").first.click()  # the tap still works
    wf(c, "JarvisVoice.speaker.sink() === 'pixel'")


def test_losing_the_chosen_output_falls_back_and_says_so(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'buds-stereo')")
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === ''")
    line = str(c.page.locator("#voiceLine").text_content())
    assert "Headphones (Galaxy Buds2 Pro) disconnected. I'll use" in line and line.endswith("Sir.")
    # the owner's panel choice is remembered: it comes back silently when the device returns (L3)
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'buds-stereo',"
        " label: 'Headphones (Galaxy Buds2 Pro)' })",
    )
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === 'buds-stereo'")
    assert c.page.locator("#voiceOffer button").count() == 0


def test_losing_some_other_device_changes_nothing(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('jbl')")
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'buds-stereo')")
    devchange(c)
    wf(c, "window.__enum >= 3")
    assert sink(c) == "jbl"


# ====================================================================== voice commands (D12)
def test_switch_commands_resolve_device_words_and_prefer_the_right_endpoint(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    r = say(c, "switch to my speaker")
    assert r["id"] == "device.switch" and sink(c) == "jbl"  # external over the built-in
    assert r["result"]["say"] == "Switching to the speaker, Sir."
    say(c, "switch to my earphones")
    assert sink(c) == "buds-stereo"  # stereo, not the call-quality endpoint
    say(c, "Jarvis, please switch to the laptop")
    assert sink(c) == "spk-realtek"
    say(c, "turn to the default now")
    assert sink(c) == ""
    ev(c, "JarvisAudioRoutePrefs.setName('jbl', 'kitchen')")
    say(c, "play it on kitchen")
    assert sink(c) == "jbl"


@pytest.mark.parametrize(
    "text",
    [
        "switch to dark mode",
        "use the earphones coupon",
        "remind me to switch to the speaker at five",
        "play it on repeat",
        "switch to",
        "move to the next page",
    ],
)
def test_phrases_that_do_not_name_a_device_fall_through_to_the_chat(
    make: Callable[..., Console], text: str
) -> None:
    c = make()
    ready(c)
    assert say(c, text) == {"handled": False}
    assert sink(c) in ("", None)


def test_commands_are_ignored_while_the_mic_is_off(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    assert say(c, "switch to my speaker", state="off") == {"handled": False}


def test_a_device_word_with_nothing_connected_says_so(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "window.__devs = window.__devs.filter(d => !/buds/i.test(d.label))")
    ev(c, "JarvisAudioRoute.refresh()")
    r = say(c, "switch to my earphones")
    assert r["handled"] is True and "can't see" in r["result"]["say"]


def test_input_commands_pick_the_mic_and_warn_about_call_quality(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    r = say(c, "use the headset mic")
    assert r["id"] == "device.input" and ev(c, "JarvisAudio.inputId()") == "buds-mic"
    assert r["result"]["say"].startswith("I'll listen through ")
    assert "call quality" in r["result"]["say"]
    r = say(c, "use my laptop microphone")
    assert r["id"] == "device.input" and ev(c, "JarvisAudio.inputId()") == "mic-array"
    assert sink(c) in ("", None)  # "use laptop mic" never became an output switch


def test_list_command_names_the_current_and_the_other_outputs(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    for phrase in ("what's connected", "which speaker are you using", "list my devices"):
        r = say(c, phrase)
        assert r["id"] == "device.list"
        text = r["result"]["say"]
        assert text.startswith(
            "You have three outputs: the laptop speakers, earphones and a speaker"
        )
        assert "I'm speaking through your earphones" in text and "names are on screen" in text
        screen = str(c.page.locator("#voiceLine").text_content())
        assert "Galaxy Buds2 Pro" in screen and "JBL Flip 5" in screen


def test_the_browser_voice_cannot_be_routed_and_he_says_how_to_pick_it(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisVoice.speaker.browser(true)")
    r = say(c, "switch to my speaker")
    assert "Windows + Ctrl + V" in r["result"]["say"] and "Sir" in r["result"]["say"]
    assert sink(c) == "jbl"  # the cloud voice will follow when it is used again


# ====================================================================== Android (D14)
def test_android_gets_instructions_not_a_switch(make: Callable[..., Console]) -> None:
    c = make((ANDROID,))
    ready(c)
    assert ev(c, "JarvisVoice.speaker.sinkSupported()") is False
    assert ev(c, "JarvisAudioRoute.outputKind()") == "unknown"
    assert ev(c, "JarvisAudioRoute.chooseOutput('jbl')") == {"ok": False, "reason": "unsupported"}
    r = say(c, "switch to my earphones")
    assert r["result"]["say"] == (
        "On this phone Android chooses where I sound, Sir: open Quick Settings and pick it"
        " under media output (the name varies by phone)."
    )
    add_buds(c)
    wf(c, "window.__enum >= 3")
    c.page.wait_for_timeout(300)
    assert c.page.locator("#voiceOffer button").count() == 0  # nothing to offer: cannot route


def test_android_panel_shows_the_steps_and_no_output_buttons(make: Callable[..., Console]) -> None:
    c = make((ANDROID,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.get_by_text("On this phone Android chooses where I sound, Sir", exact=False).wait_for()
    assert slot.locator("[data-out]").count() == 0
    assert slot.locator("[data-in]").count() == 3  # the default plus the two it exposes


# ====================================================================== the picker
def test_without_microphone_permission_the_picker_says_how_to_get_names(
    make: Callable[..., Console],
) -> None:
    c = make((UNLABELLED,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    note = "Device names appear after you allow the microphone once (tap the mic)."
    slot.get_by_text(note).wait_for()
    assert ev(c, "window.__gum") == 0


def test_picker_lists_outputs_and_inputs_and_uses_the_chosen_one(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.locator("[data-out]").first.wait_for()
    assert slot.locator("[data-out]").count() == 5  # system default + four
    assert slot.locator("[data-in]").count() == 3
    slot.locator("[data-out='jbl'] button.use").click()
    assert sink(c) == "jbl"
    assert slot.locator("[data-out='jbl'] button.use").get_attribute("aria-pressed") == "true"
    slot.locator("[data-in='buds-mic'] button.use").click()
    assert ev(c, "JarvisAudio.inputId()") == "buds-mic"
    slot.get_by_text("call quality", exact=False).first.wait_for()


def test_picker_marks_a_device_names_it_and_sets_the_connect_policy(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    row = slot.locator("[data-out='jbl']")
    row.wait_for()
    row.locator("select.kind").select_option("headphones")
    assert ev(c, "JarvisAudioRoutePrefs.prefs().kinds.jbl") == "headphones"
    row = slot.locator("[data-out='jbl']")
    row.locator("input.nick").fill("kitchen")
    row.locator("input.nick").press("Enter")
    assert ev(c, "JarvisAudioRoutePrefs.prefs().names.jbl") == "kitchen"
    slot.locator("select.onconnect").select_option("auto")
    assert ev(c, "JarvisAudioRoutePrefs.prefs().onConnect") == "auto"
    ev(c, "JarvisAudioRoute.chooseOutput(null)")  # selection survives a re-render
    assert slot.locator("select.onconnect").input_value() == "auto"


def test_test_sound_plays_a_tone_on_the_current_output(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    ev(
        c,
        "window.__tones = []; const s = JarvisVoice.speaker, t = s.tone.bind(s);"
        " s.tone = (o) => { window.__tones.push(o); return t(o); };",
    )
    _voice_panel(c)
    c.page.locator("#vSlotDevices button.test").click()
    wf(c, "window.__tones.some(t => t && t.freq === 660)")


def test_picker_follows_devices_that_come_and_go(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.locator("[data-out='jbl']").wait_for()
    add_buds(c)
    slot.locator("[data-out='pixel']").wait_for()
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'pixel')")
    devchange(c)
    wf(c, "document.querySelector('#vSlotDevices [data-out=\"pixel\"]') === null")


# ====================================================================== privacy
def test_no_request_carries_a_device_label_or_id(make: Callable[..., Console]) -> None:
    c = make()
    seen: list[str] = []
    c.page.on(
        "request",
        lambda r: seen.append(r.url + " " + (r.post_data or "")) if r.method != "GET" else None,
    )
    c.page.on("request", lambda r: seen.append(r.url))
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('jbl'); JarvisAudioRoute.chooseInput('buds-mic')")
    say(c, "switch to my earphones")
    add_buds(c)
    c.page.wait_for_timeout(700)
    blob = "\n".join(seen)
    for secret in ("JBL", "Galaxy", "Pixel", "buds-mic", "spk-realtek", "jbl"):
        assert secret not in blob, secret
    assert c.errors == [] and c.csp_violations() == []
