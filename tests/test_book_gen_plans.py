# tests/test_book_gen_plans.py
"""R6 D2, D4: what the generator reads from docs/plans — the release label (the highest
`r<N>[-<M>]` plan), each plan's title and D-headings (three heading styles), the "Architecture
fit" rows, and the Limitations (Not in this plan, Risks, Needs the owner, Open questions,
Deferred: first sentence <= 200 characters, newest plan first, at most 80), all scrubbed (D3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from book_gen_fakes import COMMIT_DATE, ROOT, fixture_needles, fixture_repo, plant_personal

from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import NoScrub, Scrubber, default_scrubber
from jarvis.buildbook.model import MAX_LIMITATIONS

SCRUB = Scrubber(frozenset())

R5 = """# Release R5 — Voice that listens

Status: PLAN v1. Not in
this plan: wake words in other languages, a second voice.

## How it fits the architecture
| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Speak to interrupt | L2 input · voice | 1 | Build now |
| **Mic off** ★ | L1 + privacy | 1 / 7 | Build now |

## Decisions

### D1 · Mostly client-side, no tools, no SDK
Body.

### D2 · The listening loop, new states
- **D2 a.** not a heading

## D13–D14 (integrated review decisions)
- **D13 — A fault never rings at night.** More text.

## Risks
- **Echo**: the speaker feeds the mic. It is cancelled in the browser.
- A long answer cuts off; the next turn
  continues it. Second sentence here.

## Open questions (need the owner)
1. Which voice? The default is Chirp.

## Needs you first (skipped this release)
- A second microphone.
"""

R51 = """# R5.1 — Observations & UI polish (plan)

## Binding decisions
- **D1 — Never change the aesthetics.** Every fix reuses tokens.
- **D1 — Never change the aesthetics.** (repeated later, ignored)

## Deferred
- A dark mode toggle. Later.
"""

SLICE = """# Phase 2 · Slice 11 — Full control

## Decisions
- **D1 Undo bin (`jarvis.undo`).** Before a delete.
- **D2 Risk by preview.** Text.

## 8. Not in this slice
Voice cloning, maybe later. And more.
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Repo:
    d = tmp_path / "docs" / "plans"
    d.mkdir(parents=True)
    (d / "r5-voice.md").write_text(R5, encoding="utf-8")
    (d / "r5-1-observations.md").write_text(R51, encoding="utf-8")
    (d / "phase2-slice11-full-control.md").write_text(SLICE, encoding="utf-8")
    (d / "notes.txt").write_text("not a plan", encoding="utf-8")
    return Repo.from_dir(tmp_path, sha="c" * 40, committed_at=COMMIT_DATE)


def test_the_release_label_is_the_highest_release_plan(repo: Repo, tmp_path: Path) -> None:
    assert plans.release_label(repo) == "R5.1"
    (tmp_path / "docs" / "plans" / "r12-big.md").write_text("# R12\n", encoding="utf-8")
    again = Repo.from_dir(tmp_path, sha="c" * 40, committed_at=COMMIT_DATE)
    assert plans.release_label(again) == "R12"


def test_labels_of_plan_files() -> None:
    assert plans.label_of("docs/plans/r6-build-book.md") == "R6"
    assert plans.label_of("docs/plans/r5-1-observations.md") == "R5.1"
    assert plans.label_of("docs/plans/r2-memory-vault.md") == "R2"
    assert plans.label_of("docs/plans/phase2-slice5c-command-deck.md") == ""


def test_plans_are_newest_first(repo: Repo) -> None:
    got = [p.path.rsplit("/", 1)[1] for p in plans.read_plans(repo, SCRUB)]
    assert got == ["r5-1-observations.md", "r5-voice.md", "phase2-slice11-full-control.md"]


def test_decisions_take_the_title_and_every_heading_style_once(repo: Repo) -> None:
    got = {d.plan.rsplit("/", 1)[1]: d for d in plans.decisions(plans.read_plans(repo, SCRUB))}
    r5 = got["r5-voice.md"]
    assert r5.title == "Release R5 — Voice that listens" and r5.release == "R5"
    assert r5.decisions == (
        "D1 · Mostly client-side, no tools, no SDK",
        "D2 · The listening loop, new states",
        "D13 · A fault never rings at night.",
    )
    assert got["r5-1-observations.md"].decisions == ("D1 · Never change the aesthetics.",)
    assert got["phase2-slice11-full-control.md"].decisions == (
        "D1 · Undo bin (jarvis.undo).",
        "D2 · Risk by preview.",
    )
    assert got["phase2-slice11-full-control.md"].release == ""


def test_fit_rows_come_from_release_plans_only(repo: Repo) -> None:
    rows = plans.fit_rows(plans.read_plans(repo, SCRUB))
    assert [(r.release, r.feature, r.layer, r.phase, r.verdict) for r in rows] == [
        ("R5", "Speak to interrupt", "L2 input · voice", "1", "Build now"),
        ("R5", "Mic off ★", "L1 + privacy", "1 / 7", "Build now"),
    ]


def test_limitations_kinds_first_sentences_and_order(repo: Repo) -> None:
    got = [(x.kind, x.text, x.release) for x in plans.limitations(plans.read_plans(repo, SCRUB))]
    assert got == [
        ("deferred", "A dark mode toggle.", "R5.1"),
        ("not_in_plan", "Wake words in other languages, a second voice.", "R5"),
        ("risk", "Echo: the speaker feeds the mic.", "R5"),
        ("risk", "A long answer cuts off; the next turn continues it.", "R5"),
        ("open_question", "Which voice?", "R5"),
        ("needs_owner", "A second microphone.", "R5"),
        ("not_in_plan", "Voice cloning, maybe later.", ""),
    ]
    assert all(
        x.source.startswith("docs/plans/") for x in plans.limitations(plans.read_plans(repo, SCRUB))
    )


def test_a_not_in_this_plan_lead_in_reads_the_list_after_it(tmp_path: Path) -> None:
    d = tmp_path / "docs" / "plans"
    d.mkdir(parents=True)
    text = "# R2\n\nStatus: x.\n\nNot in this plan:\n- Voice ID. Later.\n- A second camera.\n"
    (d / "r2-x.md").write_text(text, encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="d" * 40, committed_at=COMMIT_DATE)
    got = [(x.kind, x.text) for x in plans.limitations(plans.read_plans(r, SCRUB))]
    assert got == [("not_in_plan", "Voice ID."), ("not_in_plan", "A second camera.")]


def test_a_long_item_is_cut_to_200_characters(tmp_path: Path) -> None:
    d = tmp_path / "docs" / "plans"
    d.mkdir(parents=True)
    long = "word " * 80
    (d / "r1-x.md").write_text(f"# R1\n\n## Risks\n- {long}end.\n", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="d" * 40, committed_at=COMMIT_DATE)
    (lim,) = plans.limitations(plans.read_plans(r, SCRUB))
    assert len(lim.text) <= 200 and lim.text.endswith("…")


def test_at_most_80_limitations(tmp_path: Path) -> None:
    d = tmp_path / "docs" / "plans"
    d.mkdir(parents=True)
    items = "".join(f"- Risk number {i}.\n" for i in range(120))
    (d / "r1-x.md").write_text(f"# R1\n\n## Risks\n{items}", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="d" * 40, committed_at=COMMIT_DATE)
    got = plans.limitations(plans.read_plans(r, SCRUB))
    assert len(got) == MAX_LIMITATIONS and got[0].text == "Risk number 0."


def test_the_fixture_plans(tmp_path: Path) -> None:
    r = Repo.from_git(fixture_repo(tmp_path))
    read = plans.read_plans(r, default_scrubber())
    assert plans.release_label(r) == "R2.1"
    lims = {(x.kind, x.text) for x in plans.limitations(read)}
    assert ("not_in_plan", "Voice, the home camera.") in lims
    assert ("deferred", "Alerts by SMS (it needs a paid service).") in lims
    assert ("open_question", "Should the loop keep more than 20 turns?") in lims
    assert [f.feature for f in plans.fit_rows(read)] == ["Alerts", "Core loop", "Sealed sessions"]


def test_planted_personal_data_is_scrubbed_and_leaks_without_the_scrub(tmp_path: Path) -> None:
    root = fixture_repo(tmp_path)
    plant_personal(root)
    r = Repo.from_git(root)
    needles = [*fixture_needles()[:2], *fixture_needles()[2].split()]

    def texts(scrub: Scrubber) -> str:
        read = plans.read_plans(r, scrub)
        parts = [x.text for x in plans.limitations(read)]
        parts += [d for p in plans.decisions(read) for d in p.decisions]
        return "\n".join(parts)

    clean, raw = texts(default_scrubber()), texts(NoScrub())
    assert not any(n in clean for n in needles)
    assert all(n in raw for n in needles)  # the control: scrub off leaks every one


def test_the_real_plans_parse(tmp_path: Path) -> None:
    r = Repo.from_git(ROOT)
    read = plans.read_plans(r, default_scrubber())
    assert read[0].path == "docs/plans/r6-build-book.md" and read[0].label == "R6"
    r6 = plans.decisions(read)[0]
    assert len(r6.decisions) == 17 and r6.decisions[0].startswith("D1 · Deterministic")
    assert any(f.release == "R6" for f in plans.fit_rows(read))
    lims = plans.limitations(read)
    assert lims[0].release == "R6" and 0 < len(lims) <= MAX_LIMITATIONS
