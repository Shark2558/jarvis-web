# tests/test_recall_ops.py — slice 8 §2/§3/D8/D9: pure memory state transitions (no storage).
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.recall.errors import MemoryFull, SensitiveRejected
from jarvis.recall.models import (
    HISTORY_DAYS,
    MAX_ACTIVE,
    SHARD_SIZE,
    MemoryState,
    Profile,
)
from jarvis.recall.ops import (
    add_fact,
    delete_facts,
    edit_fact,
    export_data,
    find_duplicate,
    import_data,
    new_fact,
    purge,
    replace_fact,
    set_profile,
    wipe,
)

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


def _add(state: MemoryState, text: str, category: str = "other", **kw: object) -> MemoryState:
    f = new_fact(state, text, category, origin=kw.pop("origin", "added"), now=NOW, **kw)  # type: ignore[arg-type]
    return add_fact(state, f)


def test_new_fact_defaults_follow_the_origin() -> None:
    s = MemoryState.empty()
    told = new_fact(s, "Prefers tea", "preferences", origin="told", now=NOW)
    learned = new_fact(s, "Prefers tea", "preferences", origin="learned", now=NOW)
    assert told.pinned and told.confidence == 0.9
    assert not learned.pinned and learned.confidence == 0.7
    assert told.id.startswith("m") and told.id != learned.id
    assert told.created_at == told.updated_at == NOW


def test_add_puts_facts_into_shards_of_at_most_100() -> None:
    s = MemoryState.empty()
    for i in range(SHARD_SIZE + 5):
        s = _add(s, f"note number {i} about topic t{i}")
    assert [len(sh) for sh in s.shards] == [SHARD_SIZE, 5]
    assert len(s.active()) == SHARD_SIZE + 5


def test_memory_full_at_500_active() -> None:
    s = MemoryState.empty()
    for i in range(MAX_ACTIVE):
        s = _add(s, f"note number {i} about topic t{i}")
    with pytest.raises(MemoryFull):
        _add(s, "one more")


def test_every_add_runs_the_sensitive_filter() -> None:
    with pytest.raises(SensitiveRejected):
        _add(MemoryState.empty(), "My PIN is 4521")


def test_text_is_cleaned_and_capped() -> None:
    s = _add(MemoryState.empty(), "  line one\nline two  ")
    assert s.active()[0].text == "line one line two"
    with pytest.raises(ValueError):
        _add(MemoryState.empty(), "   ")
    with pytest.raises(ValueError):
        _add(MemoryState.empty(), "x" * 301)


def test_duplicates_are_found_by_normalised_text_and_overlap() -> None:
    s = _add(MemoryState.empty(), "Prefers window seats on flights")
    assert find_duplicate(s, "prefers WINDOW seats on flights!") is not None
    assert find_duplicate(s, "Prefers window seats on all flights") is not None
    assert find_duplicate(s, "Prefers aisle seats on trains") is None


def test_replace_keeps_history_and_never_deletes() -> None:
    s = _add(MemoryState.empty(), "Lives in Kochi", "places")
    old = s.active()[0]
    new = new_fact(s, "Lives in Thiruvananthapuram", "places", origin="learned", now=NOW)
    s2 = replace_fact(s, old.id, new, NOW)
    assert [f.text for f in s2.active()] == ["Lives in Thiruvananthapuram"]
    hist = [f for f in s2.all_facts() if not f.active]
    assert hist[0].id == old.id and hist[0].replaced_by == new.id and hist[0].replaced_at == NOW
    with pytest.raises(LookupError):
        replace_fact(s2, old.id, new, NOW)  # an already replaced fact is not active


def test_purge_drops_history_older_than_30_days_only() -> None:
    s = _add(MemoryState.empty(), "Lives in Kochi", "places")
    old = s.active()[0]
    new = new_fact(s, "Lives in Thrissur", "places", origin="told", now=NOW)
    old_replace = replace_fact(s, old.id, new, NOW - timedelta(days=HISTORY_DAYS + 1))
    assert len(purge(old_replace, NOW).all_facts()) == 1
    recent = replace_fact(s, old.id, new, NOW - timedelta(days=HISTORY_DAYS - 1))
    assert len(purge(recent, NOW).all_facts()) == 2


def test_edit_and_delete() -> None:
    s = _add(MemoryState.empty(), "Prefers tea", "preferences")
    fid = s.active()[0].id
    s, f = edit_fact(s, fid, text="Prefers green tea", category=None, pinned=False, now=NOW)
    assert f.text == "Prefers green tea" and f.pinned is False and f.category == "preferences"
    with pytest.raises(SensitiveRejected):
        edit_fact(s, fid, text="password is hunter2", category=None, pinned=None, now=NOW)
    s, gone = delete_facts(s, [fid, "m_missing"])
    assert gone == [fid] and s.all_facts() == []


def test_set_profile_filters_and_caps() -> None:
    s = set_profile(MemoryState.empty(), "about", "Akash\nProject lead")
    assert s.profile.about == "Akash\nProject lead"
    with pytest.raises(SensitiveRejected):
        set_profile(s, "work", "Salary a/c no 50100123456789")
    with pytest.raises(ValueError):
        set_profile(s, "work", "x" * 1001)
    with pytest.raises(LookupError):
        set_profile(s, "secrets", "x")


def test_wipe_keeps_settings() -> None:
    s = _add(MemoryState.empty(), "Prefers tea", "preferences")
    s = set_profile(s, "about", "Akash")
    s = s.with_settings(s.settings.model_copy(update={"learn": True}))
    w = wipe(s)
    assert w.all_facts() == [] and w.profile == Profile() and w.settings.learn is True


def test_export_import_round_trip_and_skip_rules() -> None:
    s = _add(MemoryState.empty(), "Prefers tea", "preferences", keywords=["drink"])
    s = _add(s, "Daughter is Anaya", "people")
    s = set_profile(s, "about", "Akash")
    data = export_data(s, NOW)
    assert data["version"] == 1 and len(data["facts"]) == 2
    back, added, skipped = import_data(wipe(s), data, NOW)
    assert (added, skipped) == (2, 0)
    assert sorted((f.text, f.category, f.keywords) for f in back.active()) == sorted(
        (f.text, f.category, f.keywords) for f in s.active()
    )
    assert back.profile.about == "Akash"
    assert all(f.origin == "imported" for f in back.active())
    # a second import skips duplicates; sensitive and malformed entries are skipped too
    data["facts"].append({"text": "My PIN is 4521", "category": "other"})
    data["facts"].append({"text": 42})
    _, added2, skipped2 = import_data(back, data, NOW)
    assert (added2, skipped2) == (0, 4)
