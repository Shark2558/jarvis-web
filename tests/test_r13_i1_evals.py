# tests/test_r13_i1_evals.py
"""I1 fixer: the evals' own helpers (a capture that cannot match by chance)."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _load_r7_body() -> ModuleType:
    for p in (ROOT / "evals" / "r7", ROOT / "evals", ROOT / "tests", ROOT / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location("r7_body_for_test", ROOT / "evals/r7/body.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _record(msg: str, **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)
    rec.created, rec.msecs, rec.relativeCreated = 1763000000.131, 131.7, 3131.5
    rec.thread = 131
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_the_r7_capture_keeps_the_message_and_fields_but_not_the_clock_numbers() -> None:
    cap = _load_r7_body().Capture()
    cap.emit(_record("saved", days=4, heart={"max": 8123}))
    row = cap.rows[0]
    assert "131" not in row  # a timestamp, a thread id or a millisecond is not a value
    assert "saved" in row and "8123" in row  # but the message and its own fields are searched


def test_nothing_in_the_product_calls_the_catalogs_own_correct() -> None:
    """Code review LOW: `CatalogStore.correct` would skip B's reconcile of loads, batches and
    the review queue, so every product path corrects through B (`LaundryFlows.correct`)."""
    import re

    callers = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if re.search(r"\b(store|self\.store|self\._s)\.correct\(", p.read_text("utf-8"))
    ]
    assert callers == []


def test_loading_the_r13_suites_leaves_sys_path_alone() -> None:
    """Code review LOW: `sys.path.insert(0, evals/r13)` made `catalog`, `styling`, `phone`,
    `contract` and `run` top-level names that win over anything imported later."""
    before = list(sys.path)
    for name in ("e2e", "needles"):
        spec = importlib.util.spec_from_file_location(
            f"r13_probe_{name}", ROOT / "evals" / "r13" / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert str(ROOT / "evals" / "r13") not in sys.path
    assert [p for p in sys.path if p not in before and p.endswith("evals/r13")] == []
