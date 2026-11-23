# tests/test_r63_types.py -- R6.3 I0 seam 3 (docs/plans/r6-3-book-content.md "Data model", D2, D3,
# D6-D9, D11, H2, M4, M6, L4): the types every part builds on. The writer's data model and HTTP
# contract (`buildbook/writer/{model,http}.py`), the tour's two shapes (`buildbook/tour_model.py`),
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
    return {"scenes": [_tour_scene(n) for n in range(1, 18)], "owner": timing, "guest": timing}


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


def test_the_tour_is_seventeen_scenes_inside_the_hard_band() -> None:
    assert len(tm.Tour.model_validate(_tour()).scenes) == 17
    for bad in (599.0, 900.5):
        t = _tour()
        t["owner"] = {**t["owner"], "seconds": bad}
        with pytest.raises(ValidationError):
            tm.Tour.model_validate(t)
    short = {**_tour(), "scenes": _tour()["scenes"][:16]}
    with pytest.raises(ValidationError):
        tm.Tour.model_validate(short)


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
    for page in (*model.TRIAL_PAGES, "pg_chapter_what", "pg_service_google_cloud_text_to_speech"):
        assert re.fullmatch(fm.PAGE_ID, page), page
    assert [c for c, _ in fm.CHAPTERS][1] == "example" and len(fm.CHAPTERS) == 8
    with pytest.raises(ValidationError):
        fm.FactPack.model_validate({"values": {"bad key": {"value": 1, "source": "x"}}})


def test_facts_json_is_capped_at_one_mib() -> None:
    with pytest.raises(ValueError, match="1 MiB"):
        fm.load_facts(b" " * (fm.FACTS_JSON_CAP_BYTES + 1))
    with pytest.raises(ValueError, match="not a v1"):
        fm.load_facts(b'{"v": 2}')


# ---- the writer's model (D3, D7, D8, D11, H2, L4) ------------------------------------------------
def test_the_caps_defaults_are_his_and_the_plans() -> None:
    caps = model.Caps()
    assert (caps.trial, caps.first, caps.release, caps.month, caps.limit_pct) == (
        100,  # his answer of 23 Nov 2026 (the plan proposed Rs 60)
        1_500,
        500,
        1_000,
        80,
    )
    for name, (lo, hi) in model.CAP_BOUNDS.items():
        with pytest.raises(ValidationError):
            model.Caps(**{name: hi + 1})
        with pytest.raises(ValidationError):
            model.Caps(**{name: lo - 1})


def test_the_trial_cap_lets_eight_worst_case_calls_through_and_refuses_the_ninth() -> None:
    hold = 11.84  # D8: one Sonnet first draft's worst case at Rs 95.24
    assert int(model.Caps().trial // hold) == 8 and 9 * hold > model.Caps().trial


def test_nothing_is_granted_before_his_first_yes() -> None:
    granted = model.Pick().confirmed
    assert granted.brain is None and not granted.auto_update and granted.terms_id is None
    assert (granted.caps.trial, granted.caps.first, granted.caps.release, granted.caps.month) == (
        0,
        0,
        0,
        0,
    )
    assert granted.caps.limit_pct == 10 < model.Caps().limit_pct  # the default line is a raise


YES_CASES = [("YES", True), (" YES ", True), ("yes", False), ("Yes", False), ("YES!", False)]
YES_CASES += [("", False), (None, False)]
ABOUT_CASES = [(38, 40), (37, 35), (1_144, 1_140), (301, 300), (15, 15), (12.4, 10), (95, 95)]
ABOUT_CASES += [(104, 100)]


@pytest.mark.parametrize(("typed", "ok"), YES_CASES)
def test_only_an_exact_yes_is_a_yes(typed: object, ok: bool) -> None:
    assert model.is_yes(typed) is ok


@pytest.mark.parametrize(("mid", "about"), ABOUT_CASES)
def test_about_is_the_mid_rounded_to_ten_or_five_under_a_hundred(mid: float, about: int) -> None:
    assert model.about_inr(mid) == about


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


def test_the_page_meta_is_always_the_balanced_tier() -> None:
    meta = {
        "brain": "anthropic",
        "brain_label": "Claude",
        "model": "claude-sonnet-5-5",
        "provider": "anthropic",
        "release": "abcdef0",
        "written_at": "2026-11-24T10:00:00+05:30",
        "attempt": 1,
        "tokens_in": 1,
        "tokens_out": 1,
        "inr": 1.0,
    }
    assert model.PageMeta.model_validate(meta).tier == "balanced"
    with pytest.raises(ValidationError):
        model.PageMeta.model_validate({**meta, "tier": "fast"})


def test_the_pages_index_holds_one_file_a_release_under_its_own_aad() -> None:
    entry = {
        "release": "abcdef0",
        "fid": "bf_" + "1" * 12,
        "size": 10,
        "sha256": SHA,
        "count": 1,
        "dek": "w",
        "sealed_at": "2026-11-24T10:00:00+05:30",
    }
    assert model.PagesIndex.model_validate({"files": [entry]}).find("abcdef0") is not None
    with pytest.raises(ValidationError):
        model.PagesIndex.model_validate({"files": [entry, entry]})
    assert model.aad_pages_index("u1") == "book/pages/u1/v1" != "book/index/u1/v1"
    assert model.INDEX_PURPOSE == "book_index"  # no new keyring purpose (fact 16)


def test_the_collections_and_ids() -> None:
    assert model.COLLECTIONS == (
        "book_writer",
        "book_write_lease",
        "book_write_spend",
        "book_drafts",
        "book_trial",
        "book_pages",
    )
    for pattern, good in ((model.CALL_ID, "wc_" + "0" * 16), (model.ESTIMATE_ID, "we_" + "a" * 12),
                          (model.TERMS_ID, "wt_" + "b" * 12)):  # fmt: skip
        assert re.fullmatch(pattern, good)
    assert not re.fullmatch(model.TERMS_ID, "we_" + "b" * 12)  # an estimate id is never terms


# ---- the HTTP contract ---------------------------------------------------------------------------
def test_the_thirteen_new_routes() -> None:
    keys = [(m, p) for m, p, *_ in http.ROUTES]
    assert len(keys) == 13 == len(set(keys))
    assert {g for *_, g in http.ROUTES} == {"console", "session"}
    assert [p for _, p, *_, g in http.ROUTES if g == "session"] == [
        "/v1/book/pages",
        "/v1/book/pages/{page_id}",
    ]
    assert all(p.startswith((http.WRITER_PREFIX, http.PAGES_PREFIX)) for _, p in keys)


def test_every_refusal_code_fits_the_refusal_model() -> None:
    for code in http.ERRORS:
        assert http.Refusal(error=code, detail="Plain words.").error == code
    assert http.NOT_BUILT in http.ERRORS and len(set(http.ERRORS)) == len(http.ERRORS)
    need = http.YesNeeded(detail="d", terms_id="wt_" + "c" * 12, words=("Up to Rs 500.",))
    assert need.error == "yes_needed"
