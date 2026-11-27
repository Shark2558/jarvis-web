# src/jarvis/calldesk/ports.py
"""What the call desk needs from Windows, as Protocols (R18 C).

`jarvis.calldesk.win` implements them with Core Audio (comtypes) and soundcard; the tests use
fakes. Everything blocking here is called from a worker thread, never the event loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["console", "multimedia", "communications"]
ROLES: tuple[Role, ...] = ("console", "multimedia", "communications")
Flow = Literal["render", "capture"]

# Windows' endpoint form factors (EndpointFormFactor) the desk cares about
FORM_HEADPHONES = 3
FORM_HEADSET = 5


class PolicyError(Exception):
    """Windows refused or failed an audio-device call (plain words, no device names)."""


class AudioDeviceError(Exception):
    """A sound device could not be opened, read or written (plain words)."""


@dataclass(frozen=True)
class Endpoint:
    """One active audio endpoint. `bluetooth` is True when Windows says it sits on a Bluetooth
    bus; `form_factor` is Windows' EndpointFormFactor (None when unknown)."""

    id: str
    name: str
    flow: Flow
    bluetooth: bool = False
    form_factor: int | None = None


class AudioPolicy(Protocol):
    """Windows' audio endpoints and their default roles (IMMDeviceEnumerator + IPolicyConfig)."""

    def endpoints(self, flow: Flow) -> Sequence[Endpoint]: ...

    def default_id(self, flow: Flow, role: Role) -> str | None: ...

    def set_default(self, device_id: str, role: Role) -> None: ...


class SystemSounds(Protocol):
    """The "System sounds" session of the default speaker (notification sounds)."""

    def muted(self) -> bool | None:
        """None when the session can't be found."""
        ...

    def set_muted(self, muted: bool) -> None: ...


class Capture(Protocol):
    """The loopback recording of the default speaker, 16 kHz mono PCM16."""

    def read(self) -> bytes:
        """Blocks until one 20 ms frame (640 bytes) is recorded."""
        ...

    def close(self) -> None: ...


class Player(Protocol):
    """Playback into VB-CABLE's "CABLE Input", 16 kHz mono PCM16."""

    def write(self, pcm: bytes) -> None:
        """Blocks until `pcm` (a few frames at most) is handed to the device."""
        ...

    def close(self) -> None: ...


class SoundDevices(Protocol):
    def open_loopback(self) -> Capture: ...

    def open_cable_player(self) -> Player: ...


class Processes(Protocol):
    def running(self) -> frozenset[str]:
        """Lower-case image names of the running processes (e.g. "phoneexperiencehost.exe")."""
        ...


__all__ = [
    "FORM_HEADPHONES",
    "FORM_HEADSET",
    "ROLES",
    "AudioDeviceError",
    "AudioPolicy",
    "Capture",
    "PolicyError",
    "Endpoint",
    "Flow",
    "Player",
    "Processes",
    "Role",
    "SoundDevices",
    "SystemSounds",
]
