# tests/r63_fake_brains.py -- R6.3 I0 seam 12 (docs/plans/r6-3-book-content.md D1, D5, D8, D10):
# scripted writer brains through the REAL `BrainRegistry`. Imported bare (`from r63_fake_brains
# import ...`); CI runs plain `pytest` from the repository root, which is not on sys.path.
#
# - `ScriptedWriter`: an `LLMProvider` whose `stream` plays `Step`s in order (text in chunks, the
#   vendor's token counts and stop reason, a failure before or after some text, a slow chunk).
#   `no_retry()` is the view `jarvis.llm.write` streams through (D1, M1): it shares the script and
#   the call log and says `retries_off`. `complete` is never the writer's path and fails loudly.
# - `claude_like()` (paid, the price table's Sonnet 5.5) and `gemini_like()` (free, trains on
#   content) and `registry(...)`: both brains in one real `BrainRegistry`, with an optional ready
#   laptop fallback that records any call (the writer must never make one).
# - Canned drafts in the wire format of `buildbook.writer.model` (five `## <heading>` blocks):
#   `GOOD_DRAFT` passes every check against `r63_fakes.FIXTURE_FACTS`; `FAKE_PATH_DRAFT`,
#   `TYPED_NUMBER_DRAFT`, `EMAIL_DRAFT`, `INVENTED_DRAFT`, `PLANNED_OUTSIDE_DRAFT`,
#   `UNVERIFIED_DRAFT` each break exactly one check (D10 (1)-(5)).
# No real model is ever called: there is no network here.
from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from jarvis.config import Settings
from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMError,
    LLMTransientError,
    LLMUnreachable,
    StreamUsage,
    ToolSpec,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier

CLAUDE_TIERS = {
    ModelTier.FAST: "claude-haiku-5-5",
    ModelTier.BALANCED: "claude-sonnet-5-5",
    ModelTier.STRONG: "claude-opus-5-5",
}
GEMINI_TIERS = {
    ModelTier.FAST: "gemini-3.5-flash-lite",
    ModelTier.BALANCED: "gemini-3.8-flash",
    ModelTier.STRONG: "gemini-3.8-flash",
}


@dataclass(frozen=True)
class Step:
    """One scripted stream. `fail` is raised after `fail_after` chunks (0: before any text)."""

    text: str = ""
    chunks: int = 4
    input_tokens: int | None = 20_000  # None: the vendor reports nothing (Gemini's free tier)
    output_tokens: int | None = None  # None: len(text) // 4
    stop: str | None = "end_turn"
    fail: LLMError | None = None
    fail_after: int = 0
    delay_s: float = 0.0  # before each chunk (a slow stream)


@dataclass
class Call:
    model: str
    max_tokens: int
    system: str
    system_dynamic: str | None
    messages: list[ChatMessage]
    retries_off: bool


def _pieces(text: str, n: int) -> list[str]:
    if not text:
        return []
    size = max(1, -(-len(text) // max(1, n)))
    return [text[i : i + size] for i in range(0, len(text), size)]


@dataclass
class ScriptedWriter:
    name: str = "anthropic"
    steps: list[Step] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    retries_off: bool = False
    vision: bool = False

    def push(self, *steps: Step) -> ScriptedWriter:
        self.steps.extend(steps)
        return self

    def no_retry(self) -> ScriptedWriter:
        view = copy.copy(self)  # shares `steps` and `calls` (the same lists)
        view.retries_off = True
        return view

    async def complete(self, **kw: Any) -> Completion:
        raise AssertionError("the writer streams; it never calls complete()")

    async def stream(
        self,
        *,
        system: str,
        system_dynamic: str | None = None,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int,
        effort: Effort | None = None,
        usage: StreamUsage | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[str]:
        assert tools is None, "the writer never sends tools"
        self.calls.append(
            Call(model, max_tokens, system, system_dynamic, list(messages), self.retries_off)
        )
        step = self.steps.pop(0) if self.steps else Step(text=GOOD_DRAFT)
        pieces = _pieces(step.text, step.chunks)
        if step.fail is not None and step.fail_after == 0:
            raise step.fail
        if usage is not None and step.input_tokens is not None:
            usage.started(
                input_tokens=step.input_tokens,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
        for i, piece in enumerate(pieces):
            if step.delay_s:
                await asyncio.sleep(step.delay_s)
            if step.fail is not None and i == step.fail_after:
                raise step.fail
            yield piece
        if usage is not None and step.input_tokens is not None:
            out = step.output_tokens if step.output_tokens is not None else len(step.text) // 4
            usage.finished(output_tokens=out)
        if usage is not None:
            usage.stop_reason = step.stop


def busy() -> Step:
    """A 429 / 529 before any text: never retried inside the call, the hold released (M1)."""
    return Step(fail=LLMTransientError("the AI provider is busy or rate-limited"))


def down() -> Step:
    """A 5xx / no connection before any text: the page waits, never the laptop (D1)."""
    return Step(fail=LLMUnreachable("the AI provider could not be reached"))


def cut(text: str, after: int = 2) -> Step:
    """A stream that drops after `after` chunks: reported cut, settled at its usage (H7)."""
    return Step(text=text, chunks=6, fail=LLMUnreachable("dropped"), fail_after=after)


def length_stop(text: str) -> Step:
    """Stopped at `max_tokens` (L10): complete is False."""
    return Step(text=text, stop="max_tokens")


def slow(text: str, seconds: float) -> Step:
    """A stream that takes about `seconds` (H7's slow-stream case, scaled down in tests)."""
    return Step(text=text, chunks=5, delay_s=seconds / 5)


class RecordingLaptop:
    """A READY fallback brain that records every call: the writer must never make one (D1)."""

    def __init__(self) -> None:
        self.calls = 0

    async def ready(self) -> bool:
        return True

    async def cloud_ok(self) -> None:
        return None

    async def complete(self, **kw: Any) -> Completion:
        self.calls += 1
        raise AssertionError("the writer called the laptop")

    async def stream(self, **kw: Any) -> AsyncIterator[str]:
        self.calls += 1
        raise AssertionError("the writer called the laptop")
        yield ""  # pragma: no cover - makes this an async generator


def claude_like(*steps: Step) -> BrainSpec:
    return BrainSpec(
        id="anthropic",
        label="Claude",
        provider=ScriptedWriter("anthropic").push(*steps),
        tiers=dict(CLAUDE_TIERS),
    )


def gemini_like(*steps: Step) -> BrainSpec:
    return BrainSpec(
        id="gemini",
        label="Gemini (free)",
        provider=ScriptedWriter("gemini").push(*steps),
        tiers=dict(GEMINI_TIERS),
        trains_on_content=True,
    )


def paid_gemini() -> BrainSpec:
    """A paid-tier Gemini: not training, still $0 in the price table: never offered (M2)."""
    return BrainSpec(
        id="gemini", label="Gemini", provider=ScriptedWriter("gemini"), tiers=dict(GEMINI_TIERS)
    )


def custom_brain() -> BrainSpec:
    """The OpenAI-compatible brain, its model not in the price table: never offered (M2)."""
    tiers = dict.fromkeys(ModelTier, "llama-local-70b")
    return BrainSpec(
        id="openai_compat", label="Custom", provider=ScriptedWriter("openai_compat"), tiers=tiers
    )


def registry(
    *brains: BrainSpec, laptop: RecordingLaptop | None = None, default: str = "anthropic"
) -> BrainRegistry:
    specs = list(brains) or [claude_like(), gemini_like()]
    return BrainRegistry(specs, default_id=default, fallback=laptop)  # type: ignore[arg-type]


def provider_of(spec: BrainSpec) -> ScriptedWriter:
    assert isinstance(spec.provider, ScriptedWriter)
    return spec.provider


def settings_with_both() -> Settings:
    """Mock-backend settings (no key, no network); the registry above is built by hand."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


# ---- canned drafts (the wire format: buildbook.writer.model.DRAFT_SECTIONS, in order) ---------
def draft(plain: str, example: str, how: str, costs: str, fails: str) -> str:
    return (
        f"## In plain words\n{plain}\n\n## Example (made up)\n{example}\n\n"
        f"## How it works\n{how}\n\n## What it costs\n{costs}\n\n## When it fails\n{fails}\n"
    )


GOOD_DRAFT = draft(
    "The demo router picks one model for each request.",
    "Asha asks for the weather twice; the router picks the same tier both times.",
    "The router (`src/jarvis/demo/router.py`) asks `pick` for a tier and tries at most "
    "{{fact:src/jarvis/demo/router.py:MAX_TRIES}} times. The limit is the setting "
    "`demo_limit` ({{fact:settings.demo_limit}} by default).",
    "Nothing: it runs inside the server.",
    "When every try fails it says so plainly and calls nothing else.",
)
FAKE_PATH_DRAFT = GOOD_DRAFT.replace("`src/jarvis/demo/router.py`", "`src/jarvis/demo/ghost.py`")
TYPED_NUMBER_DRAFT = GOOD_DRAFT.replace("{{fact:src/jarvis/demo/router.py:MAX_TRIES}}", "3")
EMAIL_DRAFT = GOOD_DRAFT.replace("calls nothing else", "writes to someone@example.org")
INVENTED_DRAFT = GOOD_DRAFT.replace(
    "When every try fails", "It also books flights by itself. When every try fails"
)
PLANNED_OUTSIDE_DRAFT = GOOD_DRAFT.replace(
    "Nothing: it runs inside the server.", "Nothing. Soon it will also pick a voice."
)
UNVERIFIED_DRAFT = GOOD_DRAFT.replace(
    "Nothing: it runs inside the server.", "It runs in {{fact:hosting.region}}."
)


__all__ = [
    "CLAUDE_TIERS",
    "EMAIL_DRAFT",
    "FAKE_PATH_DRAFT",
    "GEMINI_TIERS",
    "GOOD_DRAFT",
    "INVENTED_DRAFT",
    "PLANNED_OUTSIDE_DRAFT",
    "TYPED_NUMBER_DRAFT",
    "UNVERIFIED_DRAFT",
    "Call",
    "RecordingLaptop",
    "ScriptedWriter",
    "Step",
    "busy",
    "claude_like",
    "custom_brain",
    "cut",
    "down",
    "draft",
    "gemini_like",
    "length_stop",
    "paid_gemini",
    "provider_of",
    "registry",
    "settings_with_both",
    "slow",
]
