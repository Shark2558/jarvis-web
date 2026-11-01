# src/jarvis/recall/gate.py
"""The one privacy switch for memory (slice 8 D6): a brain that may train on content never sees
the notes block and never triggers learning. Memory tools reach only brains that get tools at
all (`Brain._tools_on`, the same `tools_allowed`). Callers use `gate.memory_allowed(spec)` (the
module attribute) so the eval's negative control can switch it off and prove the suite sees it.
"""

from __future__ import annotations

from jarvis.llm.brains import BrainSpec


def memory_allowed(spec: BrainSpec) -> bool:
    return spec.tools_allowed


__all__ = ["memory_allowed"]
