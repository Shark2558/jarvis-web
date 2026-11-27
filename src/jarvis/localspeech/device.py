# src/jarvis/localspeech/device.py
"""Which device the kit's engines run on, and how much memory is free (R5.2 V1; plan risk 1: a
4 GB graphics card can't hold every engine at once). Kit-safe: the standard library only.

The graphics card is found with NVIDIA's own `nvidia-smi` (installed with its driver), so no
package is needed to ask; no card, or no answer within a few seconds, means the CPU.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.localspeech.protocol import Device

log = logging.getLogger(__name__)

SMI_TIMEOUT_S: Final = 4.0
SMI_ARGS: Final = (
    "nvidia-smi",
    "--query-gpu=memory.free,memory.total,name",
    "--format=csv,noheader,nounits",
)
MB: Final = 1024 * 1024

Runner = Callable[[Sequence[str]], str]  # runs a program, returns what it printed


@dataclass(frozen=True)
class DeviceInfo:
    device: Device
    gpu_free_mb: int | None = None
    gpu_total_mb: int | None = None
    gpu_name: str = ""


def _run(args: Sequence[str]) -> str:
    done = subprocess.run(  # noqa: S603 - a fixed argument list, no shell
        list(args), capture_output=True, text=True, timeout=SMI_TIMEOUT_S, check=True
    )
    return done.stdout


def parse_smi(text: str) -> DeviceInfo | None:
    """The first card in `nvidia-smi`'s CSV answer, or None when it isn't one."""
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            free, total = int(float(parts[0])), int(float(parts[1]))
        except ValueError:
            continue
        if free < 0 or total <= 0:
            continue
        name = parts[2][:60] if len(parts) > 2 else ""
        return DeviceInfo(Device.CUDA, gpu_free_mb=free, gpu_total_mb=total, gpu_name=name)
    return None


def detect(preference: str = "auto", runner: Runner = _run) -> DeviceInfo:
    """The graphics card when there is one (and `preference` allows it), else the CPU."""
    if preference == "cpu":
        return DeviceInfo(Device.CPU)
    try:
        found = parse_smi(runner(SMI_ARGS))
    except (OSError, subprocess.SubprocessError, ValueError):
        found = None
    if found is None:
        if preference == "cuda":
            log.warning("no NVIDIA graphics card answered; the kit uses the CPU")
        return DeviceInfo(Device.CPU)
    return found


def gpu_free_mb(runner: Runner = _run) -> int | None:
    try:
        found = parse_smi(runner(SMI_ARGS))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return found.gpu_free_mb if found else None


class _MemoryStatus(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes' own declaration
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_free_mb() -> int:
    """Free memory in MB (0 when the system won't say)."""
    try:
        if sys.platform == "win32":
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined,unused-ignore]
                return int(status.ullAvailPhys // MB)
            return 0
        pages = os.sysconf("SC_AVPHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * size // MB)
    except (OSError, ValueError, AttributeError):
        return 0


__all__ = ["DeviceInfo", "detect", "gpu_free_mb", "parse_smi", "ram_free_mb"]
