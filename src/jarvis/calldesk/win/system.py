# src/jarvis/calldesk/win/system.py
"""Phone Link's process and "one desk at a time" (Windows only; R18 C)."""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

from jarvis.calldesk.checks import parse_tasklist

_ERROR_ALREADY_EXISTS = 183
_CREATE_NO_WINDOW = 0x08000000
_TASKLIST_TIMEOUT_S = 10
_held: list[int] = []  # mutex handles kept for the life of the process


class WinProcesses:
    def running(self) -> frozenset[str]:
        """Image names from Windows' own `tasklist` (no extra package); OSError on failure."""
        try:
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=_TASKLIST_TIMEOUT_S,
                check=False,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise OSError("tasklist did not answer") from None
        return parse_tasklist(out.stdout)


def single_instance(role: str) -> bool:
    """True when this is the only `role` process ("desk" or "watchdog") of this Windows user."""
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)  # noqa: B009
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, f"Local\\JARVIS-CallDesk-{role}")
    if not handle:
        return False
    if getattr(ctypes, "get_last_error")() == _ERROR_ALREADY_EXISTS:  # noqa: B009
        kernel32.CloseHandle(handle)
        return False
    _held.append(handle)
    return True


__all__ = ["WinProcesses", "single_instance"]
