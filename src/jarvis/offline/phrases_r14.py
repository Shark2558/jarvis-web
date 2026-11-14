# src/jarvis/offline/phrases_r14.py
"""No-AI pass 2 (docs/plans/r14-hardening.md D12): anchored, conservative phrase routers tried
with the other extra routers before pass 1. I0's stub: none. Part D fills `ROUTERS`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ROUTERS: tuple[Callable[..., Any], ...] = ()

__all__ = ["ROUTERS"]
