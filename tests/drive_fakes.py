# tests/drive_fakes.py — the slice 12 fake Drive + metadata server, loaded by file path from
# evals/drive/fake_drive.py (one implementation; evals never import from tests/).
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PATH = Path(__file__).resolve().parents[1] / "evals" / "drive" / "fake_drive.py"
_NAME = "jarvis_eval_fake_drive"


def _load() -> ModuleType:
    if _NAME in sys.modules:
        return sys.modules[_NAME]
    spec = importlib.util.spec_from_file_location(_NAME, _PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = mod  # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
DOC = _mod.DOC
DOCX = _mod.DOCX
DRIVE_TOKEN = _mod.DRIVE_TOKEN
FOLDER = _mod.FOLDER
PDF = _mod.PDF
SHEET = _mod.SHEET
SHORTCUT = _mod.SHORTCUT
SLIDES = _mod.SLIDES
TOKEN_URL = _mod.TOKEN_URL
TXT = _mod.TXT
FakeDrive = _mod.FakeDrive
FakeMetadata = _mod.FakeMetadata
StaticTokens = _mod.StaticTokens

__all__ = [
    "DOC",
    "DOCX",
    "DRIVE_TOKEN",
    "FOLDER",
    "PDF",
    "SHEET",
    "SHORTCUT",
    "SLIDES",
    "TOKEN_URL",
    "TXT",
    "FakeDrive",
    "FakeMetadata",
    "StaticTokens",
]
