# tests/r63_fakes_b.py -- part B's own fakes (R6.3, docs/plans/r6-3-book-content.md D5-D8, D11).
# Imported bare (`from r63_fakes_b import ...`). Everything here is fixed and in memory: no model,
# Google or Anthropic is ever called (the scripted brains of r63_fake_brains only).
#
#   TRIAL_FACTS / trial_source()   the fixture's facts with the five trial pages added (D6), so
#                                  a trial runs on the fixture; `big=True` adds a 150 KB docstring
#                                  to a cited file, so every pack fills its 96,000-byte cap (the
#                                  holds of Rs 11.84 of the trial's cap case)
#   HoldPayer                      a Claude-like provider reporting exactly its call's hold's
#                                  tokens (D8's worst case: bytes / 2.5 in, the system prompt at
#                                  the cache-write price, 4,000 out): every call settles at it
#   service(...)                   the writer's service over writer_context(...) with these
#   good_draft(page_id)            a draft that passes all six checks for that page of the fixture
from __future__ import annotations

import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from r63_fake_brains import CLAUDE_TIERS, GOOD_DRAFT, ScriptedWriter, Step, gemini_like, registry
from r63_fakes import (
    FIXTURE_FACTS,
    FIXTURE_FILES,
    FakeBilling,
    FakeSource,
    FixedClock,
    source_zip,
    writer_context,
)

from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.model import Release
from jarvis.llm.base import ChatMessage, Effort, StreamUsage, ToolSpec
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.storage.docs import MemoryDocs

_ROUTER, _STORE = "src/jarvis/demo/router.py", "src/jarvis/demo/store.py"
_JS = "src/jarvis/api/static/console-demo.js"
SYSTEM_TOKENS_AT_INPUT = 3_750  # 3,000 system tokens at the cache-write price (1.25 x input)


def _trial(pid: str, kind: str, part: str, title: str) -> IndexedPage:
    return IndexedPage(id=pid, kind=kind, title=title, part=part, refs=(_ROUTER,), sources=("C01",))  # type: ignore[arg-type]


TRIAL_EXTRA = (
    _trial("pg_card_c16", "card", "parts", "Demo router, again"),
    _trial("pg_module_wardrobe", "module", "modules", "Wardrobe"),
    _trial("pg_screen_vitals", "screen", "screens", "Vitals"),
    _trial("pg_service_telegram", "service", "services", "Telegram"),
)
TRIAL_FACTS = FIXTURE_FACTS.model_copy(update={"pages": (*FIXTURE_FACTS.pages, *TRIAL_EXTRA)})
BIG_DOC = "\n".join(f"Line {n:05d} of a long, made-up module docstring." for n in range(3_500))


def files(*, big: bool = False, **changed: str) -> dict[str, str]:
    out = dict(FIXTURE_FILES)
    if big:
        out[_ROUTER] = f'"""{BIG_DOC}"""\n\n' + out[_ROUTER].split("\n", 1)[1]
    out.update({k.replace("__", "/"): v for k, v in changed.items()})
    return out


def trial_source(*, big: bool = False, facts: FactPack = TRIAL_FACTS) -> FakeSource:
    return FakeSource(facts, zipped=source_zip(files(big=big)))


class MovableSource(FakeSource):
    """A source whose release can change (a deploy): `deploy(sha, files, facts)`."""

    def deploy(self, sha: str, tree: dict[str, str], facts: FactPack) -> Release:
        zipped = source_zip(tree)
        ref = facts.release.model_copy(update={"id": sha[:7], "sha": sha})  # type: ignore[union-attr]
        self._facts, self._zip = facts.model_copy(update={"release": ref}), zipped
        import hashlib

        digest = hashlib.sha256(zipped).hexdigest()
        self._release = Release(**ref.model_dump(), book_sha256=digest, source_sha256=digest)
        return self._release


@dataclass
class HoldPayer(ScriptedWriter):
    """Reports exactly its hold's tokens (bytes / 2.5 of what it was sent, the system prompt at the
    cache-write price, 4,000 out), so the writer settles every call at its hold (D8)."""

    over: int = 0  # extra input tokens: a call billed above its hold (M1)
    drafts: list[str] = field(default_factory=list)

    async def stream(  # type: ignore[override]
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
        sent = sum(len(m.text().encode("utf-8")) for m in messages)
        tokens = math.ceil(sent / 2.5) + SYSTEM_TOKENS_AT_INPUT + self.over
        text = self.drafts.pop(0) if self.drafts else GOOD_DRAFT
        self.steps.insert(0, Step(text=text, input_tokens=tokens, output_tokens=max_tokens))
        async for piece in super().stream(
            system=system,
            system_dynamic=system_dynamic,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            usage=usage,
            tools=tools,
        ):
            yield piece


def hold_payer(*drafts: str, over: int = 0) -> BrainSpec:
    return BrainSpec(
        id="anthropic",
        label="Claude",
        provider=HoldPayer("anthropic", over=over, drafts=list(drafts)),
        tiers=dict(CLAUDE_TIERS),
    )


def service(
    *,
    brains: BrainRegistry | None = None,
    source: FakeSource | None = None,
    billing: FakeBilling | None = None,
    clock: FixedClock | None = None,
    docs: MemoryDocs | None = None,
    limit_mb: int = 60,
) -> Any:
    from jarvis.buildbook.writer import part

    ctx = writer_context(
        brains=brains or registry(),
        billing=billing,
        source=source or trial_source(),
        docs=docs,
        clock=clock,
        limit_mb=limit_mb,
    )
    return part.build(ctx)


def both(claude: BrainSpec | None = None, gemini: BrainSpec | None = None) -> BrainRegistry:
    return registry(claude or hold_payer(), gemini or gemini_like())


__all__ = [
    "BIG_DOC",
    "TRIAL_EXTRA",
    "TRIAL_FACTS",
    "HoldPayer",
    "MovableSource",
    "both",
    "files",
    "hold_payer",
    "service",
    "trial_source",
]
