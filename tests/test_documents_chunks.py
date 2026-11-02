# tests/test_documents_chunks.py — slice 10 E: ~4,000-character chunks measured the way the
# gateway sends them (JSON-escaped), page numbers per chunk, BM25 over chunks, excerpts that fit.
from __future__ import annotations

import json

from jarvis.documents.chunking import excerpt, fit, json_cost, pages_label, rank, split
from jarvis.documents.models import CHUNK_COST, CHUNKS_PER_PART, MAX_CHUNKS
from jarvis.tools.gateway import MAX_RESULT_CHARS, serialise

MALAYALAM = "കേരള സംസ്ഥാന ഐടി മിഷൻ ഏകീകൃത രജിസ്ട്രി പദ്ധതി വിവരങ്ങൾ. "
LATIN = "The quick brown fox jumps over the lazy dog. "


def test_json_cost_is_exactly_what_the_gateway_produces() -> None:
    # integration review M2: the gateway sends real Unicode (ensure_ascii=False), so a Malayalam
    # letter or an emoji costs one character; only ASCII control characters are still escaped
    for s in ["plain", 'quote " and \\ slash', "tab\tnew\nline", "\x01", "കേരളം", "😀", "é"]:
        assert json_cost(s) == len(json.dumps(s, ensure_ascii=False)) - 2, s
    assert json_cost("കേരളം") == len("കേരളം") and json_cost("😀") == 1
    assert json_cost("\n") == 2 and json_cost("\x01") == 6


def test_a_malayalam_file_makes_about_as_many_chunks_as_a_latin_one() -> None:
    ml, _ = split((MALAYALAM * 6_000)[:300_000])
    lat, _ = split((LATIN * 8_000)[:300_000])
    assert 69 <= len(ml) <= 75 and 69 <= len(lat) <= 75, (len(ml), len(lat))
    assert abs(len(ml) - len(lat)) <= 3
    part = "".join(c.text for c in ml[:CHUNKS_PER_PART])
    assert len(serialise({"text": part})) <= MAX_RESULT_CHARS  # a doc_read part still fits


def test_plain_text_chunks_are_about_4000_characters_and_cover_everything() -> None:
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(200))
    chunks, cut = split(text)
    assert not cut
    assert all(json_cost(c.text) <= CHUNK_COST for c in chunks)
    assert all(3_000 <= len(c.text) <= 4_400 for c in chunks[:-1])
    assert "".join(c.text for c in chunks) == text
    assert [c.start for c in chunks] == [text.index(c.text) for c in chunks]


def test_chunks_break_at_paragraphs_when_they_can() -> None:
    text = "\n\n".join("x" * 1_000 for _ in range(10))
    chunks, _ = split(text)
    assert all(c.text.endswith("\n\n") for c in chunks[:-1])


def test_non_latin_chunks_are_full_size_and_still_fit_the_gateway() -> None:
    text = "കേരളം " * 3_000  # one character a letter in the gateway's JSON
    chunks, _ = split(text)
    assert all(json_cost(c.text) <= CHUNK_COST for c in chunks)
    assert len(chunks[0].text) > 3_000
    emoji = "😀" * 9_000  # astral characters too: one each, no surrogate pairs
    assert all(len(c.text) <= CHUNK_COST for c in split(emoji)[0])
    assert len(split(emoji)[0]) == 3


def test_page_numbers_follow_the_page_offsets() -> None:
    text = "\n\n".join(["a" * 2_000, "b" * 5_000, "c" * 100])
    chunks, _ = split(text, (0, 2_002, 7_004))
    assert (chunks[0].page, chunks[0].page_end) == (1, 2)  # no break worth taking: spans pages
    assert chunks[-1].page_end == 3
    assert pages_label(chunks[0].page, chunks[0].page_end) == "pp. 1–2"
    paged, _ = split("\n\n".join(["a" * 3_000, "b" * 3_000]), (0, 3_002))
    assert [(c.page, c.page_end) for c in paged] == [(1, 1), (2, 2)]  # breaks at the page gap
    assert pages_label(3, 3) == "p. 3" and pages_label(None, None) is None


def test_whitespace_only_chunks_are_skipped() -> None:
    chunks, _ = split("a" * 10 + " " * 9_000 + "b")
    assert all(c.text.strip() for c in chunks)


def test_chunk_count_is_capped_for_one_atomic_commit() -> None:
    chunks, cut = split("word " * (MAX_CHUNKS * 1_000))
    assert len(chunks) == MAX_CHUNKS and cut


def test_rank_finds_the_chunk_about_the_question() -> None:
    texts = ["The weather was fine.", "Late delivery penalties are 2% per week.", "Lunch menu."]
    hits = rank(texts, "what are the penalties for late delivery?")
    assert hits[0][0] == 1 and all(score > 0 for _, score in hits)
    assert rank(texts, "the and of") == []


def test_fit_and_excerpt_stay_within_the_budget() -> None:
    text = "intro " * 500 + "The penalty clause applies to late work. " + "outro " * 500
    assert json_cost(fit(text, 300)) <= 300
    ex = excerpt(text, "penalties", 400)
    assert "penalty clause" in ex and json_cost(ex) <= 410
    assert ex.startswith("…") and ex.endswith("…")
    assert excerpt("short text", "x", 400) == "short text"
