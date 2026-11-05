# tests/test_kb_search.py -- R2 C: deterministic search (BM25, recall's tokeniser), no model call.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jarvis.kb.models import MAX_HITS, SNIPPET_CHARS, Note, PageExcerpt
from jarvis.kb.search import rank

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def mk(i: int, text: str, **over: object) -> Note:
    base: dict[str, object] = {
        "id": f"n_{i:012x}",
        "kind": "note",
        "title": text.split(".")[0][:40],
        "text": text,
        "origin": "typed",
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=100),
    }
    base.update(over)
    return Note(**base)  # type: ignore[arg-type]


def ids(hits) -> list[str]:  # type: ignore[no-untyped-def]
    return [h.note.id for h in hits]


def test_finds_a_note_by_a_paraphrased_question() -> None:
    notes = [
        mk(1, "The plumber is Ravi, comes on Tuesdays."),
        mk(2, "Electrician Sunil charges by the hour."),
        mk(3, "Gym membership renews in March."),
    ]
    assert ids(rank(notes, "who is the plumber", NOW))[0] == notes[0].id
    assert ids(rank(notes, "when does the electrician charge", NOW))[0] == notes[1].id


def test_stemming_meets_plural_and_ing_forms() -> None:
    notes = [mk(1, "Tuesdays are bin collection days."), mk(2, "Unrelated shopping list.")]
    assert ids(rank(notes, "collecting bins", NOW)) == [notes[0].id]


def test_no_match_returns_nothing_and_stop_words_alone_match_nothing() -> None:
    notes = [mk(1, "The plumber is Ravi.")]
    assert rank(notes, "zebra", NOW) == []
    assert rank(notes, "the and of", NOW) == []


def test_tags_owner_note_and_page_excerpt_are_searched() -> None:
    page = PageExcerpt(title="p", excerpt="Kerala monsoon forecast details", fetched_at=NOW)
    notes = [
        mk(1, "plain", tags=("recipes",)),
        mk(2, "link", kind="link", url="https://example.com/", owner_note="read about gardens"),
        mk(3, "link2", kind="link", url="https://example.org/", page=page),
    ]
    assert ids(rank(notes, "recipes", NOW)) == [notes[0].id]
    assert ids(rank(notes, "gardens", NOW)) == [notes[1].id]
    hit = rank(notes, "monsoon", NOW)[0]
    assert hit.note.id == notes[2].id and hit.from_page


def test_title_words_and_recent_items_get_a_small_boost() -> None:
    old = mk(1, "Passport renewal steps listed here", title="misc")
    titled = mk(2, "Steps listed here for passport renewal", title="Passport renewal")
    assert ids(rank([old, titled], "passport renewal", NOW))[0] == titled.id
    new = mk(3, "Passport renewal steps listed here", title="misc", updated_at=NOW)
    assert ids(rank([old, new], "passport renewal", NOW))[0] == new.id


def test_at_most_eight_hits_and_300_char_snippets_around_the_match() -> None:
    notes = [
        mk(i, ("filler " * 120) + f"needle{i % 2} wordy marker " + ("tail " * 120))
        for i in range(1, 30)
    ]
    hits = rank(notes, "marker", NOW)
    assert len(hits) == MAX_HITS
    assert all(len(h.snippet) <= SNIPPET_CHARS + 2 and "marker" in h.snippet for h in hits)


def test_kind_filter_and_deleted_notes_are_excluded() -> None:
    notes = [
        mk(1, "alpha beta", kind="memo"),
        mk(2, "alpha beta"),
        mk(3, "alpha beta", deleted_at=NOW),
    ]
    assert ids(rank(notes, "alpha", NOW, kind="memo")) == [notes[0].id]
    assert notes[2].id not in ids(rank(notes, "alpha", NOW))


def test_ranking_is_deterministic() -> None:
    notes = [mk(i, "same words here") for i in range(1, 12)]
    assert ids(rank(notes, "words", NOW)) == ids(rank(list(reversed(notes)), "words", NOW))


def test_unicode_words_are_searchable() -> None:
    notes = [mk(1, "തിരുവനന്തപുരം ഓഫീസ് വിലാസം"), mk(2, "other")]
    assert ids(rank(notes, "തിരുവനന്തപുരം", NOW)) == [notes[0].id]
