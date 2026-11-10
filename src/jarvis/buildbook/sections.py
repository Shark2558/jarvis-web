# src/jarvis/buildbook/sections.py
"""The eight reader sections of the build book (R6 D2's table; `model.Book` holds them). Pure
data, frozen, extra fields refused. Every text is short and scrubbed by the generator (D3); a
setting is named, never its value.

    architecture  `Architecture`: every src/jarvis/* package -> one layer (gen/layers.py) + fit rows
    stack         `Stack`: pyproject, the Dockerfile base, CI job names, vendored releases
    libraries     `Library`: requirements.lock + dist metadata, vendored licences, flags
    integrations  `Integrations`: Settings by prefix, health probes, keyring purposes, alert kinds
    workflows     `Workflow` x 10 (`FLOW_IDS`): each step names a real symbol (gen/flows.py)
    limitations   `Limitation` (<= 80, newest first): "Not in this plan", risks, open questions
    costs         `Costs`: ₹ per unit at a dated rate, free allowances (gen/costs.py)
    decisions     `PlanDecisions`: each plan's title and D-headings
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

RELEASE_LABEL = r"^R[0-9]{1,3}(\.[0-9]{1,2})?$"  # "R6", "R5.1" (D4)
MAYBE_LABEL = r"^(R[0-9]{1,3}(\.[0-9]{1,2})?)?$"  # a label or "" (not from a release plan)
NAME = r"^[a-z][a-z0-9_]{0,59}$"
SYMBOL = r"^jarvis(\.[A-Za-z_]\w*)+(:[A-Za-z_]\w*(\.[A-Za-z_]\w*)?)?$"  # module[:Name[.attr]]
SECTION_IDS: tuple[str, ...] = (
    "architecture", "stack", "libraries", "integrations", "workflows", "limitations", "costs",
    "decisions",
)  # fmt: skip
LayerId = Literal["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "X"]
LAYERS: tuple[tuple[str, str], ...] = (
    ("L1", "User Interaction"),
    ("L2", "Input Processing"),
    ("L3", "Context & Orchestration"),
    ("L4", "Core Reasoning Engine"),
    ("L5", "Skills & Capabilities"),
    ("L6", "Integration & Tools"),
    ("L7", "Data & Persistence"),
    ("L8", "Response & Output"),
    ("X", "Cross-cutting"),
)
FlowId = Literal[
    "chat_turn",
    "approval",
    "learning",
    "voice_turn",
    "morning_tick",
    "vault_open",
    "home_alert",
    "systems_check",
    "no_ai",
    "build_book",
]
FLOW_IDS: tuple[str, ...] = get_args(FlowId)
Named = Annotated[str, Field(pattern=NAME)]


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- book.json sections (D2) ---------------------------------------------------------------------
class Package(Frozen):
    name: str = Field(pattern=NAME)  # src/jarvis/<name>
    layer: LayerId  # gen/layers.py (an unmapped package fails --check)
    files: int = Field(ge=0)
    lines: int = Field(ge=0)
    summary: str = Field(default="", max_length=200)  # the first docstring line


class FitRow(Frozen):
    """One row of a plan's "Architecture fit" / "How it fits the architecture" table."""

    release: str = Field(pattern=RELEASE_LABEL)
    feature: str = Field(max_length=160)
    layer: str = Field(max_length=160)
    phase: str = Field(default="", max_length=60)
    verdict: str = Field(default="", max_length=160)


class Architecture(Frozen):
    packages: tuple[Package, ...]
    fit: tuple[FitRow, ...] = ()

    @field_validator("packages")
    @classmethod
    def _unique(cls, v: tuple[Package, ...]) -> tuple[Package, ...]:
        if len({p.name for p in v}) != len(v):
            raise ValueError("a package is listed twice")
        return v


class StackItem(Frozen):
    role: str = Field(max_length=40)  # "language", "base image", "ci job", "3d", ...
    name: str = Field(max_length=80)
    version: str = Field(default="", max_length=40)
    source: str = Field(max_length=160)  # the repo file it was read from


class Stack(Frozen):
    items: tuple[StackItem, ...]


class Library(Frozen):
    name: str = Field(max_length=80)
    version: str = Field(default="", max_length=40)
    kind: Literal["python", "vendored", "model", "font"]
    licence: str = Field(max_length=80)  # "not stated" when nothing says (D2)
    flag: Literal["copyleft", "non_commercial"] | None = None
    role: str = Field(default="other", max_length=40)  # scene 9 groups tags by it


class Service(Frozen):
    id: str = Field(pattern=NAME)
    label: str = Field(max_length=80)
    what: str = Field(max_length=300)  # plain words (buildbook/plain.py)
    settings: tuple[Named, ...] = ()  # setting NAMES only, never a value
    checked: bool = False  # the systems check has a probe for it


class AlertRow(Frozen):
    kind: str = Field(pattern=NAME)
    level: Literal["urgent", "important", "info"]
    what: str = Field(max_length=200)


class Integrations(Frozen):
    services: tuple[Service, ...]
    key_purposes: tuple[Named, ...]
    alert_kinds: tuple[AlertRow, ...]


class Step(Frozen):
    label: str = Field(max_length=160)
    # "jarvis.core.brain:Brain.turn": the generator AST-checks that it exists (D2)
    symbol: str = Field(max_length=200, pattern=SYMBOL)


class Workflow(Frozen):
    id: FlowId
    title: str = Field(max_length=80)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=16)


class Limitation(Frozen):
    text: str = Field(min_length=1, max_length=200)
    kind: Literal["not_in_plan", "risk", "needs_owner", "open_question", "deferred", "licence"]
    source: str = Field(max_length=160)  # a plan path, or the lock file for a licence
    release: str = Field(default="", pattern=MAYBE_LABEL)


class CostItem(Frozen):
    id: str = Field(pattern=NAME)
    label: str = Field(max_length=80)
    kind: Literal["model", "voice", "search", "maps", "cloud", "other"]
    unit: str = Field(max_length=60)  # "1M input tokens", "1M characters", "minute"
    inr: float = Field(ge=0)  # ₹ per unit at the book's rate
    free: str = Field(default="", max_length=120)  # the free allowance in words ("" none)


class Costs(Frozen):
    usd_inr: float = Field(gt=0)  # billing.fx.DEFAULT_RATE
    rate_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    items: tuple[CostItem, ...]


class PlanDecisions(Frozen):
    plan: str = Field(max_length=160)  # docs/plans/<name>.md
    release: str = Field(default="", pattern=MAYBE_LABEL)
    title: str = Field(max_length=300)
    decisions: tuple[str, ...] = ()  # the D-headings, each <= 200 characters
