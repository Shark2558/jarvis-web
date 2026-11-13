# src/jarvis/homebridge/decoder.py
"""One JPEG decoded in a child process with a memory ceiling and a time limit (review C-sec H2,
C-code H3; the same idea as the cloud's `jarvis.documents.isolation`). Ships in the home kit.

The laptop is the only place a picture is decoded, and the decoder is native code reading bytes
someone else may have made: a 2 KB progressive JPEG can make libjpeg allocate half a gigabyte
before it reads a single pixel. Inside the bridge that would take the bridge, the heartbeat and
the camera down with it. So `decode_isolated` runs `cv2.imdecode` in a fresh `python -I` child:

- the child inherits no environment from the bridge (no Home Assistant token, no link keys):
  only one-thread settings and OpenCV's own pixel cap;
- it imports OpenCV first, then caps its own address space at what it already uses plus
  `DECODE_BUDGET_BYTES` (RLIMIT_AS) and its CPU seconds (RLIMIT_CPU), and only then reads the
  picture from stdin; an allocation past the ceiling fails inside the child;
- the parent kills it at `DECODE_TIMEOUT_S` and always reaps it;
- the answer is "OK" + height and width + exactly that many pixels, no larger than the caller's
  cap, or "NO"; anything else, and a child that died, is `PictureRefused("unreadable")`.

Standard library only here; NumPy is handed in by the caller (the engine loads it by name).
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess  # noqa: S404 - a fixed command, no shell, no input in it
import sys
import threading
from typing import Any

from jarvis.homebridge.jpeg import PictureRefused

log = logging.getLogger(__name__)

DECODE_BUDGET_BYTES = 320 * 1024 * 1024  # on top of what the child uses once OpenCV is loaded
DECODE_CPU_S = 15
DECODE_TIMEOUT_S = 20.0
PIXEL_CAP = 50_000_000  # the owner's own files (face_engine.OWN_MAX_PIXELS); OpenCV checks too
_HEAD = struct.Struct(">II")
_CHILD = r"""
import importlib, os, struct, sys
def used():
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0
def main():
    flag, max_side, budget, cpu = (int(a) for a in sys.argv[1:5])
    cv = importlib.import_module("cv2")
    np = importlib.import_module("numpy")
    cv.setNumThreads(1)
    try:
        import resource
        base = used()
        if base:
            resource.setrlimit(resource.RLIMIT_AS, (base + budget, base + budget))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    except (ImportError, ValueError, OSError):
        pass
    data = sys.stdin.buffer.read()
    try:
        img = cv.imdecode(np.frombuffer(data, dtype=np.uint8), flag)
    except BaseException:
        img = None
    out = sys.stdout.buffer
    ok = img is not None and img.ndim == 3 and img.shape[2] == 3 and img.dtype == np.uint8
    if not ok or max(img.shape[:2]) > max_side:
        out.write(b"NO")
        return 0
    out.write(b"OK" + struct.pack(">II", int(img.shape[0]), int(img.shape[1])))
    out.write(img.tobytes())
    out.flush()
    return 0
raise SystemExit(main())
"""


def child_env() -> dict[str, str]:
    """Nothing of the bridge's own environment: one thread each, and OpenCV's pixel cap."""
    env = {k: os.environ[k] for k in ("SYSTEMROOT",) if k in os.environ}
    env.update(
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        OPENCV_IO_MAX_IMAGE_PIXELS=str(PIXEL_CAP),
    )
    return env


def command(flag: int, max_side: int, budget: int, cpu_s: int) -> list[str]:
    return [sys.executable, "-I", "-c", _CHILD, str(flag), str(max_side), str(budget), str(cpu_s)]


def parse_child(out: bytes, returncode: int | None, *, max_side: int, np: Any) -> Any:
    """The decoded picture (height x width x 3, uint8), or None for anything else."""
    if returncode != 0 or len(out) < 2 + _HEAD.size or not out.startswith(b"OK"):
        return None
    high, wide = _HEAD.unpack_from(out, 2)
    if not (0 < high <= max_side and 0 < wide <= max_side):
        return None
    pixels = out[2 + _HEAD.size :]
    if len(pixels) != high * wide * 3:
        return None
    return np.frombuffer(bytearray(pixels), dtype=np.uint8).reshape(high, wide, 3)


def _run(cmd: list[str], data: bytes, cap: int, timeout_s: float) -> tuple[bytes, int | None]:
    proc = subprocess.Popen(  # noqa: S603 - our own interpreter and our own fixed script
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=child_env(),
        close_fds=True,
    )
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass  # the child stopped reading: its answer (or its death) says why
        out = proc.stdout.read(cap + 1)
        returncode = proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return out, returncode


def decode_isolated(
    data: bytes,
    flag: int,
    *,
    max_side: int,
    np: Any,
    budget: int = DECODE_BUDGET_BYTES,
    timeout_s: float = DECODE_TIMEOUT_S,
    cpu_s: int = DECODE_CPU_S,
) -> Any:
    """`cv2.imdecode(data, flag)` in a limited child, or `PictureRefused("unreadable")`."""
    cap = 2 + _HEAD.size + max_side * max_side * 3
    try:
        out, returncode = _run(command(flag, max_side, budget, cpu_s), data, cap, timeout_s)
    except OSError as exc:  # the child could not even start
        log.error("the picture decoder could not start", extra={"error": type(exc).__name__})
        raise PictureRefused("unreadable") from None
    img = parse_child(out, returncode, max_side=max_side, np=np)
    if img is None:
        log.info("a picture was refused by the decoder", extra={"exit": returncode})
        raise PictureRefused("unreadable")
    return img


__all__ = [
    "DECODE_BUDGET_BYTES",
    "DECODE_TIMEOUT_S",
    "PIXEL_CAP",
    "child_env",
    "command",
    "decode_isolated",
    "parse_child",
]
