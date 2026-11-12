# src/jarvis/buildbook/gen/layers.py
"""R6 D2: every `src/jarvis/*` package (and top-level module) sits in exactly one layer of the
reference architecture (`model.LAYERS`: L1-L8, X cross-cutting). A package missing here fails
the build, so `python -m jarvis.buildbook.gen --check` (the CI gate) catches a new one; a test
fails on a name that no longer exists. Where a package's docstring names its layer, this agrees.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from jarvis.buildbook.gen.repo import GenError

LAYER_OF: Mapping[str, str] = MappingProxyType(
    {
        # L1 User Interaction: where the owner reaches JARVIS
        "api": "L1",
        "cli": "L1",
        "telegram": "L1",
        # L2 Input Processing: speech, documents, vision at the edge
        "voice": "L2",
        "documents": "L2",
        "faces": "L2",
        "understand": "L2",  # R11.1 B: what was heard, and what it is understood as
        "facegroups": "L2",  # R11.1 C: unnamed face groups from the laptop (ids and counts only)
        # L3 Context & Orchestration: sessions, long-term memory, scheduled work, undo
        "memory": "L3",
        "recall": "L3",
        "ticks": "L3",
        "undo": "L3",
        # L4 Core Reasoning Engine
        "core": "L4",
        "llm": "L4",
        "offline": "L4",
        # L5 Skills & Capabilities
        "brief": "L5",
        "web": "L5",
        "people": "L5",
        "whatsapp": "L5",
        "kb": "L5",
        "belongings": "L5",
        "groceries": "L5",
        "family": "L5",
        "packages": "L5",
        "helpers": "L5",  # R11: the free proactive helpers (one package, four parts)
        "series": "L5",  # R11.1 A: a followed plan of sessions (check-ins, re-planning)
        "picture": "L5",  # R11.1 D: research a picture of a thing, place, label or logo
        # L6 Integration & Tools
        "tools": "L6",
        "integrations": "L6",
        "contacts": "L6",
        "drive": "L6",
        "places": "L6",
        "media": "L6",
        "photos": "L6",
        "home": "L6",
        "homebridge": "L6",
        "camera": "L6",
        # L7 Data & Persistence
        "storage": "L7",
        "vault": "L7",
        "vault_inbox": "L7",
        "quota": "L7",
        # L8 Response & Output
        "alerts": "L8",
        "notify": "L8",
        "webpush": "L8",
        "activity": "L8",
        # X cross-cutting: configuration, keys, security, cost, health, privacy, the book
        "config": "X",
        "about": "X",  # R6.1 D4: version + build date
        "logging": "X",
        "keyring": "X",
        "permissions": "X",
        "privacy": "X",
        "billing": "X",
        "vitals": "X",
        "health": "X",
        "buildbook": "X",
        "fixes": "X",  # R11.1: the plug-in contract the four parts of the release share
    }
)


def layer_for(name: str, table: Mapping[str, str] = LAYER_OF) -> str:
    try:
        return table[name]
    except KeyError:
        raise GenError(
            f"src/jarvis/{name} has no layer: add it to buildbook/gen/layers.py"
        ) from None


__all__ = ["LAYER_OF", "layer_for"]
