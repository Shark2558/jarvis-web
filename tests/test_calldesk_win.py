"""R18 C: the call desk's Windows adapters, run on Linux against stand-ins for comtypes, soundcard
and the Windows DLLs. Windows itself is not here, so this pins what can be pinned: the COM
interfaces' vtable order (IPolicyConfig's SetDefaultEndpoint is slot 11 of its own methods), how
endpoints, defaults, Bluetooth and the System sounds session are read, that every COM failure
becomes a PolicyError, and how audio is converted to and from soundcard's float arrays."""

from __future__ import annotations

import ctypes
import importlib
import sys
import types
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from jarvis.calldesk.ports import AudioDeviceError, PolicyError

np = pytest.importorskip("numpy")


# ---- stand-ins ---------------------------------------------------------------------------------


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, text: str = "{00000000-0000-0000-0000-000000000000}") -> None:
        super().__init__()
        ctypes.memmove(self.data, uuid.UUID(text).bytes_le, 16)

    def text(self) -> str:
        return "{" + str(uuid.UUID(bytes_le=bytes(self.data))).upper() + "}"


class IUnknown(ctypes.c_void_p):
    _iid_ = GUID()
    _methods_: list[Any] = []


class COMError(Exception):
    def __init__(self, hresult: int) -> None:
        super().__init__(hex(hresult))
        self.hresult = hresult


def _commethod(idl: Any, restype: Any, name: str, *args: Any) -> tuple[str, str]:
    return ("COMMETHOD", name)


def _stdmethod(restype: Any, name: str, args: Any = ()) -> tuple[str, str]:
    return ("STDMETHOD", name)


class _Fn:
    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any) -> Any:
        self.calls.append(args)
        return self.result


class _Dll:
    def __init__(self) -> None:
        self.PropVariantClear = _Fn(0)
        self.CoTaskMemFree = _Fn()
        self.CreateMutexW = _Fn(1234)
        self.CloseHandle = _Fn(1)


@pytest.fixture
def win(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.SimpleNamespace]:
    comtypes = types.ModuleType("comtypes")
    comtypes.GUID = GUID  # type: ignore[attr-defined]
    comtypes.IUnknown = IUnknown  # type: ignore[attr-defined]
    comtypes.HRESULT = ctypes.c_long  # type: ignore[attr-defined]
    comtypes.COMMETHOD = _commethod  # type: ignore[attr-defined]
    comtypes.STDMETHOD = _stdmethod  # type: ignore[attr-defined]
    comtypes.COMError = COMError  # type: ignore[attr-defined]
    comtypes.CoCreateInstance = _Fn()  # type: ignore[attr-defined]
    soundcard = types.ModuleType("soundcard")
    dll = _Dll()
    last_error = {"value": 0}
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "soundcard", soundcard)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: dll, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error["value"], raising=False)
    for name in [m for m in sys.modules if m.startswith("jarvis.calldesk.win")]:
        monkeypatch.delitem(sys.modules, name)
    ca = importlib.import_module("jarvis.calldesk.win.coreaudio")
    policy = importlib.import_module("jarvis.calldesk.win.policy")
    sound = importlib.import_module("jarvis.calldesk.win.sound")
    system = importlib.import_module("jarvis.calldesk.win.system")
    yield types.SimpleNamespace(
        comtypes=comtypes,
        soundcard=soundcard,
        dll=dll,
        last_error=last_error,
        ca=ca,
        policy=policy,
        sound=sound,
        system=system,
    )
    for name in [m for m in sys.modules if m.startswith("jarvis.calldesk.win")]:
        sys.modules.pop(name, None)


def _names(cls: Any) -> list[str]:
    return [m[1] for m in cls._methods_]


# ---- the interfaces ----------------------------------------------------------------------------


def test_policy_config_vtable_order(win: types.SimpleNamespace) -> None:
    ca = win.ca
    assert _names(ca.IPolicyConfig)[10] == "SetDefaultEndpoint"
    assert len(_names(ca.IPolicyConfig)) == 12
    assert ca.IPolicyConfig._iid_.text() == "{F8679F50-850A-41CF-9C72-430F290290C8}"
    assert ca.CLSID_PolicyConfigClient.text() == "{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}"


def test_the_vista_fallback_vtable_order(win: types.SimpleNamespace) -> None:
    ca = win.ca
    assert _names(ca.IPolicyConfigVista)[9] == "SetDefaultEndpoint"
    assert len(_names(ca.IPolicyConfigVista)) == 11  # no ResetDeviceFormat slot
    assert ca.IPolicyConfigVista._iid_.text() == "{568B9108-44BF-40B4-9006-86AFE5B5A620}"


def test_core_audio_vtable_orders(win: types.SimpleNamespace) -> None:
    ca = win.ca
    assert _names(ca.IMMDeviceEnumerator)[:3] == [
        "EnumAudioEndpoints",
        "GetDefaultAudioEndpoint",
        "GetDevice",
    ]
    assert _names(ca.IMMDevice) == ["Activate", "OpenPropertyStore", "GetId", "GetState"]
    assert _names(ca.IPropertyStore)[2] == "GetValue"
    assert _names(ca.ISimpleAudioVolume) == [
        "SetMasterVolume",
        "GetMasterVolume",
        "SetMute",
        "GetMute",
    ]
    assert len(_names(ca.IAudioSessionControl)) == 9
    assert _names(ca.IAudioSessionControl2)[2:4] == ["GetProcessId", "IsSystemSoundsSession"]
    assert _names(ca.IAudioSessionManager2)[0] == "GetSessionEnumerator"
    assert ctypes.sizeof(ca.PROPVARIANT) == 24  # x64: 8 header bytes + a 16-byte value


# ---- fake COM objects --------------------------------------------------------------------------


class Store:
    def __init__(self, ca: Any, name: str, enumerator: str | None, form: int | None) -> None:
        self.ca, self.values = ca, {14: name, 24: enumerator, 0: form}
        self.keep: list[Any] = []

    def GetValue(self, ref: Any) -> Any:
        key = ref._obj
        value = self.values.get(key.pid)
        pv = self.ca.PROPVARIANT()
        if isinstance(value, str):
            buf = ctypes.create_unicode_buffer(value)
            self.keep.append(buf)
            pv.vt, pv.value.pwszVal = self.ca.VT_LPWSTR, ctypes.addressof(buf)
        elif isinstance(value, int):
            pv.vt, pv.value.ulVal = self.ca.VT_UI4, value
        return pv


class Device:
    def __init__(
        self, ca: Any, dev_id: str, name: str, enum: str | None = None, form: int | None = None
    ):
        self.ca, self.id = ca, dev_id
        self.store = Store(ca, name, enum, form)
        self.buf = ctypes.create_unicode_buffer(dev_id)

    def OpenPropertyStore(self, access: int) -> Store:
        return self.store

    def GetId(self) -> int:
        return ctypes.addressof(self.buf)


class Collection:
    def __init__(self, devices: list[Device]) -> None:
        self.devices = devices

    def GetCount(self) -> int:
        return len(self.devices)

    def Item(self, i: int) -> Device:
        return self.devices[i]


class Enumerator:
    def __init__(
        self, devices: dict[int, list[Device]], defaults: dict[tuple[int, int], Device | None]
    ):
        self.devices, self.defaults = devices, defaults
        self.fail: Exception | None = None

    def EnumAudioEndpoints(self, flow: int, mask: int) -> Collection:
        if self.fail is not None:
            raise self.fail
        return Collection(self.devices[flow])

    def GetDefaultAudioEndpoint(self, flow: int, role: int) -> Any:
        if self.fail is not None:
            raise self.fail
        device = self.defaults.get((flow, role))
        if device is None:
            raise COMError(0x80070490 - 2**32)  # E_NOTFOUND, as comtypes gives it
        return device


class PolicyConfig:
    def __init__(self, enum: Enumerator, fail: bool = False) -> None:
        self.enum, self.fail = enum, fail

    def SetDefaultEndpoint(self, device_id: str, role: int) -> None:
        if self.fail:
            raise COMError(-2147024891)  # E_ACCESSDENIED
        flow = 1
        device = next(d for d in self.enum.devices[flow] if d.id == device_id)
        self.enum.defaults[(flow, role)] = device


def _wire(
    win: types.SimpleNamespace,
    enum: Enumerator,
    policy: PolicyConfig,
    vista: PolicyConfig | None = None,
) -> None:
    def create(clsid: Any, interface: Any, ctx: int) -> Any:
        if interface is win.ca.IMMDeviceEnumerator:
            return enum
        if interface is win.ca.IPolicyConfigVista:
            if vista is None:
                raise COMError(-2147221164)  # REGDB_E_CLASSNOTREG
            return vista
        return policy

    win.comtypes.CoCreateInstance = create
    win.policy.comtypes.CoCreateInstance = create


def test_endpoints_defaults_and_switching(win: types.SimpleNamespace) -> None:
    ca = win.ca
    mic = Device(ca, "{mic}", "Microphone Array (Realtek(R) Audio)", "HDAUDIO", 4)
    cable = Device(ca, "{cable}", "CABLE Output (VB-Audio Virtual Cable)", "ROOT", 10)
    buds = Device(ca, "{bt}", "Headphones (Buds)", "BTHENUM", 3)
    enum = Enumerator({0: [buds], 1: [mic, cable]}, {(1, r): mic for r in (0, 1, 2)})
    _wire(win, enum, PolicyConfig(enum))
    policy = win.policy.WinAudioPolicy()
    caps = policy.endpoints("capture")
    assert [(e.id, e.name, e.bluetooth, e.form_factor) for e in caps] == [
        ("{mic}", "Microphone Array (Realtek(R) Audio)", False, 4),
        ("{cable}", "CABLE Output (VB-Audio Virtual Cable)", False, 10),
    ]
    (bt,) = policy.endpoints("render")
    assert bt.bluetooth and bt.form_factor == 3
    assert policy.default_id("capture", "communications") == "{mic}"
    policy.set_default("{cable}", "communications")
    assert policy.default_id("capture", "communications") == "{cable}"
    assert policy.default_id("render", "console") is None  # no speaker at all: not an error
    assert win.dll.CoTaskMemFree.calls and win.dll.PropVariantClear.calls


def test_the_older_interface_is_tried_when_the_newer_one_refuses(
    win: types.SimpleNamespace,
) -> None:
    ca = win.ca
    mic = Device(ca, "{mic}", "Microphone", "HDAUDIO", 4)
    cable = Device(ca, "{cable}", "CABLE Output (VB-Audio Virtual Cable)", "ROOT", 10)
    enum = Enumerator({0: [], 1: [mic, cable]}, {(1, r): mic for r in (0, 1, 2)})
    _wire(win, enum, PolicyConfig(enum, fail=True), vista=PolicyConfig(enum))
    win.policy.WinAudioPolicy().set_default("{cable}", "console")
    assert enum.defaults[(1, 0)] is cable


def test_com_failures_become_policy_errors(win: types.SimpleNamespace) -> None:
    enum = Enumerator({0: [], 1: []}, {})
    _wire(win, enum, PolicyConfig(enum, fail=True))
    policy = win.policy.WinAudioPolicy()
    with pytest.raises(PolicyError):
        policy.set_default("{x}", "console")
    enum.fail = COMError(-2147024809)  # E_INVALIDARG
    with pytest.raises(PolicyError):
        policy.endpoints("capture")
    with pytest.raises(PolicyError):
        policy.default_id("capture", "console")
    enum.fail = OSError("RPC server unavailable")
    with pytest.raises(PolicyError):
        policy.default_id("capture", "console")


class Volume:
    def __init__(self) -> None:
        self.mute = 0

    def GetMute(self) -> int:
        return self.mute

    def SetMute(self, value: int, context: Any) -> None:
        self.mute = value


class Control:
    def __init__(self, ca: Any, system: bool, pid: int) -> None:
        self.ca, self.system, self.pid, self.volume = ca, system, pid, Volume()

    def QueryInterface(self, iface: Any) -> Any:
        return self.volume if iface is self.ca.ISimpleAudioVolume else self

    def IsSystemSoundsSession(self) -> int:
        return 0 if self.system else 1

    def GetProcessId(self) -> int:
        return self.pid


class Sessions:
    def __init__(self, controls: list[Control]) -> None:
        self.controls = controls

    def GetCount(self) -> int:
        return len(self.controls)

    def GetSession(self, i: int) -> Control:
        return self.controls[i]


class Speaker:
    def __init__(self, sessions: Sessions) -> None:
        self.sessions = sessions

    def Activate(self, iid: Any, ctx: int, params: Any) -> Any:
        return self

    def QueryInterface(self, iface: Any) -> Any:
        return self

    def GetSessionEnumerator(self) -> Sessions:
        return self.sessions


def test_system_sounds_found_muted_and_unmuted(win: types.SimpleNamespace) -> None:
    ca = win.ca
    app_session, system = Control(ca, False, 4412), Control(ca, True, 0)
    enum = Enumerator({}, {})
    enum.defaults[(0, 0)] = Speaker(Sessions([app_session, system]))  # type: ignore[assignment]
    _wire(win, enum, PolicyConfig(enum))
    sounds = win.policy.WinSystemSounds()
    assert sounds.muted() is False
    sounds.set_muted(True)
    assert system.volume.mute == 1 and app_session.volume.mute == 0 and sounds.muted() is True
    sounds.set_muted(False)
    assert sounds.muted() is False


def test_system_sounds_missing(win: types.SimpleNamespace) -> None:
    enum = Enumerator({}, {})
    enum.defaults[(0, 0)] = Speaker(Sessions([Control(win.ca, False, 7)]))  # type: ignore[assignment]
    _wire(win, enum, PolicyConfig(enum))
    sounds = win.policy.WinSystemSounds()
    assert sounds.muted() is None
    with pytest.raises(PolicyError):
        sounds.set_muted(True)


# ---- soundcard ---------------------------------------------------------------------------------


class Recorder:
    def __init__(self, block: Any) -> None:
        self.block, self.entered, self.exited = block, False, False

    def __enter__(self) -> Recorder:
        self.entered = True
        return self

    def __exit__(self, *exc: Any) -> None:
        self.exited = True

    def record(self, numframes: int) -> Any:
        if isinstance(self.block, Exception):
            raise self.block
        return self.block


class PlayerStub(Recorder):
    def __init__(self) -> None:
        super().__init__(None)
        self.played: list[Any] = []

    def play(self, data: Any) -> None:
        self.played.append(data)


def test_loopback_asks_wasapi_for_16k_mono_and_converts_to_pcm16(
    win: types.SimpleNamespace,
) -> None:
    block = np.array([[0.5]] * 160 + [[2.0]] * 160, dtype=np.float32)
    rec = Recorder(block)
    asked: dict[str, Any] = {}

    class Loop:
        def recorder(self, samplerate: int, channels: int, blocksize: int) -> Recorder:
            asked.update(samplerate=samplerate, channels=channels, blocksize=blocksize)
            return rec

    win.soundcard.default_speaker = lambda: types.SimpleNamespace(id="{spk}")
    win.soundcard.get_microphone = lambda id, include_loopback: (
        asked.update(id=id, loop=include_loopback) or Loop()
    )
    capture = win.sound.WinSoundDevices().open_loopback()
    pcm = capture.read()
    assert asked == {
        "id": "{spk}",
        "loop": True,
        "samplerate": 16000,
        "channels": 1,
        "blocksize": 1600,
    }
    values = np.frombuffer(pcm, dtype="<i2")
    assert len(pcm) == 640 and values[0] == 16383 and values[-1] == 32767  # clipped
    capture.close()
    assert rec.exited
    rec.block = RuntimeError("Error 0x88890004")  # AUDCLNT_E_DEVICE_INVALIDATED
    with pytest.raises(AudioDeviceError):
        capture.read()


def test_cable_player_takes_pcm16_and_device_errors_are_plain(
    win: types.SimpleNamespace,
) -> None:
    stub = PlayerStub()
    asked: dict[str, Any] = {}

    class Cable:
        def player(self, samplerate: int, channels: int, blocksize: int) -> PlayerStub:
            asked.update(samplerate=samplerate, channels=channels)
            return stub

    win.soundcard.get_speaker = lambda name: asked.update(name=name) or Cable()
    player = win.sound.WinSoundDevices().open_cable_player()
    player.write(np.array([16384, -32768], dtype="<i2").tobytes())
    assert asked == {"name": "CABLE Input", "samplerate": 16000, "channels": 1}
    assert stub.played[0].shape == (2, 1) and stub.played[0][0, 0] == pytest.approx(0.5)
    player.close()

    def broken(name: str) -> Any:
        raise IndexError("no device matching 'CABLE Input'")

    win.soundcard.get_speaker = broken
    with pytest.raises(AudioDeviceError, match="CABLE Input could not be opened"):
        win.sound.WinSoundDevices().open_cable_player()


# ---- processes and one desk at a time ----------------------------------------------------------


def test_processes_from_tasklist(
    win: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    out = types.SimpleNamespace(stdout='"PhoneExperienceHost.exe","9120","Console","1","1 K"\r\n')
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: out)
    assert win.system.WinProcesses().running() == {"phoneexperiencehost.exe"}

    def slow(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired("tasklist", 10)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(OSError):
        win.system.WinProcesses().running()


def test_single_instance(win: types.SimpleNamespace) -> None:
    assert win.system.single_instance("desk") is True
    win.last_error["value"] = 183  # ERROR_ALREADY_EXISTS
    assert win.system.single_instance("desk") is False
    assert win.dll.CloseHandle.calls
    win.dll.CreateMutexW.result = 0
    assert win.system.single_instance("desk") is False


def test_init_refuses_other_systems() -> None:
    from jarvis.calldesk import win as winpkg

    if sys.platform != "win32":
        with pytest.raises(RuntimeError):
            winpkg.init()
