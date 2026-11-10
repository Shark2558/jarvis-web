# tests/test_book_gen_snapshot.py
"""R6 D5: the source snapshot (`gen.snapshot`). Git-tracked files only, zipped as the home kit
does (sorted, fixed time, 0644, root `JARVIS-source-<id>/`, NFC names); vendored code, models,
binaries, files over 1 MB and the kit's skip rules are left out but listed in THIRD_PARTY.json
(path, bytes, sha256, licence); a secret-shaped string refuses the snapshot unless its SHA-256 is
in gen/fake_secrets.txt; over 15 MB is refused."""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

import pytest
from book_gen_fakes import COMMIT_DATE, ROOT, commit_all, fake_secret, fixture_repo

from jarvis.buildbook.gen import snapshot
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import SNAPSHOT_CAP_BYTES, ZIP_STAMP


def _fakes() -> frozenset[str]:
    return snapshot.load_fakes()


def _zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


@pytest.fixture()
def fx(tmp_path: Path) -> Repo:
    return Repo.from_git(fixture_repo(tmp_path))


def test_the_zip_layout_is_the_home_kits(fx: Repo) -> None:
    snap = snapshot.build(fx, _fakes())
    zf = _zip(snap.data)
    names = zf.namelist()
    root = f"JARVIS-source-{fx.id}/"
    assert names == sorted(names) and all(n.startswith(root) for n in names)
    assert set(names) == {root + f for f in fx.files} | {root + "THIRD_PARTY.json"}
    for info in zf.infolist():
        assert info.date_time == ZIP_STAMP
        assert info.external_attr >> 16 == 0o644 and info.create_system == 3
    assert (
        zf.read(root + "src/jarvis/core/loop.py")
        == (fx.root / "src/jarvis/core/loop.py").read_bytes()
    )
    assert snap.sha256 == hashlib.sha256(snap.data).hexdigest() and snap.skipped == 0


def test_the_same_commit_gives_the_same_bytes(tmp_path: Path) -> None:
    a = Repo.from_git(fixture_repo(tmp_path, "a"))
    b = Repo.from_git(fixture_repo(tmp_path, "b"))
    assert snapshot.build(a, _fakes()).data == snapshot.build(b, _fakes()).data
    assert snapshot.build(a, _fakes()).data == snapshot.build(a, _fakes()).data


def test_left_out_files_are_listed_with_their_licence(tmp_path: Path) -> None:
    root = fixture_repo(tmp_path)
    static = root / "src" / "jarvis" / "api" / "static"
    (static / "vendor").mkdir(parents=True)
    (static / "vendor" / "lib.min.js").write_text("x", encoding="utf-8")
    (static / "vendor" / "LICENSE-lib.txt").write_text("MIT License\n", encoding="utf-8")
    (static / "wakeword").mkdir()
    (static / "wakeword" / "m.onnx").write_bytes(b"\x00\x01")
    (static / "wakeword" / "LICENSE.txt").write_text("CC BY-NC-SA 4.0\n", encoding="utf-8")
    (root / "docs" / "logo.png").write_bytes(b"\x89PNG")
    (root / "big.txt").write_bytes(b"a" * (snapshot.LARGE_BYTES + 1))
    (root / "deploy" / "server.pem").write_text("x", encoding="utf-8")
    commit_all(root, "extra")
    r = Repo.from_git(root)
    snap = snapshot.build(r, _fakes())
    zf = _zip(snap.data)
    top = f"JARVIS-source-{r.id}/"
    listed = json.loads(zf.read(top + "THIRD_PARTY.json"))
    rows = {row["path"]: row for row in listed["files"]}
    assert set(rows) == {
        "src/jarvis/api/static/vendor/lib.min.js",
        "src/jarvis/api/static/vendor/LICENSE-lib.txt",
        "src/jarvis/api/static/wakeword/m.onnx",
        "src/jarvis/api/static/wakeword/LICENSE.txt",
        "docs/logo.png",
        "big.txt",
        "deploy/server.pem",
    }
    assert not any(top + p in zf.namelist() for p in rows)
    assert snap.skipped == len(rows) == listed["count"]
    onnx = rows["src/jarvis/api/static/wakeword/m.onnx"]
    assert onnx == {
        "path": "src/jarvis/api/static/wakeword/m.onnx",
        "bytes": 2,
        "sha256": hashlib.sha256(b"\x00\x01").hexdigest(),
        "licence": "CC-BY-NC-SA-4.0",
        "why": "vendored",
    }
    assert rows["src/jarvis/api/static/vendor/lib.min.js"]["licence"] == "MIT"
    assert rows["big.txt"]["why"] == "over 1 MB" and rows["docs/logo.png"]["why"] == "binary"
    assert rows["deploy/server.pem"]["why"] == "home kit skip rule"
    assert rows["docs/logo.png"]["licence"] == snapshot.OWN


def test_a_planted_secret_refuses_the_snapshot_and_names_no_secret(fx: Repo) -> None:
    key = fake_secret("google")
    (fx.root / "src" / "jarvis" / "core" / "keys.py").write_text(f'K = "{key}"\n', encoding="utf-8")
    commit_all(fx.root, "plant")
    r = Repo.from_git(fx.root)
    with pytest.raises(GenError) as err:
        snapshot.build(r, _fakes())
    assert "src/jarvis/core/keys.py" in str(err.value) and "google_api_key" in str(err.value)
    assert key not in str(err.value)
    listed = _fakes() | {hashlib.sha256(key.encode()).hexdigest()}
    assert snapshot.build(r, listed).data  # a listed fake passes


@pytest.mark.parametrize("kind", ["anthropic", "github", "aws", "telegram", "pem"])
def test_every_secret_shape_is_caught(tmp_path: Path, kind: str) -> None:
    (tmp_path / "a.txt").write_text(f"x {fake_secret(kind)} y\n", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="f" * 40, committed_at=COMMIT_DATE)
    assert len(snapshot.secret_hits(r, r.files, frozenset())) == 1


def test_the_fixtures_fake_key_is_listed(fx: Repo) -> None:
    assert snapshot.secret_hits(fx, fx.files, _fakes()) == []
    assert len(snapshot.secret_hits(fx, fx.files, frozenset())) == 1


def test_every_fake_secret_in_the_real_repo_is_listed() -> None:
    real = Repo.from_git(ROOT)
    files = tuple(f for f in real.files if snapshot.left_out(real, f) is None)
    hits = snapshot.secret_hits(real, files, _fakes())
    assert hits == [], f"unlisted secret-shaped strings in: {sorted({p for p, _ in hits})}"
    known = snapshot.secret_hits(real, files, frozenset())
    assert {p for p, _ in known} >= {"tests/fixtures/book/repo/deploy/fixture.env"}
    assert all(p.startswith(("tests/", "evals/")) for p, _ in known)


def test_fake_secrets_txt_holds_hashes_and_paths_only() -> None:
    text = snapshot.FAKES_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.fullmatch(r"[0-9a-f]{64}\s+\S+(\s+#\s*[a-z_]+)?", line), line
    r = Repo.from_dir(snapshot.FAKES_FILE.parent, sha="f" * 40, committed_at=COMMIT_DATE)
    assert snapshot.secret_hits(r, ("fake_secrets.txt",), frozenset()) == []


def test_over_the_cap_is_refused(fx: Repo) -> None:
    with pytest.raises(GenError, match="cap"):
        snapshot.build(fx, _fakes(), cap=100)
    assert SNAPSHOT_CAP_BYTES == 15 * 1024 * 1024


def test_names_are_nfc(tmp_path: Path) -> None:
    (tmp_path / unicodedata.normalize("NFD", "café.md")).write_text("x", encoding="utf-8")
    r = Repo.from_dir(tmp_path, sha="f" * 40, committed_at=COMMIT_DATE)
    names = _zip(snapshot.build(r, frozenset()).data).namelist()
    assert f"JARVIS-source-fffffff/{unicodedata.normalize('NFC', 'café.md')}" in names


def test_the_kit_skip_rules_are_the_home_kits() -> None:
    from jarvis.home import kit

    assert snapshot.KIT_SKIP_NAMES == kit.SKIP_NAMES
    assert snapshot.KIT_SKIP_PARTS == kit.SKIP_PARTS
    assert snapshot.KIT_SKIP_SUFFIXES == kit.SKIP_SUFFIXES
