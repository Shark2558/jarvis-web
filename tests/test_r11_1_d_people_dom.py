# tests/test_r11_1_d_people_dom.py -- R11.1 Part D, the People script by its BEHAVIOUR (code review
# M3): console-people.js runs in Node on a small DOM (tests/fixtures/r11_1/d_dom.js) with a dossier
# of three profiles, and "Open next" is pressed. Each press must follow exactly ONE card's own link
# (target _blank, rel noopener noreferrer) and never call window.open; R4's "Open all" line put
# back is caught by what it does, not by how it is spelled. And the "Look up" reply card (security
# review H1): it shows the fixed words and the caption line, and only his press researches the name
# in People. Everybody named here is made up.
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from r11_1_fakes_d import run_people_dom

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "src/jarvis/api/static/console-people.js").read_text(encoding="utf-8")
OPEN_NEXT = "if (next) next.a.click();"
OPEN_ALL = "S.links.forEach((l) => window.open(l.url, '_blank', 'noopener,noreferrer'));"  # R4's
NAME = "Lekha Examplekar"
LINKS = [
    "https://www.linkedin.com/in/example-person-0001",
    "https://en.wikipedia.org/wiki/Lekha_Examplekar",
    "https://x.com/example_person_0001",
]
DOSSIER: dict[str, Any] = {
    "name": NAME,
    "profiles": [
        {"platform": "linkedin", "url": LINKS[0], "title": f"{NAME} - Minister"},
        {"platform": "wikipedia", "url": LINKS[1], "title": f"{NAME} - an example article"},
        {"platform": "x", "url": LINKS[2], "title": "@example_person_0001"},
    ],
    "findings": [],
    "summary": "A made-up minister.",
    "spoken": "A made-up minister.",
    "ambiguous": False,
    "no_ai": False,
    "note": "",
}
WORDS = f"The picture's text names {NAME}. Press 'Look up' to check them with your people research."
CARD = {
    "kind": "people_offer",
    "name": NAME,
    "caption": f"MINISTER {NAME.upper()}",
    "words": WORDS,
    "button": "Look up",
}


def test_each_press_of_open_next_follows_exactly_one_cards_own_link() -> None:
    got = run_people_dom(JS, DOSSIER, presses=len(LINKS) + 1)

    assert [p["followed"] for p in got["presses"]] == [[u] for u in LINKS] + [[]]
    assert got["opens"] == 0 and all(p["opened"] == 0 for p in got["presses"])
    assert [p["button"] for p in got["presses"]] == [
        "Open next",
        "Open next",
        "All opened",
        "All opened",  # pressed once more: it is disabled and opens nothing
    ]
    assert got["presses"][-1]["disabled"] is True
    assert got["states"] == ["Opened"] * len(LINKS)


def test_every_card_has_a_real_link_that_opens_in_its_own_tab_without_opener_access() -> None:
    got = run_people_dom(JS, DOSSIER)

    assert [link["href"] for link in got["links"]] == LINKS
    assert all(
        (link["target"], link["rel"], link["text"])
        == ("_blank", "noopener noreferrer", "Open in browser")
        for link in got["links"]
    )


def test_r4s_open_all_put_back_is_caught_by_what_it_does() -> None:
    assert OPEN_NEXT in JS
    got = run_people_dom(JS.replace(OPEN_NEXT, OPEN_ALL), DOSSIER, presses=1)

    assert got["presses"][0]["followed"] == [] and got["presses"][0]["opened"] == len(LINKS)


def test_the_look_up_card_shows_its_words_and_line_and_only_his_press_researches() -> None:
    got = run_people_dom(JS, None, offer=CARD)["offer"]

    assert got["drawn"] is True and got["buttons"] == ["Look up"]
    assert WORDS in got["text"] and f"Caption read: 'MINISTER {NAME.upper()}'" in got["text"]
    assert got["deck"] == ["people"] and got["name"] == NAME
    assert got["asked"] == [{"path": "/v1/people/research", "body": {"name": NAME}}]


@pytest.mark.parametrize(
    "bad", [{"kind": "places"}, {"button": "Research now"}, {"name": ""}, {"name": 7}]
)
def test_anything_but_a_look_up_card_is_not_drawn(bad: dict[str, Any]) -> None:
    got = run_people_dom(JS, None, offer={**CARD, **bad})["offer"]

    assert got["drawn"] is False and got["asked"] == []
