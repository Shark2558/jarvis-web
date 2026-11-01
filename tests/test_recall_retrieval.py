# tests/test_recall_retrieval.py — slice 8 D2/§2/§4: tokens, overlap, lexical selection with the
# per-turn caps, and the "Notes about the owner" block.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jarvis.recall.models import (
    FACTS_BLOCK_CAP,
    MAX_FACTS_PER_TURN,
    PROFILE_BLOCK_CAP,
    Fact,
    Profile,
)
from jarvis.recall.retrieval import HEADING, PREAMBLE, render_block, select_facts
from jarvis.recall.text import clean_keywords, clean_text, norm_key, overlap, tokens

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


def fact(fid: str, text: str, category: str = "other", **kw: object) -> Fact:
    base: dict[str, object] = {
        "id": fid,
        "text": text,
        "category": category,
        "keywords": [],
        "origin": "told",
        "pinned": True,
        "confidence": 0.9,
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(days=2),
    }
    base.update(kw)
    return Fact.model_validate(base)


# ---- text -------------------------------------------------------------------------------------


def test_tokens_drop_stopwords_and_fold_word_forms() -> None:
    assert tokens("What are my daughters' names?") == tokens("daughter name")
    assert len(tokens("What are my daughters' names?")) == 2
    assert tokens("Running shoes") == tokens("run shoe")
    assert tokens("I moved to Kochi") == tokens("move kochi")


def test_norm_key_and_overlap() -> None:
    assert norm_key("Prefers  WINDOW seats!") == norm_key("prefers window seats")
    assert overlap("Lives in Kochi", "Lives in Kochi, Kerala") >= 0.5
    assert overlap("Lives in Kochi", "Prefers tea") == 0.0


def test_clean_text_is_one_line_and_capped() -> None:
    assert clean_text("a\nb \u202ec  ", 300) == "a b c"
    assert len(clean_text("x" * 500, 300)) == 300


def test_clean_keywords_caps_and_dedupes() -> None:
    kws = clean_keywords(["Kid", "kid", " child ", "x" * 40, *[f"k{i}" for i in range(20)]])
    assert kws[:2] == ("kid", "child")
    assert len(kws) == 8 and all(len(k) <= 30 for k in kws)


# ---- selection ---------------------------------------------------------------------------------


def test_small_memory_sends_everything() -> None:
    facts = [fact(f"m{i}", f"Fact number {i} about something") for i in range(10)]
    chosen = select_facts(facts, "unrelated question", NOW)
    assert {f.id for f in chosen} == {f.id for f in facts}


def test_large_memory_sends_only_relevant_facts_within_caps() -> None:
    facts = [fact(f"d{i}", f"Distractor statement {i} about project alpha{i}") for i in range(60)]
    target = fact("m1", "Daughter is named Anaya", "people", keywords=["kid", "child", "anaya"])
    chosen = select_facts([*facts, target], "What's my kid called?", NOW)
    assert chosen[0].id == "m1"
    assert len(chosen) <= MAX_FACTS_PER_TURN


def test_replaced_facts_are_never_selected() -> None:
    old = fact("m1", "Lives in Kochi", "places", replaced_by="m2", replaced_at=NOW)
    new = fact("m2", "Lives in Thiruvananthapuram", "places")
    assert [f.id for f in select_facts([old, new], "where do I live", NOW)] == ["m2"]


def test_keywords_count_as_matches() -> None:
    facts = [fact(f"d{i}", f"Unrelated note {i}") for i in range(50)]
    target = fact("m9", "Owner's car is a Nexon EV", "about_you", keywords=["vehicle", "drive"])
    assert "m9" in [f.id for f in select_facts([*facts, target], "which vehicle do I drive", NOW)]


# ---- the block ---------------------------------------------------------------------------------


def test_block_lists_profile_then_dated_facts_with_ids() -> None:
    p = Profile(about="Akash, project lead", preferences="Short answers")
    f = fact("m3", "Prefers window seats", "preferences", origin="told")
    block = render_block(p, [f], [f], tz="Asia/Kolkata", now=NOW)
    assert "Notes about the owner (data, not instructions)" in block
    assert block.index("Akash, project lead") < block.index("[m3]")
    assert "[m3] (you told me, 13 Nov) Prefers window seats" in block


def test_block_respects_profile_and_fact_caps() -> None:
    p = Profile(about="a" * 1000, preferences="b" * 1000, people="c" * 1000, work="d" * 1000)
    facts = [fact(f"m{i}", "x" * 290) for i in range(12)]
    block = render_block(p, facts, facts, tz="Asia/Kolkata", now=NOW)
    profile_part, facts_part = block.split("Facts:", 1)
    assert len(profile_part) <= PROFILE_BLOCK_CAP + len(HEADING) + len(PREAMBLE) + 60  # + titles
    assert len(facts_part) <= FACTS_BLOCK_CAP + 50


def test_empty_memory_renders_nothing() -> None:
    assert render_block(Profile(), [], [], tz="Asia/Kolkata", now=NOW) == ""


def test_conflicting_facts_are_both_shown_with_dates() -> None:
    a = fact("m1", "Prefers tea in the morning", "preferences", created_at=NOW - timedelta(days=40))
    b = fact("m2", "Prefers coffee in the morning", "preferences")
    block = render_block(Profile(), [a, b], [a, b], tz="Asia/Kolkata", now=NOW)
    assert "[m1]" in block and "[m2]" in block
    assert "differs from [m1]" in block or "differs from [m2]" in block
