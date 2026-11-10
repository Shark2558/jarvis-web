# tests/test_book_gen_determinism.py
"""R6 D2-D5 end to end: `gen.write` assembles the Book from the sections, the show and the digest;
the same commit gives byte-identical book.json and source.zip; `release.json` names both
SHA-256s; `--check` builds twice and compares; `--best-effort` writes a release with `error` and no
book; the scrub holds across the whole book (and its control, scrub off, leaks)."""

from __future__ import annotations

import hashlib
import io
import itertools
import json
import zipfile
from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, ROOT, fixture_needles, fixture_repo, plant_personal

from jarvis.buildbook.gen import __main__ as cli
from jarvis.buildbook.gen import write
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import NoScrub
from jarvis.buildbook.model import (
    BOOK_SCENES,
    FLOW_IDS,
    SECTION_IDS,
    Release,
    canonical_bytes,
    load_book,
)

OPTS = write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT")


@pytest.fixture()
def fx(tmp_path: Path) -> Repo:
    return Repo.from_git(fixture_repo(tmp_path))


def test_the_fixture_builds_a_whole_book(fx: Repo) -> None:
    built = write.build(fx, OPTS)
    book = load_book(built.book)
    assert canonical_bytes(book) == built.book  # canonical bytes (sorted keys, NFC, compact)
    assert set(book.sections()) == set(SECTION_IDS)
    assert book.release.id == fx.id and book.release.label == "R2.1"
    assert [s.n for s in book.show.scenes] == list(range(1, BOOK_SCENES + 1))
    assert tuple(w.id for w in book.workflows) == FLOW_IDS
    assert {p.name for p in book.architecture.packages} == {"core", "notify", "vault"}
    assert book.digest.chunks and book.digest.overview.startswith("JARVIS build book")
    zf = zipfile.ZipFile(io.BytesIO(built.source))
    assert f"JARVIS-source-{fx.id}/THIRD_PARTY.json" in zf.namelist()


def test_release_json_names_both_digests(fx: Repo) -> None:
    built = write.build(fx, OPTS)
    rel = built.release
    assert isinstance(rel, Release) and rel.ok
    assert (rel.id, rel.sha, rel.label, rel.committed_at) == (
        fx.id,
        fx.sha,
        "R2.1",
        fx.committed_at,
    )
    assert rel.book_sha256 == hashlib.sha256(built.book).hexdigest()
    assert rel.source_sha256 == hashlib.sha256(built.source).hexdigest()
    assert rel.source_bytes == len(built.source) and rel.skipped == 0
    data = json.loads(write.release_bytes(rel))
    assert list(data) == sorted(data) and Release.model_validate(data) == rel


def test_the_same_commit_gives_the_same_bytes(tmp_path: Path) -> None:
    a = Repo.from_git(fixture_repo(tmp_path, "a"))
    b = Repo.from_git(fixture_repo(tmp_path, "b"))
    one, two = write.build(a, OPTS), write.build(b, OPTS)
    assert (one.book, one.source) == (two.book, two.source)
    assert write.release_bytes(one.release) == write.release_bytes(two.release)


def test_check_builds_twice_and_catches_drift(fx: Repo) -> None:
    assert write.check(fx, OPTS).book == write.build(fx, OPTS).book
    counter = itertools.count()
    drifting = write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: f"MIT-{next(counter)}")
    with pytest.raises(GenError, match="differ"):
        write.check(fx, drifting)


def test_personal_data_never_reaches_the_book_and_the_control_leaks(tmp_path: Path) -> None:
    root = fixture_repo(tmp_path)
    plant_personal(root)
    r = Repo.from_git(root)
    email, phone, name = fixture_needles()
    needles = [email, phone, *name.split()]
    clean = write.build(r, OPTS).book.decode("utf-8")
    assert not any(n in clean for n in needles)
    raw = write.build(
        r, write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT", scrubber=NoScrub())
    )
    assert all(n in raw.book.decode("utf-8") for n in needles)


def test_a_flow_naming_a_missing_function_fails_the_build(fx: Repo) -> None:
    with pytest.raises(GenError, match="flow"):
        write.build(fx, write.Options(licence=lambda _n: "MIT"))  # the real flows


def test_an_unmapped_package_fails_the_build(fx: Repo) -> None:
    with pytest.raises(GenError, match="no layer"):
        write.build(fx, write.Options(flows=FIXTURE_FLOWS, layer_of={}, licence=lambda _n: "MIT"))


def test_a_book_over_its_cap_is_refused(fx: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write, "BOOK_JSON_CAP_BYTES", 1_000)
    with pytest.raises(GenError, match="book.json"):
        write.build(fx, OPTS)


def test_write_puts_three_files_and_the_release_last(fx: Repo, tmp_path: Path) -> None:
    built = write.build(fx, OPTS)
    out = tmp_path / "out"
    write.write(out, built)
    assert sorted(p.name for p in out.iterdir()) == ["book.json", "release.json", "source.zip"]
    assert (out / "book.json").read_bytes() == built.book
    assert Release.model_validate_json((out / "release.json").read_bytes()) == built.release


def test_an_error_release_has_no_book(fx: Repo, tmp_path: Path) -> None:
    out = tmp_path / "out"
    write.write(out, write.build(fx, OPTS))
    rel = write.write_error(out, fx, "the code snapshot is 16.0 MB, over its 15.0 MB cap")
    assert not rel.ok and rel.book_sha256 is None and rel.id == fx.id
    assert sorted(p.name for p in out.iterdir()) == ["release.json"]  # no stale book left


# ---- the show script and the digest (D15, D11) -----------------------------------------------
def test_the_show_draws_its_facts_from_the_book(fx: Repo) -> None:
    from jarvis.buildbook.gen import show
    from jarvis.buildbook.model import LAYERS

    book = load_book(write.build(fx, OPTS).book)
    scenes = {s.id: s for s in book.show.scenes}
    layers = scenes["layers"]
    assert [b.focus for b in layers.beats] == [lid for lid, _ in LAYERS]
    assert any(f.label == "Core Reasoning Engine" and f.n == 1 for f in layers.facts)
    turn = scenes["turn"]
    assert turn.beats[1].focus == "core.loop:Loop.turn" and turn.facts[0].group == "step"
    costs_scene = scenes["costs"]
    assert all(f.value.startswith("₹") for f in costs_scene.facts)
    later = scenes["later"]
    assert len(later.beats) == 2 + min(show.LATER_BEATS, len(book.limitations))
    assert all(len(s.facts) <= show.MAX_FACTS for s in book.show.scenes)
    assert all(b.text.strip() for s in book.show.scenes for b in s.beats)


def test_the_digest_is_chunked_by_section(fx: Repo) -> None:
    book = load_book(write.build(fx, OPTS).book)
    d = book.digest
    assert len(d.overview) <= 2_000 and "R2.1" in d.overview
    assert {c.section for c in d.chunks} <= {
        "architecture", "fit", "stack", "libraries", "integrations", "workflows",
        "limitations", "costs", "decisions",
    }  # fmt: skip
    assert [c.id for c in d.chunks] == [f"c{n:03d}" for n in range(1, len(d.chunks) + 1)]
    assert all(0 < len(c.text) <= 1_500 for c in d.chunks)
    assert any("Loop.turn" in c.text for c in d.chunks if c.section == "workflows")


@pytest.mark.parametrize(
    ("label", "want"),
    [
        ("Telegram delivers it", "Telegram delivers it"),
        ("JARVIS's voice speaks it", "JARVIS's voice speaks it"),
        ("Cloud Scheduler calls in", "Cloud Scheduler calls in"),
        ("The alert goes out", "the alert goes out"),
    ],
)
def test_joined_labels_keep_names_capitalised(label: str, want: str) -> None:
    from jarvis.buildbook.gen import show

    assert show._lower_first(label) == want


# ---- the command line ------------------------------------------------------------------------
def test_the_cli_refuses_and_best_effort_writes_an_error_release(fx: Repo, tmp_path: Path) -> None:
    out = tmp_path / "out"
    # the fixture has no licence table (and the real flows name code it doesn't have): a plain
    # failure ...
    assert cli.main(["--repo", str(fx.root), "--out", str(out)]) == 1
    assert not out.exists()
    # ... and with --best-effort the deploy goes on: release.json with the error, no book
    assert cli.main(["--repo", str(fx.root), "--out", str(out), "--best-effort"]) == 0
    rel = Release.model_validate_json((out / "release.json").read_bytes())
    assert rel.error and "licences" in rel.error and not (out / "book.json").exists()


def test_the_cli_outside_a_checkout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--repo", str(tmp_path), "--best-effort", "--out", str(tmp_path / "o")]) == 0
    assert not (tmp_path / "o" / "release.json").exists()  # no commit: nothing to name
    assert "build book" in capsys.readouterr().err


def test_the_real_repo_builds_and_the_show_is_about_six_thousand_characters() -> None:
    built = write.build(Repo.from_git(ROOT))
    book = load_book(built.book)
    spoken = sum(len(b.text) for s in book.show.scenes for b in s.beats)
    assert 4_500 <= spoken <= 8_000, spoken
    assert len(built.book) <= 2 * 1024 * 1024 and built.release.skipped > 0
    assert book.release.label == "R6"
