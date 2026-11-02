# evals/realrun/guard.py
"""The spending stop for a real-model run (confirm-before-commit's second half).

`install` wraps the Claude provider's `complete` and `stream` for the life of one suite process.

Before a call: the model must be priced, and what was spent so far (all suites, kept in this
run's ledger file) plus the most every call already in flight could still cost plus the most this
call could cost (its estimated input at full price and its whole `max_tokens` of output) must stay
within the stop; otherwise the run stops (`SpendCapReached`) before anything is sent. So calls a
suite runs at the same time count against the stop together.
After a call: its metered cost is added. A call that failed or was cut off may still have reached
the model (a timeout, a lost answer), so it is metered at its estimated input. Going past the
stop raises `SpendCapReached` too.

Fails closed: a ledger that can't be read or written stops the run, and the guard keeps its own
running total, so a ledger that vanishes or is reset mid-run never lowers what was spent.
`SpendCapReached` is a BaseException: no `except Exception` inside a suite can swallow it, and
every later call is refused anyway.

Limits (why this is a safety stop, not an exact one): input is estimated at characters / 4 × 1.3,
so a prompt that tokenizes much denser, or cache writes, can cost more than reserved; a call that
reached the model but whose answer never came is metered at its input only.

Patches only `jarvis.llm.anthropic_provider.AnthropicProvider`, the single place every paid call
of these suites goes through; it never imports the vendor SDK itself.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import runpy
import sys
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import ChatMessage, Completion, StreamUsage, ToolSpec, Usage
from jarvis.llm.pricing import cost_usd, is_paid, stream_usage
from realrun.estimate import tokens

EXIT_CAP = 3  # a suite stopped at the safety stop
EXIT_UNMETERED = 4  # a suite asked for a model whose price is unknown
ORIGINAL_COMPLETE = AnthropicProvider.complete
ORIGINAL_STREAM = AnthropicProvider.stream


class SpendCapReached(BaseException):  # noqa: N818 — BaseException on purpose (see module doc)
    """The run's spending reached the safety stop. Nothing more is sent."""


class UnmeteredModel(BaseException):  # noqa: N818
    """A model without a price: its spending could not be measured, so it is never called."""


class Ledger:
    """Total US dollars metered so far in this run, shared by its suite processes one after the
    other (written atomically after every call, so a crash never loses what was spent).
    `read` is strict: a missing file is 0 (nothing spent yet); an unreadable one raises."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> float:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return 0.0
        data = json.loads(text)
        v = data.get("spent_usd") if isinstance(data, dict) else None
        if not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            raise ValueError("spending record holds no valid amount")
        return float(v)

    def write(self, total: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".spend-")
        with os.fdopen(fd, "w") as f:
            json.dump({"spent_usd": round(total, 6)}, f)
        os.replace(tmp, self.path)

    def add(self, usd: float) -> float:
        total = self.read() + max(0.0, usd)
        self.write(total)
        return total

    def reset(self) -> None:
        """A new run starts at zero."""
        self.write(0.0)


class SpendGuard:
    def __init__(self, *, cap_usd: float, ledger: Ledger) -> None:
        self.cap_usd = cap_usd
        self.ledger = ledger
        self._total = 0.0  # never decreases: max(what this process metered, the ledger)
        self._held = 0.0  # the most the calls now in flight could still cost
        self._unrecorded = False  # a write failed: spending can no longer be kept, so stop

    def spent(self) -> float:
        if self._unrecorded:
            raise SpendCapReached("the spending record can't be written")
        try:
            recorded = self.ledger.read()
        except (OSError, ValueError) as exc:
            raise SpendCapReached("the spending record can't be read") from exc
        self._total = max(self._total, recorded)
        return self._total

    def before(self, model: str, most_usd: float) -> None:
        """Admit a call that could cost up to `most_usd`, or stop the run."""
        if not is_paid(model):
            raise UnmeteredModel(model)
        if self.spent() + self._held + most_usd > self.cap_usd:
            raise SpendCapReached("the next call could take spending past the safety stop")
        self._held += most_usd

    def after(self, usd: float, held_usd: float) -> None:
        """A call admitted with `held_usd` cost `usd`."""
        self._held = max(0.0, self._held - held_usd)
        total = self.spent() + max(0.0, usd)
        self._total = total
        try:
            self.ledger.write(total)
        except OSError as exc:
            self._unrecorded = True
            raise SpendCapReached("the spending record can't be written") from exc
        if total > self.cap_usd:
            raise SpendCapReached("this call took spending past the safety stop")


def _input_chars(kw: Mapping[str, Any]) -> int:
    messages: Sequence[ChatMessage] = kw["messages"]
    specs: Sequence[ToolSpec] = kw.get("tools") or ()
    return (
        len(kw["system"])
        + len(kw.get("system_dynamic") or "")
        + sum(len(m.text()) for m in messages)
        + sum(len(t.model_dump_json()) for t in specs)
    )


def _input_usd(model: str, chars: int) -> float:
    return cost_usd(model, Usage(input_tokens=tokens(chars)))


def _most_usd(model: str, chars: int, max_tokens: int) -> float:
    return cost_usd(model, Usage(input_tokens=tokens(chars), output_tokens=max_tokens))


def install(guard: SpendGuard) -> Callable[[], None]:
    """Wrap the Claude provider; returns the function that puts the originals back."""

    async def complete(self: AnthropicProvider, **kw: Any) -> Completion:
        model, chars = kw["model"], _input_chars(kw)
        held = _most_usd(model, chars, kw["max_tokens"])
        guard.before(model, held)
        try:
            c = await ORIGINAL_COMPLETE(self, **kw)
        except (Exception, asyncio.CancelledError):  # it may have reached the model
            guard.after(_input_usd(model, chars), held)
            raise
        guard.after(c.cost_usd, held)
        return c

    async def stream(self: AnthropicProvider, **kw: Any) -> AsyncIterator[str]:
        model, chars = kw["model"], _input_chars(kw)
        held = _most_usd(model, chars, kw["max_tokens"])
        guard.before(model, held)
        sink = kw.get("usage") or StreamUsage()
        kw["usage"] = sink
        got = 0
        try:
            async for delta in ORIGINAL_STREAM(self, **kw):
                got += len(delta)
                yield delta
        finally:  # finished, failed or cut off: the vendor's counts, else the estimate
            usage = stream_usage(sink, input_chars=chars, output_chars=got)
            guard.after(cost_usd(model, usage), held)

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
