# tests/test_r52_v1_manager.py -- R5.2 V1 (plan 3.1 "Downloads", risk 2): the model manager.
# Only pinned https files of the pinned hosts, only permissive licences; a file is kept only when
# its size and SHA-256 match (a mismatch keeps nothing); LICENCE.txt beside every model; one
# installed.json; verify re-hashes. Fake downloads only: no network.
from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import pytest
from pydantic import ValidationError

from jarvis.localspeech.manager import (
    LICENCE_NAME,
    Manifest,
    ModelEntry,
    ModelError,
    ModelFile,
    ModelManager,
    https_open,
    load_manifest,
    manifest_text,
)
from jarvis.localspeech.protocol import EngineSlot

S = EngineSlot
BASE = "https://huggingface.co/example/model/resolve/0123456789abcdef0123456789abcdef01234567"
WEIGHTS = b"\x00weights" * 1000
LICENCE = b"MIT License\n\nCopyright (c) example\n"


def pinned(name: str, data: bytes) -> ModelFile:
    return ModelFile(
        name=name, url=f"{BASE}/{name}", sha256=hashlib.sha256(data).hexdigest(), size=len(data)
    )


def entry(files: tuple[ModelFile, ...], **kw: object) -> ModelEntry:
    return ModelEntry(
        slot=kw.get("slot", S.WHISPER_SMALL),  # type: ignore[arg-type]
        model="small-int8",
        source="https://huggingface.co/example/model",
        revision="0123456789abcdef0123456789abcdef01234567",
        licence=str(kw.get("licence", "MIT")),
        licence_file=kw.get("licence_file"),  # type: ignore[arg-type]
        files=files,
    )


class Web:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.opened: list[str] = []

    @contextmanager
    def open(self, url: str) -> Iterator[IO[bytes]]:
        self.opened.append(url)
        yield io.BytesIO(self.files[url.rsplit("/", 1)[1]])


def manager(tmp: Path, manifest: Manifest, web: Web) -> ModelManager:
    return ModelManager(
        manifest,
        tmp / "models",
        tmp / "installed.json",
        opener=web.open,
        now=lambda: datetime(2026, 11, 27, tzinfo=UTC),
    )


def one_model(**kw: object) -> Manifest:
    files = (pinned("model.bin", WEIGHTS), pinned("LICENSE", LICENCE))
    return Manifest(
        manifest=1, kit_version="1.0.0", models=(entry(files, licence_file="LICENSE", **kw),)
    )


def test_an_install_keeps_matching_files_with_their_licence_and_records_them(
    tmp_path: Path,
) -> None:
    web = Web({"model.bin": WEIGHTS, "LICENSE": LICENCE})
    m = manager(tmp_path, one_model(), web)
    assert m.model_dir(S.WHISPER_SMALL) is None
    folder = m.install(S.WHISPER_SMALL)
    assert (folder / "model.bin").read_bytes() == WEIGHTS
    licence = (folder / LICENCE_NAME).read_text()
    assert (
        "Licence: MIT" in licence
        and "MIT License" in licence
        and "Revision: 0123456789ab" in licence
    )
    assert m.model_dir(S.WHISPER_SMALL) == folder
    done = json.loads((tmp_path / "installed.json").read_text())
    assert done["models"][0]["slot"] == "whisper-small" and len(done["models"][0]["files"]) == 2
    assert m.verify() == {S.WHISPER_SMALL: None}
    m.install(S.WHISPER_SMALL)  # again: nothing downloaded twice
    assert len(web.opened) == 2


def test_a_file_that_does_not_match_its_hash_is_not_kept(tmp_path: Path) -> None:
    web = Web({"model.bin": WEIGHTS[:-1] + b"X", "LICENSE": LICENCE})
    m = manager(tmp_path, one_model(), web)
    with pytest.raises(ModelError, match="SHA-256"):
        m.install(S.WHISPER_SMALL)
    folder = tmp_path / "models" / "whisper-small"
    assert list(folder.iterdir()) == [] and m.model_dir(S.WHISPER_SMALL) is None
    assert not (tmp_path / "installed.json").exists()


def test_a_file_bigger_than_pinned_stops_the_download(tmp_path: Path) -> None:
    web = Web({"model.bin": WEIGHTS + b"more", "LICENSE": LICENCE})
    with pytest.raises(ModelError, match="bigger"):
        manager(tmp_path, one_model(), web).install(S.WHISPER_SMALL)
    assert not list((tmp_path / "models" / "whisper-small").glob("*.part"))


def test_verify_finds_a_changed_file_and_model_dir_a_missing_one(tmp_path: Path) -> None:
    m = manager(tmp_path, one_model(), Web({"model.bin": WEIGHTS, "LICENSE": LICENCE}))
    folder = m.install(S.WHISPER_SMALL)
    (folder / "model.bin").write_bytes(WEIGHTS[:-1] + b"Y")
    assert m.verify() == {S.WHISPER_SMALL: "hash mismatch: model.bin"}
    (folder / "LICENSE").unlink()
    assert m.model_dir(S.WHISPER_SMALL) is None
    assert m.verify([S.KOKORO]) == {S.KOKORO: "not installed"}


def test_remove_forgets_a_model(tmp_path: Path) -> None:
    m = manager(tmp_path, one_model(), Web({"model.bin": WEIGHTS, "LICENSE": LICENCE}))
    m.install(S.WHISPER_SMALL)
    assert m.remove(S.WHISPER_SMALL) and m.installed().models == ()
    assert not (tmp_path / "models" / "whisper-small").exists()


def test_only_permissive_licences_and_pinned_https_hosts() -> None:
    files = (pinned("model.bin", WEIGHTS),)
    for licence in ("GPL-3.0-or-later", "CC-BY-NC-SA-4.0", "LicenseRef-Owner", "unknown"):
        with pytest.raises(ValidationError):
            entry(files, licence=licence)
    for url in (
        "http://huggingface.co/x/model.bin",
        "https://example.com/model.bin",
        "https://u@huggingface.co/m",
    ):
        with pytest.raises(ValidationError):
            ModelFile(name="model.bin", url=url, sha256="0" * 64, size=1)
    for name in ("../escape", "a/b", ".hidden", "LICENCE.txt"):
        with pytest.raises(ValidationError):
            entry((ModelFile(name=name, url=f"{BASE}/x", sha256="0" * 64, size=1),))
    with pytest.raises(ValidationError):
        entry(files, licence_file="NOT-PINNED")


def test_a_slot_is_pinned_once_or_left_out(tmp_path: Path) -> None:
    files = (pinned("model.bin", WEIGHTS),)
    with pytest.raises(ValidationError):
        Manifest(manifest=1, kit_version="1.0.0", models=(entry(files), entry(files)))
    with pytest.raises(ValidationError):
        Manifest.model_validate(
            {
                "manifest": 1,
                "kit_version": "1.0.0",
                "models": [entry(files).model_dump()],
                "left_out": [{"slot": "whisper-small", "source": BASE, "why": "x"}],
            }
        )
    path = tmp_path / "models.json"
    path.write_text("{not json")
    with pytest.raises(ModelError, match="not valid"):
        load_manifest(path)
    with pytest.raises(ModelError, match="missing"):
        load_manifest(tmp_path / "none.json")


def test_an_install_of_a_slot_with_no_pin_is_refused(tmp_path: Path) -> None:
    m = manager(tmp_path, Manifest(manifest=1, kit_version="1.0.0"), Web({}))
    with pytest.raises(ModelError, match="no pinned model"):
        m.install(S.KOKORO)
    assert manifest_text(m.manifest) == []


def test_the_real_opener_refuses_anything_but_the_pinned_hosts() -> None:
    for url in ("http://huggingface.co/x", "https://evil.example/x", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            https_open(url)
