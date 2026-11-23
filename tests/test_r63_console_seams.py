# tests/test_r63_console_seams.py -- R6.3 I0 seams 8 and 9 (docs/plans/r6-3-book-content.md D9,
# D14): the console's joins. console-book.js loads C's `console-book-pages.js` ONCE at the Book
# panel's first open (a script built in JS, never a tag in console.html, which stays
# byte-identical) and hands it its host and deps (R6.3.1 D8: `console-book-writer.js` is gone);
# the show's script
# reader moved into `console-book-script.js` unchanged for today's show and reads the tour's shape
# too (n 1-17, t ids, a picture {visual, facts} per scene): the picture modules get today's picture
# number and the scene's OWN data, Questions as 12 and Closing as 13. book.html loads it first.
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
API = STATIC.parent


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_the_console_sizes_hold() -> None:
    assert _lines(STATIC / "console-book.js") <= 390
    assert _lines(STATIC / "console-book-show.js") <= 370
    assert _lines(STATIC / "console-book-script.js") <= 200
    assert _lines(STATIC / "console-book-tour.js") <= 300
    assert not (STATIC / "console-book-writer.js").exists()  # R6.3.1 D8
    assert _lines(STATIC / "console-book-pages.js") <= 400
    assert _lines(STATIC / "console-book-reader.js") <= 270
    assert _lines(STATIC / "book.html") <= 130
    assert _lines(API / "console.py") <= 473


def test_the_panel_loads_the_pages_once_at_its_first_open_and_never_the_writer() -> None:
    panel = _read("console-book.js")
    assert "'console-book-pages.js'" in panel and "'JarvisBookPages'" in panel
    assert "console-book-writer" not in panel and "JarvisBookWriter" not in panel  # R6.3.1 D8
    assert "if (d.open) { more(); load(); }" in panel and "if (X.pages) return;" in panel
    assert "/static/console-book-pages.js" not in _read("console.html")  # loaded by code
    assert "Object.freeze({ mount, page, more })" in _read("console-book-pages.js")


def test_the_show_page_loads_the_script_reader_before_the_show() -> None:
    html = _read("book.html")
    names = re.findall(r'<script [^>]*src="/static/([^"]+)"', html)
    assert names.index("console-book-script.js") < names.index("console-book-show.js")
    assert "console-book-tour.js" in names
    show = _read("console-book-show.js")
    for moved in ("function normalScene", "function normalScript", "function timeline("):
        assert moved not in show and moved in _read("console-book-script.js")
    assert "SC.normalScript(" in show and "SC.timeline(" in show and "SC.picture(" in show
    assert (
        "/ 13" not in show and "<= 11" not in show
    )  # the fixed scene numbers come from the script


NODE = shutil.which("node")
SHOW = {
    "kind": "show",
    "audience": "owner",
    "release": {"id": "abcdef0", "label": "R6.3", "version": "v6.3.0"},
    "scenes": [
        {
            "n": 2,
            "id": "layers",
            "title": "Eight layers",
            "beats": [{"id": "s02b01", "text": "B."}],
        },
        {
            "n": 1,
            "id": "book",
            "title": "The build book",
            "beats": [{"id": "s01b01", "text": "A."}],
        },
    ],
    "lines": {"ask": {"id": "ask", "text": "Any questions?"}},
    "closing": [{"id": "thanks_owner", "text": "Thank you."}],
    "talk": {"on": True},
}
TOUR = {
    **SHOW,
    "kind": "tour",
    "seconds": 790.5,
    "scenes": [
        {
            "n": 13,
            "id": "wardrobe",
            "title": "Highlight 7 of 7: Wardrobe & Try-on",
            "picture": {"visual": 9, "facts": [{"label": "Catalogue", "group": "wardrobe"}]},
            "chapter": "pg_module_wardrobe",
            "audience": "both",
            "beats": [{"id": "t13b01", "text": "Clothes.", "audience": "both"}],
        },
        {
            "n": 16,
            "id": "costs",
            "title": "What I cost",
            "picture": {"visual": 10, "facts": [{"label": "Rs", "n": 1}]},
            "audience": "owner",
            "beats": [{"id": "s16b01", "text": "A show id in a tour: dropped."}],
        },
    ],
}
RUN = """
global.window = {};
eval(require('fs').readFileSync(process.argv[1], 'utf8'));
const S = window.JarvisBookScript, out = {};
for (const [name, raw] of Object.entries(JSON.parse(process.argv[2]))) {
  const sc = S.normalScript(raw, 'guest');
  const beats = sc ? S.timeline(sc) : [];
  out[name] = sc && { kind: sc.kind, qn: sc.qn, cn: sc.cn, seconds: sc.seconds, scenes: sc.scenes,
    beats: beats.map((b) => [b.scene, b.id]),
    pictures: [...sc.scenes.map((s) => s.n), sc.qn, sc.cn].map((n) => S.picture(sc, n, beats))
      .map((p) => ({ n: p.n, id: p.id, facts: p.facts.map((f) => f.label) })) };
}
process.stdout.write(JSON.stringify(out));
"""


def _run(**scripts: Any) -> dict[str, Any]:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "-e", RUN, str(STATIC / "console-book-script.js"), json.dumps(scripts)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    got: dict[str, Any] = json.loads(done.stdout)
    return got


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_todays_show_reads_as_before_with_questions_12_and_closing_13() -> None:
    got = _run(show=SHOW)["show"]
    assert (got["kind"], got["qn"], got["cn"], got["seconds"]) == ("show", 12, 13, None)
    assert [s["n"] for s in got["scenes"]] == [1, 2]  # sorted, as before
    assert got["scenes"][0] == {
        "n": 1,
        "id": "book",
        "title": "The build book",
        "beats": [{"id": "s01b01", "text": "A.", "focus": ""}],
        "facts": [],
    }
    assert got["beats"] == [[1, "s01b01"], [2, "s02b01"], [12, "ask"], [13, "thanks_owner"]]
    assert [p["n"] for p in got["pictures"]] == [1, 2, 12, 13]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_a_tour_scene_draws_todays_picture_with_its_own_facts() -> None:
    got = _run(tour=TOUR)["tour"]
    assert (got["kind"], got["qn"], got["cn"], got["seconds"]) == ("tour", 18, 19, 790.5)
    assert [s["n"] for s in got["scenes"]] == [13]  # T16's show-style id is refused: no beat left
    scene = got["scenes"][0]
    assert scene["picture"] == {
        "visual": 9,
        "facts": [{"label": "Catalogue", "value": "", "n": None, "group": "wardrobe", "flag": ""}],
    }
    assert scene["chapter"] == "pg_module_wardrobe" and scene["audience"] == "both"
    assert got["beats"] == [[13, "t13b01"], [18, "ask"], [19, "thanks_owner"]]
    assert got["pictures"] == [
        {"n": 9, "id": "wardrobe", "facts": ["Catalogue"]},
        {"n": 12, "id": "questions", "facts": []},
        {"n": 13, "id": "closing", "facts": []},
    ]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_a_tour_line_id_is_never_read_as_a_show_line_and_back() -> None:
    show_with_t = {
        **SHOW,
        "scenes": [{**SHOW["scenes"][1], "beats": [{"id": "t01b01", "text": "x"}]}],
    }
    assert _run(bad=show_with_t)["bad"] is None  # no show scene is left
