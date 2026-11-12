# src/jarvis/documents/worker.py
"""The extraction worker: one child process per upload (security review H1/H2).

Started by `jarvis.documents.isolation` as `python -I -c <boot> <src> <kind> <limits> <cpu_s>
<memory_bytes>` with no inherited environment. Before it reads a single byte of the file it caps
itself: RLIMIT_CPU (the kernel stops it past the CPU seconds) and RLIMIT_AS (allocations past the
address-space cap fail: MemoryError → "too complex"). Setting the limits here rather than in a
`preexec_fn` keeps the parent free of fork-time hooks, which are unsafe in a threaded server;
where `resource` or a limit is unavailable it carries on, and the parent's wall-clock kill still
applies. It reads the file from stdin, writes one JSON object to stdout, and imports nothing from
the app but `jarvis.documents.limits` and `extract` (no settings, no vendor SDKs, no secrets).

    stdout   {"ok": true, "text", "pages", "pages_total", "page_starts", "truncated",
              "sheets", "rows", "slides", "files", "skipped",        (R11.1: counts, or null)
              "pictures": [{"name", "media_type", "data": base64}]}  (checked, metadata removed)
             {"ok": false, "code", "detail", "status"}
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any


def _limit_self(cpu_s: int, memory_bytes: int) -> None:
    try:
        import resource
    except ImportError:  # not POSIX: only the parent's wall-clock kill applies
        return
    wanted = (
        (getattr(resource, "RLIMIT_CPU", None), cpu_s, cpu_s + 1),  # soft → SIGXCPU, hard → KILL
        (getattr(resource, "RLIMIT_AS", None), memory_bytes, memory_bytes),
    )
    for which, soft, hard in wanted:
        if which is None or soft <= 0:
            continue
        try:
            resource.setrlimit(which, (soft, hard))
        except (ValueError, OSError):  # a stricter limit already holds, or not supported here
            continue


# Optional imports of the readers that the child never needs. openpyxl imports numpy when it is
# installed, and numpy's OpenBLAS reserves address space per CPU: on a 4-CPU machine that alone
# passed the RLIMIT_AS cap, and the child died before reading (CI run 107). Kept out, a reader's
# own `try: import numpy` takes its ImportError path, on every machine alike.
UNNEEDED_MODULES = ("numpy", "pandas")


def _keep_out_unneeded() -> None:
    for name in UNNEEDED_MODULES:
        sys.modules.setdefault(name, None)  # type: ignore[arg-type]  # None: import fails


def _refusal(code: str, detail: str, status: int) -> dict[str, Any]:
    return {"ok": False, "code": code, "detail": detail, "status": status}


def main(argv: list[str]) -> int:
    kind, limits_json, cpu_s, memory_bytes = argv[0], argv[1], int(argv[2]), int(argv[3])
    _limit_self(cpu_s, memory_bytes)
    _keep_out_unneeded()
    from jarvis.documents.extract import Limits, extract, too_complex
    from jarvis.documents.limits import MAX_FILE_BYTES, DocumentRejected

    data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    payload: dict[str, Any]
    try:
        out = extract(data, kind, Limits(**json.loads(limits_json)))
        payload = {
            "ok": True,
            "text": out.text,
            "pages": out.pages,
            "pages_total": out.pages_total,
            "page_starts": list(out.page_starts),
            "truncated": out.truncated,
            "sheets": out.sheets,
            "rows": out.rows,
            "slides": out.slides,
            "files": out.files,
            "skipped": out.skipped,
            "pictures": [
                {
                    "name": pic.name,
                    "media_type": pic.media_type,
                    "data": base64.b64encode(pic.data).decode("ascii"),
                }
                for pic in out.pictures
            ],
        }
    except DocumentRejected as exc:
        payload = _refusal(exc.code, str(exc), exc.status)
    except MemoryError:
        e = too_complex()
        payload = _refusal(e.code, str(e), e.status)
    except Exception:  # noqa: BLE001 — anything else a hostile file causes
        payload = _refusal("unreadable", "JARVIS couldn't read this file.", 422)
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
