# tests/test_r61_book_version.py -- R6.1 decision 3: the build book keeps its commit id
# (RELEASE_ID stays ^[0-9a-f]{7}$, so sealed R6 books still open) and gains an optional
# `version` ("v6.1.0"), read from the documented checkout's src/jarvis/__init__.py, shown next
# to the id. Books, releases and sealed index entries written before R6.1 have none.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, ROOT, commit_all, fixture_repo
from pydantic import ValidationError

import jarvis
from jarvis.buildbook.gen import fallback, write
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.model import (
    RELEASE_ID,
    VERSION,
    Release,
    ReleaseRef,
    SealedFile,
    SealedRelease,
    canonical_bytes,
    load_book,
)
from jarvis.buildbook.release import ReleaseSource
from jarvis.buildbook.seal_index import BookIndex

OPTS = write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT")
R6_BOOK = ROOT / "tests" / "fixtures" / "book" / "_book"  # written by R6 code: no `version`
SHA = "4a7068351dbb76d099f3440b44559e7d739e4e3d"
REF = {"id": SHA[:7], "sha": SHA, "label": "R6.1", "committed_at": "2026-11-11T09:00:00+05:30"}


def _versioned(tmp: Path, init: str = '__version__ = "6.1.0"\n') -> Repo:
    root = fixture_repo(tmp)
    (root / "src" / "jarvis" / "__init__.py").write_text(init, encoding="utf-8")
    commit_all(root, "version")
    return Repo.from_git(root)


# ---- the model -----------------------------------------------------------------------------
def test_the_release_id_pattern_is_unchanged() -> None:
    assert RELEASE_ID == r"^[0-9a-f]{7}$"


@pytest.mark.parametrize("good", ["v6.1.0", "v0.12.1", "v10.0.0"])
def test_a_version_is_a_v_and_three_numbers(good: str) -> None:
    assert ReleaseRef(**REF, version=good).version == good


@pytest.mark.parametrize("bad", ["6.1.0", "v6.1", "v6.1.0-rc1", "V6.1.0", "", "v6.1.0 "])
def test_anything_else_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        ReleaseRef(**REF, version=bad)


def test_the_version_is_optional_and_carried_by_ref_and_the_sealed_row() -> None:
    assert ReleaseRef(**REF).version is None
    rel = Release(**REF, version="v6.1.0", error="the build book failed")
    assert rel.ref().version == "v6.1.0"
    sealed = SealedRelease(
        **rel.ref().model_dump(),
        sealed_at="2026-11-11T09:10:00+05:30",
        files=tuple(
            SealedFile(kind=k, fid=f"bf_{n:012x}", size=1, sha256="0" * 64, count=1, dek="w")
            for n, k in enumerate(("book", "source"))
        ),
    )
    assert sealed.view()["version"] == "v6.1.0"
    assert set(sealed.view()) == {"id", "label", "version", "sealed_at", "mb"}
    assert sealed.model_dump()["version"] == "v6.1.0"


def test_a_sealed_r6_book_and_its_release_still_open() -> None:
    """The committed fixture was written by R6 code (no `version` anywhere)."""
    raw = (R6_BOOK / "book.json").read_bytes()
    assert "version" not in json.loads(raw)["release"]
    assert "version" not in json.loads((R6_BOOK / "release.json").read_bytes())
    assert canonical_bytes(load_book(raw)) == raw  # its canonical bytes are unchanged
    assert load_book(raw).release.version is None
    source = ReleaseSource(R6_BOOK)
    current = source.current()
    assert current is not None and current.ok and current.version is None
    assert source.book().release.id == current.id


def test_a_sealed_index_from_r6_still_parses() -> None:
    row = {
        **{k: REF[k] for k in ("id", "sha", "committed_at")},
        "label": "R6",
        "sealed_at": "2026-11-10T19:40:00+05:30",
        "files": [
            {"kind": k, "fid": f"bf_{n:012x}", "size": 1, "sha256": "0" * 64, "count": 1}
            | {"dek": "w"}
            for n, k in enumerate(("book", "source"))
        ],
    }
    index = BookIndex.model_validate_json(json.dumps({"v": 1, "releases": [row]}))
    assert index.releases[0].version is None
    assert set(index.releases[0].view()) == {"id", "label", "sealed_at", "mb"}  # as in R6
    assert "version" not in index.model_dump(mode="json")["releases"][0]  # re-sealed as written


# ---- the generator ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "want"),
    [
        ('__version__ = "6.1.0"\n', "v6.1.0"),
        ("# a comment\n__version__ = '0.12.1'\n", "v0.12.1"),
        ('__version__ = "6.1"\n', None),
        ('__version__ = "6.1.0rc1"\n', None),
        ('version = "6.1.0"\n', None),
        ("", None),
        (None, None),
    ],
)
def test_the_version_is_read_from_the_checkouts_init(text: str | None, want: str | None) -> None:
    assert fallback.version_of(text) == want
    if want:
        assert ReleaseRef(**REF, version=want)  # what it reads always fits the model


def test_a_versioned_checkout_names_its_version_in_book_and_release(tmp_path: Path) -> None:
    repo = _versioned(tmp_path)
    built = write.build(repo, OPTS)
    book = load_book(built.book)
    assert book.release.version == "v6.1.0" and built.release.version == "v6.1.0"
    assert book.release.id == repo.id  # still the commit
    assert '"version": "v6.1.0"' in write.release_bytes(built.release).decode()


def test_the_version_is_said_next_to_the_commit_in_the_show_and_the_digest(tmp_path: Path) -> None:
    repo = _versioned(tmp_path)
    book = load_book(write.build(repo, OPTS).book)
    first = book.show.scenes[0].beats[0].text
    assert f"version v6.1.0, commit {repo.id}" in first
    assert f"version v6.1.0, commit {repo.id}" in book.digest.overview
    facts = [(f.label, f.value) for f in book.show.scenes[0].facts]
    assert ("Commit", repo.id) in facts and len(facts) <= 6  # scene 1 draws six tiles: unchanged


def test_an_unversioned_checkout_builds_as_before(tmp_path: Path) -> None:
    repo = Repo.from_git(fixture_repo(tmp_path))
    built = write.build(repo, OPTS)
    book = load_book(built.book)
    assert book.release.version is None and built.release.version is None
    assert "version" not in book.show.scenes[0].beats[0].text


def test_two_builds_of_a_versioned_commit_are_byte_identical(tmp_path: Path) -> None:
    repo = _versioned(tmp_path)
    assert write.check(repo, OPTS).release.version == "v6.1.0"


def test_an_unversioned_release_writes_r6s_bytes() -> None:
    rel = Release(**{**REF, "label": "R6"}, error="boom")
    assert '"version"' not in write.release_bytes(rel).decode()
    doc = fallback.release_doc(REF["sha"], "R6", REF["committed_at"], "boom")
    assert doc == write.release_bytes(rel)


def test_a_failed_build_names_the_version_too(tmp_path: Path) -> None:
    repo = _versioned(tmp_path)
    out = tmp_path / "out"
    rel = write.write_error(out, repo, "boom")
    assert rel.version == "v6.1.0" and not rel.ok


def test_the_fallback_writes_the_same_bytes_with_the_version(tmp_path: Path) -> None:
    """Best effort without the generator's packages: release.json still names the version, in
    the bytes `write.release_bytes` would write."""
    repo = _versioned(tmp_path)
    code = (
        "import sys; sys.modules['pydantic'] = None\n"
        "from jarvis.buildbook.gen import __main__ as m\n"
        f"sys.exit(m.main(['--repo', {str(repo.root)!r}, '--out', {str(tmp_path / 'o')!r},"
        " '--best-effort']))\n"
    )
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    raw = (tmp_path / "o" / "release.json").read_bytes()
    rel = Release.model_validate_json(raw)
    assert rel.version == "v6.1.0" and rel.error
    assert raw == write.release_bytes(rel)


def test_the_real_checkout_carries_this_releases_version() -> None:
    text = (ROOT / fallback.VERSION_FILE).read_text(encoding="utf-8")
    assert fallback.version_of(text) == f"v{jarvis.__version__}"  # the number: test_about
    assert VERSION == r"^v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,4}$"
