# tests/test_book_release.py
"""R6 D4: the release id at run time (`jarvis.buildbook.release`). `ReleaseSource` implements
the `BookSource` port: it reads `_book/release.json` (package data, via importlib.resources), checks
both files' SHA-256 ONCE per process, and answers None when there is no book or a file doesn't
match ("This server has no build book"); a failed build's release (with `error`) is returned as
is, and `read`/`book` refuse it. Tests run on the I0 `_book` fixture, copied and tampered with."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from book_gen_fakes import ROOT

from jarvis.buildbook import release
from jarvis.buildbook.model import Book, Release
from jarvis.buildbook.ports import BookSource, BookUnavailable

FIXTURE = ROOT / "tests" / "fixtures" / "book" / "_book"


@pytest.fixture()
def book_dir(tmp_path: Path) -> Path:
    out = tmp_path / "_book"
    shutil.copytree(FIXTURE, out)
    return out


def test_it_is_a_book_source(book_dir: Path) -> None:
    assert isinstance(release.ReleaseSource(book_dir), BookSource)


def test_a_good_release_is_current_and_its_files_verified(book_dir: Path) -> None:
    src = release.ReleaseSource(book_dir)
    cur = src.current()
    assert isinstance(cur, Release) and cur.ok and cur.id == "4a70683" and cur.label == "R2.1"
    data = src.read("source")
    assert hashlib.sha256(data).hexdigest() == cur.source_sha256
    assert hashlib.sha256(src.read("book")).hexdigest() == cur.book_sha256
    book = src.book()
    assert isinstance(book, Book) and book.release.id == cur.id
    assert src.book() is book  # parsed once


@pytest.mark.parametrize("name", ["book.json", "source.zip"])
def test_a_file_that_does_not_match_means_no_book(book_dir: Path, name: str) -> None:
    (book_dir / name).write_bytes((book_dir / name).read_bytes() + b" ")
    src = release.ReleaseSource(book_dir)
    assert src.current() is None
    with pytest.raises(BookUnavailable, match="no build book"):
        src.read("book")


@pytest.mark.parametrize("name", ["release.json", "book.json"])
def test_a_missing_file_means_no_book(book_dir: Path, name: str) -> None:
    (book_dir / name).unlink()
    assert release.ReleaseSource(book_dir).current() is None


def test_no_folder_and_a_broken_release_json_mean_no_book(tmp_path: Path, book_dir: Path) -> None:
    assert release.ReleaseSource(tmp_path / "nowhere").current() is None
    (book_dir / "release.json").write_text("{not json", encoding="utf-8")
    assert release.ReleaseSource(book_dir).current() is None


def test_the_check_runs_once_per_process(book_dir: Path) -> None:
    src = release.ReleaseSource(book_dir)
    assert src.current() is not None
    (book_dir / "release.json").unlink()
    assert src.current() is not None  # remembered


def test_a_file_changed_after_the_check_is_refused_on_read(book_dir: Path) -> None:
    src = release.ReleaseSource(book_dir)
    assert src.current() is not None
    (book_dir / "source.zip").write_bytes(b"tampered")
    with pytest.raises(BookUnavailable):
        src.read("source")


def test_a_failed_build_is_returned_with_its_error_and_has_no_book(book_dir: Path) -> None:
    doc = json.loads((book_dir / "release.json").read_text(encoding="utf-8"))
    doc.update(
        book_sha256=None, source_sha256=None, source_bytes=0, error="the snapshot is too big"
    )
    (book_dir / "release.json").write_text(json.dumps(doc), encoding="utf-8")
    (book_dir / "book.json").unlink()
    src = release.ReleaseSource(book_dir)
    cur = src.current()
    assert cur is not None and not cur.ok and cur.error == "the snapshot is too big"
    with pytest.raises(BookUnavailable):
        src.book()


def test_the_packaged_default_and_current(monkeypatch: pytest.MonkeyPatch, book_dir: Path) -> None:
    release.default_source.cache_clear()
    monkeypatch.setattr(release, "BOOK_DIR", book_dir)
    try:
        assert (
            release.current() is not None
            and release.current() == release.default_source().current()
        )
    finally:
        release.default_source.cache_clear()


def test_a_book_holding_an_owner_address_or_its_local_part_is_caught() -> None:
    data = b'{"text":"Mail Owner.Person@Example.com"}'
    assert release.owner_mentioned(data, ["owner.person@example.com"])
    assert release.owner_mentioned(b'{"t":"owner.person said"}', ["owner.person@example.com"])
    assert not release.owner_mentioned(data, ["someone@else.org"])
    assert not release.owner_mentioned(data, [" ", ""])


def test_hand_deploys_upload_the_git_ignored_book() -> None:
    # gcloud run deploy --source . reads .gitignore when there is no .gcloudignore, which would
    # drop src/jarvis/buildbook/_book (D4); ours is gcloud's default plus that folder
    lines = (ROOT / ".gcloudignore").read_text(encoding="utf-8").splitlines()
    rules = [ln for ln in lines if ln and (not ln.startswith("#") or ln.startswith("#!"))]
    assert rules == [".gcloudignore", ".git", ".gitignore", "#!include:.gitignore",
                     "!src/jarvis/buildbook/_book/"]  # fmt: skip
    assert "src/jarvis/buildbook/_book/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
    assert script.index("make book ||") < script.index('gcloud run deploy "$SERVICE" --source .')
