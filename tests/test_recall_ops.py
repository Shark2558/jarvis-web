# tests/test_recall_ops.py — slice 8 §2/§3/D8/D9: pure memory state transitions (no storage).
from __future__ import annotations

import random
import string
import time
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.recall.errors import (
    ImportRejected,
    InvalidMemoryInput,
    MemoryFull,
    SensitiveRejected,
)
from jarvis.recall.models import (
    HISTORY_DAYS,
    MAX_ACTIVE,
    SHARD_SIZE,
    Fact,
    MemoryState,
    Profile,
)
from jarvis.recall.ops import (
    add_fact,
    delete_facts,
    edit_fact,
    export_data,
    fact_text,
    find_duplicate,
    import_data,
    new_fact,
    purge,
    replace_fact,
    set_profile,
    wipe,
)
from jarvis.recall.retrieval import render_block, select_facts

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


# ---- review findings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keywords",
    [
        ["4111111111111111"],
        ["4539", "1488", "0343", "6467"],  # a Luhn-valid number, one group per keyword
        ["AKIAABCDEFGHIJKLMNOP"],
        ["password is hunter2"],
    ],
)
def test_keywords_cannot_smuggle_sensitive_data(keywords: list[str]) -> None:
    """MEDIUM 7: keywords skipped the filter on every path."""
    with pytest.raises(SensitiveRejected):
        new_fact(
            MemoryState.empty(),
            "Has a credit card",
            "other",
            origin="told",
            now=NOW,
            keywords=keywords,
        )
    raw = {"text": "Has a credit card", "category": "other", "keywords": keywords}
    _, added, skipped = import_data(MemoryState.empty(), {"facts": [raw]}, NOW)
    assert (added, skipped) == (0, 1)


def test_text_and_keywords_are_checked_together() -> None:
    with pytest.raises(SensitiveRejected):
        new_fact(
            MemoryState.empty(), "Card PIN", "other", origin="told", now=NOW, keywords=["4321"]
        )


def _words(seed: int, n: int) -> str:
    rnd = random.Random(seed)
    return " ".join(
        "".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(4, 9)))
        for _ in range(n)
    )


def test_a_500_fact_import_is_not_quadratic() -> None:
    """HIGH 2: duplicate checks re-tokenised every stored fact for every imported one (O(n²)):
    500 facts blocked the event loop for ~14 s."""
    raw = [
        {"text": _words(i, 25), "category": "other", "keywords": _words(i + 9_999, 3).split()}
        for i in range(500)
    ]
    t0 = time.perf_counter()
    state, added, skipped = import_data(MemoryState.empty(), {"facts": raw}, NOW)
    assert time.perf_counter() - t0 < 3.0
    assert (added, skipped) == (500, 0) and len(state.active()) == 500
    t0 = time.perf_counter()  # again on a full memory: every one a duplicate
    _, added, skipped = import_data(state, {"facts": raw}, NOW)
    assert time.perf_counter() - t0 < 3.0 and (added, skipped) == (0, 500)


def test_an_import_over_1000_facts_is_refused() -> None:
    raw = [{"text": f"note {i}", "category": "other"} for i in range(1_001)]
    with pytest.raises(ImportRejected):
        import_data(MemoryState.empty(), {"facts": raw}, NOW)


def test_an_import_stops_adding_at_500_active_and_counts_the_rest_skipped() -> None:
    raw = [{"text": _words(i, 6), "category": "other"} for i in range(600)]
    state, added, skipped = import_data(MemoryState.empty(), {"facts": raw}, NOW)
    assert (added, skipped) == (MAX_ACTIVE, 100) and len(state.active()) == MAX_ACTIVE
    assert all(len(s) <= SHARD_SIZE for s in state.shards)


@pytest.mark.parametrize(
    "stamp", ["2026-01-01T00:00:00", "9999-12-31T23:59:59+00:00", "0001-01-01T00:00:00+00:00"]
)
def test_imported_timestamps_are_aware_and_clamped(stamp: str) -> None:
    """MEDIUM 9: a naive or year-9999 created_at made every recall raise (memory silently off)."""
    raw = [
        {"text": "Likes tea", "category": "preferences", "created_at": stamp},
        {"text": "Likes green walks", "category": "preferences"},
    ]
    state, added, _ = import_data(MemoryState.empty(), {"facts": raw}, NOW)
    assert added == 2
    for f in state.active():
        assert f.created_at.tzinfo is not None
        assert datetime(2000, 1, 1, tzinfo=UTC) <= f.created_at <= NOW
    chosen = select_facts(state.active(), "tea", NOW, tz="Asia/Kolkata")
    assert "Likes tea" in render_block(
        Profile(), chosen, state.active(), tz="Asia/Kolkata", now=NOW
    )


def test_stored_naive_or_absurd_dates_load_as_aware_utc() -> None:
    f = Fact.model_validate(
        {
            "id": "m1",
            "text": "Likes tea",
            "category": "other",
            "origin": "imported",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "9999-12-31T23:59:59+00:00",
        }
    )
    assert f.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert f.updated_at.tzinfo is not None and f.updated_at.year < 9999


@pytest.mark.parametrize("text", ["", "   ", "​​", "‍ ⁠"])
def test_blank_text_is_an_input_error_not_a_crash(text: str) -> None:
    """LOW 13: zero-width-only text was a 500."""
    with pytest.raises(InvalidMemoryInput):
        fact_text(text)
    state = _add(MemoryState.empty(), "Prefers tea")
    fid = state.active()[0].id
    with pytest.raises(InvalidMemoryInput):
        edit_fact(state, fid, text=text, category=None, pinned=None, now=NOW)


def test_deleting_a_fact_also_deletes_the_facts_it_replaced() -> None:
    """LOW 14: a deleted fact's predecessors stayed (30 days, exported)."""
    s = _add(MemoryState.empty(), "Lives in Kochi", "places")
    s = _add(s, "Prefers tea", "preferences")
    a = next(f for f in s.active() if "Kochi" in f.text)
    b = new_fact(s, "Lives in Delhi", "places", origin="learned", now=NOW)
    s = replace_fact(s, a.id, b, NOW)
    c = new_fact(s, "Lives in Thiruvananthapuram", "places", origin="learned", now=NOW)
    s = replace_fact(s, b.id, c, NOW)
    assert len(s.all_facts()) == 4
    s2, gone = delete_facts(s, [c.id])
    assert gone == [c.id]
    assert [f.text for f in s2.all_facts()] == ["Prefers tea"]


def test_editing_the_text_drops_stale_keywords() -> None:
    """LOW 15: keywords of the old text kept matching after an edit."""
    s = _add(MemoryState.empty(), "Daughter is Anaya", "people", keywords=["kid", "child"])
    fid = s.active()[0].id
    s2, f = edit_fact(s, fid, text=None, category="other", pinned=None, now=NOW)
    assert f.keywords == ("kid", "child")
    s3, f = edit_fact(s2, fid, text="Owns a red bicycle", category=None, pinned=None, now=NOW)
    assert f.keywords == ()
    _, f = edit_fact(s3, fid, text="Owns a red bicycle", category=None, pinned=True, now=NOW)
    assert f.keywords == ()


def test_editing_a_replaced_fact_is_not_found() -> None:
    s = _add(MemoryState.empty(), "Lives in Kochi", "places")
    old = s.active()[0]
    s = replace_fact(
        s, old.id, new_fact(s, "Lives in Delhi", "places", origin="told", now=NOW), NOW
    )
    with pytest.raises(LookupError):
        edit_fact(s, old.id, text=None, category=None, pinned=True, now=NOW)
