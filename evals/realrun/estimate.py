# evals/realrun/estimate.py
"""What a real-model run will cost, in rupees, before anything is spent.

Per suite: model calls × typical tokens per call × the price table (`jarvis.llm.pricing`) × the
day's rate (`jarvis.billing.fx`, falling back to the saved default). Call counts come from the
suites' own case files, so the estimate follows the suites. Tokens are characters / 4 × 1.3: the
current Claude tokenizer counts up to ~1.3 × the classic rule of thumb, and an estimate that is a
little high is safer than one the safety stop (1.5 × the estimate) would cut short. Prompt
caching makes real runs cheaper than this; it is ignored here on purpose.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jarvis.billing import rupees
from jarvis.billing.fx import Rate
from jarvis.core.prompts import build_system_prompt
from jarvis.llm.pricing import CHARS_PER_TOKEN, PRICES, is_paid
from jarvis.llm.router import ModelTier

TOKENIZER_FACTOR = 1.3
CAP_FACTOR = 1.5
TOOL_SPECS_CHARS = 4_500  # the 9 Calendar + Gmail tool descriptions (≈ 4,350 characters, Nov 2026)
MEMORY_REAL_FACTS = 20  # evals/memory/run.py --real uses the first 20 recall cases
LEARNING_BATCH = 5  # facts per learning run (evals/memory/real.py BATCH)
SLICE6_CALLS_PER_CASE = 3  # ask → tool result → answer (a hostile case may try one more round)

TITLES = {
    "phase0": "Everyday conversation (the Phase 0 check)",
    "memory": "Long-term memory",
    "voice": "Voice manners (wit and spoken replies)",
    "brief": "Morning brief safety",
    "slice6": "Calendar and email tools safety",
}


class Unpriced(ValueError):
    """A model in use has no price: the cost can't be estimated, so nothing is run."""


@dataclass(frozen=True)
class Calls:
    what: str
    tier: ModelTier
    count: int
    input_chars: int  # per call: system prompt + tools + conversation
    output_tokens: int  # per call, typical


@dataclass(frozen=True)
class Suite:
    key: str
    title: str
    argv: tuple[str, ...]  # script (relative to the repo) + its arguments
    calls: tuple[Calls, ...] = ()
    report: str = ""

    def __post_init__(self) -> None:
        if not self.report:
            object.__setattr__(self, "report", f"evals/{self.key}/report.json")

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Suite:
        calls = tuple(
            Calls(c["what"], ModelTier(c["tier"]), c["count"], c["input_chars"], c["output_tokens"])
            for c in d.get("calls", ())
        )
        return cls(d["key"], d["title"], tuple(d["argv"]), calls, d.get("report", ""))

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["argv"] = list(self.argv)
        out["calls"] = [{**asdict(c), "tier": c.tier.value} for c in self.calls]
        return out


@dataclass(frozen=True)
class Estimate:
    inr_per_usd: float
    rate_as_of: str | None
    rate_source: str
    lines: tuple[tuple[str, str, int, float], ...]  # key, title, model calls, rupees
    total_inr: int  # shown to the owner: whole rupees, rounded up, at least ₹1

    @property
    def cap_inr(self) -> float:
        return CAP_FACTOR * self.total_inr

    @property
    def cap_usd(self) -> float:
        return self.cap_inr / self.inr_per_usd

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "lines": [list(x) for x in self.lines]}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Estimate:
        lines = tuple((str(a), str(b), int(c), float(e)) for a, b, c, e in d["lines"])
        return cls(
            float(d["inr_per_usd"]),
            d.get("rate_as_of"),
            str(d["rate_source"]),
            lines,
            int(d["total_inr"]),
        )


def tokens(chars: int) -> int:
    return math.ceil(max(0, chars) / CHARS_PER_TOKEN * TOKENIZER_FACTOR)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _list_len(path: Path, name: str) -> int:
    """len() of a module-level list literal, read without importing the module."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return len(node.value.elts)
    raise ValueError(f"{name} not found in {path}")


def catalogue(root: Path) -> dict[str, Suite]:
    """Every suite with a real mode, in the order they run (phase0 is the default)."""
    ev = root / "evals"
    system = len(build_system_prompt(honorific="Sir", wit="film"))
    turns = sum(len(c["turns"]) for c in _jsonl(ev / "phase0" / "cases.jsonl"))
    facts = min(MEMORY_REAL_FACTS, len(_jsonl(ev / "memory" / "cases_recall.jsonl")))
    spoken = _list_len(ev / "voice" / "real.py", "GENERAL") + _list_len(
        ev / "voice" / "real.py", "SENSITIVE"
    )
    briefs = len(_jsonl(ev / "brief" / "cases_injection.jsonl"))
    tool_cases = len(_jsonl(ev / "slice6" / "cases_calendar.jsonl")) + len(
        _jsonl(ev / "slice6" / "cases_injection.jsonl")
    )
    fast, balanced = ModelTier.FAST, ModelTier.BALANCED
    suites = [
        Suite("phase0", TITLES["phase0"], ("evals/phase0/run.py",),
              (Calls("replies", balanced, turns, system + 1_200, 150),)),
        Suite("memory", TITLES["memory"], ("evals/memory/run.py", "--real"),
              (Calls("learning runs", fast, math.ceil(facts / LEARNING_BATCH), 8_000, 500),
               Calls("answers", fast, facts, system + 3_000, 120))),
        Suite("voice", TITLES["voice"], ("evals/voice/run.py", "--real"),
              (Calls("spoken replies", balanced, spoken, system + 1_000, 150),
               Calls("grading", fast, spoken, 2_000, 80))),
        Suite("brief", TITLES["brief"], ("evals/brief/run.py", "--real"),
              (Calls("brief summaries", fast, briefs, 6_000, 300),)),
        Suite("slice6", TITLES["slice6"], ("evals/slice6/run.py",),
              (Calls("tool rounds", balanced, tool_cases * SLICE6_CALLS_PER_CASE,
                     system + TOOL_SPECS_CHARS + 6_000, 200),)),
    ]  # fmt: skip
    return {s.key: s for s in suites}


def suite_usd(suite: Suite, tiers: Mapping[ModelTier, str]) -> float:
    total = 0.0
    for c in suite.calls:
        model = tiers[c.tier]
        if not is_paid(model):
            raise Unpriced(model)
        p = PRICES[model]
        per_call = tokens(c.input_chars) * p.input_per_mtok + c.output_tokens * p.output_per_mtok
        total += c.count * per_call / 1_000_000
    return total


def build_estimate(suites: Sequence[Suite], tiers: Mapping[ModelTier, str], rate: Rate) -> Estimate:
    lines = tuple(
        (s.key, s.title, sum(c.count for c in s.calls), suite_usd(s, tiers) * rate.inr_per_usd)
        for s in suites
    )
    total = max(1, math.ceil(sum(x[3] for x in lines)))
    return Estimate(rate.inr_per_usd, rate.as_of, rate.source, lines, total)


def rate_note(e: Estimate) -> str:
    per = rupees(e.inr_per_usd)
    if e.rate_source == "default":
        return f"Rupee figures use {per} per US dollar (today's rate could not be fetched)."
    when = f" ({e.rate_as_of})" if e.rate_as_of else ""
    return f"Rupee figures use {per} per US dollar{when}."


def render(e: Estimate) -> str:
    out = ["What will be tested with the real Claude models, and what it should cost:", ""]
    for i, (_, title, calls, inr) in enumerate(e.lines, 1):
        out.append(f"  {i}. {title} — {calls} model calls — about {rupees(inr)}")
    out += [
        "",
        f"  Estimated total: about {rupees(e.total_inr)}",
        f"  Safety stop: the run stops by itself if spending reaches {rupees(e.cap_inr)}"
        " (1.5 times the estimate).",
        "",
        rate_note(e),
        "Anthropic bills in US dollars and your bank converts, so every rupee figure is an"
        " estimate.",
    ]
    return "\n".join(out)


__all__ = [
    "CAP_FACTOR",
    "TITLES",
    "TOKENIZER_FACTOR",
    "Calls",
    "Estimate",
    "Suite",
    "Unpriced",
    "build_estimate",
    "catalogue",
    "render",
    "suite_usd",
    "tokens",
]
