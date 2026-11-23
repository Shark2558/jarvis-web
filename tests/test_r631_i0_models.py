# tests/test_r631_i0_models.py -- R6.3.1 I0 (docs/plans/r6-3-1-book-at-build.md D1-D3): the
# authored page file (YAML front matter + the five-section wire format) and the flowchart spec,
# their loaders, and the one error type that names the file and the problem, never its content.
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from r631_i0_fakes import GOOD_BODY, GOOD_FLOW, ROUTER, page_text, write_flow, write_page

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.authored import AuthoredError, load_flow, load_page
from jarvis.buildbook.book.flow import FlowSpec

NEEDLE = "zq-needle-private-7781"  # never echoed by any error


def _page(tmp: Path, text: str, pid: str = "pg_card_c01") -> Path:
    return write_page(tmp, pid, text)


# ---- the page file (D1, D2) -----------------------------------------------------------------
def test_a_page_file_loads_its_front_matter_and_five_sections(tmp_path: Path) -> None:
    sources = {ROUTER: "0123456789abcdef"}
    pf = load_page(_page(tmp_path, page_text("pg_card_c01", sources)))
    assert (pf.page, pf.written_by, pf.written_on) == (
        "pg_card_c01",
        "Workshop · Mark XXIV",
        date(2026, 11, 24),
    )
    assert pf.sources == sources
    assert list(pf.sections) == ["plain", "example", "how", "costs", "fails"]
    assert pf.sections["plain"] == "The demo router picks one model for each request."


def test_sources_may_be_left_out_or_empty_until_the_first_stamp(tmp_path: Path) -> None:
    assert load_page(_page(tmp_path, page_text("pg_card_c01"))).sources == {}
    assert load_page(_page(tmp_path, page_text("pg_card_c01", {}))).sources == {}


def test_crlf_and_a_byte_order_mark_are_read_as_plain_lines(tmp_path: Path) -> None:
    text = "\ufeff" + page_text("pg_card_c01").replace("\n", "\r\n")
    path = tmp_path / "pg_card_c01.md"
    path.write_bytes(text.encode("utf-8"))
    assert load_page(path).sections["fails"].endswith("calls nothing else.")


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (page_text("pg_card_c02"), "the page field must equal the file name"),
        (page_text("pg_card_c01", extra=f"note: {NEEDLE}"), "an unknown field"),
        (page_text("pg_card_c01", written_by="W" * 61), "written_by"),
        (page_text("pg_card_c01", written_on="the 24th"), "written_on"),
        (page_text("pg_card_c01", {ROUTER: "XYZ"}), "16 lower-case hex"),
        (page_text("pg_card_c01", {ROUTER: NEEDLE}), "16 lower-case hex"),
        (GOOD_BODY, "front matter"),
        ("---\npage: [unclosed\n---\n" + GOOD_BODY, "not YAML"),
        ("---\n- a list\n---\n" + GOOD_BODY, "a mapping"),
        ("---\na: &x 1\nb: *x\n---\n" + GOOD_BODY, "anchors"),
        (page_text("pg_card_c01", body="## In plain words\nOnly one section.\n"), "five sections"),
        (page_text("pg_card_c01", body=f"{NEEDLE}\n" + GOOD_BODY), "five sections"),
    ],
)
def test_a_bad_page_file_is_refused_in_plain_words(tmp_path: Path, text: str, said: str) -> None:
    with pytest.raises(AuthoredError) as err:
        load_page(_page(tmp_path, text))
    message = str(err.value)
    assert message.startswith("pages/pg_card_c01.md: ") and said in message
    assert NEEDLE not in message and str(tmp_path) not in message


def test_a_file_name_that_is_no_page_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "Not A Page.md"
    path.write_text(page_text("pg_card_c01"), encoding="utf-8")
    with pytest.raises(AuthoredError, match="not a page id"):
        load_page(path)


def test_a_file_that_is_not_utf8_or_too_big_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "pg_card_c01.md"
    path.write_bytes(b"---\npage: \xff\n---\n")
    with pytest.raises(AuthoredError, match="UTF-8"):
        load_page(path)
    path.write_text("x" * (authored.PAGE_CAP_BYTES + 1), encoding="utf-8")
    with pytest.raises(AuthoredError, match="bytes"):
        load_page(path)
    with pytest.raises(AuthoredError, match="can't be read"):
        load_page(tmp_path / "pg_card_c09.md")


# ---- the flowchart spec (D3) ------------------------------------------------------------------
def _flow(**changes: Any) -> dict[str, Any]:
    spec = copy.deepcopy(GOOD_FLOW)
    spec.update(changes)
    return spec


def test_a_flow_loads_and_keeps_its_edges_from_and_style() -> None:
    spec = FlowSpec.model_validate(GOOD_FLOW)
    assert (spec.title, spec.dir, len(spec.nodes), len(spec.edges)) == ("The demo router", "down",
                                                                        3, 2)  # fmt: skip
    assert spec.edges[0].from_ == "ask" and spec.edges[0].style == "main"
    assert spec.edges[1].style == "side" and spec.nodes[1].ref == ROUTER
    assert spec.model_dump(mode="json", by_alias=True, exclude_none=True)["edges"][0] == {
        "from": "ask",
        "to": "pick",
        "style": "main",
    }


def _node(i: int, **kw: Any) -> dict[str, Any]:
    return {"id": f"n{i}", "label": f"Step {i}", "kind": "step", "rank": i % 10, "col": i // 10,
            **kw}  # fmt: skip


@pytest.mark.parametrize(
    "spec",
    [
        _flow(title="T" * 61),
        _flow(title=""),
        _flow(dir="up"),
        _flow(nodes=[_node(0)]),
        _flow(nodes=[_node(i) for i in range(15)]),
        _flow(edges=[]),
        _flow(
            nodes=[_node(i) for i in range(10)], edges=[{"from": "n0", "to": "n1"}] * 25
        ),  # fmt: skip
        _flow(nodes=[_node(0), _node(1, id="N1")], edges=[{"from": "n0", "to": "N1"}]),
        _flow(nodes=[_node(0), _node(1, id="n0")], edges=[{"from": "n0", "to": "n0"}]),
        _flow(nodes=[_node(0), _node(1, rank=0)], edges=[{"from": "n0", "to": "n1"}]),
        _flow(nodes=[_node(0), _node(1, label="L" * 29)], edges=[{"from": "n0", "to": "n1"}]),
        _flow(nodes=[_node(0), _node(1, kind="cloud")], edges=[{"from": "n0", "to": "n1"}]),
        _flow(nodes=[_node(0), _node(1, rank=10)], edges=[{"from": "n0", "to": "n1"}]),
        _flow(nodes=[_node(0), _node(1, col=6)], edges=[{"from": "n0", "to": "n1"}]),
        _flow(nodes=[_node(0), _node(1)], edges=[{"from": "n0", "to": "n9"}]),
        _flow(nodes=[_node(0), _node(1)], edges=[{"from": "n0", "to": "n1", "label": "E" * 21}]),
        _flow(nodes=[_node(0), _node(1)], edges=[{"from": "n0", "to": "n1", "style": "dotted"}]),
        _flow(nodes=[_node(0), _node(1)], edges=[{"from": "n0", "to": "n1", "colour": "red"}]),
        _flow(nodes=[_node(0), _node(1, shape="box")], edges=[{"from": "n0", "to": "n1"}]),
        _flow(theme="night"),
    ],
)
def test_the_flow_spec_refuses_anything_outside_d3(spec: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        FlowSpec.model_validate(spec)


def test_the_flow_spec_takes_its_limits() -> None:
    nodes = [_node(i) for i in range(14)]
    edges = [{"from": f"n{i}", "to": f"n{i + 1}", "label": "E" * 20} for i in range(13)]
    edges += [{"from": "n0", "to": f"n{i}", "style": "side"} for i in range(2, 13)]
    spec = FlowSpec.model_validate(_flow(title="T" * 60, dir="right", nodes=nodes, edges=edges))
    assert len(spec.nodes) == 14 and len(spec.edges) == 24


def test_a_flow_file_is_refused_in_plain_words(tmp_path: Path) -> None:
    bad = _flow(nodes=[_node(0), _node(1, label=NEEDLE * 2)], edges=[{"from": "n0", "to": "n1"}])
    with pytest.raises(AuthoredError) as err:
        load_flow(write_flow(tmp_path, "pg_module_demo", bad))
    assert str(err.value).startswith("flows/pg_module_demo.json: ") and "label" in str(err.value)
    assert NEEDLE not in str(err.value)
    for text, said in (
        ("{not json", "not JSON"),
        ('{"title": "a", "title": "b"}', "twice"),
        (json.dumps(_flow(extra=NEEDLE)), "an unknown field"),
        ("[1, 2]", "an object"),
    ):
        with pytest.raises(AuthoredError, match=said) as err:
            load_flow(write_flow(tmp_path, "pg_module_demo", text))
        assert NEEDLE not in str(err.value)


# ---- every file at once (what the generator and `pages` read) ---------------------------------
def test_all_pages_and_flows_keep_the_good_and_name_the_bad(tmp_path: Path) -> None:
    write_page(tmp_path, "pg_card_c01", page_text("pg_card_c01"))
    write_page(tmp_path, "pg_card_c02", page_text("pg_card_c01"))
    (tmp_path / authored.BOOK_DIR / "pages" / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / authored.BOOK_DIR / "pages" / "notes.txt").write_text(NEEDLE, encoding="utf-8")
    write_flow(tmp_path, "pg_module_demo")
    write_flow(tmp_path, "pg_chapter_what", "{")
    pages = authored.all_pages(tmp_path)
    assert set(pages.items) == {"pg_card_c01"}
    assert set(pages.errors) == {"pages/pg_card_c02.md", "pages/notes.txt"}
    assert all(NEEDLE not in e for e in pages.errors.values())
    flows = authored.all_flows(tmp_path)
    assert set(flows.items) == {"pg_module_demo"} and set(flows.errors) == {
        "flows/pg_chapter_what.json"
    }


def test_no_folder_yet_is_no_pages(tmp_path: Path) -> None:
    assert authored.all_pages(tmp_path).items == {} and authored.all_flows(tmp_path).errors == {}
