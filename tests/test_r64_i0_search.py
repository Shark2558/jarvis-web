# tests/test_r64_i0_search.py
"""R6.4 D4 (docs/plans/r6-4-book-look.md): search over one release's compiled pages, no AI: the
query's words matched case-insensitively at the start of the book's words (a light stem, so
"expiry" finds "expires"), every word on the page; ranked title > the flowchart's headings > the
text, then the index's order; at most 20 results, each with a ~160-character snippet around its
first hit and the matched words as [start, end) ranges in UTF-16 units (never HTML)."""

from __future__ import annotations

from typing import Any

import pytest
from r631_i0_fakes import GOOD_FLOW, PACK

from jarvis.buildbook.book.flow import FlowSpec
from jarvis.buildbook.facts_model import IndexedPage
from jarvis.buildbook.writer import pages, search
from jarvis.buildbook.writer.model import PageMeta, PagesFile

META = PageMeta(written_by="Workshop · Mark XXIV", written_on="2026-11-24", release="3131313")
TEXTS: dict[str, dict[Any, str]] = {
    "pg_module_demo": {"plain": "The demo picks one model. It checks the expiry date of each key.",
                       "how": "It keeps `notes` with each request."},
    "pg_card_c01": {"plain": "Keys expire after a while.", "fails": "An expired key is refused."},
    "pg_card_c02": {"plain": "The store keeps notes for the demo."},
}  # fmt: skip


def _file(extra: tuple[Any, ...] = ()) -> PagesFile:
    out = [pages.written(ip, TEXTS[ip.id], META) if ip.id in TEXTS
           else pages.generator_page(ip, PACK) for ip in PACK.pages]  # fmt: skip
    return PagesFile(release="3131313", pages=(*out, *extra))


DEMO_FLOW = pages.encode_flows({"pg_module_demo": FlowSpec.model_validate(GOOD_FLOW)})
FLOWS = pages.decode_flows(DEMO_FLOW)


def find(q: str, f: PagesFile | None = None) -> Any:
    return search.find(search.corpus(f or _file(), FLOWS), "3131313", q)


def u16(text: str, a: int, b: int) -> str:
    return text.encode("utf-16-le")[2 * a : 2 * b].decode("utf-16-le")


def test_title_beats_headings_beats_text_then_the_index_order() -> None:
    got = find("router")
    assert [r.id for r in got.results][:2] == ["pg_card_c01", "pg_module_demo"]  # title, heading
    got = find("demo")
    ids = [r.id for r in got.results]
    # all three by title; then the heading (the module's flowchart), then the text's hits (c02)
    assert ids[:3] == ["pg_module_demo", "pg_card_c02", "pg_card_c01"]
    assert got.total == len(ids) and got.release == "3131313" and got.q == "demo"


def test_words_match_their_start_case_blind_with_a_light_stem() -> None:
    got = find("EXPIRY")
    assert [r.id for r in got.results] == ["pg_card_c01", "pg_module_demo"]  # 2 hits beat 1
    hit = got.results[0]
    words = [u16(hit.snippet, a, b) for a, b in hit.marks]
    assert words == ["expire", "expired"] and hit.kind == "card" and hit.title == "Demo router"
    assert [r.id for r in find("demo notes").results] == ["pg_module_demo", "pg_card_c02"]


def test_nothing_found_is_an_empty_answer() -> None:
    got = find("zebra")
    assert (got.results, got.total) == ((), 0)
    assert find("??").total == 0  # no words at all


@pytest.mark.parametrize("q", ["", " ", "x", " y ", "z" * 61])
def test_a_query_is_2_to_60_characters_after_trimming(q: str) -> None:
    assert search.normal_query(q) is None


def test_a_query_is_trimmed_and_its_spaces_folded() -> None:
    assert search.normal_query("  demo   notes ") == "demo notes"
    assert search.normal_query("ab") == "ab" and search.normal_query("a" * 60) == "a" * 60


def test_at_most_20_results_and_the_total_of_all() -> None:
    more = tuple(
        pages.generator_page(
            IndexedPage(id=f"pg_card_c{n}", kind="card", title=f"Card {n}", part="parts"), PACK
        )  # fmt: skip
        for n in range(10, 35)
    )
    got = find("written", _file(more))
    assert len(got.results) == 20 and got.total == len(PACK.pages) - 3 + 25


def test_the_snippet_is_around_the_first_hit_with_utf16_marks_and_no_html() -> None:
    long = ("Words " * 40) + "🙂 the expiry <b>date</b> is checked. " + ("More " * 40)
    page = pages.written(PACK.pages[3], {"plain": long}, META)  # pg_card_c02
    f = PagesFile(release="3131313", pages=(page,))
    (hit,) = find("expiry", f).results
    assert hit.snippet.startswith("…") and hit.snippet.endswith("…")
    assert len(hit.snippet) <= search.SNIPPET + 2 and "<mark>" not in hit.snippet
    assert [u16(hit.snippet, a, b) for a, b in hit.marks] == ["expiry"]
    assert "🙂" in hit.snippet and "`" not in find("notes").results[0].snippet


def test_a_title_only_hit_shows_the_page_s_opening_words() -> None:
    hit = next(r for r in find("router").results if r.id == "pg_card_c01")
    assert hit.snippet.startswith("Keys expire") and hit.marks == ()
