# tests/test_r63_d_script.py -- R6.3 part D (docs/plans/r6-3-book-content.md "The short tour's
# first script", D9; plan review M6): `gen/tour.json` is the owner's approved script (approval stop
# 2, 23 Nov 2026, 14:53 IST), copied VERBATIM. Every beat's words equal the plan's tables, before
# and after filling, with no doubled word (L1); each scene is pinned as approved (`TOUR_SCENES`);
# its picture borrows the show scene of the same subject (`from_show`) or, for T12-T14, carries its
# own data written from its own words; its `facts` name exactly the keys it uses.
from __future__ import annotations

import re

from r63_fakes_d import PLAN_VALUES, approved, built, fill

from jarvis.buildbook.facts_model import CHAPTERS, FACT_TOUR_KEYS, TOUR_TIMER_KEYS
from jarvis.buildbook.gen import modules, tour
from jarvis.buildbook.tour_model import (
    HIGHLIGHTS,
    OWN_PICTURE_DATA,
    TOUR_SCENES,
    FromShow,
)

SCRIPT = tour.load_script()
FROM_SHOW = {
    1: 1,
    2: 2,
    3: 3,
    5: 3,
    4: 5,
    8: 5,
    6: 4,
    9: 4,
    10: 4,
    7: 6,
    11: 7,
    15: 9,
    16: 10,
    17: 11,
}
DOUBLED = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
KEY = re.compile(r"\{\{([a-z0-9_.]+)\}\}")


def test_the_plan_still_holds_the_approved_script() -> None:
    """The reader of the plan's tables sees 17 scenes and 55 beats; three lines typed here by hand
    from the plan guard the reader itself."""
    scenes = approved()
    assert [s.n for s in scenes] == list(range(1, 18))
    beats = {b.id: b for s in scenes for b in s.beats}
    assert len(beats) == 55
    assert beats["t03b01"].text == (
        "Let's follow one request from start to finish. My owner taps the microphone and says: "
        '"Add a dentist appointment on Friday at 5 pm."'
    )
    assert beats["t16b01"].text.startswith("This scene is for you only, {h}. The bars are my")
    assert beats["t17b02"].text == (
        "Next: {{roadmap.next}}. After that: {{roadmap.after}}. The full book's planned chapter "
        "lists the rest, and goes deeper into every part you've seen today."
    )
    assert (beats["t13b03"].audience, beats["t13b04"].audience) == ("owner", "guest")
    assert [s.n for s in scenes if s.audience == "owner"] == [16]


def test_every_spoken_line_is_the_approved_one() -> None:
    plan = {b.id: b for s in approved() for b in s.beats}
    mine = {b.id: b for s in SCRIPT.scenes for b in s.beats}
    assert list(mine) == list(plan)
    for bid, beat in mine.items():
        assert (beat.text, beat.audience) == (plan[bid].text, plan[bid].audience), bid
    filled = built()
    assert filled is not None
    for audience, minutes in ((filled.owner, 14), (filled.guest, 13)):
        values = {**PLAN_VALUES, "tour.minutes": minutes}
        for scene in audience.scenes:
            for beat in scene.beats:
                assert beat.text == fill(plan[beat.id].text, values), beat.id
                assert not DOUBLED.search(beat.text), beat.id


def test_each_scene_is_pinned_as_approved() -> None:
    plan = approved()
    assert [(s.n, s.title, s.picture, s.audience) for s in plan] == [
        (n, title, visual, who) for n, _, title, visual, who in TOUR_SCENES
    ]
    for scene, pinned in zip(SCRIPT.scenes, TOUR_SCENES, strict=True):
        assert (scene.n, scene.id, scene.title, scene.picture.visual, scene.audience) == pinned
        assert all(b.id.startswith(f"t{scene.n:02d}b") for b in scene.beats)
    highlights = [s.id for s in SCRIPT.scenes if s.title.startswith("Highlight ")]
    assert tuple(highlights) == HIGHLIGHTS


def test_each_picture_borrows_its_show_scene_or_carries_its_own_words() -> None:
    for scene in SCRIPT.scenes:
        facts = scene.picture.facts
        if scene.n in OWN_PICTURE_DATA:
            assert isinstance(facts, tuple) and facts, scene.n
        else:
            assert isinstance(facts, FromShow) and facts.from_show == FROM_SHOW[scene.n], scene.n
    else_scene = SCRIPT.scenes[13]
    assert [f.label for f in else_scene.picture.facts] == ["{{modules.others}}"]  # type: ignore[union-attr]


def test_each_scene_names_exactly_the_keys_it_uses() -> None:
    known = set(FACT_TOUR_KEYS) | set(TOUR_TIMER_KEYS) | set(tour.PICTURE_KEYS)
    for scene in SCRIPT.scenes:
        texts = [b.text for b in scene.beats]
        if isinstance(scene.picture.facts, tuple):
            texts += [v for f in scene.picture.facts for v in (f.label, f.value, f.group)]
        used = list(dict.fromkeys(k for t in texts for k in KEY.findall(t)))
        assert list(scene.facts) == used, scene.n
        assert set(used) <= known, scene.n


def test_each_scene_names_its_full_book_chapter() -> None:
    pages = {f"pg_chapter_{cid}" for cid, _ in CHAPTERS} | {
        f"pg_module_{m.id}" for m in modules.MODULES
    }
    chapters = {s.n: s.chapter for s in SCRIPT.scenes}
    assert all(c == "" or c in pages for c in chapters.values())
    mine = [chapters[n] for n in range(7, 14)]
    assert mine == [f"pg_module_{m}" for m in modules.TOUR_HIGHLIGHTS]
    assert (chapters[3], chapters[4], chapters[5]) == ("pg_chapter_example",) * 3
    assert chapters[16] == "pg_chapter_costs" and chapters[17] == "pg_chapter_planned"


def test_the_script_file_is_ascii_package_data() -> None:
    raw = tour.SCRIPT_FILE.read_bytes()
    assert raw.isascii()
    assert tour.load_script() == SCRIPT and len(SCRIPT.scenes) == 17
