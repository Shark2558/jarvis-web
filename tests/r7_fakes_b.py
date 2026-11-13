# tests/r7_fakes_b.py -- R7 Part B's fakes (docs/plans/r7-mobile.md D11-D14): a clock, a made-up
# token key, Results of each task as the browser engine makes them (plain data, no picture), and
# the Node harness that runs the console's camera door, engine and panel on a small fake DOM
# (tests/fixtures/r7/b_dom.js). Nothing here is a real person's data.
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from r7_jsguard import AROUND, D13_APIS, use_case_problems

from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.vision.store import VisionStore

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
DOM_JS = ROOT / "tests" / "fixtures" / "r7" / "b_dom.js"
ROOT_KEY = bytes(range(101, 133))  # a made-up token key: never a real one
OTHER_KEY = bytes(range(1, 33))
UID = "owner-b"
LABEL_TEXT = "MRP Rs 125.00  NET WT 500 g  BEST BEFORE 12 2027"
QR_TEXT = "https://example.com/r7-label-0042"
# 13 Nov 2026, 12:00 IST
NOON_IST = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
JS_FILES = ("console-camera.js", "console-vision.js", "console-camera-panel.js")


@dataclass
class Clock:
    at: datetime = NOON_IST

    def __call__(self) -> datetime:
        return self.at


def result(task: str, data: dict[str, Any], **over: Any) -> dict[str, Any]:
    """One Result as console-vision.js makes it (D13)."""
    base: dict[str, Any] = {
        "task": task,
        "v": 1,
        "at": int(NOON_IST.timestamp()),
        "ms": 840,
        "device": "phone",
        "ok": True,
        "data": data,
        "quality": {"light": 0.6, "sharp": 0.7},
    }
    return {**base, **over}


def text_result(text: str = LABEL_TEXT, **over: Any) -> dict[str, Any]:
    return result("text", {"text": text, "confidence": 0.91}, **over)


def code_result(value: str = QR_TEXT, **over: Any) -> dict[str, Any]:
    return result("code", {"codes": [{"format": "qr_code", "value": value}]}, **over)


def objects_result(**over: Any) -> dict[str, Any]:
    thing = {"label": "cup", "score": 0.82, "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}}
    return result("objects", {"objects": [thing]}, **over)


def quality_result(**over: Any) -> dict[str, Any]:
    return result("quality", {"light": 0.55, "sharp": 0.31}, **over)


def store(
    clock: Clock | None = None,
    *,
    key: bytes | None = ROOT_KEY,
    docs: MemoryDocs | None = None,
    keep_days: int = 90,
) -> VisionStore:
    return VisionStore(
        docs if docs is not None else MemoryDocs(),
        Keyring(key) if key is not None else None,
        now=clock or Clock(),
        keep_days=keep_days,
    )


def run_dom(script: str, **payload: Any) -> dict[str, Any]:
    """Run one scenario of tests/fixtures/r7/b_dom.js on the console's own files (or changed copies
    in `sources`); see that file for the scenarios. Raises RuntimeError without Node."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    sources = payload.pop("sources", None) or {}
    files = {
        name: sources.get(name) or (STATIC / name).read_text(encoding="utf-8") for name in JS_FILES
    }
    done = subprocess.run(
        [node, str(DOM_JS)],
        input=json.dumps({"script": script, "files": files, **payload}),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    out: dict[str, Any] = json.loads(done.stdout)
    if "crashed" in out:
        raise RuntimeError(out["crashed"])
    return out


# ---- D13: what a use case's module may never use (static; for R8-R10's modules) ---------------
# The lexer-based guard lives in tests/r7_jsguard.py (it fails closed); these names are its API.
def use_case_modules() -> list[Path]:
    """Every console script that hands a use case to the engine (`JarvisVision.use`)."""
    use = re.compile(r"(?:JarvisVision|parts\s*\.\s*vision)\s*\.\s*use\s*\(")
    return [
        path
        for path in sorted(STATIC.glob("*.js"))
        if path.name != "console-vision.js" and use.search(path.read_text(encoding="utf-8"))
    ]


CLEAN_USE_CASE = """
// a use case receives results only: R9's label scanner might look like this
JarvisVision.use({ id: 'label-scan', tasks: ['text', 'code'],
  onResult: (r, state) => ({ seen: ((state && state.seen) || 0) + 1, last: r.ok ? r.task : null }),
  summary: (state) => ({ seen: (state && state.seen) || 0 }) });
"""


__all__ = [
    "AROUND",
    "CLEAN_USE_CASE",
    "D13_APIS",
    "use_case_modules",
    "use_case_problems",
]
