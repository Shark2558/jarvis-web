# tests/test_r63_types.py -- R6.3 I0 seam 3 (docs/plans/r6-3-book-content.md "Data model", D2, D3,
# D6-D9, D11, H2, M4, M6, L4): the types every part builds on. The pages' data model and HTTP
# contract (`buildbook/writer/{model,http}.py`; R6.3.1 D8: the writer's money, brain and run
# models went with it), the tour's two shapes (`buildbook/tour_model.py`),
# the fact pack (`buildbook/facts_model.py`), and `Book.tour` / `Release.facts_sha256`, which leave
# an older book's and release's bytes exactly as they were (47ee8fc's real book.json round-trips).
from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jarvis.buildbook import facts_model as fm
from jarvis.buildbook import tour_model as tm
from jarvis.buildbook.model import Fact, Release, canonical_bytes, load_book
from jarvis.buildbook.writer import http, model

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r6_3"
OLD_BOOK_SHA = "92f2df75db0775c322b1899db5af332b08b91f35a84dd821da59e5245d691ab2"  # 47ee8fc's
SHA = "a" * 64


def _old_book() -> bytes:
    return gzip.decompress((FIXTURES / "book-47ee8fc.json.gz").read_bytes())


# ---- Book.tour and Release.facts_sha256: older books and releases are unchanged ------------------
def test_the_real_book_of_47ee8fc_loads_with_no_tour_and_keeps_its_bytes() -> None:
    data = _old_book()
    assert hashlib.sha256(data).hexdigest() == OLD_BOOK_SHA and len(data) == 198_076
    book = load_book(data)
    assert book.tour is None and book.release.id == "47ee8fc"
    assert canonical_bytes(book) == data  # no "tour" key appears: the sealed digest still holds


def _release(**kw: Any) -> Release:
    base: dict[str, Any] = {
        "id": "abcdef0",
        "sha": "abcdef0" + "1" * 33,
        "label": "R6.3",
        "committed_at": "2026-11-23T15:00:00+05:30",
        "version": "v6.3.0",
        "book_sha256": SHA,
        "source_sha256": SHA,
    }
    return Release(**{**base, **kw})


def test_a_release_without_facts_dumps_as_before_and_with_them_names_the_digest() -> None:
    assert "facts_sha256" not in _release().model_dump(mode="json")
    assert _release(facts_sha256="b" * 64).model_dump(mode="json")["facts_sha256"] == "b" * 64
    with pytest.raises(ValidationError):
        _release(facts_sha256="not-a-digest")


def _tour_scene(n: int, beats: int = 3) -> dict[str, Any]:
    _, sid, title, visual, audience = tm.TOUR_SCENES[n - 1]
    lines = [{"id": f"t{n:02d}b{i + 1:02d}", "text": f"Line {i + 1}."} for i in range(beats)]
    return {
        "n": n,
        "id": sid,
        "title": title,
        "picture": {"visual": visual, "facts": [{"label": "a"}]},
        "audience": audience,
        "beats": lines,
    }


def _tour() -> dict[str, Any]:
    timing = {"seconds": 800.0, "words": 1700, "chars": 9000, "lines": 54}
    owner = {"scenes": [_tour_scene(n) for n in range(1, 18)], **timing}
    guest = {"scenes": [_tour_scene(n) for n in range(1, 18) if n != 16], **timing}
    return {"owner": owner, "guest": guest}


def test_a_book_with_a_tour_writes_it_and_reads_it_back() -> None:
    book = load_book(_old_book())
    with_tour = book.model_copy(update={"tour": tm.Tour.model_validate(_tour())})
    data = canonical_bytes(with_tour)
    assert b'"tour":{' in data and load_book(data) == with_tour


# ---- the tour's shapes (D9, M6) ------------------------------------------------------------------
def test_the_approved_scenes_are_pinned_with_his_seven_highlights_in_order() -> None:
    assert [s[0] for s in tm.TOUR_SCENES] == list(range(1, 18))
    assert [s[1] for s in tm.TOUR_SCENES[6:13]] == list(tm.HIGHLIGHTS)
    assert tm.HIGHLIGHTS == ("voice", "approvals", "memory", "vault", "home", "phone", "wardrobe")
    assert [s for s in tm.TOUR_SCENES if s[4] == "owner"] == [
        (16, "costs", "What I cost", 10, "owner")
    ]
    assert {s[0] for s in tm.TOUR_SCENES if s[3] == 10} == {16}  # no guest scene uses picture 10
    assert tm.OWN_PICTURE_DATA == {12, 13, 14}


def test_an_empty_script_is_the_stub_and_a_partial_one_is_refused() -> None:
    assert tm.TourScript().scenes == ()
    one = {**_tour_scene(1), "picture": {"visual": 1, "facts": {"from_show": 1}}}
    with pytest.raises(ValidationError):
        tm.TourScript.model_validate({"scenes": [one]})
    whole = [{**_tour_scene(n), "picture": {"visual": tm.TOUR_SCENES[n - 1][3], "facts": []}}
             for n in range(1, 18)]  # fmt: skip
    assert len(tm.TourScript.model_validate({"scenes": whole}).scenes) == 17


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Voice"},  # not the approved title
        {"audience": "owner"},  # T01 is everyone's
        {"picture": {"visual": 2, "facts": []}},  # T01 borrows picture 1
        {"beats": [{"id": "t02b01", "text": "x"}]},  # a beat of another scene
    ],
)
def test_a_scene_that_is_not_the_approved_one_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        tm.TourScene.model_validate({**_tour_scene(1), **change})


def test_the_tour_is_filled_per_audience_inside_the_hard_band() -> None:
    tour = tm.Tour.model_validate(_tour())
    assert len(tour.owner.scenes) == 17 and [s.n for s in tour.guest.scenes] == [
        *range(1, 16),
        17,
    ]
    for bad in (599.0, 900.5):
        t = _tour()
        t["owner"] = {**t["owner"], "seconds": bad}
        with pytest.raises(ValidationError):
            tm.Tour.model_validate(t)
    short = _tour()
    short["owner"] = {**short["owner"], "scenes": short["owner"]["scenes"][:16]}
    with pytest.raises(ValidationError):
        tm.Tour.model_validate(short)


def test_a_guests_tour_has_no_owner_scene_and_no_owner_line() -> None:
    with_costs = _tour()
    with_costs["guest"] = {**with_costs["guest"], "scenes": [_tour_scene(n) for n in range(1, 18)]}
    with pytest.raises(ValidationError):
        tm.Tour.model_validate(with_costs)  # T16 is the owner's
    owner_line = _tour()
    scene13 = _tour_scene(13)
    scene13["beats"][2] = {**scene13["beats"][2], "audience": "owner"}
    owner_line["guest"]["scenes"][12] = scene13
    with pytest.raises(ValidationError):
        tm.Tour.model_validate(owner_line)  # t13b03 is his


def test_the_timer_gives_the_plans_figures() -> None:
    assert tm.seconds(1_762, 54, 17) == pytest.approx(796.1, abs=0.1)  # the owner's tour
    assert tm.seconds(1_700, 53, 16) == pytest.approx(768.2, abs=0.1)  # a guest's
    assert tm.AIMED_S == {"owner": (780.0, 870.0), "guest": (760.0, 850.0)}


def test_a_tour_fact_is_the_shows_fact() -> None:
    assert tm.TourFact.model_fields.keys() == Fact.model_fields.keys()
    for name, field in Fact.model_fields.items():
        assert repr(tm.TourFact.model_fields[name].metadata) == repr(field.metadata), name


# ---- the fact pack (D2, D3) ----------------------------------------------------------------------
def test_an_empty_fact_pack_is_valid_and_its_bytes_are_canonical() -> None:
    pack = fm.FactPack()
    data = fm.canonical_facts(pack)
    assert fm.load_facts(data) == pack and data.startswith(b"{") and b" " not in data


def test_the_fact_keys_and_page_ids() -> None:
    assert len(fm.FACT_TOUR_KEYS) == 30 and len(set(fm.FACT_TOUR_KEYS)) == 30
    keys = (*fm.FACT_TOUR_KEYS, "src/jarvis/llm/fallback.py:BREAKER_S", "settings.demo_limit")
    assert all(re.fullmatch(fm.FACT_KEY, k) for k in keys)
    assert not re.fullmatch(fm.FACT_KEY, "has space")
    trial = (
        "pg_chapter_example",
        "pg_card_c16",
        "pg_module_wardrobe",
        "pg_screen_vitals",
        "pg_service_telegram",
    )  # R6.3's trial pages (the writer's TRIAL_PAGES, R6.3.1 D8)
    for page in (*trial, "pg_chapter_what", "pg_service_google_cloud_text_to_speech"):
        assert re.fullmatch(fm.PAGE_ID, page), page
    assert [c for c, _ in fm.CHAPTERS][1] == "example" and len(fm.CHAPTERS) == 8
    with pytest.raises(ValidationError):
        fm.FactPack.model_validate({"values": {"bad key": {"value": 1, "source": "x"}}})


def test_facts_json_is_capped_at_two_mib() -> None:  # I1: 1 MiB at I0 (INTEGRATION-A 5.4)
    with pytest.raises(ValueError, match="2 MiB"):
        fm.load_facts(b" " * (fm.FACTS_JSON_CAP_BYTES + 1))
    with pytest.raises(ValueError, match="not a v1"):
        fm.load_facts(b'{"v": 2}')


# ---- the page model (D3; R6.3.1 D4, D8: no money or brain fields) ------------------------------
def _section(sid: model.SectionId, text: str = "words") -> dict[str, Any]:
    return {"id": sid, "heading": model.HEADINGS[sid], "text": text}


def _page(**kw: Any) -> dict[str, Any]:
    base = {"id": "pg_card_c16", "kind": "card", "title": "Brain router", "part": "parts"}
    return {**base, "sections": [_section(s) for s in model.SECTION_IDS], **kw}


def test_a_page_has_the_six_sections_in_order_each_within_its_cap() -> None:
    page = model.Page.model_validate(_page())
    assert [s.heading for s in page.sections][1] == "Example (made up)" and page.meta is None
    with pytest.raises(ValidationError):
        model.Page.model_validate(_page(sections=[_section(s) for s in model.DRAFT_SECTIONS]))
    long = [_section(s, "x" * (model.SECTION_CAPS[s] + 1) if s == "plain" else "w")
            for s in model.SECTION_IDS]  # fmt: skip
    with pytest.raises(ValidationError):
        model.Page.model_validate(_page(sections=long))
    assert model.DRAFT_SECTIONS == ("plain", "example", "how", "costs", "fails")


def test_the_page_meta_is_who_wrote_it_when_and_for_which_release() -> None:
    meta = {"written_by": "Workshop · Mark XXIV", "written_on": "2026-11-24",
            "release": "abcdef0", "version": "v6.3.2"}  # fmt: skip
    assert model.PageMeta.model_validate(meta).model_dump(mode="json") == meta
    for bad in ({"tier": "balanced"}, {"inr": 1.0}, {"written_by": ""}, {"release": "x"}):
        with pytest.raises(ValidationError):
            model.PageMeta.model_validate({**meta, **bad})


def test_a_pages_file_holds_each_page_once() -> None:
    one = model.Page.model_validate(_page())
    f = model.PagesFile(release="abcdef0", pages=(one,), modules={"demo": "Demo"}, limitations=3)
    assert f.v == 2 and f.limitations == 3
    with pytest.raises(ValidationError):
        model.PagesFile(release="abcdef0", pages=(one, one))


def test_the_old_writer_collections_are_named_for_the_privacy_row() -> None:
    assert model.COLLECTIONS == (
        "book_writer",
        "book_write_lease",
        "book_write_spend",
        "book_drafts",
        "book_trial",
        "book_pages",
    )


# ---- the HTTP contract ---------------------------------------------------------------------------
def test_the_pages_routes() -> None:
    keys = [(m, p) for m, p, *_ in http.ROUTES]
    pages_routes = [k for k in keys if k[1].startswith(http.PAGES_PREFIX)]
    # R6.4 D4: search before `{page_id}`, so "search" is never read as a page id
    assert pages_routes == [
        ("GET", "/v1/book/pages"),
        ("GET", "/v1/book/pages/search"),
        ("GET", "/v1/book/pages/{page_id}"),
    ]
    assert {g for *_, g in http.ROUTES} == {"session"}
    # R6.4 D5, D6: the chapters' two routes, the only others
    rest = [k for k in keys if k not in pages_routes]
    assert rest == [("GET", "/v1/book/chapters"), ("GET", "/v1/book/chapters/{chapter_id}")]


def test_every_refusal_code_fits_the_refusal_model() -> None:
    for code in http.ERRORS:
        assert http.Refusal(error=code, detail="Plain words.").error == code
    assert len(set(http.ERRORS)) == len(http.ERRORS) and "no_pages" in http.ERRORS
