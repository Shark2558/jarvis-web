# evals/r6_book/gen.py
"""R6 eval part `gen` (builder A): the build book generator (D2-D5), on copies of the I0 fixture
repo (tests/fixtures/book/repo), committed into throw-away git checkouts.

    double_build_byte_equal   two builds, and two copies of the same commit, give the same bytes
    every_section_present     the eight sections, scenes 1-11, the ten flows and the digest
    no_personal_data          the fixture's e-mail, phone and hashed name, planted where the
                              generator reads, never reach book.json
    planted_key_refused       a planted `AIza…` key refuses the snapshot (and names no secret)
    listed_fake_passes        the same key listed in fake_secrets passes; so does the fixture's own
    snapshot_16mb_refused     a 16 MB snapshot is refused at the real 15 MB cap
    missing_flow_fails        a flow naming a function that isn't there fails the build
    licences_labelled         MIT / Apache / GPL / unknown labelled; GPL flagged and listed

Negative control: the scrub off (`NoScrub`): the planted e-mail reaches book.json and the suite
must fail. Every secret-shaped string here is assembled at run time (book_gen_fakes.fake_secret).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from book_gen_fakes import (
    FIXTURE_FLOWS,
    commit_all,
    fake_secret,
    fixture_needles,
    fixture_repo,
    plant_personal,
)

from jarvis.buildbook.gen import snapshot, write
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import NoScrub, Scrubber, default_scrubber
from jarvis.buildbook.model import BOOK_SCENES, FLOW_IDS, SECTION_IDS, load_book

PART = "gen"
BUILT = True
Case = dict[str, Any]
LICENCES = {"fastapi": "MIT", "httpx": "Apache-2.0", "pydantic": "GPL-3.0-only"}


def _opts(scrub: Scrubber, **kw: Any) -> write.Options:
    licence: Callable[[str], str] = lambda n: LICENCES.get(n, "not stated")  # noqa: E731
    return write.Options(flows=FIXTURE_FLOWS, scrubber=scrub, licence=licence, **kw)


def _case(name: str, failures: list[str]) -> Case:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


def _double(tmp: Path, scrub: Scrubber) -> Case:
    a, b = Repo.from_git(fixture_repo(tmp, "a")), Repo.from_git(fixture_repo(tmp, "b"))
    one, two, again = (write.build(r, _opts(scrub)) for r in (a, b, a))
    same = (one.book, one.source) == (two.book, two.source) == (again.book, again.source)
    return _case("double_build_byte_equal", [] if same else ["the bytes differ"])


def _sections(tmp: Path, scrub: Scrubber) -> Case:
    book = load_book(write.build(Repo.from_git(fixture_repo(tmp, "s")), _opts(scrub)).book)
    fails = [f"section {s} missing" for s in SECTION_IDS if s not in book.sections()]
    if len(book.show.scenes) != BOOK_SCENES:
        fails.append("the show is not scenes 1-11")
    if tuple(w.id for w in book.workflows) != FLOW_IDS:
        fails.append("a flow is missing")
    if not book.digest.chunks:
        fails.append("the digest is empty")
    return _case("every_section_present", fails)


def _personal(tmp: Path, scrub: Scrubber) -> Case:
    root = fixture_repo(tmp, "p")
    plant_personal(root)
    text = write.build(Repo.from_git(root), _opts(scrub)).book.decode("utf-8")
    email, phone, name = fixture_needles()
    kinds = {"the e-mail": [email], "the phone": [phone], "the name": name.split()}
    return _case(
        "no_personal_data",
        [f"{k} reached book.json" for k, v in kinds.items() if any(n in text for n in v)],
    )


def _secrets(tmp: Path) -> list[Case]:
    root = fixture_repo(tmp, "k")
    key = fake_secret("google")
    (root / "src" / "jarvis" / "core" / "keys.py").write_text(f'K = "{key}"\n', encoding="utf-8")
    commit_all(root, "plant a key")
    r, fakes = Repo.from_git(root), snapshot.load_fakes()
    refused: list[str] = ["the planted key was not refused"]
    try:
        snapshot.build(r, fakes)
    except GenError as exc:
        refused = ["the refusal shows the secret"] if key in str(exc) else []
    listed: list[str] = []
    try:
        fake = (hashlib.sha256(key.encode()).hexdigest(), "src/jarvis/core/keys.py")
        snapshot.build(r, fakes | {fake})
    except GenError:
        listed.append("a listed fake was refused")
    return [_case("planted_key_refused", refused), _case("listed_fake_passes", listed)]


def _cap(tmp: Path) -> Case:
    root = tmp / "big"
    root.mkdir()
    for n in range(17):  # incompressible, each under the 1 MB "left out" line
        (root / f"blob{n:02d}.txt").write_bytes(os.urandom(snapshot.LARGE_BYTES - 4096))
    r = Repo.from_dir(root, sha="b" * 40, committed_at="2026-11-10T09:00:00+05:30")
    try:
        snapshot.build(r, frozenset())
    except GenError as exc:
        return _case("snapshot_16mb_refused", [] if "cap" in str(exc) else [str(exc)[:80]])
    return _case("snapshot_16mb_refused", ["a 16 MB snapshot was accepted"])


def _flow(tmp: Path, scrub: Scrubber) -> Case:
    broken = tuple(
        (f, t, (*s, ("Moved", "core.loop:Loop.vanished"))) if f == "approval" else (f, t, s)
        for f, t, s in FIXTURE_FLOWS
    )
    r = Repo.from_git(fixture_repo(tmp, "f"))
    try:
        write.build(r, write.Options(flows=broken, scrubber=scrub, licence=lambda _n: "MIT"))
    except GenError as exc:
        return _case("missing_flow_fails", [] if "approval" in str(exc) else ["wrong message"])
    return _case("missing_flow_fails", ["a flow naming missing code was accepted"])


def _licences(tmp: Path, scrub: Scrubber) -> Case:
    root = fixture_repo(tmp, "l")
    with (root / "requirements.lock").open("a", encoding="utf-8") as fh:
        fh.write("mystery-lib==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n")
    commit_all(root, "an unknown dist")
    book = load_book(write.build(Repo.from_git(root), _opts(scrub)).book)
    got = {lib.name: (lib.licence, lib.flag) for lib in book.libraries}
    want = {
        "fastapi": ("MIT", None),
        "httpx": ("Apache-2.0", None),
        "pydantic": ("GPL-3.0-only", "copyleft"),
        "mystery-lib": ("not stated", None),
    }
    fails = [f"{n}: {got.get(n)} != {w}" for n, w in want.items() if got.get(n) != w]
    if not any(x.kind == "licence" and "pydantic" in x.text for x in book.limitations):
        fails.append("the GPL flag is not a limitation")
    return _case("licences_labelled", fails)


def _run(scrub: Scrubber) -> list[Case]:
    with tempfile.TemporaryDirectory(prefix="r6-gen-") as d:
        tmp = Path(d)
        return [
            _double(tmp, scrub),
            _sections(tmp, scrub),
            _personal(tmp, scrub),
            *_secrets(tmp),
            _cap(tmp),
            _flow(tmp, scrub),
            _licences(tmp, scrub),
        ]


async def cases() -> list[Case]:
    return _run(default_scrubber())


async def control() -> dict[str, Any]:
    results = _run(NoScrub())
    failed = [c["id"] for c in results if not c["passed"]]
    return {"name": "gen: scrub off", "suite_failed": bool(failed), "failed_cases": failed}
