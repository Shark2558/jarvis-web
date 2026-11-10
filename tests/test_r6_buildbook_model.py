# tests/test_r6_buildbook_model.py -- R6 I0 seam 6 and 7 (docs/plans/r6-build-book.md): the build
# book's one schema (`jarvis.buildbook.model`: Release, Book v1 and its sections, Scene, Beat,
# SealedRelease, SessionView; KEEP and the caps), D13's fixed lines verbatim (`buildbook/lines.py`)
# and the two fixtures builders A-D work against (tests/fixtures/book/repo and .../_book).
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jarvis.buildbook import lines, model
from jarvis.buildbook.model import (
    BOOK_JSON_CAP_BYTES,
    KEEP,
    SCHEMA_VERSION,
    SECTION_IDS,
    SHOW_SCENES,
    SNAPSHOT_CAP_BYTES,
    Book,
    Release,
    SealedFile,
    SealedRelease,
    SessionView,
    canonical_bytes,
    load_book,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "book"
BOOK = FIX / "_book"
REPO = FIX / "repo"
SHA = "3f2a1c9" + "0" * 33
MIB = 1024 * 1024
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(\+91[\s-]?)?[6-9]\d{9}")  # D3
GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_-]{35}")


def _release(**kw: Any) -> Release:
    base: dict[str, Any] = {
        "id": SHA[:7],
        "sha": SHA,
        "label": "R6",
        "committed_at": "2026-11-10T09:00:00+05:30",
        "book_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "source_bytes": 4_000_000,
    }
    return Release.model_validate({**base, **kw})


def _fixture_book() -> Book:
    return load_book((BOOK / "book.json").read_bytes())


def test_the_constants_follow_the_plan() -> None:
    assert (KEEP, SCHEMA_VERSION) == (3, 1)
    assert SNAPSHOT_CAP_BYTES == 15 * MIB and BOOK_JSON_CAP_BYTES == 2 * MIB
    assert SECTION_IDS == (
        "architecture",
        "stack",
        "libraries",
        "integrations",
        "workflows",
        "limitations",
        "costs",
        "decisions",
    )
    assert [n for n, _, _ in SHOW_SCENES] == list(range(1, 14)) and model.BOOK_SCENES == 11


def test_a_release_is_frozen_strict_and_names_its_commit() -> None:
    r = _release()
    assert r.ok and r.v == 1
    with pytest.raises(ValidationError):
        r.label = "R7"  # type: ignore[misc]
    for bad in (
        {"id": "1234567"},  # not the sha's first seven
        {"label": "r6"},
        {"label": "R6.1.2"},
        {"committed_at": "2026-11-10T09:00:00"},  # no offset
        {"surprise": 1},
    ):
        with pytest.raises(ValidationError):
            _release(**bad)
    assert _release(label="R5.1").label == "R5.1"


def test_a_good_release_carries_both_digests_and_a_failed_one_none() -> None:
    with pytest.raises(ValidationError):
        _release(source_sha256=None)
    failed = _release(error="the generator failed", book_sha256=None, source_sha256=None)
    assert not failed.ok and failed.source_bytes == 4_000_000
    with pytest.raises(ValidationError):  # a failed build wrote no book
        _release(error="x")
    with pytest.raises(ValidationError):
        _release(source_bytes=SNAPSHOT_CAP_BYTES + 1)


def test_the_fixture_release_matches_its_files() -> None:
    rel = Release.model_validate_json((BOOK / "release.json").read_bytes())
    book, source = (BOOK / "book.json").read_bytes(), (BOOK / "source.zip").read_bytes()
    assert rel.ok and rel.book_sha256 == hashlib.sha256(book).hexdigest()
    assert rel.source_sha256 == hashlib.sha256(source).hexdigest()
    assert rel.source_bytes == len(source)
    assert _fixture_book().release == rel.ref()


def test_the_fixture_book_is_canonical_v1_with_every_section() -> None:
    raw = (BOOK / "book.json").read_bytes()
    book = load_book(raw)
    assert canonical_bytes(book) == raw and len(raw) <= BOOK_JSON_CAP_BYTES
    assert book.v == SCHEMA_VERSION and tuple(book.sections()) == SECTION_IDS
    assert json.loads(raw)["v"] == 1 and list(json.loads(raw)) == sorted(json.loads(raw))
    assert {w.id for w in book.workflows} == set(model.FLOW_IDS)
    assert book.digest.chunks and all(len(c.text) <= 1_500 for c in book.digest.chunks)


def test_the_fixture_source_zip_has_three_files_laid_out_like_the_kit() -> None:
    rel = Release.model_validate_json((BOOK / "release.json").read_bytes())
    with zipfile.ZipFile(BOOK / "source.zip") as zf:
        infos = zf.infolist()
    names = [i.filename for i in infos]
    assert len(names) == 3 and names == sorted(names)
    assert all(n.startswith(f"JARVIS-source-{rel.id}/") for n in names)
    assert {i.date_time for i in infos} == {model.ZIP_STAMP}
    assert {i.external_attr >> 16 for i in infos} == {0o644}


def test_load_book_refuses_oversize_and_other_versions() -> None:
    raw = json.loads((BOOK / "book.json").read_bytes())
    with pytest.raises(ValueError):
        load_book(json.dumps({**raw, "v": 2}).encode())
    with pytest.raises(ValueError):
        load_book(b" " * (BOOK_JSON_CAP_BYTES + 1))
    with pytest.raises(ValueError):
        load_book(b"\xff not json")


def test_the_show_is_scenes_one_to_eleven_with_unique_line_ids() -> None:
    show = _fixture_book().show
    assert [s.n for s in show.scenes] == list(range(1, 12))
    for scene, (n, sid, title) in zip(show.scenes, SHOW_SCENES, strict=False):
        assert (scene.n, scene.id, scene.title) == (n, sid, title)
        assert scene.beats and all(b.id.startswith(f"s{n:02d}b") for b in scene.beats)
    ids = [b.id for s in show.scenes for b in s.beats]
    assert len(ids) == len(set(ids))


def test_a_show_out_of_order_or_with_a_repeated_line_is_refused() -> None:
    raw = json.loads((BOOK / "book.json").read_bytes())
    scenes = raw["show"]["scenes"]
    swapped = {**raw, "show": {"scenes": [scenes[1], scenes[0], *scenes[2:]]}}
    with pytest.raises(ValueError):
        load_book(json.dumps(swapped).encode())
    twice = json.loads(json.dumps(raw))
    beats = twice["show"]["scenes"][0]["beats"]
    beats.append(dict(beats[0]))
    with pytest.raises(ValueError):
        load_book(json.dumps(twice).encode())


def test_a_sealed_release_shows_megabytes_and_hides_its_keys() -> None:
    def sealed_file(kind: str, n: str, size: int, count: int) -> SealedFile:
        return SealedFile.model_validate(
            {"kind": kind, "fid": "bf_" + n * 12, "size": size, "sha256": n * 64}
            | {"count": count, "dek": "WRAPPED"}
        )

    files = (sealed_file("book", "a", MIB // 2, 1), sealed_file("source", "b", MIB + MIB // 2, 3))
    sealed = SealedRelease(
        id=SHA[:7],
        label="R6",
        sha=SHA,
        committed_at="2026-11-10T09:00:00+05:30",
        sealed_at="2026-11-10T09:05:00+05:30",
        files=files,
    )
    assert sealed.view() == {
        "id": "3f2a1c9",
        "label": "R6",
        "sealed_at": sealed.sealed_at,
        "mb": 2.0,
    }
    assert "WRAPPED" not in repr(sealed)
    with pytest.raises(ValidationError):  # one book and one source, never two of a kind
        SealedRelease.model_validate({**sealed.model_dump(), "files": [files[0].model_dump()] * 2})


def test_a_session_view_carries_no_secret() -> None:
    v = SessionView(
        session_id="bk_" + "0" * 16,
        audience="guest",
        created_at="2026-11-10T14:02:00+05:30",
        until="2026-11-10T14:47:00+05:30",
        idle_until="2026-11-10T14:12:00+05:30",
        questions=0,
        questions_left=20,
    )
    assert set(v.model_dump()) == {
        "session_id",
        "audience",
        "created_at",
        "until",
        "idle_until",
        "questions",
        "questions_left",
        "state",
    }
    with pytest.raises(ValidationError):
        SessionView.model_validate({**v.model_dump(), "audience": "admin"})


# ---- D13: the fixed lines ------------------------------------------------------------------------
D13 = {
    "ask": "Do you have any questions about how I'm built?",
    "anything_else": "Anything else you'd like to know?",
    "refuse_data": "That belongs to my owner, and none of it is in this session. I can tell you "
    "how I'm built.",
    "refuse_action": "I can't do anything from the build book; I can explain how that feature "
    "works.",
    "refuse_meta": "I'll keep to explaining how I'm built.",
    "ai_off": "My conversational brain is off, so I can't take questions; the show still works.",
    "limit": "That's all the questions I can take in one session.",
    "credit": "Everything you've seen was designed and built by {by}. The credit is all {his}.",
    "sealed_guest": "The code is sealed in my vault, for the people my owner allows.",
    "thanks_guest": "Thank you for listening.",
    "sealed_owner": "The code is sealed in your vault, for the people you allow, {h}.",
    "thanks_owner": "Thank you, {h}.",
    "hand_back": "Please hand the device back to my owner.",
}


def test_the_d13_lines_are_verbatim() -> None:
    assert dict(lines.LINES) == D13
    assert lines.CLOSING == {
        "guest": ("credit", "sealed_guest", "thanks_guest"),
        "owner": ("credit", "sealed_owner", "thanks_owner"),
    }
    with pytest.raises(TypeError):
        lines.LINES["ask"] = "x"  # type: ignore[index]


def test_render_fills_the_honorific_pronoun_and_creator() -> None:
    by = lines.credit_by("Akash")
    assert by == "Akash, my owner and creator"
    assert lines.credit_by(None) == lines.credit_by("   ") == "my owner and creator"
    assert len(lines.credit_by("x" * 90)) == 40 + len(", my owner and creator")
    assert lines.render("credit", h="Sir", his="his", by=by) == (
        "Everything you've seen was designed and built by Akash, my owner and creator. "
        "The credit is all his."
    )
    assert lines.render("thanks_owner", h="Ma'am", his="hers", by=by) == "Thank you, Ma'am."
    assert lines.render("credit", h="Sir", his="his", by="{h}").endswith(
        "by {h}. The credit is all his."
    )
    with pytest.raises(KeyError):
        lines.render("nope", h="Sir", his="his", by=by)


def test_the_pronoun_follows_the_honorific() -> None:
    assert [lines.possessive(h) for h in ("Sir", "sir", "Ma'am", "Madam", "Boss", "")] == [
        "his",
        "his",
        "hers",
        "hers",
        "theirs",
        "theirs",
    ]


def test_the_closing_reads_in_order_for_each_audience() -> None:
    by = lines.credit_by(None)
    assert lines.closing("guest", h="Sir", his="his", by=by) == (
        "Everything you've seen was designed and built by my owner and creator. "
        "The credit is all his.",
        "The code is sealed in my vault, for the people my owner allows.",
        "Thank you for listening.",
    )
    owner = lines.closing("owner", h="Sir", his="his", by=by)
    assert owner[1:] == (
        "The code is sealed in your vault, for the people you allow, Sir.",
        "Thank you, Sir.",
    )
    assert all(len(t) <= 300 for t in D13.values())


# ---- seam 7: the generator's fixture repo --------------------------------------------------------
def test_the_repo_fixture_holds_what_the_generator_must_scrub_and_refuse() -> None:
    plans = sorted((REPO / "docs" / "plans").glob("*.md"))
    assert len(plans) == 2
    text = "\n".join(p.read_text(encoding="utf-8") for p in plans)
    assert EMAIL.search(text) and PHONE.search(text)
    modules = [p for p in (REPO / "src" / "jarvis").rglob("*.py") if p.name != "__init__.py"]
    assert len(modules) == 3
    lock = (REPO / "requirements.lock").read_text(encoding="utf-8")
    assert re.search(r"^[a-z0-9-]+==[0-9.]+ \\$", lock, re.MULTILINE)
    planted = [
        p
        for p in REPO.rglob("*")
        if p.is_file() and GOOGLE_KEY.search(p.read_text(encoding="utf-8"))
    ]
    assert len(planted) == 1
