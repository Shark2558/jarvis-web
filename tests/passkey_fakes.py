# tests/passkey_fakes.py — the slice 10 D software authenticator, loaded by file path from
# evals/permissions/authenticator.py (one implementation; evals never import from tests/).
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PATH = Path(__file__).resolve().parents[1] / "evals" / "permissions" / "authenticator.py"
_NAME = "jarvis_eval_soft_authenticator"


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
SoftAuthenticator = _mod.SoftAuthenticator
b64u = _mod.b64u
unb64u = _mod.unb64u

__all__ = ["SoftAuthenticator", "b64u", "unb64u"]
