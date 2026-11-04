# tests/r1d_fakes.py -- the R1 builder-D fakes (evals/r1d_common.py, shared with the eval harness)
# loaded by path, like tasks_fakes.py. A plain module so test files can import it directly.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "evals" / "r1d_common.py"
_spec = importlib.util.spec_from_file_location("r1d_common", _PATH)
assert _spec is not None and _spec.loader is not None
_mod = sys.modules.get("r1d_common") or importlib.util.module_from_spec(_spec)
if "r1d_common" not in sys.modules:
    sys.modules["r1d_common"] = _mod
    _spec.loader.exec_module(_mod)

GmailFake = _mod.GmailFake
FakeTasks = _mod.FakeTasks
GroceryTasks = _mod.GroceryTasks
FamilyCalendars = _mod.FamilyCalendars
Harness = _mod.Harness
OWNER = _mod.OWNER
connector = _mod.connector
gmail_message = _mod.gmail_message
harness = _mod.harness
b64 = _mod.b64

__all__ = [
    "OWNER",
    "FakeTasks",
    "FamilyCalendars",
    "GmailFake",
    "GroceryTasks",
    "Harness",
    "b64",
    "connector",
    "gmail_message",
    "harness",
]
