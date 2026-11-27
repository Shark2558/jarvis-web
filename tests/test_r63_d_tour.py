# tests/test_r63_d_tour.py -- R6.3 part D (docs/plans/r6-3-book-content.md D9, row 380 · tour; plan
# review M6, L1, H1): `gen/tour.build` fills the approved script from the fact pack once per
# audience, times each (145 words a minute, 0.8 s a line, 1.4 s a scene) inside 600-900 s, keeps
# his seven highlights in his order and the running example's two lines, gives a guest no T16, no
# owner-only line and no Rs (lines AND picture facts), copies each borrowed picture from the show
# and refuses a picture without what its visual reads. Any typing mistake is a GenError.
from __future__ import annotations

import json
import re
from typing import Any

import pytest
from r63_fakes_d import OLD_BOOK, PLAN_VALUES, TOUR_FACTS, built, pack, with_tour

from jarvis.buildbook import tour_model
from jarvis.buildbook.gen import modules, tour
from jarvis.buildbook.gen.repo import GenError
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.model import canonical_bytes, load_book
from jarvis.buildbook.tour_model import AIMED_S, HARD_BAND_S, HIGHLIGHTS, Tour, TourScript

RUPEE = re.compile(r"₹|\bRs\b|rupee", re.IGNORECASE)
EXAMPLE = ("Add a dentist appointment on Friday at 5 pm", "Cancel it")


def _tour() -> Tour:
    got = built()
    assert got is not None
    return got


def _script(**changes: Any) -> TourScript:
    """The approved script with one beat's text (by id) or one scene's picture facts replaced."""
    doc = json.loads(tour.SCRIPT_FILE.read_bytes())
    for scene in doc["scenes"]:
        for beat in scene["beats"]:
            if beat["id"] in changes:
                beat["text"] = changes[beat["id"]]
        if f"t{scene['n']:02d}" in changes:
            scene["picture"]["facts"] = changes[f"t{scene['n']:02d}"]
    return TourScript.model_validate(doc)


def _lines(t: tour_model.AudienceTour) -> list[str]:
    return [b.text for s in t.scenes for b in s.beats]


def test_row380_the_tour_is_ten_to_fifteen_minutes_with_his_seven_highlights() -> None:
    t = _tour()
    for who, aud in (("owner", t.owner), ("guest", t.guest)):
        low, high = AIMED_S[who]
        assert low <= aud.seconds <= high, (who, aud.seconds)
        assert HARD_BAND_S[0] <= aud.seconds <= HARD_BAND_S[1]
        assert tuple(s.id for s in aud.scenes if s.title.startswith("Highlight ")) == HIGHLIGHTS
        said = " ".join(_lines(aud))
        assert all(f'"{line}' in said for line in EXAMPLE), who
    assert tuple(modules.TOUR_HIGHLIGHTS)[-1] == "wardrobe" and HIGHLIGHTS[-1] == "wardrobe"


def test_each_audience_is_timed_on_its_own_lines() -> None:
    t = _tour()
    for aud, lines, scenes in ((t.owner, 54, 17), (t.guest, 53, 16)):
        texts = _lines(aud)
        words = sum(len(x.split()) for x in texts)
        assert (aud.lines, len(aud.scenes), aud.words) == (lines, scenes, words)
        assert aud.chars == sum(len(x) for x in texts)
        assert aud.seconds == tour_model.seconds(words, lines, scenes)
    assert 1740 <= t.owner.words <= 1790 and 1680 <= t.guest.words <= 1730  # the plan: 1,762; 1,700


def test_the_minutes_are_each_audiences_own() -> None:
    t = _tour()
    first = {aud: s.scenes[0].beats[0].text for aud, s in (("owner", t.owner), ("guest", t.guest))}
    assert first["owner"].endswith("it takes about 14 minutes.")
    assert first["guest"].endswith("it takes about 13 minutes.")


def test_a_guests_tour_has_no_rupee_no_t16_and_no_owner_only_line() -> None:
    t = _tour()
    guest = t.guest
    assert [s.n for s in guest.scenes] == [n for n in range(1, 18) if n != 16]
    ids = [b.id for s in guest.scenes for b in s.beats]
    assert "t13b03" not in ids and "t13b04" in ids and not any(i.startswith("t16") for i in ids)
    assert not RUPEE.search(guest.model_dump_json())
    owner_ids = [b.id for s in t.owner.scenes for b in s.beats]
    assert "t13b03" in owner_ids and "t16b01" in owner_ids and "t13b04" not in owner_ids
    assert "₹9" in t.owner.model_dump_json()  # the owner's own line keeps its price


def test_a_rupee_in_a_guests_line_is_refused() -> None:
    with pytest.raises(GenError, match="guest"):
        built(pack({**PLAN_VALUES, "release.new": "a ₹5 thing"}))


def test_the_owners_honorific_is_left_for_the_show() -> None:
    t16 = _tour().owner.scenes[15].beats[0].text
    assert t16.startswith(
        "This scene is for you only, {h}. The bars are my prices in rupees, at 95.24"
    )


def test_borrowed_pictures_are_copied_from_the_show() -> None:
    t, show = _tour(), {s.n: s for s in OLD_BOOK.show.scenes}
    owner = {s.n: s for s in t.owner.scenes}
    for n, borrowed in ((1, 1), (2, 2), (3, 3), (5, 3), (6, 4), (16, 10), (17, 11)):
        want = [f.model_dump() for f in show[borrowed].facts]
        assert [f.model_dump() for f in owner[n].picture.facts] == want, n
    guest17 = next(s for s in t.guest.scenes if s.n == 17).picture.facts
    kept = [f for f in show[11].facts if not RUPEE.search(f.model_dump_json())]
    assert [f.model_dump() for f in guest17] == [f.model_dump() for f in kept]
    assert len(kept) < len(show[11].facts)  # the show's planned list names Rs; a guest's drops it


def test_what_else_lists_the_other_modules_from_the_map() -> None:
    else_ = _tour().guest.scenes[13]
    titles = {m.id: m.title for m in modules.MODULES}
    assert [f.label for f in else_.picture.facts] == [titles[m] for m in modules.others()]
    assert len(else_.picture.facts) == 12 and {f.group for f in else_.picture.facts} == {"modules"}
    with pytest.raises(GenError, match="else_count"):
        built(pack({**PLAN_VALUES, "modules.else_count": 13}))


def test_own_pictures_are_filled_from_the_pack() -> None:
    owner = {s.n: s for s in _tour().owner.scenes}
    sos = {f.label: f.value for f in owner[12].picture.facts}
    assert sos["Hold SOS"] == "2 seconds" and sos["Offer to call"] == "112"
    assert {f.group for f in owner[12].picture.facts} == {"phone app", "sos"}
    assert any(f.value == "6 measurements" for f in owner[13].picture.facts)


def test_every_pictures_data_has_what_its_visual_reads() -> None:
    t = _tour()
    for aud in (t.owner, t.guest):
        for scene in aud.scenes:
            assert tour.picture_problems(scene.picture.visual, scene.picture.facts) == [], scene.n


@pytest.mark.parametrize(
    ("visual", "facts", "problem"),
    [
        (9, [{"label": "Talk tile"}], "group"),
        (7, [{"label": "x", "group": "home"}], "edge"),
        (4, [{"label": "x", "group": "other"}], "purpose"),
        (10, [{"label": "x"}], "number"),
        (2, [{"label": "", "value": "L1"}], "label"),
        (3, [], "nothing"),
    ],
)
def test_a_picture_without_what_its_visual_reads_has_a_problem(
    visual: int, facts: list[dict[str, Any]], problem: str
) -> None:
    got = tour.picture_problems(visual, tuple(tour_model.TourFact(**f) for f in facts))
    assert got and problem in " ".join(got)


def test_t12s_picture_without_a_group_is_refused() -> None:
    flat = [{"label": "Talk tile"}, {"label": "Hold SOS", "value": "{{sos.hold_s}} seconds"}]
    with pytest.raises(GenError, match="T12"):
        built(script=_script(t12=flat))


def test_an_unknown_placeholder_is_refused() -> None:
    with pytest.raises(GenError, match="nope.key"):
        built(script=_script(t02b01="I'm built in {{nope.key}} layers."))


def test_a_half_computed_pack_is_refused() -> None:
    values = {k: v for k, v in PLAN_VALUES.items() if k != "sos.hold_s"}
    with pytest.raises(GenError, match="sos.hold_s"):
        built(pack(values))


def test_no_script_or_no_tour_facts_means_no_tour() -> None:
    assert built(script=TourScript()) is None
    assert built(pack({})) is None  # A's stub (I0): an empty pack, no tour
    assert built(pack({"src/jarvis/x.py:LIMIT": 3, "settings.demo": 5})) is None  # no tour key


def test_a_line_over_400_characters_once_filled_is_refused() -> None:
    with pytest.raises(GenError, match="400"):
        built(pack({**PLAN_VALUES, "release.new": "word " * 70}))


@pytest.mark.parametrize(
    "text",
    [
        "I'm built in 8 layers.",
        'My owner says: "Call me at 5." and more.',  # quoted, but not the running example's scene
        "A 2nd try.",
    ],
)
def test_a_digit_typed_outside_a_placeholder_is_refused(text: str) -> None:
    with pytest.raises(GenError, match="digit"):
        built(script=_script(t02b01=text))


def test_the_running_examples_quoted_words_and_3d_may_hold_digits() -> None:
    t = _tour()
    said = " ".join(_lines(t.owner))
    assert '"Add a dentist appointment on Friday at 5 pm."' in said and "grey 3D figure" in said


def test_a_doubled_word_is_refused() -> None:
    with pytest.raises(GenError, match="about about"):
        built(pack({**PLAN_VALUES, "loc.python_code": "about 124 thousand"}))


def test_a_brace_the_show_cannot_fill_is_refused() -> None:
    with pytest.raises(GenError, match="placeholder"):
        built(script=_script(t02b01="I'm built in {layers} layers."))


def test_a_pace_outside_the_hard_band_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tour_model, "PACE_WPM", 290)
    with pytest.raises(GenError, match="600"):
        built()


def test_the_tour_needs_the_show_for_its_borrowed_pictures() -> None:
    with pytest.raises(GenError, match="show"):
        built(show=None)


def test_the_filled_tour_passes_the_scrubber_and_round_trips_in_a_book() -> None:
    t = _tour()
    default_scrubber().verify(t.model_dump(mode="json"))  # no hashed name, path or secret in it
    book = with_tour(OLD_BOOK, t)
    data = canonical_bytes(book)
    assert load_book(data).tour == t and canonical_bytes(load_book(data)) == data
    assert len(data) - len(canonical_bytes(OLD_BOOK)) < 200_000
    assert canonical_bytes(with_tour(OLD_BOOK, built())) == data  # the same facts: the same bytes


def test_the_hand_made_pack_has_every_tour_key() -> None:
    assert set(TOUR_FACTS.values) == set(PLAN_VALUES)
