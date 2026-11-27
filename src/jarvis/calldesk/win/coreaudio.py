# src/jarvis/calldesk/win/coreaudio.py
"""Windows Core Audio interfaces for comtypes (Windows only; R18 C).

Documented: IMMDeviceEnumerator, IMMDeviceCollection, IMMDevice, IPropertyStore (mmdeviceapi.h,
propsys.h) and the audio session API (audiopolicy.h: IAudioSessionManager2, the session enumerator
and controls, ISimpleAudioVolume). Undocumented but stable since Windows 7 and used the same way by
the common open tools that switch default devices: IPolicyConfig (CLSID 870af99c-...,
IID f8679f50-...), whose `SetDefaultEndpoint(id, role)` is what Sound settings' "Set as Default
Device" calls. The vtable order below must match Windows' exactly: the slots the desk doesn't call
are declared with placeholder argument types only.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, Union, c_float, c_int, c_ulonglong, c_ushort, c_void_p
from ctypes.wintypes import BOOL, DWORD, LPCWSTR, UINT

from comtypes import COMMETHOD, GUID, HRESULT, STDMETHOD, IUnknown

CLSCTX_ALL = 0x17
DEVICE_STATE_ACTIVE = 0x1
STGM_READ = 0x0
E_RENDER, E_CAPTURE = 0, 1
ROLE_CONSOLE, ROLE_MULTIMEDIA, ROLE_COMMUNICATIONS = 0, 1, 2
VT_EMPTY, VT_UI4, VT_LPWSTR = 0, 19, 31

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
CLSID_PolicyConfigClient = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
CLSID_PolicyConfigVistaClient = GUID("{294935CE-F637-4E7C-A41B-AB255460B862}")


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


def _key(fmtid: str, pid: int) -> PROPERTYKEY:
    return PROPERTYKEY(GUID(fmtid), pid)


PKEY_Device_FriendlyName = _key("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)
PKEY_Device_EnumeratorName = _key("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 24)
PKEY_AudioEndpoint_FormFactor = _key("{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}", 0)


class _PropValue(Union):
    _fields_ = [("ulVal", DWORD), ("pwszVal", c_void_p), ("_pad", c_ulonglong * 2)]


class PROPVARIANT(Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("value", _PropValue),
    ]


_ole32 = getattr(ctypes, "WinDLL")("ole32")  # noqa: B009 - Windows only (typed on any OS)
PropVariantClear = _ole32.PropVariantClear
PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
PropVariantClear.restype = HRESULT
CoTaskMemFree = _ole32.CoTaskMemFree
CoTaskMemFree.argtypes = [c_void_p]
CoTaskMemFree.restype = None


class IPropertyStore(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "cProps")),
        COMMETHOD(
            [], HRESULT, "GetAt", (["in"], DWORD, "iProp"), (["out"], POINTER(PROPERTYKEY), "pkey")
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetValue",
            (["in"], POINTER(PROPERTYKEY), "key"),
            (["out"], POINTER(PROPVARIANT), "pv"),
        ),
        STDMETHOD(HRESULT, "SetValue", [POINTER(PROPERTYKEY), POINTER(PROPVARIANT)]),
        STDMETHOD(HRESULT, "Commit", []),
    ]


class IMMDevice(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], POINTER(GUID), "iid"),
            (["in"], DWORD, "dwClsCtx"),
            (["in"], c_void_p, "pActivationParams"),
            (["out"], POINTER(POINTER(IUnknown)), "ppInterface"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OpenPropertyStore",
            (["in"], DWORD, "stgmAccess"),
            (["out"], POINTER(POINTER(IPropertyStore)), "ppProperties"),
        ),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
    ]


class IMMDeviceCollection(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(UINT), "pcDevices")),
        COMMETHOD(
            [],
            HRESULT,
            "Item",
            (["in"], UINT, "nDevice"),
            (["out"], POINTER(POINTER(IMMDevice)), "ppDevice"),
        ),
    ]


class IMMDeviceEnumerator(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "EnumAudioEndpoints",
            (["in"], DWORD, "dataFlow"),
            (["in"], DWORD, "dwStateMask"),
            (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], DWORD, "dataFlow"),
            (["in"], DWORD, "role"),
            (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevice",
            (["in"], LPCWSTR, "pwstrId"),
            (["out"], POINTER(POINTER(IMMDevice)), "ppDevice"),
        ),
        STDMETHOD(HRESULT, "RegisterEndpointNotificationCallback", [c_void_p]),
        STDMETHOD(HRESULT, "UnregisterEndpointNotificationCallback", [c_void_p]),
    ]


class IPolicyConfig(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetMixFormat", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetDeviceFormat", [LPCWSTR, c_int, c_void_p]),
        STDMETHOD(HRESULT, "ResetDeviceFormat", [LPCWSTR]),
        STDMETHOD(HRESULT, "SetDeviceFormat", [LPCWSTR, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "GetProcessingPeriod", [LPCWSTR, c_int, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "SetProcessingPeriod", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetShareMode", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "SetShareMode", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetPropertyValue", [LPCWSTR, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "SetPropertyValue", [LPCWSTR, c_void_p, c_void_p]),
        COMMETHOD(
            [],
            HRESULT,
            "SetDefaultEndpoint",
            (["in"], LPCWSTR, "wszDeviceId"),
            (["in"], DWORD, "eRole"),
        ),
        STDMETHOD(HRESULT, "SetEndpointVisibility", [LPCWSTR, c_int]),
    ]


class IPolicyConfigVista(IUnknown):  # type: ignore[misc]
    """The older interface (no ResetDeviceFormat slot): the fallback when IPolicyConfig is not
    there or refuses, as the common device-switching tools do."""

    _iid_ = GUID("{568B9108-44BF-40B4-9006-86AFE5B5A620}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetMixFormat", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetDeviceFormat", [LPCWSTR, c_int, c_void_p]),
        STDMETHOD(HRESULT, "SetDeviceFormat", [LPCWSTR, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "GetProcessingPeriod", [LPCWSTR, c_int, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "SetProcessingPeriod", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetShareMode", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "SetShareMode", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetPropertyValue", [LPCWSTR, c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "SetPropertyValue", [LPCWSTR, c_void_p, c_void_p]),
        COMMETHOD(
            [],
            HRESULT,
            "SetDefaultEndpoint",
            (["in"], LPCWSTR, "wszDeviceId"),
            (["in"], DWORD, "eRole"),
        ),
        STDMETHOD(HRESULT, "SetEndpointVisibility", [LPCWSTR, c_int]),
    ]


class ISimpleAudioVolume(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{87CE5498-68D6-44E5-9215-6F24A2F2ED5A}")
    _methods_ = [
        STDMETHOD(HRESULT, "SetMasterVolume", [c_float, POINTER(GUID)]),
        COMMETHOD([], HRESULT, "GetMasterVolume", (["out"], POINTER(c_float), "pfLevel")),
        COMMETHOD(
            [],
            HRESULT,
            "SetMute",
            (["in"], BOOL, "bMute"),
            (["in"], POINTER(GUID), "EventContext"),
        ),
        COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
    ]


class IAudioSessionControl(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetState", [c_void_p]),
        STDMETHOD(HRESULT, "GetDisplayName", [c_void_p]),
        STDMETHOD(HRESULT, "SetDisplayName", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetIconPath", [c_void_p]),
        STDMETHOD(HRESULT, "SetIconPath", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetGroupingParam", [c_void_p]),
        STDMETHOD(HRESULT, "SetGroupingParam", [c_void_p, c_void_p]),
        STDMETHOD(HRESULT, "RegisterAudioSessionNotification", [c_void_p]),
        STDMETHOD(HRESULT, "UnregisterAudioSessionNotification", [c_void_p]),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetSessionIdentifier", [c_void_p]),
        STDMETHOD(HRESULT, "GetSessionInstanceIdentifier", [c_void_p]),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(DWORD), "pRetVal")),
        STDMETHOD(HRESULT, "IsSystemSoundsSession", []),  # S_OK (0) for the System sounds one
        STDMETHOD(HRESULT, "SetDuckingPreference", [BOOL]),
    ]


class IAudioSessionEnumerator(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "SessionCount")),
        COMMETHOD(
            [],
            HRESULT,
            "GetSession",
            (["in"], c_int, "SessionCount"),
            (["out"], POINTER(POINTER(IAudioSessionControl)), "Session"),
        ),
    ]


class IAudioSessionManager(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{BFA971F1-4D5E-40BB-935E-967039BFBEE4}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetAudioSessionControl", [POINTER(GUID), DWORD, c_void_p]),
        STDMETHOD(HRESULT, "GetSimpleAudioVolume", [POINTER(GUID), DWORD, c_void_p]),
    ]


class IAudioSessionManager2(IAudioSessionManager):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "GetSessionEnumerator",
            (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "SessionEnum"),
        ),
        STDMETHOD(HRESULT, "RegisterSessionNotification", [c_void_p]),
        STDMETHOD(HRESULT, "UnregisterSessionNotification", [c_void_p]),
        STDMETHOD(HRESULT, "RegisterDuckNotification", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "UnregisterDuckNotification", [c_void_p]),
    ]


def read_text(store: object, key: PROPERTYKEY) -> str | None:
    """A string property (VT_LPWSTR), or None."""
    pv = store.GetValue(ctypes.byref(key))  # type: ignore[attr-defined]
    try:
        if pv.vt == VT_LPWSTR and pv.value.pwszVal:
            return ctypes.wstring_at(pv.value.pwszVal)
        return None
    finally:
        PropVariantClear(ctypes.byref(pv))


def read_uint(store: object, key: PROPERTYKEY) -> int | None:
    """A 32-bit unsigned property (VT_UI4), or None."""
    pv = store.GetValue(ctypes.byref(key))  # type: ignore[attr-defined]
    try:
        return int(pv.value.ulVal) if pv.vt == VT_UI4 else None
    finally:
        PropVariantClear(ctypes.byref(pv))


def device_id(device: object) -> str:
    ptr = device.GetId()  # type: ignore[attr-defined]
    try:
        return ctypes.wstring_at(ptr)
    finally:
        CoTaskMemFree(ptr)
