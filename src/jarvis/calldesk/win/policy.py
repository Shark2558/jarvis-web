# src/jarvis/calldesk/win/policy.py
"""`ports.AudioPolicy` and `ports.SystemSounds` on Windows Core Audio (Windows only; R18 C).

Every COM failure becomes `PolicyError` with plain words (no device names); the callers
(`micguard`, `checks`) decide what the owner is told. Objects are made per call: they are cheap,
and a device plugged in or out between two calls is then seen.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import comtypes

from jarvis.calldesk.ports import Endpoint, Flow, PolicyError, Role
from jarvis.calldesk.win import coreaudio as ca

log = logging.getLogger(__name__)

_FLOW = {"render": ca.E_RENDER, "capture": ca.E_CAPTURE}
_ROLE = {
    "console": ca.ROLE_CONSOLE,
    "multimedia": ca.ROLE_MULTIMEDIA,
    "communications": ca.ROLE_COMMUNICATIONS,
}
_BLUETOOTH_ENUMERATORS = frozenset({"BTHENUM", "BTHHFENUM", "BTHLEDEVICE", "BTHLE"})
_COM_ERRORS: tuple[type[BaseException], ...] = (comtypes.COMError, OSError, ValueError)
_E_NOTFOUND = 0x80070490  # HRESULT_FROM_WIN32(ERROR_NOT_FOUND)


def _enumerator() -> Any:
    return comtypes.CoCreateInstance(
        ca.CLSID_MMDeviceEnumerator, ca.IMMDeviceEnumerator, ca.CLSCTX_ALL
    )


def _endpoint(device: Any, flow: Flow) -> Endpoint:
    store = device.OpenPropertyStore(ca.STGM_READ)
    name = ca.read_text(store, ca.PKEY_Device_FriendlyName) or ""
    try:
        enumerator = (ca.read_text(store, ca.PKEY_Device_EnumeratorName) or "").upper()
    except _COM_ERRORS:
        enumerator = ""
    try:
        form = ca.read_uint(store, ca.PKEY_AudioEndpoint_FormFactor)
    except _COM_ERRORS:
        form = None
    return Endpoint(
        id=ca.device_id(device),
        name=name,
        flow=flow,
        bluetooth=enumerator in _BLUETOOTH_ENUMERATORS,
        form_factor=form,
    )


class WinAudioPolicy:
    def endpoints(self, flow: Flow) -> Sequence[Endpoint]:
        try:
            devices = _enumerator().EnumAudioEndpoints(_FLOW[flow], ca.DEVICE_STATE_ACTIVE)
            return [_endpoint(devices.Item(i), flow) for i in range(devices.GetCount())]
        except _COM_ERRORS:
            raise PolicyError("Windows' list of sound devices could not be read") from None

    def default_id(self, flow: Flow, role: Role) -> str | None:
        try:
            device = _enumerator().GetDefaultAudioEndpoint(_FLOW[flow], _ROLE[role])
        except comtypes.COMError as exc:
            if (exc.hresult & 0xFFFFFFFF) == _E_NOTFOUND:
                return None  # no device of that kind at all
            raise PolicyError("Windows' default sound device could not be read") from None
        except _COM_ERRORS:
            raise PolicyError("Windows' default sound device could not be read") from None
        try:
            return ca.device_id(device)
        except _COM_ERRORS:
            raise PolicyError("Windows' default sound device could not be read") from None

    def set_default(self, device_id: str, role: Role) -> None:
        try:
            policy = comtypes.CoCreateInstance(
                ca.CLSID_PolicyConfigClient, ca.IPolicyConfig, ca.CLSCTX_ALL
            )
            policy.SetDefaultEndpoint(device_id, _ROLE[role])
        except _COM_ERRORS:
            raise PolicyError("Windows did not change the default sound device") from None


class WinSystemSounds:
    """The "System sounds" session of the default speaker (where notification sounds play)."""

    def _volume(self) -> Any | None:
        speaker = _enumerator().GetDefaultAudioEndpoint(ca.E_RENDER, ca.ROLE_CONSOLE)
        unknown = speaker.Activate(ca.IAudioSessionManager2._iid_, ca.CLSCTX_ALL, None)
        manager = unknown.QueryInterface(ca.IAudioSessionManager2)
        sessions = manager.GetSessionEnumerator()
        for i in range(sessions.GetCount()):
            control = sessions.GetSession(i).QueryInterface(ca.IAudioSessionControl2)
            if control.IsSystemSoundsSession() == 0 or control.GetProcessId() == 0:
                return control.QueryInterface(ca.ISimpleAudioVolume)
        return None

    def muted(self) -> bool | None:
        try:
            volume = self._volume()
            return None if volume is None else bool(volume.GetMute())
        except _COM_ERRORS:
            raise PolicyError("the notification sounds' volume could not be read") from None

    def set_muted(self, muted: bool) -> None:
        try:
            volume = self._volume()
            if volume is None:
                raise PolicyError("the notification sounds were not found")
            volume.SetMute(1 if muted else 0, None)
        except _COM_ERRORS:
            raise PolicyError("the notification sounds could not be changed") from None


__all__ = ["WinAudioPolicy", "WinSystemSounds"]
