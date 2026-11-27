# tests/test_r52_review_manager.py -- R5.2 combined review: the model manager's git-blob pins.
# A small text file pinned by its git blob id (I1's recorded deviation) must be fetched AT the
# pinned commit: the commit is what makes a SHA-1 pin safe to take. The I1 rule only asked that
# "/<commit>/" appear somewhere in the address, so a moving ref passed when the commit sat in a
# query, a fragment or a folder below the ref (`.../resolve/main/<commit>/config.json`). Now the
# address must be exactly the host's raw-file path at that commit, ending in the file's own name.
from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from jarvis.localspeech.manager import ModelEntry, ModelFile
from jarvis.localspeech.protocol import EngineSlot

REV = "0123456789abcdef0123456789abcdef01234567"
DATA = b'{"alignment_heads": [[1, 0]]}\n'
BLOB = hashlib.sha1(b"blob %d\x00" % len(DATA) + DATA).hexdigest()
HF = "https://huggingface.co/example/model"


def _entry(url: str, name: str = "config.json") -> ModelEntry:
    return ModelEntry(
        slot=EngineSlot.WHISPER_SMALL,
        model="small",
        source=HF,
        revision=REV,
        licence="MIT",
        files=(ModelFile(name=name, url=url, git_blob_sha1=BLOB, size=len(DATA)),),
    )


@pytest.mark.parametrize(
    "url",
    [
        f"{HF}/resolve/main/config.json?/{REV}/",  # the commit only in a query
        f"{HF}/resolve/main/config.json#/{REV}/",  # ... or a fragment
        f"{HF}/resolve/main/{REV}/config.json",  # a folder named like the commit, under main
        f"https://huggingface.co/{REV}/model/resolve/main/config.json",  # the commit as the owner
        f"{HF}/blob/{REV}/config.json",  # Hugging Face's page, not the file
        f"{HF}/resolve/{REV}/other.json",  # another file than the one pinned
        f"{HF}/resolve/{REV}/sub/../config.json",  # dot segments
        f"{HF}/resolve/{REV}/config%2Ejson",  # escapes
        f"https://huggingface.co:444/example/model/resolve/{REV}/config.json",  # another port
        f"https://github.com/example/model/blob/{REV}/config.json",  # GitHub's page
    ],
)
def test_review_a_blob_pin_must_be_fetched_at_its_commit(url: str) -> None:
    with pytest.raises(ValidationError):
        _entry(url)


@pytest.mark.parametrize(
    "url",
    [
        f"{HF}/resolve/{REV}/config.json",
        f"https://github.com/example/model/raw/{REV}/config.json",
        f"https://github.com/example/model/raw/{REV}/assets/config.json",
    ],
)
def test_review_the_hosts_raw_file_address_at_the_commit_is_taken(url: str) -> None:
    assert _entry(url).files[0].url == url


def test_review_a_sha256_pin_keeps_its_freedom_of_address() -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    entry = ModelEntry(
        slot=EngineSlot.WHISPER_SMALL,
        model="small",
        source=HF,
        revision="v1.0",
        licence="MIT",
        files=(
            ModelFile(name="model.bin", url=f"{HF}/resolve/v1.0/model.bin", sha256=digest, size=10),
        ),
    )
    assert entry.revision == "v1.0"  # the content's own hash is the check
