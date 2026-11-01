# src/jarvis/recall/models.py
"""Long-term memory data model (Layer 3/7, slice 8 §2–§3) and the API's request/response shapes.

A `MemoryState` is one owner's whole memory as an immutable value: settings, the four profile
blocks, facts in shards of ≤ 100 (the storage layout, D11), per-fact use counters and the
learning bookkeeping. Every change makes a new state (`jarvis.recall.ops`); the store writes
only what differs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---- limits (§2) -------------------------------------------------------------------------------

MAX_ACTIVE = 500
MAX_TEXT = 300
MAX_KEYWORDS = 8
MAX_KEYWORD_CHARS = 30
MAX_PROFILE = 1_000
PROFILE_BLOCK_CAP = 2_400
FACTS_BLOCK_CAP = 1_600
MAX_FACTS_PER_TURN = 12
SEND_ALL_UNDER = 40
IMPORT_MAX_BYTES = 512 * 1024
IMPORT_MAX_FACTS = 1_000  # an export holds ≤ 700 (500 active + history)
HISTORY_DAYS = 30
SHARD_SIZE = 100
MAX_SHARDS = 7  # header + 7 shards = a cold reload of ≤ 8 reads
MAX_STORED = SHARD_SIZE * MAX_SHARDS  # active + replaced history

Category = Literal["about_you", "preferences", "people", "work", "places", "plans", "other"]
Origin = Literal["learned", "told", "added", "imported"]
ProfileLabel = Literal["about", "preferences", "people", "work"]
CATEGORIES: tuple[str, ...] = get_args(Category)
PROFILE_LABELS: tuple[str, ...] = get_args(ProfileLabel)
CONFIDENCE: dict[str, float] = {"learned": 0.7, "told": 0.9, "added": 0.9, "imported": 0.9}


EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
LATEST = datetime(2100, 1, 1, tzinfo=UTC)


def aware(at: datetime) -> datetime:
    """Every stored date is timezone-aware UTC within 2000 … 2100: a naive date (an edited or
    foreign import) is read as UTC, and an absurd one (year 1, year 9999) is clamped, so
    comparing, sorting and showing dates can never raise."""
    try:
        at = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
    except OverflowError:  # year 1 east of UTC / year 9999 west of it
        return EARLIEST if at.year < EARLIEST.year else LATEST
    return min(max(at, EARLIEST), LATEST)


# ---- stored ------------------------------------------------------------------------------------


class FactSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    turn: int | None = None  # the owner message it came from, when known (learned facts)


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    category: Category
    keywords: tuple[str, ...] = ()
    origin: Origin
    pinned: bool = False
    confidence: float = 0.9
    source: FactSource | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    use_count: int = 0
    replaced_by: str | None = None
    replaced_at: datetime | None = None

    @field_validator("created_at", "updated_at", "last_used_at", "replaced_at", mode="after")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else aware(v)

    @property
    def active(self) -> bool:
        return self.replaced_at is None


class MemorySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    use: bool = True
    learn: bool = False
    learn_consented_at: datetime | None = None


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    about: str = ""
    preferences: str = ""
    people: str = ""
    work: str = ""


class UseStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: datetime
    n: int = 0


class Lease(BaseModel):
    """A learning run in flight on one conversation's batch: turns `start` … `end - 1`. The
    cursor moves to `end` only when the result is applied (same transaction); a lease that
    failed, or is older than 5 minutes (the instance was frozen or killed), is retried."""

    model_config = ConfigDict(frozen=True)

    lease_id: str
    started_at: datetime
    start: int
    end: int
    attempts: int = 1
    gen: int = 0  # LearnState.gen when claimed: a wipe or "learning off" since makes it stale
    failed: bool = False


class LearnState(BaseModel):
    """Learning bookkeeping: runs on the owner's local `day`, per conversation how many turns
    have been considered already (newest conversations only), the runs in flight, and a
    generation bumped by "Forget everything" and by switching learning off."""

    model_config = ConfigDict(frozen=True)

    day: str = ""
    runs: int = 0
    cursors: dict[str, int] = Field(default_factory=dict)
    leases: dict[str, Lease] = Field(default_factory=dict)
    gen: int = 0


class Header(BaseModel):
    """What the header document holds besides the shard revision (read on every turn)."""

    settings: MemorySettings = Field(default_factory=MemorySettings)
    profile: Profile = Field(default_factory=Profile)
    usage: dict[str, UseStat] = Field(default_factory=dict)
    learn: LearnState = Field(default_factory=LearnState)


Shards = tuple[tuple[Fact, ...], ...]


@dataclass(frozen=True)
class MemoryState:
    """One owner's memory. `rev` names the shard contents (set by the store)."""

    rev: str = ""
    settings: MemorySettings = field(default_factory=MemorySettings)
    profile: Profile = field(default_factory=Profile)
    shards: Shards = ()
    usage: Mapping[str, UseStat] = field(default_factory=dict)
    learn: LearnState = field(default_factory=LearnState)

    @classmethod
    def empty(cls) -> MemoryState:
        return cls()

    def merged(self, f: Fact) -> Fact:
        """`f` with its use counters (kept in the header, not the shards)."""
        u = self.usage.get(f.id)
        return f if u is None else f.model_copy(update={"last_used_at": u.at, "use_count": u.n})

    def all_facts(self) -> list[Fact]:
        return [self.merged(f) for shard in self.shards for f in shard]

    def active(self) -> list[Fact]:
        return [self.merged(f) for shard in self.shards for f in shard if f.active]

    def ids(self) -> set[str]:
        return {f.id for shard in self.shards for f in shard}

    def header(self) -> Header:
        return Header(
            settings=self.settings,
            profile=self.profile,
            usage=dict(self.usage),
            learn=self.learn,
        )

    def with_settings(self, settings: MemorySettings) -> MemoryState:
        return replace(self, settings=settings)

    def with_profile(self, profile: Profile) -> MemoryState:
        return replace(self, profile=profile)

    def with_shards(self, shards: Shards) -> MemoryState:
        return replace(self, shards=shards)

    def with_learn(self, learn: LearnState) -> MemoryState:
        return replace(self, learn=learn)

    def with_usage(self, update: Mapping[str, UseStat]) -> MemoryState:
        """Merge `update` into the counters; counters of facts that no longer exist go."""
        known = self.ids()
        merged = {k: v for k, v in {**self.usage, **update}.items() if k in known}
        return replace(self, usage=merged)


# ---- API (§5) --------------------------------------------------------------------------------


class MemoryRef(BaseModel):
    """One fact sent with a reply ("Used N memories")."""

    id: str
    text: str


class Counts(BaseModel):
    active: int
    replaced: int
    limit: int


class MemoryView(BaseModel):
    settings: MemorySettings
    profile: Profile
    facts: list[Fact]
    counts: Counts
    learn_cost_note_inr: str
    runs_today: int


class SettingsPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    use: bool | None = None
    learn: bool | None = None
    confirm_spend: bool = False


class ProfileText(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    text: str = Field(max_length=MAX_PROFILE)


class NewFact(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    text: str = Field(min_length=1, max_length=MAX_TEXT)
    category: Category


class FactPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    category: Category | None = None
    pinned: bool | None = None


class ImportRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    data: dict[str, Any]


class ImportResult(BaseModel):
    added: int
    skipped: int


class ForgetAll(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    confirm: str = Field(max_length=32)


__all__ = [
    "CATEGORIES",
    "CONFIDENCE",
    "FACTS_BLOCK_CAP",
    "EARLIEST",
    "HISTORY_DAYS",
    "IMPORT_MAX_BYTES",
    "IMPORT_MAX_FACTS",
    "MAX_ACTIVE",
    "MAX_FACTS_PER_TURN",
    "MAX_KEYWORDS",
    "MAX_KEYWORD_CHARS",
    "MAX_PROFILE",
    "MAX_SHARDS",
    "MAX_STORED",
    "MAX_TEXT",
    "PROFILE_BLOCK_CAP",
    "PROFILE_LABELS",
    "SEND_ALL_UNDER",
    "SHARD_SIZE",
    "Category",
    "Counts",
    "Fact",
    "FactPatch",
    "FactSource",
    "ForgetAll",
    "Header",
    "ImportRequest",
    "ImportResult",
    "LearnState",
    "Lease",
    "MemoryRef",
    "MemorySettings",
    "MemoryState",
    "MemoryView",
    "NewFact",
    "Origin",
    "Profile",
    "ProfileLabel",
    "ProfileText",
    "SettingsPatch",
    "Shards",
    "UseStat",
    "aware",
]
