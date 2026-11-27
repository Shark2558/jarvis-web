# src/jarvis/localspeech/manager.py
"""The kit's model manager (R5.2 V1; plan 3.1 "Downloads", risk 2). Kit-safe: the standard library
and Pydantic only.

The manifest (`deploy/local-speech/models.json`) pins every model file the kit may download: its
https address at a fixed revision, its size and its SHA-256, and the model's licence, which must
be one of `protocol.PERMISSIVE_LICENCES`. Nothing else is ever downloaded. A file is written to a
temporary name while its hash is computed and only renamed into place when size and hash match;
a mismatch deletes it and installs nothing.

The one exception to "a SHA-256 per file" (the Workshop's decision at the R5.2 join, a recorded
deviation from the build brief's rule 9): a small text file that the model's host keeps in plain
git (JSON or TXT, at most `BLOB_PIN_MAX` bytes), fetched at a revision that is a full commit id
(its address is exactly the host's raw file at that commit: `_at_commit`), may be pinned by its
git blob id (`git_blob_sha1`, the SHA-1 Hugging Face publishes) instead. It is
checked after download as git computes it (SHA-1 of "blob <size>", a zero byte, then the data)
and refused on a mismatch; its SHA-256 is then recorded in `installed.json` and `LICENCE.txt`.
The commit pins the content and a second preimage on SHA-1 is infeasible. Weights (`model.bin`,
any LFS file) always need a SHA-256: an LFS file's blob id is its pointer's, never its data's.

Beside each model the manager writes `LICENCE.txt` (its licence, source and revision, and the
licence file itself when the source ships one), and `installed.json` lists what this kit
installed. Models the builders could not pin from a primary source are listed under `left_out`
with the reason, and are never installed.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.localspeech.kitconfig import KIT_VERSION_NOW, private_dir, write_private
from jarvis.localspeech.protocol import KIT_VERSION, PERMISSIVE_LICENCES, SHA256, EngineSlot

log = logging.getLogger(__name__)

FILE_NAME: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
REVISION: Final = r"^[0-9a-f]{7,64}$|^v?[0-9][0-9A-Za-z.\-]{0,30}$"
MAX_FILE: Final = 4_000_000_000  # one model file
CHUNK: Final = 1024 * 1024
TIMEOUT_S: Final = 60
ALLOWED_HOSTS: Final = frozenset({"huggingface.co", "github.com"})
LICENCE_NAME: Final = "LICENCE.txt"
GIT_BLOB: Final = r"^[0-9a-f]{40}$"
COMMIT: Final = re.compile(r"[0-9a-f]{40}")
BLOB_PIN_SUFFIXES: Final = (".json", ".txt")  # small text files kept in plain git
BLOB_PIN_MAX: Final = 5_000_000
RAW_PATH: Final = {"huggingface.co": "resolve", "github.com": "raw"}  # each host's raw-file path
_SEGMENT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # never ".", "..", "" or "%"
USER_AGENT: Final = f"jarvis-speech-kit/{KIT_VERSION_NOW}"


class ModelError(RuntimeError):
    """A model could not be installed or checked (plain words; nothing half-installed is kept)."""


def _https(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username:
        raise ValueError("model files come only from https addresses of the pinned hosts")
    return url


def _at_commit(url: str, revision: str, name: str) -> bool:
    """A blob-pinned file's address is the host's raw file at exactly `revision` (R5.2 review: the
    commit anywhere else in the address, such as a query or a folder under a moving ref, is not
    the commit the file is fetched at): `/<owner>/<repo>/<resolve|raw>/<revision>/.../<name>`,
    plain segments only, no port, query or fragment."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    if port is not None or parts.query or parts.fragment or not parts.path.startswith("/"):
        return False
    segments = parts.path[1:].split("/")
    if len(segments) < 5 or not all(_SEGMENT.fullmatch(s) for s in segments):
        return False
    _owner, _repo, kind, at, *_ = segments
    raw = RAW_PATH.get(parts.hostname or "")
    return kind == raw and at == revision and segments[-1] == name


def _permissive(licence: str) -> str:
    if licence not in PERMISSIVE_LICENCES:
        raise ValueError("a model whose licence is not permissive is left out")
    return licence


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelFile(_Strict):
    name: str = Field(pattern=FILE_NAME)
    url: str = Field(max_length=500)
    sha256: str | None = Field(default=None, pattern=SHA256)
    git_blob_sha1: str | None = Field(default=None, pattern=GIT_BLOB)  # small text files only
    size: int = Field(gt=0, le=MAX_FILE)

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _https(self.url)
        if (self.sha256 is None) == (self.git_blob_sha1 is None):
            raise ValueError("a file is pinned by its SHA-256, or a small text file by its blob id")
        if self.git_blob_sha1 is not None and (
            not self.name.endswith(BLOB_PIN_SUFFIXES) or self.size > BLOB_PIN_MAX
        ):
            raise ValueError("only a JSON or TXT file of at most 5 MB may be pinned by its blob id")
        return self

    def matches(self, sha256: str, blob_sha1: str) -> bool:
        if self.sha256 is not None:
            return sha256 == self.sha256
        return blob_sha1 == self.git_blob_sha1


class ModelEntry(_Strict):
    slot: EngineSlot
    model: str = Field(min_length=1, max_length=80)
    source: str = Field(max_length=300)  # the model's own page
    revision: str = Field(pattern=REVISION)
    licence: str
    licence_file: str | None = Field(default=None, pattern=FILE_NAME)
    files: tuple[ModelFile, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _https(self.source)
        _permissive(self.licence)
        names = [f.name for f in self.files]
        if len(set(names)) != len(names) or LICENCE_NAME in names:
            raise ValueError("file names are unique and never LICENCE.txt")
        if self.licence_file is not None and self.licence_file not in names:
            raise ValueError("the licence file is one of the pinned files")
        for f in self.files:
            if f.git_blob_sha1 is None:
                continue
            if not COMMIT.fullmatch(self.revision) or not _at_commit(f.url, self.revision, f.name):
                raise ValueError("a blob id pins a file only when it is fetched at a full commit")
        return self


class LeftOut(_Strict):
    slot: EngineSlot
    source: str = Field(max_length=300)
    licence: str | None = None  # as confirmed, or None when it could not be
    why: str = Field(min_length=1, max_length=300)


class Manifest(_Strict):
    manifest: Literal[1]
    kit_version: str = Field(pattern=KIT_VERSION)
    models: tuple[ModelEntry, ...] = Field(default=(), max_length=16)
    left_out: tuple[LeftOut, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _one_each(self) -> Self:
        slots = [m.slot for m in self.models]
        if len(set(slots)) != len(slots):
            raise ValueError("one pinned model per slot")
        if set(slots) & {m.slot for m in self.left_out}:
            raise ValueError("a slot is pinned or left out, not both")
        return self

    def entry(self, slot: EngineSlot) -> ModelEntry | None:
        return next((m for m in self.models if m.slot is slot), None)


class InstalledFile(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    sha256: str
    size: int


class InstalledModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    slot: EngineSlot
    model: str
    revision: str
    licence: str
    source: str
    files: tuple[InstalledFile, ...]
    installed_at: AwareDatetime


class Installed(BaseModel):
    model_config = ConfigDict(frozen=True)
    kit_version: str = KIT_VERSION_NOW
    models: tuple[InstalledModel, ...] = ()

    def get(self, slot: EngineSlot) -> InstalledModel | None:
        return next((m for m in self.models if m.slot is slot), None)


def load_manifest(path: Path) -> Manifest:
    try:
        return Manifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        raise ModelError("The kit's model list (models.json) is missing.") from None
    except ValidationError:
        raise ModelError("The kit's model list (models.json) is not valid.") from None


# ---- downloads -----------------------------------------------------------------------------------
Opener = Callable[[str], AbstractContextManager[IO[bytes]]]


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]  # urllib's own signature
        self, req, fp, code, msg, headers, newurl
    ):
        if urlsplit(newurl).scheme != "https":
            raise ModelError("A download tried to leave https; nothing was installed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_open(url: str) -> AbstractContextManager[IO[bytes]]:
    """Open a pinned address (https only, redirects only to https; the hash is the real check)."""
    _https(url)
    opener = urllib.request.build_opener(_HttpsOnly())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    response: AbstractContextManager[IO[bytes]] = opener.open(request, timeout=TIMEOUT_S)
    return response


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob(size: int) -> hashlib._Hash:
    """git's blob id of `size` bytes, to be fed the data: SHA-1 of "blob <size>", NUL, data."""
    return hashlib.sha1(b"blob %d\0" % size)


def digests_of(path: Path) -> tuple[str, str]:
    """(SHA-256, git blob id) of a file, in one read."""
    sha, blob = hashlib.sha256(), git_blob(path.stat().st_size)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            sha.update(block)
            blob.update(block)
    return sha.hexdigest(), blob.hexdigest()


class ModelManager:
    def __init__(
        self,
        manifest: Manifest,
        models_dir: Path,
        installed_file: Path,
        *,
        opener: Opener = https_open,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.manifest = manifest
        self.models_dir = models_dir
        self.installed_file = installed_file
        self._open = opener
        self._now = now

    def installed(self) -> Installed:
        try:
            return Installed.model_validate_json(self.installed_file.read_bytes())
        except FileNotFoundError:
            return Installed()
        except ValidationError:
            log.warning("installed.json is not readable; treating it as empty")
            return Installed()

    def model_dir(self, slot: EngineSlot) -> Path | None:
        """The slot's folder when its pinned files are all there at their sizes, else None."""
        done = self.installed().get(slot)
        pinned = self.manifest.entry(slot)
        if done is None or pinned is None or done.revision != pinned.revision:
            return None
        folder = self.models_dir / slot.value
        for f in pinned.files:
            target = folder / f.name
            if not target.is_file() or target.stat().st_size != f.size:
                return None
        return folder

    def install(self, slot: EngineSlot, progress: Callable[[str], None] = lambda _: None) -> Path:
        entry = self.manifest.entry(slot)
        if entry is None:
            raise ModelError("That engine has no pinned model in this kit.")
        folder = private_dir(self.models_dir / slot.value)
        hashes: dict[str, str] = {}  # name -> SHA-256 (computed for a blob-pinned file)
        for f in entry.files:
            target = folder / f.name
            have = self._matching(f, target)
            if have is not None:
                progress(f"{f.name}: already here, hash OK")
                hashes[f.name] = have
                continue
            progress(f"{f.name}: downloading {f.size / 1e6:,.1f} MB")
            hashes[f.name] = self._download(f, target)
        self._write_licence(entry, folder, hashes)
        self._record(entry, hashes)
        return folder

    @staticmethod
    def _matching(f: ModelFile, target: Path) -> str | None:
        """The file's SHA-256 when it is there and matches its pin, else None."""
        if not target.is_file() or target.stat().st_size != f.size:
            return None
        sha, blob = digests_of(target)
        return sha if f.matches(sha, blob) else None

    def _download(self, f: ModelFile, target: Path) -> str:
        part = target.with_name(f"{target.name}.part")
        digest, blob = hashlib.sha256(), git_blob(f.size)
        count = 0
        try:
            with self._open(f.url) as response, part.open("wb") as out:
                for block in iter(lambda: response.read(CHUNK), b""):
                    count += len(block)
                    if count > f.size:
                        raise ModelError(f"{f.name} is bigger than pinned; nothing was installed.")
                    digest.update(block)
                    blob.update(block)
                    out.write(block)
            if count != f.size or not f.matches(digest.hexdigest(), blob.hexdigest()):
                kind = "SHA-256" if f.sha256 is not None else "git blob id"
                raise ModelError(f"{f.name} did not match its pinned {kind}; nothing installed.")
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        part.replace(target)
        return digest.hexdigest()

    def _write_licence(self, entry: ModelEntry, folder: Path, hashes: dict[str, str]) -> None:
        lines = [
            f"Model: {entry.model} (JARVIS speech kit slot {entry.slot.value})",
            f"Licence: {entry.licence} (SPDX)",
            f"Source: {entry.source}",
            f"Revision: {entry.revision}",
            "Files (SHA-256):",
            *(f"  {hashes[f.name]}  {f.name}" for f in entry.files),
        ]
        if entry.licence_file is not None:
            text = (folder / entry.licence_file).read_text(encoding="utf-8", errors="replace")
            lines += ["", f"--- {entry.licence_file} ---", text]
        write_private(folder / LICENCE_NAME, ("\n".join(lines) + "\n").encode("utf-8"))

    def _record(self, entry: ModelEntry, hashes: dict[str, str]) -> None:
        current = [m for m in self.installed().models if m.slot is not entry.slot]
        current.append(
            InstalledModel(
                slot=entry.slot,
                model=entry.model,
                revision=entry.revision,
                licence=entry.licence,
                source=entry.source,
                files=tuple(
                    InstalledFile(name=f.name, sha256=hashes[f.name], size=f.size)
                    for f in entry.files
                ),
                installed_at=self._now(),
            )
        )
        done = Installed(models=tuple(sorted(current, key=lambda m: m.slot.value)))
        write_private(self.installed_file, done.model_dump_json(indent=2).encode("utf-8"))

    def verify(self, slots: Iterable[EngineSlot] | None = None) -> dict[EngineSlot, str | None]:
        """Re-hash every installed file: None when the slot is whole, else plain words."""
        found: dict[EngineSlot, str | None] = {}
        wanted = list(slots) if slots is not None else [m.slot for m in self.installed().models]
        for slot in wanted:
            entry = self.manifest.entry(slot)
            if entry is None or self.model_dir(slot) is None:
                found[slot] = "not installed"
                continue
            bad = [
                f.name
                for f in entry.files
                if self._matching(f, self.models_dir / slot.value / f.name) is None
            ]
            found[slot] = f"hash mismatch: {', '.join(bad)}" if bad else None
        return found

    def remove(self, slot: EngineSlot) -> bool:
        folder = self.models_dir / slot.value
        existed = folder.exists()
        if existed:
            shutil.rmtree(folder)
        remaining = tuple(m for m in self.installed().models if m.slot is not slot)
        write_private(
            self.installed_file, Installed(models=remaining).model_dump_json(indent=2).encode()
        )
        return existed


def manifest_text(manifest: Manifest) -> list[str]:
    """Plain lines: what may be installed and what was left out, with licences."""
    lines = [
        f"{m.slot.value}: {m.model} ({m.licence}), {sum(f.size for f in m.files) / 1e6:,.0f} MB"
        for m in manifest.models
    ]
    lines += [f"{m.slot.value}: left out ({m.why})" for m in manifest.left_out]
    return lines


__all__ = [
    "ALLOWED_HOSTS",
    "LICENCE_NAME",
    "Installed",
    "InstalledModel",
    "LeftOut",
    "Manifest",
    "ModelEntry",
    "ModelError",
    "ModelFile",
    "ModelManager",
    "digests_of",
    "git_blob",
    "https_open",
    "load_manifest",
    "manifest_text",
    "sha256_of",
]
