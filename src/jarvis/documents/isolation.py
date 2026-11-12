# src/jarvis/documents/isolation.py
"""Run text extraction in a killable child process (slice 10 E, security review H1/H2).

A hostile PDF or Word file can make a parser loop, allocate hundreds of MB or recurse; inside the
server that would block a worker thread nobody can stop and could take the single Cloud Run
instance (512 MiB) down with every chat in flight. So every upload's bytes go to a fresh
`python -I` child (`jarvis.documents.worker`):

  - no inherited environment (the app's secrets never reach the process that reads hostile
    bytes), no PYTHON* variables, no user site, no script directory on the path;
  - the child caps its own CPU seconds and address space before reading anything;
  - the parent kills it at the wall-clock timeout, and whenever the upload is cancelled (the
    owner closed the tab): `finally` always kills and reaps;
  - the answer is one JSON object, size-capped and validated: anything odd is "unreadable";
    a child that died (CPU limit, out of memory) is "too slow" / "too complex". R11.1: a
    picture in the answer must be a JPEG or PNG by its first bytes, within the size cap, and
    there are at most `Limits.max_pictures` of them.

The service runs at most one child at a time (`DocumentService`).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import os
import signal
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jarvis
from jarvis.documents.extract import Extracted, Limits, Picture, too_complex, too_slow
from jarvis.documents.limits import NAME_LIMIT, PICTURE_TYPES, DocumentRejected
from jarvis.logging import get_logger

log = get_logger(__name__)

CPU_LIMIT_S = 30
MEMORY_LIMIT_BYTES = 200 * 1024 * 1024  # RLIMIT_AS: the 512 MiB instance also runs the server
WALL_TIMEOUT_S = 45.0
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
KILL_WAIT_S = 5.0
CODES = frozenset(
    {
        "unsupported",
        "empty",
        "encrypted",
        "no_text",
        "unreadable",
        "too_complex",
        "too_slow",
        "too_large",  # R11.1: a picture over its size cap
        "bad_picture",
        "unsafe_archive",  # a nested archive, a path outside the zip, a password
    }
)
_MAGIC = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}
STATUSES = frozenset({413, 415, 422})
_KILLED = frozenset(-s for s in (getattr(signal, "SIGKILL", 9), getattr(signal, "SIGXCPU", 24)))
_BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from jarvis.documents.worker import main; raise SystemExit(main(sys.argv[2:]))"
)
PKG_ROOT = str(Path(jarvis.__file__).resolve().parent.parent)


@dataclass(frozen=True)
class Sandbox:
    cpu_s: int = CPU_LIMIT_S
    memory_bytes: int = MEMORY_LIMIT_BYTES
    timeout_s: float = WALL_TIMEOUT_S


def child_env() -> dict[str, str]:
    """Nothing from the app's environment (API keys, tokens): Windows needs SYSTEMROOT only."""
    return {k: os.environ[k] for k in ("SYSTEMROOT",) if k in os.environ}


def _unreadable() -> DocumentRejected:
    return DocumentRejected(
        "unreadable", "JARVIS couldn't read this file. It may be damaged; try saving it again."
    )


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError("bad count")
    return v


def _picture(raw: Any, limits: Limits) -> Picture:
    """One picture from the child's answer, checked again: its type, its first bytes, its size."""
    if not isinstance(raw, dict):
        raise ValueError("bad picture")
    name, media, data = raw.get("name"), raw.get("media_type"), raw.get("data")
    if not isinstance(name, str) or media not in PICTURE_TYPES or not isinstance(data, str):
        raise ValueError("bad picture")
    try:
        blob = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("bad picture") from None
    if not blob.startswith(_MAGIC[media]) or len(blob) > limits.picture_max_bytes:
        raise ValueError("bad picture")
    return Picture(name=name[:NAME_LIMIT], media_type=media, data=blob)


def _extracted(p: dict[str, Any], kind: str, limits: Limits) -> Extracted:
    text, starts, truncated = p.get("text"), p.get("page_starts", []), p.get("truncated")
    if not isinstance(text, str) or not isinstance(truncated, bool) or not isinstance(starts, list):
        raise ValueError("bad shape")
    pictures = p.get("pictures") or []
    if not isinstance(pictures, list) or len(pictures) > limits.max_pictures:
        raise ValueError("bad pictures")
    page_starts = tuple(_int_or_none(s) or 0 for s in starts)
    return Extracted(
        kind=kind,
        text=text[: limits.max_chars],
        pages=_int_or_none(p.get("pages")),
        pages_total=_int_or_none(p.get("pages_total")),
        page_starts=page_starts,
        truncated=truncated or len(text) > limits.max_chars,
        sheets=_int_or_none(p.get("sheets")),
        rows=_int_or_none(p.get("rows")),
        slides=_int_or_none(p.get("slides")),
        files=_int_or_none(p.get("files")),
        skipped=_int_or_none(p.get("skipped")) or 0,
        pictures=tuple(_picture(x, limits) for x in pictures),
    )


def parse_output(out: bytes, returncode: int | None, *, kind: str, limits: Limits) -> Extracted:
    """The child's answer as an `Extracted`, or the plain refusal it (or its death) amounts to."""
    try:
        payload = json.loads(out) if out and len(out) <= MAX_OUTPUT_BYTES else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        if returncode in _KILLED:
            raise too_slow()
        raise too_complex() if returncode not in (0, None) else _unreadable()
    if payload.get("ok") is True:
        try:
            return _extracted(payload, kind, limits)
        except ValueError:
            raise _unreadable() from None
    code, detail, status = payload.get("code"), payload.get("detail"), payload.get("status")
    if code in CODES and isinstance(detail, str) and 0 < len(detail) <= 500 and status in STATUSES:
        raise DocumentRejected(code, detail, status=status)
    raise _unreadable()


async def _reap(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), KILL_WAIT_S)


async def extract_isolated(
    data: bytes, kind: str, limits: Limits, box: Sandbox | None = None
) -> Extracted:
    """`extract(data, kind, limits)`, run in a fresh limited child process."""
    sb = box or Sandbox()
    cmd = [
        sys.executable,
        "-I",
        "-c",
        _BOOT,
        PKG_ROOT,
        kind,
        json.dumps(asdict(limits)),
        str(sb.cpu_s),
        str(sb.memory_bytes),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=child_env(),
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(data), sb.timeout_s)
    except TimeoutError:
        log.warning("document worker timed out; killed", extra={"kind": kind})
        raise too_slow() from None
    finally:
        await _reap(proc)  # also on cancellation: the child never outlives its upload
    if proc.returncode != 0:
        log.warning(
            "document worker ended abnormally", extra={"kind": kind, "code": proc.returncode}
        )
    return parse_output(out, proc.returncode, kind=kind, limits=limits)


__all__ = ["Sandbox", "child_env", "extract_isolated", "parse_output"]
