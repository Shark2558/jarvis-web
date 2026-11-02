# tests/test_documents_ranking.py — slice 10 E: document search reuses the memory ranking (BM25
# from jarvis.recall.retrieval, the same tokens) without crowding the token memo with long texts.
from __future__ import annotations

from collections import Counter

from jarvis.recall.retrieval import bm25
from jarvis.recall.text import tokenize, tokens


def test_bm25_scores_only_bags_that_share_a_query_word() -> None:
    bags = [Counter(tokens("invoice due in march")), Counter(tokens("holiday plans"))]
    s = bm25(bags, set(tokens("when is the invoice due")))
    assert s[0] > 0 and s[1] == 0


def test_bm25_prefers_the_rarer_word() -> None:
    bags = [
        Counter(tokens("report report report")),
        Counter(tokens("report penalty clause")),
        Counter(tokens("report summary")),
    ]
    s = bm25(bags, set(tokens("penalty report")))
    assert s.index(max(s)) == 1


def test_bm25_without_query_words_or_bags_is_all_zero() -> None:
    assert bm25([], {"x"}) == []
    assert bm25([Counter({"a": 1})], set()) == [0.0]


def test_tokenize_matches_tokens_but_does_not_use_the_memo() -> None:
    from jarvis.recall import text as text_mod

    text = "Penalties are levied on late deliveries " * 50
    assert tokenize(text) == tokens(text)
    size = text_mod._tokens.cache_info().currsize
    tokenize(text + " unique tail words")
    assert text_mod._tokens.cache_info().currsize == size
