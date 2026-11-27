# tests/test_r52_i1_manager_blob.py -- R5.2 I1 (the Workshop's decision; a recorded deviation from
# the build brief's rule 9): the kit's model manager may pin a small plain-git text file (JSON or
# TXT, at most 5 MB, at a full commit in its address) by its git blob id instead of a SHA-256. It
# checks sha1(b"blob <size>\0" + data) after download, refuses a mismatch and records the file's
# SHA-256. Weights always need a SHA-256. Fake downloads only: no network.
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
    BLOB_PIN_MAX,
    LICENCE_NAME,
    Manifest,
    ModelEntry,
    ModelError,
    ModelFile,
    ModelManager,
    digests_of,
    git_blob,
)
from jarvis.localspeech.protocol import EngineSlot

REV = "0123456789abcdef0123456789abcdef01234567"
BASE = f"https://huggingface.co/example/model/resolve/{REV}"
WEIGHTS = b"\x00weights" * 1000
CONFIG = b'{"alignment_heads": [[1, 0]], "lang_ids": [50259]}\n'


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def weights() -> ModelFile:
    return ModelFile(
        name="model.bin", url=f"{BASE}/model.bin", sha256=sha(WEIGHTS), size=len(WEIGHTS)
    )


def text_file(name: str = "config.json", data: bytes = CONFIG, **kw: object) -> ModelFile:
    return ModelFile(
        name=name,
        url=str(kw.get("url", f"{BASE}/{name}")),
        git_blob_sha1=str(kw.get("blob", blob_id(data))),
        size=int(kw.get("size", len(data))),  # type: ignore[call-overload]
    )


def entry(files: tuple[ModelFile, ...], revision: str = REV) -> ModelEntry:
    return ModelEntry(
        slot=EngineSlot.WHISPER_SMALL,
        model="small",
        source="https://huggingface.co/example/model",
        revision=revision,
        licence="MIT",
        files=files,
    )


class Web:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    @contextmanager
    def open(self, url: str) -> Iterator[IO[bytes]]:
        yield io.BytesIO(self.files[url.rsplit("/", 1)[1]])


def manager(tmp: Path, files: tuple[ModelFile, ...], web: dict[str, bytes]) -> ModelManager:
    manifest = Manifest(manifest=1, kit_version="1.0.0", models=(entry(files),))
    return ModelManager(
        manifest,
        tmp / "models",
        tmp / "installed.json",
        opener=Web(web).open,
        now=lambda: datetime(2026, 11, 27, tzinfo=UTC),
    )


def test_gits_blob_id_is_the_one_hugging_face_publishes() -> None:
    blob = git_blob(len(CONFIG))
    blob.update(CONFIG)
    assert blob.hexdigest() == blob_id(CONFIG)
    assert blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # git's empty blob


def test_a_matching_text_file_is_kept_and_its_sha256_recorded(tmp_path: Path) -> None:
    m = manager(tmp_path, (weights(), text_file()), {"model.bin": WEIGHTS, "config.json": CONFIG})
    folder = m.install(EngineSlot.WHISPER_SMALL)
    assert (folder / "config.json").read_bytes() == CONFIG
    done = json.loads((tmp_path / "installed.json").read_text())
    recorded = {f["name"]: f["sha256"] for f in done["models"][0]["files"]}
    assert recorded == {"model.bin": sha(WEIGHTS), "config.json": sha(CONFIG)}
    assert f"{sha(CONFIG)}  config.json" in (folder / LICENCE_NAME).read_text()
    assert digests_of(folder / "config.json") == (sha(CONFIG), blob_id(CONFIG))
    assert m.verify() == {EngineSlot.WHISPER_SMALL: None}
    (folder / "config.json").write_bytes(CONFIG.replace(b"1, 0", b"2, 0"))  # same size, changed
    assert m.verify() == {EngineSlot.WHISPER_SMALL: "hash mismatch: config.json"}


def test_a_text_file_whose_blob_id_does_not_match_is_refused_and_nothing_kept(
    tmp_path: Path,
) -> None:
    other = CONFIG.replace(b"50259", b"50260")
    m = manager(tmp_path, (text_file(),), {"config.json": other})
    with pytest.raises(ModelError, match="git blob id"):
        m.install(EngineSlot.WHISPER_SMALL)
    folder = tmp_path / "models" / "whisper-small"
    assert not (folder / "config.json").exists() and not (folder / "config.json.part").exists()
    assert not (tmp_path / "installed.json").exists()


def test_a_blob_id_never_pins_a_big_file() -> None:
    with pytest.raises(ValidationError):
        text_file("tokenizer.json", size=BLOB_PIN_MAX + 1, blob="0" * 40)
    assert text_file("tokenizer.json", size=BLOB_PIN_MAX, blob="0" * 40).size == BLOB_PIN_MAX


@pytest.mark.parametrize("name", ["model.bin", "weights.onnx", "model.safetensors", "README.md"])
def test_a_blob_id_never_pins_weights_or_another_kind_of_file(name: str) -> None:
    with pytest.raises(ValidationError):
        text_file(name, blob="0" * 40, size=10)


def test_a_blob_id_holds_only_at_a_full_commit_in_the_files_address() -> None:
    with pytest.raises(ValidationError):  # a tag is not a commit
        entry(
            (text_file(url="https://huggingface.co/example/model/resolve/v1.0/config.json"),),
            "v1.0",
        )
    with pytest.raises(ValidationError):  # a short commit is not enough
        entry(
            (text_file(url=f"https://huggingface.co/example/model/resolve/{REV[:7]}/config.json"),),
            REV[:7],
        )
    with pytest.raises(ValidationError):  # the address must be at the pinned commit
        entry((text_file(url="https://huggingface.co/example/model/resolve/main/config.json"),))
    with pytest.raises(ValidationError):  # the revision is required
        ModelEntry.model_validate(
            {
                "slot": "whisper-small",
                "model": "small",
                "source": "https://huggingface.co/example/model",
                "licence": "MIT",
                "files": [text_file().model_dump()],
            }
        )
    assert entry((text_file(),)).revision == REV


def test_a_file_is_pinned_by_exactly_one_hash() -> None:
    with pytest.raises(ValidationError):  # neither
        ModelFile(name="config.json", url=f"{BASE}/config.json", size=10)
    with pytest.raises(ValidationError):  # both
        ModelFile(
            name="config.json",
            url=f"{BASE}/config.json",
            sha256=sha(CONFIG),
            git_blob_sha1=blob_id(CONFIG),
            size=len(CONFIG),
        )
    with pytest.raises(ValidationError):  # not a SHA-1
        text_file(blob="abc")


def test_weights_pinned_by_sha256_still_install_beside_blob_pinned_text(tmp_path: Path) -> None:
    m = manager(
        tmp_path, (weights(), text_file()), {"model.bin": WEIGHTS + b"!", "config.json": CONFIG}
    )
    with pytest.raises(ModelError, match="bigger than pinned"):
        m.install(EngineSlot.WHISPER_SMALL)
