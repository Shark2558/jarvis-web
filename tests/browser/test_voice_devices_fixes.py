# tests/browser/test_voice_devices_fixes.py - R5 part B fixes (security + code review), real browser.
# ruff: noqa: E501, F401, F811  (embedded JavaScript lines; imported fixtures)
# Privacy first: a device label or nickname never reaches spoken text, so never reaches the cloud TTS.
# Then permission-gated listings, honest sink results, session-only voice choices, multi-tab storage.
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import FakeVoice, _voice_panel
from test_voice_devices import (
    ANDROID,
    ROUTE_KEY,
    UNLABELLED,
    add_buds,
    browser,
    devchange,
    ev,
    make,
    ready,
    say,
    sink,
    wf,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SECRET_WORDS = ("akash", "airpods")
# A capturing stand-in for JarvisVoiceLoop: every say/ask is recorded with its speak flag.
RECORDER = """
window.__said = [];
(() => {
  const real = window.JarvisVoiceLoop;
  window.__loopState = 'listening';
  window.JarvisVoiceLoop = {
    state: () => window.__loopState, inConversation: () => true,
    say: (t, o) => { window.__said.push({ t, speak: !!(o && o.speak !== false && o.speak === true) }); return real.say(t, { speak: false }); },
    ask: (q, o) => { window.__said.push({ t: q, speak: true, ask: true }); return Promise.resolve('cancelled'); },
    offer: real.offer, end: real.end,
  };
})();
"""
ADD_AKASH = """
window.__devs.push({ kind: 'audiooutput', deviceId: 'akash', label: "Headphones (Akash's AirPods)" });
window.__devs.push({ kind: 'audioinput', deviceId: 'akash-mic', label: "Headset (Akash's AirPods)" });
"""


def spoken(c: Console) -> list[str]:
    return [x["t"] for x in ev(c, "window.__said") if x["speak"]]


def ids(c: Console) -> list[str]:
    return [o["id"] for o in ev(c, "JarvisAudioRoute.refresh()")["outputs"]]


def with_akash(c: Console) -> None:
    ready(c)
    ev(c, ADD_AKASH)
    ev(c, "JarvisAudioRoute.refresh()")
    ev(c, "JarvisAudioRoutePrefs.setName('akash', 'Akash buds')")
    ev(c, RECORDER)


# ====================================================================== H1: names never spoken
def test_no_spoken_line_on_any_path_contains_a_label_or_nickname(
    make: Callable[..., Console],
) -> None:
    c = make()
    with_akash(c)
    results = [
        say(c, "switch to akash buds"),
        say(c, "use akash buds mic"),
        say(c, "list my devices"),
        say(c, "switch to the akash tv"),
        say(c, "use the akash tv mic"),
        say(c, "switch to airpods"),
    ]
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'akash')")
    devchange(c)
    wf(c, "window.__said.some(x => /disconnected/i.test(x.t))")
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'akash2', label: \"Headphones (Akash's AirPods Pro)\" })",
    )
    devchange(c)
    wf(c, "window.__said.some(x => x.ask)")
    lines = [r["result"]["say"] for r in results if r.get("result") and r["result"].get("say")]
    lines += spoken(c)
    assert len(lines) >= 6, lines
    blob = "\n".join(lines).lower()
    for word in SECRET_WORDS:
        assert word not in blob, (word, lines)
    # the full name is still shown, on screen only
    assert any(not x["speak"] and "Akash" in x["t"] for x in ev(c, "window.__said"))


def test_the_auto_policy_and_the_chip_accept_say_a_kind_never_a_name(
    make: Callable[..., Console],
) -> None:
    c = make(route={"v": 1, "onConnect": "auto"})
    ready(c)
    ev(c, RECORDER)
    ev(c, ADD_AKASH)
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === 'akash'")
    lines = spoken(c)
    assert lines and not any(w in "\n".join(lines).lower() for w in SECRET_WORDS)
    assert any("Akash" in x["t"] and not x["speak"] for x in ev(c, "window.__said"))


def test_router_results_keep_the_frozen_shape(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    for phrase in (
        "switch to my speaker",
        "use the headset mic",
        "list my devices",
        "switch to the zzz",
    ):
        r = say(c, phrase)
        if r.get("result") is not None:
            assert set(r["result"]) <= {"say", "then"}, phrase


SPEAK_ALWAYS = "localStorage.setItem('jarvis_voice_device_v1', JSON.stringify({ interruptBy: 'tap', speak: 'always' }));"


def test_cloud_speak_requests_never_carry_a_label_or_nickname(make: Callable[..., Console]) -> None:
    c = make((SPEAK_ALWAYS,))
    fv = FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, ADD_AKASH)
    ev(c, "JarvisAudioRoute.refresh()")
    ev(c, "JarvisAudioRoutePrefs.setName('akash', 'Akash buds')")
    seen: list[str] = []
    c.page.on(
        "request",
        lambda r: seen.append(r.url + " " + (r.post_data or "")) if r.method != "GET" else None,
    )
    for phrase in ("switch to akash buds", "list my devices", "use akash buds mic"):
        r = say(c, phrase)
        ev(
            c, f"JarvisVoiceLoop.say({json.dumps(r['result']['say'])}, {{ speak: true }})"
        )  # what A's caller does
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'akash')")
    devchange(c)
    wf(c, "document.getElementById('voiceLine').textContent.includes('disconnected')")
    c.page.wait_for_timeout(1200)
    assert fv.spoken(), "nothing was spoken: the test would prove nothing"
    blob = "\n".join(fv.spoken() + seen).lower()
    for word in (*SECRET_WORDS, "buds"):
        assert word not in blob, word


# ====================================================================== M1: voice choices are session-only
def test_a_voice_switch_applies_this_page_session_but_is_not_saved(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    say(c, "switch to my speaker")
    say(c, "use the headset mic")
    assert sink(c) == "jbl" and ev(c, "JarvisAudio.inputId()") == "buds-mic"
    assert (
        ev(c, f"localStorage.getItem('{ROUTE_KEY}')") in (None, "")
        or json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')")).get("output") is None
    )
    devchange(c)  # a listing does not undo the session choice either
    c.page.wait_for_timeout(900)
    assert sink(c) == "jbl" and ev(c, "JarvisAudio.inputId()") == "buds-mic"
    c.open()  # reload
    wf(c, "window.__enum >= 1")
    assert sink(c) in ("", None) and ev(c, "JarvisAudio.inputId()") is None


def test_a_panel_choice_is_saved(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.locator("[data-out='jbl'] button.use").click()
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["output"]["id"] == "jbl"


# ====================================================================== permission: unlabelled, then labelled
PRELABEL = "window.__perm = false;"
LABELLED = "window.__perm = true;"
PIXEL = "window.__devs.push({ kind: 'audiooutput', deviceId: 'pixel', label: 'Headphones (Pixel Buds)' });"


@pytest.mark.parametrize("policy", ["ask", "auto"])
def test_a_listing_before_permission_then_after_restores_silently(
    make: Callable[..., Console], policy: str
) -> None:
    saved = {
        "v": 1,
        "onConnect": policy,
        "output": {"id": "pixel", "label": "Headphones (Pixel Buds)"},
    }
    c = make((PRELABEL, PIXEL), route=saved)
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, RECORDER)
    assert ev(c, "JarvisAudioRoutePrefs.devices().labelled") is False
    assert sink(c) in ("", None)
    ev(c, LABELLED)
    ev(c, "JarvisAudioRoute.refresh()")
    wf(c, "JarvisVoice.speaker.sink() === 'pixel'")
    c.page.wait_for_timeout(2000)
    assert c.page.locator("#voiceOffer button").count() == 0
    assert spoken(c) == [] and sink(c) == "pixel"


def test_permission_arriving_later_re_lists_without_any_manual_refresh(
    make: Callable[..., Console],
) -> None:
    saved = {"v": 1, "output": {"id": "pixel", "label": "Headphones (Pixel Buds)"}}
    c = make((PRELABEL, PIXEL), route=saved)
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, LABELLED)
    ev(c, "document.dispatchEvent(new Event('visibilitychange'))")
    wf(c, "JarvisVoice.speaker.sink() === 'pixel'")


def test_the_picker_fills_in_once_the_listing_becomes_labelled(
    make: Callable[..., Console],
) -> None:
    c = make((PRELABEL,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.get_by_text("Device names appear after you allow the microphone once").wait_for()
    ev(c, LABELLED)
    ev(c, "JarvisAudioRoute.refresh()")
    slot.locator("[data-out='jbl']").wait_for()


def test_the_saved_input_survives_an_unlabelled_first_listing(make: Callable[..., Console]) -> None:
    c = make(
        (PRELABEL,),
        route={
            "v": 1,
            "input": {"id": "buds-mic", "label": "Headset (Galaxy Buds2 Pro Hands-Free AG Audio)"},
        },
    )
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    assert ev(c, "JarvisAudio.inputId()") == "buds-mic"


# ====================================================================== M2/M7: failed, slow and hanging listings
def test_a_failed_listing_keeps_the_list_and_announces_nothing(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, RECORDER)
    ev(c, "window.__enumFail = 1")
    n = ev(c, "window.__enum")
    devchange(c)
    wf(c, f"window.__enum > {n}")
    c.page.wait_for_timeout(300)
    assert sink(c) == "buds-stereo" and spoken(c) == []
    assert len(ids(c)) == 4  # the previous list stands (and the next good one finds no news)
    c.page.wait_for_timeout(1800)
    assert c.page.locator("#voiceOffer button").count() == 0 and spoken(c) == []
    assert c.errors == []


def test_a_rejecting_listing_at_boot_leaves_no_unhandled_rejection(
    make: Callable[..., Console],
) -> None:
    c = make(("window.__enumFail = 2;",))
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    assert ev(c, "JarvisAudioRoute.refresh().then(() => 'ok', () => 'rejected')") == "ok"
    assert c.errors == []


def test_a_hanging_listing_is_given_up_on_so_later_ones_still_run(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "window.__enumHang = true")
    t0 = ev(c, "performance.now()")
    assert ev(c, "JarvisAudioRoute.refresh().then(() => 'done')") == "done"
    assert ev(c, "performance.now()") - t0 < 4500
    ev(c, "window.__enumHang = false; " + PIXEL)
    res = ev(c, "JarvisAudioRoute.refresh()")
    assert "pixel" in [o["id"] for o in res["outputs"]]


def test_a_devicechange_during_a_slow_listing_is_not_lost(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "window.__enumDelay = 600")
    ev(c, "window.__slow = JarvisAudioRoute.refresh()")
    ev(c, PIXEL)
    devchange(c)
    ev(c, "window.__enumDelay = 0")
    wf(c, "JarvisAudioRoutePrefs.devices().outputs.some(o => o.id === 'pixel')")


# ====================================================================== M3: honest sink results
def make_ctx_and_fail(c: Console, name: str) -> None:
    ev(c, "JarvisVoice.speaker.tone({ freq: 440, ms: 30, gain: 0.01 })")  # builds the AudioContext
    c.page.wait_for_timeout(300)
    ev(c, f"window.__sinkErr = '{name}'")


@pytest.mark.parametrize("err", ["NotAllowedError", "NotFoundError"])
def test_a_refused_sink_is_not_reported_as_a_switch(make: Callable[..., Console], err: str) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, RECORDER)
    make_ctx_and_fail(c, err)
    r = say(c, "switch to my speaker")
    said = r["result"]["say"]
    assert "Switching" not in said and "couldn't" in said.lower()
    assert sink(c) in ("", None)
    status = ev(c, "JarvisAudioRoutePrefs.status()")
    assert "couldn't switch the sound to that device" in status and "still using" in status
    assert all("Switching" not in t for t in spoken(c))


def test_a_failed_fallback_says_only_that_it_disconnected_and_keeps_a_status(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, RECORDER)
    make_ctx_and_fail(c, "NotAllowedError")
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'buds-stereo')")
    devchange(c)
    wf(c, "window.__said.length > 0")
    lines = spoken(c)
    assert lines and all("I'll use" not in t for t in lines)
    assert any("disconnected" in t.lower() for t in lines)
    assert "disconnected" in ev(c, "JarvisAudioRoutePrefs.status()")


def test_a_disconnect_leaves_a_persistent_on_screen_status(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'buds-stereo')")
    devchange(c)
    wf(c, "JarvisAudioRoutePrefs.status().includes('Galaxy Buds2 Pro')")
    devchange(c)
    c.page.wait_for_timeout(900)
    assert "disconnected" in ev(
        c, "JarvisAudioRoutePrefs.status()"
    )  # outlives the fading voice line
    _voice_panel(c)
    c.page.locator("#vSlotDevices .vdev-status").get_by_text("disconnected", exact=False).wait_for()


# ====================================================================== M8: the mic is open mid-conversation
def test_choosing_a_mic_while_it_is_open_is_pending_until_the_next_open(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page).hold_transcribe = True
    c.open()
    wf(c, "window.__enum >= 1")
    c.page.locator("#micBtn").click()
    wf(c, "JarvisAudio.isOpen()")
    r = say(c, "use the headset mic", state="listening")
    assert "next time I open the mic" in r["result"]["say"]
    assert ev(c, "JarvisAudioRoutePrefs.inputPending()") is True
    assert ev(c, "JarvisAudioRoute.chooseInput('mic-array')") == {"ok": True, "pending": True}


def test_choosing_a_mic_while_it_is_closed_is_not_pending(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    assert ev(c, "JarvisAudioRoute.chooseInput('mic-array')") == {"ok": True}
    assert ev(c, "JarvisAudioRoutePrefs.inputPending()") is False


# ====================================================================== M9: several tabs
def test_a_write_merges_what_another_tab_saved(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    other = {"v": 2, "names": {"jbl": {"value": "kitchen", "label": "Speakers (JBL Flip 5)"}}}
    ev(c, f"localStorage.setItem('{ROUTE_KEY}', {json.dumps(json.dumps(other))})")
    ev(c, "JarvisAudioRoutePrefs.setKind('buds-stereo', 'headphones')")
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["v"] == 2
    assert (
        saved["names"]["jbl"]["value"] == "kitchen"
        and saved["kinds"]["buds-stereo"]["value"] == "headphones"
    )


def test_a_storage_event_reloads_the_prefs_and_rebuilds(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    other = {"v": 2, "names": {"jbl": {"value": "kitchen", "label": "Speakers (JBL Flip 5)"}}}
    ev(c, f"localStorage.setItem('{ROUTE_KEY}', {json.dumps(json.dumps(other))})")
    ev(c, f"window.dispatchEvent(new StorageEvent('storage', {{ key: '{ROUTE_KEY}' }}))")
    wf(c, "JarvisAudioRoutePrefs.prefs().names.jbl === 'kitchen'")
    assert ev(c, "JarvisAudioRoute.find('kitchen').id") == "jbl"


def test_a_hidden_tab_updates_silently(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, RECORDER)
    ev(c, "Object.defineProperty(document, 'visibilityState', { get: () => 'hidden' })")
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, "window.__devs = window.__devs.filter(d => d.deviceId !== 'buds-stereo'); " + PIXEL)
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === ''")
    wf(c, "JarvisAudioRoutePrefs.devices().outputs.some(o => o.id === 'pixel')")
    c.page.wait_for_timeout(2000)
    assert spoken(c) == [] and c.page.locator("#voiceOffer button").count() == 0


# ====================================================================== lows
def test_prototype_names_never_resolve_to_a_device(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    for word in ("constructor", "toString", "__proto__", "hasOwnProperty"):
        assert say(c, f"switch to {word}") == {"handled": False}
        assert ev(c, f"JarvisAudioRoute.find('{word}')") is None


def test_hidden_characters_in_saved_labels_and_nicknames_are_stripped(
    make: Callable[..., Console],
) -> None:
    dirty = {
        "v": 1,
        "output": {"id": "x", "label": "Evil‮​"},
        "names": {"jbl": "ki​tchen‮"},
        "kinds": {"jbl": "speakers"},
    }
    c = make(route=dirty)
    ready(c)
    assert ev(c, "JarvisAudioRoutePrefs.prefs().names.jbl") == "kitchen"
    assert ev(c, "JarvisAudioRoutePrefs.prefs().output.label") == "Evil"


def test_hostile_labels_render_inertly_and_clipped(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'evil', label: '<img src=x onerror=window.__pwn=1>' },"
        " { kind: 'audiooutput', deviceId: 'long', label: 'L'.repeat(5000) },"
        " { kind: 'audiooutput', deviceId: 'bidi', label: 'A\\u202eB\\u200bC' })",
    )
    ev(c, "JarvisAudioRoute.refresh()")
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.locator("[data-out='evil']").wait_for()
    assert slot.locator("img").count() == 0 and ev(c, "window.__pwn") is None
    assert len(ev(c, "JarvisAudioRoute.find('LLLL').label")) <= 120
    assert (
        ev(c, "JarvisAudioRoutePrefs.devices().outputs.find(o => o.id === 'bidi').label") == "ABC"
    )
    assert c.errors == []


def test_a_missing_addeventlistener_on_media_devices_still_lists(
    make: Callable[..., Console],
) -> None:
    c = make(
        (
            "Object.defineProperty(navigator.mediaDevices, 'addEventListener', { value: undefined });",
        )
    )
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    assert c.errors == []


def test_auto_switches_only_to_a_known_external_kind(make: Callable[..., Console]) -> None:
    c = make(route={"v": 1, "onConnect": "auto"})
    ready(c)
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'steam', label: 'Steam Streaming Speakers' })",
    )
    devchange(c)
    wf(c, "JarvisAudioRoutePrefs.devices().outputs.some(o => o.id === 'steam')")
    c.page.wait_for_timeout(2200)
    assert sink(c) in ("", None)  # an unmarked virtual device is only offered
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'steam2', label: 'Another Virtual Speakers' }); "
        + PIXEL,
    )
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === 'pixel'")  # the best external one of the burst


def test_a_hands_free_endpoint_is_never_offered_and_the_stereo_one_is_offered_once(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'foo-hf', label: 'Headset (Foo Hands-Free AG Audio)' })",
    )
    devchange(c)
    wf(c, "JarvisAudioRoutePrefs.devices().outputs.some(o => o.id === 'foo-hf')")
    c.page.wait_for_timeout(1000)
    ev(c, "window.__devs.push({ kind: 'audiooutput', deviceId: 'foo', label: 'Headphones (Foo)' })")
    devchange(c)
    offer = c.page.locator("#voiceOffer")
    offer.locator("button", has_text="Use Headphones (Foo)").wait_for()
    c.page.wait_for_timeout(1800)
    assert offer.locator("button", has_text="Use").count() == 1
    assert "Hands-Free" not in str(offer.text_content())


def test_a_lone_hands_free_endpoint_is_never_offered(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'bar-hf', label: 'Headset (Bar Hands-Free AG Audio)' })",
    )
    devchange(c)
    c.page.wait_for_timeout(2400)
    assert c.page.locator("#voiceOffer button").count() == 0


def test_the_aloud_question_is_asked_only_when_the_loop_is_listening(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, RECORDER)
    ev(c, "window.__loopState = 'thinking'")
    add_buds(c)
    c.page.locator("#voiceOffer button", has_text="Use Headphones").wait_for()
    assert not any(x.get("ask") for x in ev(c, "window.__said"))


def test_a_same_label_device_with_a_new_id_is_a_rebind_not_a_disconnect(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoute.chooseOutput('buds-stereo')")
    ev(c, RECORDER)
    ev(
        c,
        "window.__devs.forEach(d => { if (d.deviceId === 'buds-stereo') d.deviceId = 'buds-stereo-2'; })",
    )
    devchange(c)
    wf(c, "JarvisVoice.speaker.sink() === 'buds-stereo-2'")
    assert not any("disconnected" in x["t"].lower() for x in ev(c, "window.__said"))
    assert (
        json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))["output"]["id"] == "buds-stereo-2"
    )


def test_marks_follow_a_device_whose_id_changed_and_are_stored_with_labels(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(
        c,
        "JarvisAudioRoutePrefs.setKind('jbl', 'headphones'); JarvisAudioRoutePrefs.setName('jbl', 'kitchen')",
    )
    saved = json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))
    assert saved["v"] == 2 and saved["kinds"]["jbl"] == {
        "value": "headphones",
        "label": "Speakers (JBL Flip 5)",
    }
    ev(c, "window.__devs.forEach(d => { if (d.deviceId === 'jbl') d.deviceId = 'jbl-2'; })")
    ev(c, "JarvisAudioRoute.refresh()")
    assert ev(c, "JarvisAudioRoutePrefs.prefs().kinds['jbl-2']") == "headphones"
    assert ev(c, "JarvisAudioRoute.find('kitchen').id") == "jbl-2"


def test_a_v1_save_migrates_to_v2_and_tampered_marks_are_ignored(
    make: Callable[..., Console],
) -> None:
    old = {
        "v": 1,
        "kinds": {"jbl": "headphones", "evil": "bogus"},
        "names": {"jbl": "kitchen", "n": 7},
    }
    c = make(route=old)
    ready(c)
    p = ev(c, "JarvisAudioRoutePrefs.prefs()")
    assert p["kinds"] == {"jbl": "headphones"} and p["names"] == {"jbl": "kitchen"}
    ev(c, "JarvisAudioRoutePrefs.setOnConnect('never')")
    assert json.loads(ev(c, f"localStorage.getItem('{ROUTE_KEY}')"))["v"] == 2
    bad = {
        "v": 2,
        "kinds": {"jbl": {"value": "bogus", "label": "x"}, "a": 5},
        "names": {"jbl": {"value": "k" * 99, "label": "x"}},
    }
    c2 = make(route=bad)
    ready(c2)
    assert (
        ev(c2, "JarvisAudioRoutePrefs.prefs().kinds") == {}
        and ev(c2, "JarvisAudioRoutePrefs.prefs().names") == {}
    )


# ====================================================================== words, scripts, wording of labels
def test_two_word_and_generic_phrases_resolve_in_the_page(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    say(c, "switch to the laptop speakers")
    assert sink(c) == "spk-realtek"
    say(c, "switch to bluetooth speaker")
    assert sink(c) == "jbl"
    assert say(c, "switch to audio") == {"handled": False}


def test_an_ambiguous_word_asks_which_and_shows_both_names(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    r = say(c, "switch to bluetooth")
    assert r["result"]["say"] == "I can see two, which one, Sir?"
    line = str(c.page.locator("#voiceLine").text_content())
    assert "Galaxy Buds2 Pro" in line and "JBL Flip 5" in line
    assert sink(c) in ("", None)


@pytest.mark.parametrize("nick", ["ഹെഡ്ഫോൺ", "हेडफोन", "हेडफ़ोन"])
def test_indic_nicknames_are_kept_and_matched_by_voice(
    make: Callable[..., Console], nick: str
) -> None:
    c = make()
    ready(c)
    ev(c, f"JarvisAudioRoutePrefs.setName('jbl', {json.dumps(nick)})")
    assert ev(c, "JarvisAudioRoutePrefs.prefs().names.jbl") == nick
    assert ev(c, f"JarvisAudioRoute.find({json.dumps(nick)}).id") == "jbl"
    assert say(c, f"switch to {nick}")["id"] == "device.switch" and sink(c) == "jbl"


def test_a_filler_word_in_a_nickname_is_ignored(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoutePrefs.setName('jbl', 'my kitchen')")
    assert ev(c, "JarvisAudioRoute.find('kitchen').id") == "jbl"


def test_windows_naming_patterns_group_in_the_page(make: Callable[..., Console]) -> None:
    c = make()
    ready(c)
    ev(
        c,
        "window.__devs.push({ kind: 'audiooutput', deviceId: 'xs', label: 'Headphones (WH-1000XM4 Stereo)' },"
        " { kind: 'audiooutput', deviceId: 'xh', label: 'Headset (WH-1000XM4 Hands-Free AG Audio)' },"
        " { kind: 'audiooutput', deviceId: 'ps', label: 'Headphones (X)' },"
        " { kind: 'audiooutput', deviceId: 'ph', label: 'Headset (X)' })",
    )
    res = ev(c, "JarvisAudioRoute.refresh()")
    flagged = {o["id"] for o in res["outputs"] if o["callQuality"]}
    assert {"xh", "ph"} <= flagged and "xs" not in flagged and "ps" not in flagged


# ====================================================================== timers
def test_a_stray_yes_after_the_question_timed_out_switches_nothing(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page).hold_transcribe = True
    c.open()
    wf(c, "window.__enum >= 1")
    c.page.locator("#micBtn").click()
    wf(c, "JarvisVoiceLoop.inConversation()")
    add_buds(c)
    wf(c, "JarvisVoiceCommands.pending() !== null")
    wf(c, "JarvisVoiceCommands.pending() === null")  # the 8 s timeout
    ev(c, "JarvisVoiceCommands.handle('yes please', {source: 'voice', state: 'listening'})")
    c.page.wait_for_timeout(300)
    assert sink(c) in ("", None)


def test_the_offer_chip_goes_away_after_thirty_seconds(make: Callable[..., Console]) -> None:
    c = make()
    c.page.clock.install()
    ready(c)
    add_buds(c)
    c.page.clock.run_for(2000)
    c.page.locator("#voiceOffer button", has_text="Use Headphones").wait_for()
    c.page.clock.run_for(31000)
    assert c.page.locator("#voiceOffer button").count() == 0
    assert sink(c) in ("", None)


# ====================================================================== focus
def test_the_picker_is_not_rebuilt_under_a_nickname_being_typed(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    nick = slot.locator("[data-out='jbl'] input.nick")
    nick.wait_for()
    nick.focus()
    nick.press_sequentially("kit")
    add_buds(c)
    wf(c, "JarvisAudioRoutePrefs.devices().outputs.some(o => o.id === 'pixel')")
    c.page.wait_for_timeout(300)
    assert slot.locator("[data-out='jbl'] input.nick").input_value() == "kit"
    assert slot.locator("[data-out='pixel']").count() == 0  # deferred until the field loses focus
    c.page.locator("body").click(position={"x": 5, "y": 5})
    slot.locator("[data-out='pixel']").wait_for()


# ====================================================================== shared strings
def test_the_panel_uses_the_route_strings(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    slot = c.page.locator("#vSlotDevices")
    slot.locator("[data-out='jbl']").wait_for()
    line = ev(c, "JarvisAudioRoutePrefs.text.browserVoice()")
    assert line.startswith("My browser voice follows Windows' sound output")
    assert line in str(slot.text_content())
    assert set(ev(c, "Object.keys(JarvisAudioRoutePrefs.text)")) == {
        "android",
        "browserVoice",
        "unsupported",
        "noNames",
    }


def test_an_utterance_over_the_word_cap_is_never_a_device_command(
    make: Callable[..., Console],
) -> None:
    c = make()
    ready(c)
    ev(c, "JarvisAudioRoutePrefs.setName('jbl', 'kitchen')")
    assert say(c, "switch to kitchen")["id"] == "device.switch"
    assert say(c, "switch to the kitchen speaker that i bought last year") == {"handled": False}


# ====================================================================== I1: cross-module seams
# Every listed microphone "exists": the fake capture device stands in for whichever id is asked for,
# and each request is recorded, so a test can see which device a listening turn opened.
ANY_MIC = """
(() => {
  window.__cons = [];
  const md = navigator.mediaDevices, inner = md.getUserMedia.bind(md);
  md.getUserMedia = (c) => {
    window.__cons.push(JSON.parse(JSON.stringify(c)));
    const audio = Object.assign({}, c.audio); delete audio.deviceId;
    return inner({ audio });
  };
})();
"""
NOT_SPOKEN = """localStorage.setItem('jarvis_voice_device_v1',
  JSON.stringify({ interruptBy: 'tap', speak: 'never', keepListening: false }));"""


def test_a_mic_chosen_mid_conversation_takes_over_at_the_next_turn_and_is_no_longer_pending(
    make: Callable[..., Console],
) -> None:
    # the conversation holds the mic open (D3); the choice applies when the next turn opens it
    c = make((ANY_MIC,))
    FakeVoice(c.page)
    c.open()
    wf(c, "window.__enum >= 1")
    c.page.locator("#micBtn").click()
    wf(c, "JarvisAudio.isOpen()")
    r = say(c, "use the headset mic", state="listening")
    assert "next time I open the mic" in r["result"]["say"]
    assert ev(c, "JarvisAudioRoutePrefs.inputPending()") is True
    n = ev(c, "window.__cons.length")
    c.page.wait_for_function(f"() => window.__cons.length > {n}", timeout=60000)
    assert ev(c, "window.__cons[window.__cons.length - 1].audio.deviceId") == {"exact": "buds-mic"}
    wf(c, "JarvisAudioRoutePrefs.inputPending() === false")
    assert ev(c, "JarvisAudio.isOpen()") is True and ev(c, "JarvisAudio.inputId()") == "buds-mic"
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_a_device_line_with_no_name_in_it_is_shown_even_when_replies_are_not_spoken(
    make: Callable[..., Console],
) -> None:
    # a line from done() (here Android's steps) was only ever spoken: with "Speak replies: Never" the
    # owner saw nothing at all. Name-free lines are shown as they are said (I1)
    c = make((ANDROID, NOT_SPOKEN))
    fake = FakeVoice(c.page)
    fake.transcript = {**fake.transcript, "text": "switch to my earphones"}
    c.open()
    wf(c, "window.__enum >= 1")
    c.page.locator("#micBtn").click()
    wf(c, "/open Quick Settings/.test(document.getElementById('voiceLine').textContent)")
    assert fake.spoken() == []
    assert c.errors == []
