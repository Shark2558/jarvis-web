# src/jarvis/calldesk/win/__init__.py
"""The call desk's Windows parts (R18 C): Core Audio through comtypes (endpoints, default roles via
IPolicyConfig, the System sounds session), soundcard's WASAPI loopback and playback, Phone Link's
process, one desk at a time. Imported only on Windows, only by `jarvis.calldesk.app`; nothing in
this package runs in the repository's tests (they use fakes of `jarvis.calldesk.ports`).

`init()` must run on the main thread before any worker thread starts: it joins COM's
multithreaded apartment (`sys.coinit_flags = 0` before comtypes is imported; soundcard does the
same), so the worker threads share it for the life of the process.
"""

from __future__ import annotations

import sys


def init() -> None:
    if sys.platform != "win32":
        raise RuntimeError("the call desk runs on Windows only")
    setattr(sys, "coinit_flags", 0)  # noqa: B010 - COINIT_MULTITHREADED, read by comtypes
    import comtypes  # noqa: F401
    import soundcard  # noqa: F401


__all__ = ["init"]
