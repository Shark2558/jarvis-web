# tests/test_r63_gen_joins.py -- R6.3 I0 seam 5 (docs/plans/r6-3-book-content.md D2, D3, D9): the
# generator's joins. `gen/write.py` calls A's `facts.build`, A's `pages_index.build` and D's
# `tour.build` (I0's stubs: an empty pack, no pages, no tour), writes `_book/facts.json` beside
# book.json (its SHA-256 in release.json as `facts_sha256`), checks it twice with `--check`, scrubs
# it (`Scrubber.verify`, H6) and caps it at 1 MiB; `ReleaseSource.facts()` reads it back verified;
# `gen/tour.json` (an empty script) is package data; a stale facts.json is cleared first.
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, fixture_repo

from jarvis.buildbook import release as release_mod
from jarvis.buildbook.facts_model import FACTS_FILE, FactPack, FactValue, load_facts
from jarvis.buildbook.gen import facts, fallback, pages_index, tour, write
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import Release, load_book
from jarvis.buildbook.ports import BookUnavailable
from jarvis.buildbook.tour_model import TourScript

OPTS = write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT")


@pytest.fixture()
def fx(tmp_path: Path) -> Repo:
    return Repo.from_git(fixture_repo(tmp_path))


def test_the_stubs_give_an_empty_pack_no_pages_and_no_tour(fx: Repo) -> None:
    built = write.build(fx, OPTS)
    pack = load_facts(built.facts)
    assert pack.values == {} and pack.pages == () and pack.release == built.release.ref()
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

    def fake_tour(repo: Repo, pack: FactPack) -> None:
        seen.append(f"tour:{pack.value('cards.count')}")

    monkeypatch.setattr(facts, "build", fake_facts)
    monkeypatch.setattr(pages_index, "build", fake_pages)
    monkeypatch.setattr(tour, "build", fake_tour)
    built = write.build(fx, OPTS)
    assert seen == ["facts", "pages:73", "tour:73"]
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


def test_facts_over_one_mib_fail_the_build(fx: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write, "FACTS_JSON_CAP_BYTES", 100)
    with pytest.raises(GenError, match="facts.json"):
        write.build(fx, OPTS)


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


def test_the_empty_tour_script_is_package_data() -> None:
    assert TourScript.model_validate_json(tour.SCRIPT_FILE.read_bytes()).scenes == ()
    assert tour.load_script().scenes == ()


def test_an_error_release_names_no_facts(fx: Repo, tmp_path: Path) -> None:
    rel = write.write_error(tmp_path / "o", fx, "a test failure")
    assert rel.facts_sha256 is None and not (tmp_path / "o" / FACTS_FILE).exists()
