# src/jarvis/buildbook/gen/write.py
"""R6 D2-D5: assemble the book, build its three files, check determinism, write them.

    build(repo, opts)      -> Built(release, book bytes, source bytes); GenError when the book
                              can't be built honestly (an unmapped package, a flow naming
                              missing code, personal text left, a secret, a file over its cap)
    check(repo, opts)      -> builds twice and refuses if the bytes differ (the CI gate)
    write(out, built)      -> book.json, source.zip, then release.json (last, so a reader never
                              sees a release naming files that aren't there yet)
    write_error(out, repo, message) -> the best-effort release.json: `error`, no book (D4)

`Options` carries what tests replace: the flows, the layer table, the scrubber (the eval's
negative control passes `NoScrub`), the known fakes, the snapshot cap and the licence lookup
(default: the checkout's committed requirements.licences.json, never the environment).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from jarvis.buildbook.gen import code, costs, fallback, flows, libs, licences, plans, snapshot
from jarvis.buildbook.gen.chunks import build_digest
from jarvis.buildbook.gen.code import clip
from jarvis.buildbook.gen.layers import LAYER_OF
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import Scrubber, default_scrubber
from jarvis.buildbook.gen.show import Parts, build_show
from jarvis.buildbook.model import (
    BOOK_JSON_CAP_BYTES,
    MAX_LIMITATIONS,
    SNAPSHOT_CAP_BYTES,
    Book,
    Release,
    ReleaseRef,
    canonical_bytes,
)
from jarvis.buildbook.sections import Architecture

FILES = ("book.json", "source.zip")
RELEASE_FILE = "release.json"


@dataclass(frozen=True)
class Options:
    flows: tuple[flows.Flow, ...] = flows.FLOWS
    layer_of: Mapping[str, str] = field(default_factory=lambda: LAYER_OF)
    scrubber: Scrubber | None = None  # None: gen/redact.json
    fakes: snapshot.Fakes | None = None  # None: gen/fake_secrets.txt
    snapshot_cap: int = SNAPSHOT_CAP_BYTES
    licence: libs.LicenceLookup | None = None  # None: requirements.licences.json (the commit's)


@dataclass(frozen=True)
class Built:
    release: Release
    book: bytes
    source: bytes


def release_version(repo: Repo) -> str | None:
    """R6.1 decision 3: "v6.1.0" from the documented checkout's own src/jarvis/__init__.py."""
    return fallback.version_of(repo.text(fallback.VERSION_FILE))


def _parts(repo: Repo, opts: Options, scrub: Scrubber) -> Parts:
    label = plans.release_label(repo)
    read = plans.read_plans(repo, scrub)
    libraries = libs.libraries(repo, opts.licence or licences.table_lookup(repo))
    limits = (*libs.licence_limits(libraries, label), *plans.limitations(read))
    return Parts(
        release=ReleaseRef(
            id=repo.id,
            sha=repo.sha,
            label=label,
            committed_at=repo.committed_at,
            version=release_version(repo),
        ),
        architecture=Architecture(
            packages=code.packages(repo, opts.layer_of, scrub), fit=plans.fit_rows(read)
        ),
        stack=libs.stack(repo),
        libraries=libraries,
        integrations=code.integrations(repo, scrub),
        workflows=flows.workflows(repo, opts.flows),
        limitations=limits[:MAX_LIMITATIONS],
        costs=costs.costs(repo),
        decisions=plans.decisions(read),
    )


def assemble(repo: Repo, opts: Options) -> Book:
    scrub = opts.scrubber or default_scrubber()
    try:
        p = _parts(repo, opts, scrub)
        book = Book(
            release=p.release,
            architecture=p.architecture,
            stack=p.stack,
            libraries=p.libraries,
            integrations=p.integrations,
            workflows=p.workflows,
            limitations=p.limitations,
            costs=p.costs,
            decisions=p.decisions,
            show=build_show(p),
            digest=build_digest(p),
        )
    except ValidationError as exc:
        where = sorted({".".join(str(x) for x in e["loc"][:2]) for e in exc.errors()})[:5]
        raise GenError(f"the book doesn't fit its schema ({exc.error_count()}): {where}") from None
    scrub.verify(book.model_dump(mode="json"))
    return book


def build(repo: Repo, opts: Options = Options()) -> Built:  # noqa: B008 - frozen, immutable
    data = canonical_bytes(assemble(repo, opts))
    if len(data) > BOOK_JSON_CAP_BYTES:
        raise GenError(f"book.json is {len(data):,} bytes, over its {BOOK_JSON_CAP_BYTES:,} cap")
    fakes = opts.fakes if opts.fakes is not None else snapshot.load_fakes()
    snap = snapshot.build(repo, fakes, cap=opts.snapshot_cap)
    release = Release(
        id=repo.id,
        sha=repo.sha,
        label=plans.release_label(repo),
        committed_at=repo.committed_at,
        version=release_version(repo),
        book_sha256=hashlib.sha256(data).hexdigest(),
        source_sha256=snap.sha256,
        source_bytes=len(snap.data),
        skipped=snap.skipped,
    )
    return Built(release=release, book=data, source=snap.data)


def check(repo: Repo, opts: Options = Options()) -> Built:  # noqa: B008
    first, second = build(repo, opts), build(repo, opts)
    differ = [
        n
        for n, a, b in (
            ("book.json", first.book, second.book),
            ("source.zip", first.source, second.source),
        )
        if a != b
    ]
    if differ:
        raise GenError(f"two builds of the same commit differ: {', '.join(differ)}")
    return first


def release_bytes(release: Release) -> bytes:
    doc = release.model_dump(mode="json")
    return (json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _put(out: Path, name: str, data: bytes) -> None:
    tmp = out / f".{name}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, out / name)


def write(out: Path, built: Built) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _put(out, FILES[0], built.book)
    _put(out, FILES[1], built.source)
    _put(out, RELEASE_FILE, release_bytes(built.release))


def write_error(out: Path, repo: Repo, message: str) -> Release:
    """D4 best effort: a release.json that says the book failed, and no book beside it."""
    try:
        label = plans.release_label(repo)
    except (OSError, GenError):
        label = "R0"
    release = Release(
        id=repo.id,
        sha=repo.sha,
        label=label,
        committed_at=repo.committed_at,
        version=release_version(repo),
        error=clip(message, 200) or "the build book failed",
    )
    out.mkdir(parents=True, exist_ok=True)
    fallback.clear(out)
    _put(out, RELEASE_FILE, release_bytes(release))
    return release


__all__ = [
    "Built",
    "Options",
    "assemble",
    "build",
    "check",
    "release_bytes",
    "release_version",
    "write",
    "write_error",
]
