# src/jarvis/calldesk/checks.py
"""The checks before every call (R18 build brief; plan section 4 step 2, risks 6 and 7).

S0 has not run on the owner's laptop yet, so the desk proves the audio path itself, each time:

- VB-CABLE is installed: both "CABLE Input" (JARVIS plays into it) and "CABLE Output" (the
  microphone Phone Link sends into the call);
- Phone Link is running (its process, PhoneExperienceHost.exe; YourPhone.exe on older builds);
- no Bluetooth headset is connected to the LAPTOP: Phone Link refuses calls then ("Calls using
  Bluetooth headsets are not supported", seen 25 Nov 2026). A headset is an endpoint on a Bluetooth
  bus whose form factor is headphones or headset, or one Windows names "... Hands-Free AG Audio"
  (Windows as the audio gateway, the headset as hands-free unit);
- the audio path is alive: the loopback recording of the default speaker and CABLE Input open
  and move audio.

The report carries plain words for the call card and no device names (a headset can be named after
its owner). `ready` is False when a call can't work; a cable he left as his own microphone is a
warning only.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from jarvis.calldesk.audio import FRAME_BYTES
from jarvis.calldesk.micguard import CABLE_LEFT, CABLE_MIC
from jarvis.calldesk.ports import (
    FORM_HEADPHONES,
    FORM_HEADSET,
    AudioDeviceError,
    AudioPolicy,
    Endpoint,
    PolicyError,
    Processes,
    SoundDevices,
)

log = logging.getLogger(__name__)

CABLE_SPEAKER = "CABLE Input"  # VB-CABLE's playback side: JARVIS plays into it
PHONE_LINK_PROCESSES = frozenset({"phoneexperiencehost.exe", "yourphone.exe"})
_HANDS_FREE_AG = "hands-free ag audio"

NO_CABLE = (
    "VB-CABLE is not installed (CABLE Input and CABLE Output are missing): install it (README "
    "step 2) and restart the laptop."
)
NO_PHONE_LINK = (
    "Phone Link is not running on the laptop: open Phone Link and check that your phone is "
    "connected for calls."
)
BT_HEADSET = (
    "A Bluetooth headset is connected to the laptop, and Phone Link refuses calls then: "
    "disconnect it (Settings > Bluetooth & devices), or take the call on your phone."
)
NO_AUDIO = (
    "The laptop's sound could not be opened for the call (the speaker recording or CABLE Input): "
    "check Settings > System > Sound, then restart the call desk."
)
NO_DEVICES = "Windows' list of sound devices could not be read: restart the call desk."


@dataclass(frozen=True)
class DeskCheck:
    ready: bool
    problems: tuple[str, ...]
    bt_headset: bool
    cable: bool
    phone_link: bool
    audio_ok: bool


def _has(endpoints: Sequence[Endpoint], name: str) -> bool:
    needle = name.casefold()
    return any(needle in e.name.casefold() for e in endpoints)


def is_bluetooth_headset(endpoint: Endpoint) -> bool:
    if _HANDS_FREE_AG in endpoint.name.casefold():
        return True
    return endpoint.bluetooth and endpoint.form_factor in (FORM_HEADPHONES, FORM_HEADSET)


def parse_tasklist(text: str) -> frozenset[str]:
    """Image names from `tasklist /FO CSV /NH` (lower case)."""
    names = set()
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip():
            names.add(row[0].strip().casefold())
    return frozenset(names)


def probe_audio(devices: SoundDevices) -> bool:
    """Open the loopback and CABLE Input and move one frame through each."""
    try:
        capture = devices.open_loopback()
        try:
            frame = capture.read()
        finally:
            capture.close()
        player = devices.open_cable_player()
        try:
            player.write(b"\x00" * FRAME_BYTES)
        finally:
            player.close()
    except AudioDeviceError:
        log.warning("the audio path check failed")
        return False
    return len(frame) == FRAME_BYTES


class Checker:
    def __init__(
        self,
        policy: AudioPolicy,
        processes: Processes,
        probe: Callable[[], bool],
        *,
        cable_left: Callable[[], bool] = lambda: False,
    ) -> None:
        self._policy = policy
        self._processes = processes
        self._probe = probe
        self._cable_left = cable_left
        self._audio_ok: bool | None = None  # the last probe's answer

    def run(self, *, probe_audio: bool = True) -> DeskCheck:
        """Blocking (Windows calls): run it in a worker thread."""
        problems: list[str] = []
        try:
            render = self._policy.endpoints("render")
            capture = self._policy.endpoints("capture")
        except PolicyError:
            log.warning("listing the audio devices failed")
            return DeskCheck(False, (NO_DEVICES,), False, False, False, False)
        cable = _has(render, CABLE_SPEAKER) and _has(capture, CABLE_MIC)
        if not cable:
            problems.append(NO_CABLE)
        try:
            phone_link = bool(self._processes.running() & PHONE_LINK_PROCESSES)
        except OSError:
            phone_link = False
        if not phone_link:
            problems.append(NO_PHONE_LINK)
        bt_headset = any(is_bluetooth_headset(e) for e in (*render, *capture))
        if bt_headset:
            problems.append(BT_HEADSET)
        audio_ok = self._audio(cable, probe_audio)
        if cable and not audio_ok:
            problems.append(NO_AUDIO)
        ready = cable and phone_link and not bt_headset and audio_ok
        if self._safe_cable_left():
            problems.append(CABLE_LEFT)
        return DeskCheck(ready, tuple(problems), bt_headset, cable, phone_link, audio_ok)

    def _audio(self, cable: bool, probe: bool) -> bool:
        if not cable:
            return False
        if probe:
            self._audio_ok = self._probe()
        return self._audio_ok is not False  # not probed yet: not known to fail

    def _safe_cable_left(self) -> bool:
        try:
            return self._cable_left()
        except PolicyError:
            return False


__all__ = [
    "BT_HEADSET",
    "CABLE_SPEAKER",
    "NO_AUDIO",
    "NO_CABLE",
    "NO_PHONE_LINK",
    "PHONE_LINK_PROCESSES",
    "Checker",
    "DeskCheck",
    "is_bluetooth_headset",
    "parse_tasklist",
    "probe_audio",
]
