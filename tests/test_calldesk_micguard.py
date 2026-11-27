"""R18 C: the default-microphone switch and its restore (plan section 8: "audio left routed to the
cable after a crash"), with a fake Windows audio policy.

The rule under test: the owner is never left without his microphone. The previous defaults are
saved BEFORE anything changes, a switch Windows doesn't confirm is undone at once, a crash leaves a
state file that the next start (or the watchdog) restores from, and only roles still pointing at
the cable are touched.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis.calldesk.micguard import CABLE_MIC, AudioStateFile, MicGuard, SavedAudio
from jarvis.calldesk.ports import ROLES, Endpoint, Flow, PolicyError, Role

OWN = Endpoint(id="{own}", name="Microphone Array (Realtek(R) Audio)", flow="capture")
USB = Endpoint(id="{usb}", name="Headset Microphone (USB Audio)", flow="capture")
CABLE = Endpoint(id="{cable}", name="CABLE Output (VB-Audio Virtual Cable)", flow="capture")
SPEAKER = Endpoint(id="{spk}", name="Speakers (Realtek(R) Audio)", flow="render")


class FakePolicy:
    def __init__(self, captures: Sequence[Endpoint] = (OWN, CABLE)) -> None:
        self.captures = list(captures)
        self.defaults: dict[Role, str | None] = dict.fromkeys(ROLES, OWN.id)
        self.calls: list[tuple[str, Role]] = []
        self.fail_on: set[Role] = set()
        self.ignore: set[Role] = set()  # Windows "accepts" but nothing changes

    def endpoints(self, flow: Flow) -> Sequence[Endpoint]:
        return list(self.captures) if flow == "capture" else [SPEAKER]

    def default_id(self, flow: Flow, role: Role) -> str | None:
        assert flow == "capture"
        return self.defaults[role]

    def set_default(self, device_id: str, role: Role) -> None:
        self.calls.append((device_id, role))
        if role in self.fail_on:
            raise PolicyError("set_default failed")
        if role not in self.ignore:
            self.defaults[role] = device_id


class FakeSounds:
    def __init__(self, muted: bool | None = False) -> None:
        self.state = muted
        self.fail = False

    def muted(self) -> bool | None:
        return self.state

    def set_muted(self, muted: bool) -> None:
        if self.fail:
            raise PolicyError("no session")
        self.state = muted


@pytest.fixture
def store(tmp_path: Path) -> AudioStateFile:
    return AudioStateFile(tmp_path / "audio-state.json")


def _guard(policy: FakePolicy, store: AudioStateFile, sounds: FakeSounds | None = None) -> MicGuard:
    return MicGuard(policy, sounds, store, clock=lambda: 1_000.0)


def test_switch_saves_the_previous_defaults_before_changing_anything(
    store: AudioStateFile,
) -> None:
    policy = FakePolicy()
    seen: list[SavedAudio | None] = []
    original = policy.set_default

    def spy(device_id: str, role: Role) -> None:
        seen.append(store.load())
        original(device_id, role)

    policy.set_default = spy  # type: ignore[method-assign]
    out = _guard(policy, store).switch_to_cable("call_1")
    assert out.ok and out.problems == ()
    assert policy.defaults == dict.fromkeys(ROLES, CABLE.id)
    first = seen[0]
    assert first is not None and first.mic_switched and first.cable_id == CABLE.id
    assert dict(first.previous) == dict.fromkeys(ROLES, OWN.id) and first.call_id == "call_1"


def test_restore_puts_every_role_back_and_clears_the_state(store: AudioStateFile) -> None:
    policy = FakePolicy([OWN, USB, CABLE])
    policy.defaults = {"console": OWN.id, "multimedia": OWN.id, "communications": USB.id}
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    out = guard.restore()
    assert out.ok and out.changed
    assert policy.defaults == {"console": OWN.id, "multimedia": OWN.id, "communications": USB.id}
    assert store.load() is None


def test_a_switch_windows_does_not_confirm_is_undone_at_once(store: AudioStateFile) -> None:
    policy = FakePolicy()
    policy.ignore = {"communications"}
    out = _guard(policy, store).switch_to_cable("call_1")
    assert not out.ok and out.problems
    assert "your own microphone is kept" in out.problems[0]
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)
    assert store.load() is None


def test_a_failing_switch_is_undone_and_reported(store: AudioStateFile) -> None:
    policy = FakePolicy()
    policy.fail_on = {"multimedia"}
    out = _guard(policy, store).switch_to_cable("call_1")
    assert not out.ok
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_no_cable_no_switch(store: AudioStateFile) -> None:
    policy = FakePolicy([OWN])
    out = _guard(policy, store).switch_to_cable("call_1")
    assert not out.ok and "VB-CABLE" in out.problems[0]
    assert policy.calls == [] and store.load() is None


def test_a_state_file_that_cannot_be_written_means_no_switch(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x")
    store = AudioStateFile(blocked / "audio-state.json")
    policy = FakePolicy()
    out = _guard(policy, store).switch_to_cable("call_1")
    assert not out.ok and policy.calls == []
    assert "could not save" in out.problems[0]


def test_after_a_crash_the_next_start_restores_from_the_state_file(store: AudioStateFile) -> None:
    policy = FakePolicy()
    assert _guard(policy, store).switch_to_cable("call_1").ok
    # the desk died here; a new process (or the watchdog) starts with a fresh guard
    out = _guard(policy, store).restore_left_over()
    assert out is not None and out.ok and out.changed
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)
    assert _guard(policy, store).restore_left_over() is None  # nothing left to do


def test_restore_leaves_a_role_the_owner_already_changed(store: AudioStateFile) -> None:
    policy = FakePolicy([OWN, USB, CABLE])
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    policy.defaults["console"] = USB.id  # he picked his USB headset during the call
    assert guard.restore().ok
    assert policy.defaults == {"console": USB.id, "multimedia": OWN.id, "communications": OWN.id}


def test_restore_falls_back_when_the_saved_microphone_is_gone(store: AudioStateFile) -> None:
    policy = FakePolicy([OWN, USB, CABLE])
    policy.defaults = dict.fromkeys(ROLES, USB.id)
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    policy.captures = [OWN, CABLE]  # the USB headset was unplugged
    out = guard.restore()
    assert out.ok and policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_restore_that_fails_keeps_the_state_for_the_next_try(store: AudioStateFile) -> None:
    policy = FakePolicy()
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    policy.fail_on = set(ROLES)
    out = guard.restore()
    assert not out.ok and "could not be switched back" in out.problems[0]
    saved = store.load()
    assert saved is not None and saved.mic_switched
    policy.fail_on = set()
    assert _guard(policy, store).restore_left_over() is not None
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id) and store.load() is None


def test_a_cable_left_as_default_is_never_saved_as_the_owners_microphone(
    store: AudioStateFile,
) -> None:
    policy = FakePolicy([CABLE, OWN])
    policy.defaults = dict.fromkeys(ROLES, CABLE.id)  # left by hand after S0, say
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    saved = store.load()
    assert saved is not None and set(saved.previous.values()) == {OWN.id}
    assert guard.restore().ok and policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_a_second_prepare_keeps_the_true_originals(store: AudioStateFile) -> None:
    policy = FakePolicy()
    guard = _guard(policy, store)
    assert guard.switch_to_cable("call_1").ok
    assert guard.switch_to_cable("call_1").ok  # the cloud asked again after a reconnect
    assert guard.restore().ok and policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_an_unreadable_state_file_restores_any_role_left_on_the_cable(
    store: AudioStateFile,
) -> None:
    policy = FakePolicy()
    policy.defaults = {"console": CABLE.id, "multimedia": CABLE.id, "communications": OWN.id}
    store.path.write_text("{not json", encoding="utf-8")
    out = _guard(policy, store).restore_left_over()
    assert out is not None and out.ok
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id) and store.load() is None


def test_no_state_file_means_hands_off_even_if_the_cable_is_default(
    store: AudioStateFile,
) -> None:
    policy = FakePolicy()
    policy.defaults = dict.fromkeys(ROLES, CABLE.id)
    guard = _guard(policy, store)
    assert guard.restore_left_over() is None and policy.calls == []
    assert guard.cable_left_as_default()


# ---- notification sounds -----------------------------------------------------------------------


def test_sounds_muted_for_the_call_and_unmuted_on_release(store: AudioStateFile) -> None:
    policy, sounds = FakePolicy(), FakeSounds(muted=False)
    guard = _guard(policy, store, sounds)
    assert guard.switch_to_cable("call_1").ok
    assert guard.mute_sounds() and sounds.state is True
    # takeover: his microphone back, the sounds stay off (the recording runs on)
    assert guard.restore(sounds=False).ok
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id) and sounds.state is True
    saved = store.load()
    assert saved is not None and saved.sounds_muted_by_desk and not saved.mic_switched
    assert guard.restore().ok and sounds.state is False and store.load() is None


def test_sounds_he_muted_himself_stay_muted(store: AudioStateFile) -> None:
    sounds = FakeSounds(muted=True)
    guard = _guard(FakePolicy(), store, sounds)
    assert guard.switch_to_cable("call_1").ok and guard.mute_sounds()
    assert guard.restore().ok and sounds.state is True


def test_sounds_muted_before_a_crash_are_unmuted_at_next_start(store: AudioStateFile) -> None:
    policy, sounds = FakePolicy(), FakeSounds(muted=False)
    guard = _guard(policy, store, sounds)
    assert guard.switch_to_cable("call_1").ok and guard.mute_sounds()
    assert _guard(policy, store, sounds).restore_left_over() is not None
    assert sounds.state is False


def test_sounds_that_cannot_be_muted_do_not_stop_the_call(store: AudioStateFile) -> None:
    sounds = FakeSounds(muted=False)
    sounds.fail = True
    guard = _guard(FakePolicy(), store, sounds)
    assert guard.switch_to_cable("call_1").ok
    assert guard.mute_sounds() is False
    saved = store.load()
    assert saved is not None and not saved.sounds_muted_by_desk
    assert _guard(FakePolicy(), store, None).mute_sounds() is False


def test_state_file_is_small_json_without_names(store: AudioStateFile) -> None:
    guard = _guard(FakePolicy(), store)
    assert guard.switch_to_cable("call_1").ok
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["v"] == 1 and raw["mic_switched"] is True
    assert "Realtek" not in store.path.read_text(encoding="utf-8")
    assert CABLE_MIC == "CABLE Output"
