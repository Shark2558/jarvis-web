# evals/realrun/guard.py
"""The hard spending stop for a real-model run (confirm-before-commit's second half).

`install` wraps the Claude provider's `complete` and `stream` for the life of one suite process:
before each call the model must be priced and the run's spending (all suites so far, kept in a
small ledger file) must be under the cap; after it, the call's metered cost is added. Crossing the
cap raises `SpendCapReached` — a BaseException, so no `except Exception` inside a suite can
swallow it — and every later call is refused before anything is sent. At most the one call that
crossed the cap is spent beyond it.

Patches only `jarvis.llm.anthropic_provider.AnthropicProvider`, the single place every paid call
of these suites goes through; it never imports the vendor SDK itself.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import ChatMessage, Completion, StreamUsage
from jarvis.llm.pricing import cost_usd, is_paid, stream_usage

EXIT_CAP = 3  # a suite stopped at the safety stop
EXIT_UNMETERED = 4  # a suite asked for a model whose price is unknown
ORIGINAL_COMPLETE = AnthropicProvider.complete
ORIGINAL_STREAM = AnthropicProvider.stream


class SpendCapReached(BaseException):  # noqa: N818 — BaseException on purpose (see module doc)
    """The run's spending reached the safety stop. Nothing more is sent."""


class UnmeteredModel(BaseException):  # noqa: N818
    """A model without a price: its spending could not be measured, so it is never called."""


class Ledger:
    """Total US dollars metered so far in this run, shared by the suite processes one after the
    other (written atomically after every call, so a crash never loses what was spent)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> float:
        try:
            v = json.loads(self.path.read_text()).get("spent_usd", 0.0)
        except (OSError, ValueError, AttributeError):
            return 0.0
        return float(v) if isinstance(v, int | float) and v >= 0 else 0.0

    def add(self, usd: float) -> float:
        total = self.read() + max(0.0, usd)
        self._write(total)
        return total

    def reset(self) -> None:
        """A new run starts at zero."""
        self._write(0.0)

    def _write(self, total: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".spend-")
        with os.fdopen(fd, "w") as f:
            json.dump({"spent_usd": round(total, 6)}, f)
        os.replace(tmp, self.path)


class SpendGuard:
    def __init__(self, *, cap_usd: float, ledger: Ledger) -> None:
        self.cap_usd = cap_usd
        self.ledger = ledger

    def before(self, model: str) -> None:
        if not is_paid(model):
            raise UnmeteredModel(model)
        if self.ledger.read() >= self.cap_usd:
            raise SpendCapReached("the safety stop was reached earlier in this run")

    def after(self, usd: float) -> None:
        if self.ledger.add(usd) > self.cap_usd:
            raise SpendCapReached("this call took spending past the safety stop")


def _chars(system: str, system_dynamic: str | None, messages: Sequence[ChatMessage]) -> int:
    return len(system) + len(system_dynamic or "") + sum(len(m.text()) for m in messages)


def install(guard: SpendGuard) -> Callable[[], None]:
    """Wrap the Claude provider; returns the function that puts the originals back."""

    async def complete(self: AnthropicProvider, **kw: Any) -> Completion:
        guard.before(kw["model"])
        c = await ORIGINAL_COMPLETE(self, **kw)
        guard.after(c.cost_usd)
        return c

    async def stream(self: AnthropicProvider, **kw: Any) -> AsyncIterator[str]:
        model = kw["model"]
        guard.before(model)
        sink = kw.get("usage") or StreamUsage()
        kw["usage"] = sink
        sent = _chars(kw["system"], kw.get("system_dynamic"), kw["messages"])
        got = 0
        try:
            async for delta in ORIGINAL_STREAM(self, **kw):
                got += len(delta)
                yield delta
        finally:
            guard.after(cost_usd(model, stream_usage(sink, input_chars=sent, output_chars=got)))

    AnthropicProvider.complete = complete  # type: ignore[method-assign]
    AnthropicProvider.stream = stream  # type: ignore[method-assign]

    def undo() -> None:
        AnthropicProvider.complete = ORIGINAL_COMPLETE  # type: ignore[method-assign]
        AnthropicProvider.stream = ORIGINAL_STREAM  # type: ignore[method-assign]

    return undo


def run_script(script: Path, args: Sequence[str], guard: SpendGuard) -> int:
    """Run one suite's script as __main__ under the guard; its exit status, or EXIT_CAP /
    EXIT_UNMETERED when the guard stopped it."""
    undo = install(guard)
    saved_argv, saved_path = list(sys.argv), list(sys.path)
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except SpendCapReached:
        return EXIT_CAP
    except UnmeteredModel:
        return EXIT_UNMETERED
    finally:
        sys.argv, sys.path[:] = saved_argv, saved_path
        undo()


__all__ = [
    "EXIT_CAP",
    "EXIT_UNMETERED",
    "Ledger",
    "SpendCapReached",
    "SpendGuard",
    "UnmeteredModel",
    "install",
    "run_script",
]
