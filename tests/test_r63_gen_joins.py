# tests/test_r63_gen_joins.py -- R6.3 I0 seam 5 (docs/plans/r6-3-book-content.md D2, D3, D9): the
# generator's joins. `gen/write.py` calls A's `facts.build`, A's `pages_index.build` and D's
# `tour.build` (with the show, I1: D's `from_show` pictures), writes `_book/facts.json` beside
# book.json (its SHA-256 in release.json as `facts_sha256`), checks it twice with `--check`, scrubs
# it (`Scrubber.verify`, H6) and caps it at 2 MiB (I1: 1 MiB at I0; the real pack was at 97 %),
# saying a warning past 80 %; `ReleaseSource.facts()` reads it back verified; `gen/tour.json` (D's
# 17 scenes) is package data; a stale facts.json is cleared first.
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, fixture_repo

from jarvis.buildbook import release as release_mod
from jarvis.buildbook.facts_model import (
    CHAPTERS,
    FACT_TOUR_KEYS,
    FACTS_FILE,
    FACTS_JSON_CAP_BYTES,
    FACTS_JSON_WARN_BYTES,
    FactPack,
    FactValue,
    load_facts,
)
from jarvis.buildbook.gen import facts, fallback, pages_index, runner, tour, write
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import MIB, Release, Show, load_book
from jarvis.buildbook.ports import BookUnavailable
from jarvis.buildbook.tour_model import TourScript

OPTS = write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT")


@pytest.fixture()
def fx(tmp_path: Path) -> Repo:
    return Repo.from_git(fixture_repo(tmp_path))


def test_a_fixture_s_pack_has_no_tour_keys_and_its_eight_chapters(fx: Repo) -> None:
    built = write.build(fx, OPTS)  # I1 (INTEGRATION-A 5.1): A's pack, no longer I0's empty one
    pack = load_facts(built.facts)
    assert not set(FACT_TOUR_KEYS) & set(pack.values) and pack.release == built.release.ref()
    assert [p.id for p in pack.pages] == [f"pg_chapter_{c}" for c, _ in CHAPTERS]
    assert load_book(built.book).tour is None
    assert built.release.facts_sha256 == hashlib.sha256(built.facts).hexdigest()


def test_the_parts_functions_are_called_with_the_repo_and_the_pack(
    fx: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    value = FactValue(value=73, source="docs/architecture/JARVIS-Architecture.md")

    def fake_facts(repo: Repo, scrub: object) -> FactPack:
        seen.append("facts")
        return FactPack(values={"cards.count": value})

    def fake_pages(repo: Repo, pack: FactPack) -> tuple[()]:
        seen.append(f"pages:{pack.value('cards.count')}")
        return ()

    def fake_tour(repo: Repo, pack: FactPack, show: object = None) -> None:
        shown = "show" if isinstance(show, Show) and show.scenes else "no show"  # D's from_show
        seen.append(f"tour:{pack.value('cards.count')}:{shown}")

    monkeypatch.setattr(facts, "build", fake_facts)
    monkeypatch.setattr(pages_index, "build", fake_pages)
    monkeypatch.setattr(tour, "build", fake_tour)
    built = write.build(fx, OPTS)
    assert seen == ["facts", "pages:73", "tour:73:show"]
    assert load_facts(built.facts).value("cards.count") == 73


def test_check_builds_the_facts_twice_and_catches_drift(
    fx: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert write.check(fx, OPTS).facts == write.build(fx, OPTS).facts
    counter = itertools.count()

    def drifting(repo: Repo, scrub: object) -> FactPack:
        return FactPack(values={"n": FactValue(value=next(counter), source="x")})

    monkeypatch.setattr(facts, "build", drifting)
    with pytest.raises(GenError, match="facts.json"):
        write.check(fx, OPTS)


def test_personal_text_in_the_facts_fails_the_build(
    fx: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak = FactValue(value="write to someone@example.org", source="x")
    monkeypatch.setattr(facts, "build", lambda r, s: FactPack(values={"leak": leak}))
    with pytest.raises(GenError, match="values.leak"):
        write.build(fx, OPTS)


def test_facts_over_their_cap_fail_the_build(fx: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write, "FACTS_JSON_CAP_BYTES", 100)
    with pytest.raises(GenError, match="facts.json is .* bytes, over its 2 MiB cap"):
        write.build(fx, OPTS)


def test_facts_json_is_capped_at_two_mib_and_warns_past_eighty_percent() -> None:
    # I1 (INTEGRATION-A 5.4): A's real pack is 1,018,018 bytes after the join, 97 % of 1 MiB;
    # an overflow means no book, so the cap is 2 MiB and the generator warns from 80 % on
    assert FACTS_JSON_CAP_BYTES == 2 * MIB and FACTS_JSON_WARN_BYTES == 1_677_721
    assert write.facts_warning(FACTS_JSON_WARN_BYTES) is None
    words = write.facts_warning(FACTS_JSON_WARN_BYTES + 1)
    assert words == "facts.json is 1,677,722 bytes, over 80 % of its 2 MiB cap"
    with pytest.raises(ValueError, match="2 MiB"):
        load_facts(b" " * (FACTS_JSON_CAP_BYTES + 1))


def test_the_generator_says_the_warning_on_stderr(
    fx: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built = write.build(fx, OPTS)
    big = dataclasses.replace(built, facts=b" " * (FACTS_JSON_WARN_BYTES + 1))
    monkeypatch.setattr(write, "check", lambda repo: big)
    args = argparse.Namespace(repo=fx.root, out=None, check=True, best_effort=False)
    assert runner.run(args) == 0
    err = capsys.readouterr().err
    assert "build book warning: facts.json is 1,677,722 bytes, over 80 % of its 2 MiB cap" in err
    monkeypatch.setattr(write, "check", lambda repo: built)
    assert runner.run(args) == 0 and "warning" not in capsys.readouterr().err


def test_write_puts_facts_json_before_the_release(fx: Repo, tmp_path: Path) -> None:
    built = write.build(fx, OPTS)
    out = tmp_path / "out"
    write.write(out, built)
    names = sorted(p.name for p in out.iterdir())
    assert names == ["book.json", FACTS_FILE, "release.json", "source.zip"]
    assert (out / FACTS_FILE).read_bytes() == built.facts
    rel = Release.model_validate_json((out / "release.json").read_bytes())
    assert rel.facts_sha256 == hashlib.sha256(built.facts).hexdigest()


def test_a_stale_facts_json_is_cleared_first(tmp_path: Path) -> None:
    out = tmp_path / "o"
    out.mkdir()
    for name in (FACTS_FILE, f".{FACTS_FILE}.tmp", "keep.txt"):
        (out / name).write_bytes(b"old")
    fallback.clear(out)
    assert sorted(p.name for p in out.iterdir()) == ["keep.txt"]


def test_the_release_source_reads_the_facts_verified(fx: Repo, tmp_path: Path) -> None:
    out = tmp_path / "book"
    write.write(out, write.build(fx, OPTS))
    src = release_mod.ReleaseSource(out)
    assert src.facts().release == src.current().ref()  # type: ignore[union-attr]
    (out / FACTS_FILE).write_bytes(b'{"v":1}')  # changed after the build: never served
    with pytest.raises(BookUnavailable):
        release_mod.ReleaseSource(out).facts()
    assert release_mod.ReleaseSource(out).book() is not None  # the book itself still opens


def test_an_older_release_has_no_facts(fx: Repo, tmp_path: Path) -> None:
    out = tmp_path / "book"
    write.write(out, write.build(fx, OPTS))
    doc = json.loads((out / "release.json").read_text(encoding="utf-8"))
    doc.pop("facts_sha256")
    (out / "release.json").write_text(json.dumps(doc), encoding="utf-8")
    (out / FACTS_FILE).unlink()
    src = release_mod.ReleaseSource(out)
    assert src.current() is not None and src.book() is not None
    with pytest.raises(BookUnavailable):
        src.facts()


def test_the_tour_script_is_package_data() -> None:
    script = TourScript.model_validate_json(tour.SCRIPT_FILE.read_bytes())  # I1: D's 17 scenes
    assert script == tour.load_script() and len(script.scenes) == 17


def test_an_error_release_names_no_facts(fx: Repo, tmp_path: Path) -> None:
    rel = write.write_error(tmp_path / "o", fx, "a test failure")
    assert rel.facts_sha256 is None and not (tmp_path / "o" / FACTS_FILE).exists()
