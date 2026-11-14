# tests/r14_fakes_d.py -- R14 Part D's shared fakes for the tests (imported bare: `from r14_fakes_d
# import ...`; CI runs plain pytest from the repository root, which is not on sys.path). ONE
# implementation: evals/r14/noai_fakes.py, loaded here by file path (evals never import from
# tests/; python review M2), under one module name so the eval and the tests share it.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PATH = Path(__file__).resolve().parents[1] / "evals" / "r14" / "noai_fakes.py"
NAME = "jarvis_eval_r14_noai_fakes"


def _load() -> ModuleType:
    if NAME in sys.modules:
        return sys.modules[NAME]
    spec = importlib.util.spec_from_file_location(NAME, _PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = mod  # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
CARDS = _mod.CARDS
D12_ROWS = _mod.D12_ROWS
GENERATIVE = _mod.GENERATIVE
TIERS = _mod.TIERS
WRITES = _mod.WRITES
Seen = _mod.Seen
fake_tool = _mod.fake_tool
no_ai_brain = _mod.no_ai_brain
no_ai_settings = _mod.no_ai_settings

__all__ = [
    "CARDS",
    "D12_ROWS",
    "GENERATIVE",
    "TIERS",
    "WRITES",
    "Seen",
    "fake_tool",
    "no_ai_brain",
    "no_ai_settings",
]
