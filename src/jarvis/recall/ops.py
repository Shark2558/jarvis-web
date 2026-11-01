# src/jarvis/recall/ops.py
"""Pure memory state transitions (no I/O): every change makes a new `MemoryState`.

Each write path ends in `add_fact` / `edit_fact` / `set_profile`, which run the sensitive-data
filter (D9) and the limits (§2). Contradictions are `replace_fact` (the old fact stays as
history for 30 days, D8); only the owner deletes (`delete_facts`, `wipe`). A new fact goes into
the first shard with room, so one change rewrites at most two shards (D11).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from jarvis.recall.errors import ImportRejected, InvalidMemoryInput, MemoryFull, SensitiveRejected
from jarvis.recall.models import (
    CATEGORIES,
    CONFIDENCE,
    EARLIEST,
    HISTORY_DAYS,
    IMPORT_MAX_FACTS,
    MAX_ACTIVE,
    MAX_PROFILE,
    MAX_SHARDS,
    MAX_STORED,
    MAX_TEXT,
    PROFILE_LABELS,
    SHARD_SIZE,
    Fact,
    FactSource,
    MemoryState,
    Origin,
    Profile,
    Shards,
    aware,
)
from jarvis.recall.sensitive import is_sensitive
from jarvis.recall.text import (
    clean_block,
    clean_keywords,
    clean_text,
    jaccard,
    norm_key,
    token_set,
)

FACT_ID = re.compile(r"m[a-z0-9]{3,24}")
DUPLICATE_OVERLAP = 0.8
_ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
EXPORT_VERSION = 1


# ---- validation -----------------------------------------------------------------------------


def fact_text(raw: object) -> str:
    """The stored form of a fact's text, or InvalidMemoryInput / SensitiveRejected."""
    if not isinstance(raw, str):
        raise InvalidMemoryInput("A fact must be text.")
    text = clean_text(raw, MAX_TEXT * 4)
    if not text:
        raise InvalidMemoryInput("A fact needs some text.")
    if len(text) > MAX_TEXT:
        raise InvalidMemoryInput(f"A fact is at most {MAX_TEXT} characters.")
    if is_sensitive(text):
        raise SensitiveRejected()
    return text


def check_sensitive(text: str, keywords: Iterable[str] = ()) -> None:
    """The D9 filter over a fact's text AND its keywords, read together (a keyword can carry a
    number as well as the text can, and "Card PIN" + "4321" is a PIN)."""
    if is_sensitive(" ".join([text, *keywords])):
        raise SensitiveRejected()


def category_of(raw: object) -> str:
    if raw not in CATEGORIES:
        raise InvalidMemoryInput("Category must be one of: " + ", ".join(CATEGORIES) + ".")
    return str(raw)


def _new_id(taken: set[str]) -> str:
    while True:
        fid = "m" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))
        if fid not in taken:
            return fid


def new_fact(
    state: MemoryState,
    text: object,
    category: object,
    *,
    origin: Origin,
    now: datetime,
    keywords: Iterable[object] | None = None,
    source: FactSource | None = None,
    pinned: bool | None = None,
    confidence: float | None = None,
) -> Fact:
    clean, kws = fact_text(text), clean_keywords(keywords)
    check_sensitive(clean, kws)
    return Fact(
        id=_new_id(state.ids()),
        text=clean,
        category=category_of(category),  # type: ignore[arg-type]
        keywords=kws,
        origin=origin,
        pinned=pinned if pinned is not None else origin in ("told", "added"),
        confidence=confidence if confidence is not None else CONFIDENCE[origin],
        source=source,
        created_at=now,
        updated_at=now,
    )


# ---- shards ---------------------------------------------------------------------------------


def _map(state: MemoryState, fn: Callable[[Fact], Fact | None]) -> Shards:
    """Apply `fn(fact) -> fact | None` to every fact (None drops it); trailing empty shards go."""
    shards = [tuple(g for f in shard if (g := fn(f)) is not None) for shard in state.shards]
    while shards and not shards[-1]:
        shards.pop()
    return tuple(shards)


def _place(shards: Shards, fact: Fact) -> Shards:
    for i, shard in enumerate(shards):
        if len(shard) < SHARD_SIZE:
            return (*shards[:i], (*shard, fact), *shards[i + 1 :])
    if len(shards) >= MAX_SHARDS:
        raise MemoryFull()
    return (*shards, (fact,))


def _make_room(state: MemoryState) -> MemoryState:
    """At the storage ceiling, the oldest history (replaced facts) goes before the 30 days."""
    total = sum(len(s) for s in state.shards)
    if total < MAX_STORED:
        return state
    history = sorted(
        (f for f in state.all_facts() if not f.active),
        key=lambda f: f.replaced_at or f.updated_at,
    )
    drop = {f.id for f in history[: total - MAX_STORED + 1]}
    return state.with_shards(_map(state, lambda f: None if f.id in drop else f))


# ---- facts ----------------------------------------------------------------------------------


class DupIndex:
    """Duplicate lookup over many facts at once: normalised-text keys plus an inverted index of
    content words, so checking one text costs the facts that share a word with it, not a
    re-tokenisation of every stored fact (an import checks hundreds)."""

    def __init__(self, facts: Iterable[Fact] = ()) -> None:
        self._facts: list[Fact] = []
        self._sets: list[frozenset[str]] = []
        self._keys: dict[str, int] = {}
        self._postings: dict[str, list[int]] = {}
        for f in facts:
            self.add(f)

    def add(self, f: Fact) -> None:
        i = len(self._facts)
        ts = token_set(f.text)
        self._facts.append(f)
        self._sets.append(ts)
        self._keys.setdefault(norm_key(f.text), i)
        for t in ts:
            self._postings.setdefault(t, []).append(i)

    def find(self, text: str) -> Fact | None:
        """The first fact (in insertion order) that `text` duplicates, or None."""
        hit = self._keys.get(norm_key(text))
        ts = token_set(text)
        shared: dict[int, int] = {}
        for t in ts:
            for i in self._postings.get(t, ()):
                shared[i] = shared.get(i, 0) + 1
        for i in sorted(shared):
            if hit is not None and hit < i:
                break
            if shared[i] / (len(ts) + len(self._sets[i]) - shared[i]) >= DUPLICATE_OVERLAP:
                return self._facts[i]
        return None if hit is None else self._facts[hit]


def find_duplicate(state: MemoryState, text: str) -> Fact | None:
    key, ts = norm_key(text), token_set(text)
    for f in state.active():
        if norm_key(f.text) == key or jaccard(token_set(f.text), ts) >= DUPLICATE_OVERLAP:
            return f
    return None


def add_fact(state: MemoryState, fact: Fact) -> MemoryState:
    check_sensitive(fact.text, fact.keywords)  # every path, even a Fact built elsewhere
    if fact.id in state.ids():
        raise ValueError("fact id already used")
    if len(state.active()) >= MAX_ACTIVE:
        raise MemoryFull()
    roomy = _make_room(state)
    return roomy.with_shards(_place(roomy.shards, fact))


def _get(state: MemoryState, fid: str, *, active_only: bool = True) -> Fact:
    """The stored fact (without its use counters, which live in the header)."""
    for shard in state.shards:
        for f in shard:
            if f.id == fid and (f.active or not active_only):
                return f
    raise LookupError("No such fact.")


def replace_fact(state: MemoryState, old_id: str, new: Fact, now: datetime) -> MemoryState:
    """`new` supersedes `old_id`, which stays in history (replaced_by / replaced_at)."""
    _get(state, old_id)

    def mark(f: Fact) -> Fact:
        if f.id != old_id:
            return f
        return f.model_copy(update={"replaced_by": new.id, "replaced_at": now})

    return add_fact(state.with_shards(_map(state, mark)), new)


def edit_fact(
    state: MemoryState,
    fid: str,
    *,
    text: str | None,
    category: str | None,
    pinned: bool | None,
    now: datetime,
) -> tuple[MemoryState, Fact]:
    """The owner's own correction: in place (no history). Only an active fact can be edited (a
    replaced one is history); new text drops the old text's keywords (they described it)."""
    cur = _get(state, fid)
    update: dict[str, Any] = {"updated_at": now}
    if text is not None:
        update["text"] = fact_text(text)
        if norm_key(update["text"]) != norm_key(cur.text):
            update["keywords"] = ()
    if category is not None:
        update["category"] = category_of(category)
    if pinned is not None:
        update["pinned"] = bool(pinned)
    new = cur.model_copy(update=update)
    out = state.with_shards(_map(state, lambda f: new if f.id == fid else f))
    return out, out.merged(new)


def _with_history(state: MemoryState, ids: set[str]) -> set[str]:
    """`ids` plus every fact they replaced, along the whole `replaced_by` chain."""
    out = set(ids)
    grew = True
    while grew:
        more = {f.id for f in state.all_facts() if f.replaced_by in out and f.id not in out}
        out |= more
        grew = bool(more)
    return out


def delete_facts(state: MemoryState, ids: Iterable[str]) -> tuple[MemoryState, list[str]]:
    """The owner's delete: the facts named (returned) and the history they replaced."""
    wanted = set(ids)
    gone = [f.id for f in state.all_facts() if f.id in wanted]
    if not gone:
        return state, []
    drop = _with_history(state, set(gone))
    out = state.with_shards(_map(state, lambda f: None if f.id in drop else f))
    return out.with_usage({}), gone


def purge(state: MemoryState, now: datetime) -> MemoryState:
    """Replaced facts older than 30 days go (lazily, on a write)."""
    cutoff = now - timedelta(days=HISTORY_DAYS)
    if not any(f.replaced_at is not None and f.replaced_at < cutoff for f in state.all_facts()):
        return state

    def keep(f: Fact) -> Fact | None:
        return None if f.replaced_at is not None and f.replaced_at < cutoff else f

    return state.with_shards(_map(state, keep)).with_usage({})


# ---- profile, wipe -----------------------------------------------------------------------------


def set_profile(state: MemoryState, label: str, text: object) -> MemoryState:
    if label not in PROFILE_LABELS:
        raise LookupError("No such profile block.")
    if not isinstance(text, str):
        raise InvalidMemoryInput("A profile block must be text.")
    clean = clean_block(text, MAX_PROFILE)
    if len(clean) > MAX_PROFILE:
        raise InvalidMemoryInput(f"A profile block is at most {MAX_PROFILE:,} characters.")
    if is_sensitive(clean):
        raise SensitiveRejected()
    return state.with_profile(state.profile.model_copy(update={label: clean}))


def wipe(state: MemoryState) -> MemoryState:
    """Forget everything: facts (with history) and profile. Settings stay."""
    return MemoryState(rev=state.rev, settings=state.settings, learn=state.learn)


# ---- export / import ------------------------------------------------------------------------


def export_data(state: MemoryState, now: datetime) -> dict[str, Any]:
    return {
        "version": EXPORT_VERSION,
        "exported_at": now.isoformat(),
        "settings": state.settings.model_dump(mode="json"),
        "profile": state.profile.model_dump(mode="json"),
        "facts": [f.model_dump(mode="json") for f in state.all_facts()],
    }


def _imported_at(raw: object, now: datetime) -> datetime:
    """An exported date, aware UTC within 2000 … now; anything unreadable is `now`."""
    try:
        at = aware(TypeAdapter(datetime).validate_python(raw)) if raw else now
    except (ValueError, ValidationError):
        return now
    return min(max(at, EARLIEST), now)


def _imported(raw: Any, now: datetime, taken: set[str]) -> Fact | None:
    """One exported fact as an imported one, or None (skipped: history, malformed, sensitive —
    text or keywords)."""
    if not isinstance(raw, dict) or raw.get("replaced_at"):
        return None
    try:
        text = fact_text(raw.get("text"))
        kws = raw.get("keywords")
        keywords = clean_keywords(kws if isinstance(kws, list) else ())
        check_sensitive(text, keywords)
        conf = raw.get("confidence", CONFIDENCE["imported"])
        fid = raw.get("id")
        return Fact(
            id=fid
            if isinstance(fid, str) and FACT_ID.fullmatch(fid) and fid not in taken
            else _new_id(taken),
            text=text,
            category=category_of(raw.get("category")),  # type: ignore[arg-type]
            keywords=keywords,
            origin="imported",
            pinned=bool(raw.get("pinned", True)),
            confidence=float(conf) if isinstance(conf, int | float) and 0 <= conf <= 1 else 0.9,
            created_at=_imported_at(raw.get("created_at"), now),
            updated_at=now,
        )
    except (ValueError, ValidationError):  # SensitiveRejected is a ValueError
        return None


def _add_many(state: MemoryState, facts: list[Fact]) -> MemoryState:
    """Place new facts in one pass (history purged first if the storage ceiling needs it)."""
    if not facts:
        return state
    total = sum(len(s) for s in state.shards) + len(facts)
    if total > MAX_STORED:
        history = sorted(
            (f for f in state.all_facts() if not f.active),
            key=lambda f: f.replaced_at or f.updated_at,
        )
        drop = {f.id for f in history[: total - MAX_STORED]}
        state = state.with_shards(_map(state, lambda f: None if f.id in drop else f))
    shards = [list(s) for s in state.shards]
    for f in facts:
        room = next((s for s in shards if len(s) < SHARD_SIZE), None)
        if room is None:
            if len(shards) >= MAX_SHARDS:
                raise MemoryFull()
            room = []
            shards.append(room)
        room.append(f)
    return state.with_shards(tuple(tuple(s) for s in shards))


def _import_profile(state: MemoryState, raw: Any) -> MemoryState:
    if not isinstance(raw, dict):
        return state
    for label in PROFILE_LABELS:
        text = raw.get(label)
        if isinstance(text, str) and text.strip() and not getattr(state.profile, label):
            try:
                state = set_profile(state, label, text)
            except (ValueError, LookupError):
                continue
    return state


def import_data(
    state: MemoryState, data: dict[str, Any], now: datetime
) -> tuple[MemoryState, int, int]:
    """Merge an export: duplicates, sensitive, malformed and history entries are skipped, and
    facts past 500 active; empty profile blocks are filled. Settings are never imported
    (learning needs the owner's consent). Linear in the facts: one duplicate index, one
    placement pass."""
    raw_facts = data.get("facts", [])
    if not isinstance(raw_facts, list):
        raise ValueError("facts must be a list")
    if len(raw_facts) > IMPORT_MAX_FACTS:
        raise ImportRejected()
    active = state.active()
    taken, index = state.ids(), DupIndex(active)
    room = MAX_ACTIVE - len(active)
    new: list[Fact] = []
    for raw in raw_facts:
        fact = _imported(raw, now, taken)
        if fact is None or room <= 0 or index.find(fact.text) is not None:
            continue
        taken.add(fact.id)
        index.add(fact)
        new.append(fact)
        room -= 1
    out = _add_many(state, new)
    return _import_profile(out, data.get("profile")), len(new), len(raw_facts) - len(new)


__all__ = [
    "DUPLICATE_OVERLAP",
    "FACT_ID",
    "DupIndex",
    "Profile",
    "add_fact",
    "category_of",
    "check_sensitive",
    "delete_facts",
    "edit_fact",
    "export_data",
    "fact_text",
    "find_duplicate",
    "import_data",
    "new_fact",
    "purge",
    "replace_fact",
    "set_profile",
    "wipe",
]
