"""R18 C: the checks before every call (VB-CABLE, Phone Link, no Bluetooth headset on the laptop,
the audio path), with fake Windows parts. Plan risk 7: a headset on the laptop makes Phone Link
refuse calls, so the desk says so before anything is dialled."""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.calldesk import checks
from jarvis.calldesk.audio import FRAME_BYTES
from jarvis.calldesk.ports import (
    FORM_HEADPHONES,
    FORM_HEADSET,
    AudioDeviceError,
    Endpoint,
    Flow,
    PolicyError,
    Role,
)

SPEAKER = Endpoint("{spk}", "Speakers (Realtek(R) Audio)", "render", form_factor=1)
CABLE_IN = Endpoint("{cin}", "CABLE Input (VB-Audio Virtual Cable)", "render")
MIC = Endpoint("{mic}", "Microphone Array (Realtek(R) Audio)", "capture", form_factor=4)
CABLE_OUT = Endpoint("{cout}", "CABLE Output (VB-Audio Virtual Cable)", "capture")


class Policy:
    def __init__(self, render: Sequence[Endpoint], capture: Sequence[Endpoint]) -> None:
        self.render, self.capture = list(render), list(capture)
        self.broken = False

    def endpoints(self, flow: Flow) -> Sequence[Endpoint]:
        if self.broken:
            raise PolicyError("enumeration failed")
        return self.render if flow == "render" else self.capture

    def default_id(self, flow: Flow, role: Role) -> str | None:
        return None

    def set_default(self, device_id: str, role: Role) -> None:
        raise AssertionError("checks never change a device")


class Procs:
    def __init__(self, names: set[str]) -> None:
        self.names = frozenset(names)

    def running(self) -> frozenset[str]:
        return self.names


def _checker(
    policy: Policy | None = None,
    procs: Procs | None = None,
    probe: bool = True,
    cable_left: bool = False,
) -> checks.Checker:
    return checks.Checker(
        policy or Policy([SPEAKER, CABLE_IN], [MIC, CABLE_OUT]),
        procs or Procs({"explorer.exe", "phoneexperiencehost.exe"}),
        lambda: probe,
        cable_left=lambda: cable_left,
    )


def test_all_good_is_ready_with_no_problems() -> None:
    got = _checker().run()
    assert got == checks.DeskCheck(True, (), False, True, True, True)


def test_missing_cable_is_not_ready() -> None:
    got = _checker(Policy([SPEAKER, CABLE_IN], [MIC])).run()
    assert not got.ready and not got.cable and got.problems == (checks.NO_CABLE,)
    assert not got.audio_ok


def test_phone_link_not_running_is_not_ready() -> None:
    got = _checker(procs=Procs({"explorer.exe"})).run()
    assert not got.ready and not got.phone_link and got.problems == (checks.NO_PHONE_LINK,)
    assert _checker(procs=Procs({"yourphone.exe"})).run().phone_link  # the older name


def test_a_bluetooth_headset_on_the_laptop_is_not_ready_and_names_no_device() -> None:
    buds = Endpoint("{bt}", "Headphones (Ravi's Buds)", "render", True, FORM_HEADPHONES)
    got = _checker(Policy([SPEAKER, CABLE_IN, buds], [MIC, CABLE_OUT])).run()
    assert not got.ready and got.bt_headset and got.problems == (checks.BT_HEADSET,)
    assert "Ravi" not in " ".join(got.problems)


def test_headset_rules() -> None:
    assert checks.is_bluetooth_headset(
        Endpoint("{a}", "Headset (WH-1000XM4 Hands-Free AG Audio)", "capture")
    )
    assert checks.is_bluetooth_headset(Endpoint("{b}", "Headset", "capture", True, FORM_HEADSET))
    # the phone's own hands-free link (Phone Link calls), a Bluetooth speaker (form factor 1) or
    # a USB headset is fine for Phone Link
    assert not checks.is_bluetooth_headset(
        Endpoint("{p}", "Headset (Galaxy Hands-Free HF Audio)", "capture", True, FORM_HEADSET)
    )
    assert not checks.is_bluetooth_headset(Endpoint("{c}", "Speaker", "render", True, 1))
    assert not checks.is_bluetooth_headset(
        Endpoint("{d}", "Headset (USB Audio)", "render", False, FORM_HEADSET)
    )


def test_a_dead_audio_path_is_not_ready_and_the_answer_is_kept() -> None:
    checker = _checker(probe=False)
    got = checker.run()
    assert not got.ready and not got.audio_ok and got.problems == (checks.NO_AUDIO,)
    later = checker.run(probe_audio=False)  # a light periodic check keeps the last answer
    assert not later.audio_ok and not later.ready


def test_light_check_before_any_probe_is_not_a_failure() -> None:
    got = _checker(probe=False).run(probe_audio=False)
    assert got.ready and got.audio_ok


def test_a_cable_he_left_as_his_microphone_is_a_warning_only() -> None:
    got = _checker(cable_left=True).run()
    assert got.ready and len(got.problems) == 1 and "CABLE Output" in got.problems[0]


def test_unreadable_device_list_is_not_ready() -> None:
    policy = Policy([], [])
    policy.broken = True
    got = _checker(policy).run()
    assert not got.ready and got.problems == (checks.NO_DEVICES,)


def test_parse_tasklist_csv() -> None:
    text = (
        '"System Idle Process","0","Services","0","8 K"\r\n'
        '"PhoneExperienceHost.exe","9120","Console","1","120,404 K"\r\n'
        '\r\n"explorer.exe","4412","Console","1","200,000 K"\r\n'
    )
    assert checks.parse_tasklist(text) == {
        "system idle process",
        "phoneexperiencehost.exe",
        "explorer.exe",
    }


class _Cap:
    def __init__(self, frame: bytes) -> None:
        self.frame, self.closed = frame, False

    def read(self) -> bytes:
        return self.frame

    def close(self) -> None:
        self.closed = True


class _Play:
    def __init__(self, fail: bool) -> None:
        self.fail, self.closed, self.written = fail, False, b""

    def write(self, pcm: bytes) -> None:
        if self.fail:
            raise AudioDeviceError("CABLE Input could not be opened")
        self.written += pcm

    def close(self) -> None:
        self.closed = True


class _Devices:
    def __init__(self, frame: bytes = b"\x00" * FRAME_BYTES, fail_play: bool = False) -> None:
        self.cap, self.play = _Cap(frame), _Play(fail_play)

    def open_loopback(self) -> _Cap:
        return self.cap

    def open_cable_player(self) -> _Play:
        return self.play


def test_probe_moves_one_frame_each_way_and_closes_both() -> None:
    devices = _Devices()
    assert checks.probe_audio(devices)
    assert devices.cap.closed and devices.play.closed and len(devices.play.written) == FRAME_BYTES


def test_probe_fails_on_a_device_error_or_a_short_frame() -> None:
    failing = _Devices(fail_play=True)
    assert not checks.probe_audio(failing) and failing.play.closed
    assert not checks.probe_audio(_Devices(frame=b"\x00" * 10))
