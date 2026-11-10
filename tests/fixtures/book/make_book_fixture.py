# tests/fixtures/book/make_book_fixture.py
# ruff: noqa: E501 -- the fixture book is a data table
"""Writes tests/fixtures/book/_book/ (R6 I0 seam 7): a valid `release.json`, a canonical
`book.json` (`jarvis.buildbook.model.Book` v1, every section, scenes 1-11, all 10 flows) and a
3-file `source.zip` laid out as D5 says (sorted, fixed stamp, 0644, root `JARVIS-source-<id>/`),
taken from the fixture repo next to it. The book is what a scrubbed build of that repo could say:
no e-mail, phone number or name from its plans. The files are committed; re-run after a schema
change:

    PYTHONPATH=src python tests/fixtures/book/make_book_fixture.py
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

from jarvis.buildbook import model
from jarvis.buildbook.model import Book, Release, canonical_bytes

HERE = Path(__file__).resolve().parent
REPO, OUT = HERE / "repo", HERE / "_book"
SHA = hashlib.sha1(b"jarvis r6 build book fixture").hexdigest()  # a fake commit id
RID = SHA[:7]
COMMITTED = "2026-11-10T09:00:00+05:30"
SOURCES = ("src/jarvis/core/loop.py", "src/jarvis/notify/ports.py", "src/jarvis/vault/store.py")
FLOWS = {
    "chat_turn": ("One conversation turn", "jarvis.core.loop:Loop.turn"),
    "approval": ("Confirm before commit", "jarvis.core.loop:Loop"),
    "learning": ("Learning after a turn", "jarvis.core.loop"),
    "voice_turn": ("A spoken turn", "jarvis.core.loop:Loop.turn"),
    "morning_tick": ("The morning tick", "jarvis.notify.ports:text_for"),
    "vault_open": ("Opening the vault", "jarvis.vault.store:seal"),
    "home_alert": ("A home alert", "jarvis.notify.ports:TEMPLATES"),
    "systems_check": ("The systems check", "jarvis.notify.ports"),
    "no_ai": ("No-AI mode", "jarvis.core.loop"),
    "build_book": ("The build book", "jarvis.vault.store"),
}


def _source_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in sorted(SOURCES):
            info = zipfile.ZipInfo(f"JARVIS-source-{RID}/{rel}", date_time=model.ZIP_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (REPO / rel).read_bytes())
    return buf.getvalue()


def _sections() -> dict[str, Any]:
    return {
        "architecture": {
            "packages": [
                {"name": "core", "layer": "L4", "files": 2, "lines": 12, "summary": "Core reasoning (build book fixture)."},
                {"name": "notify", "layer": "L8", "files": 2, "lines": 10, "summary": "Alerts (build book fixture)."},
                {"name": "vault", "layer": "L7", "files": 2, "lines": 9, "summary": "Sealed storage (build book fixture)."},
            ],
            "fit": [
                {"release": "R1", "feature": "Core loop", "layer": "L4 reasoning · Task & Productivity", "phase": "0", "verdict": "Build now"},
                {"release": "R2.1", "feature": "Alerts", "layer": "L8 output · Communication", "phase": "4", "verdict": "Build now"},
            ],
        },
        "stack": {
            "items": [
                {"role": "language", "name": "Python", "version": ">=3.11", "source": "pyproject.toml"},
                {"role": "base image", "name": "python", "version": "3.12-slim", "source": "Dockerfile"},
                {"role": "ci job", "name": "test", "source": ".github/workflows/ci.yml"},
                {"role": "ci job", "name": "deploy", "source": ".github/workflows/ci.yml"},
            ]
        },
        "libraries": [
            {"name": "fastapi", "version": "0.115.0", "kind": "python", "licence": "MIT", "role": "web"},
            {"name": "httpx", "version": "0.27.2", "kind": "python", "licence": "BSD-3-Clause", "role": "web"},
            {"name": "pydantic", "version": "2.9.2", "kind": "python", "licence": "MIT", "role": "data"},
        ],
        "integrations": {
            "services": [
                {"id": "telegram", "label": "Telegram", "what": "Sends the owner's alerts from fixed templates.", "settings": ["telegram_bot_token"], "checked": True},
            ],
            "key_purposes": ["vault", "book_index", "book_session"],
            "alert_kinds": [
                {"kind": "book_sealed", "level": "important", "what": "A release's build book was sealed in the vault."},
            ],
        },
        "workflows": [
            {"id": fid, "title": title, "steps": [{"label": title, "symbol": symbol}]}
            for fid, (title, symbol) in FLOWS.items()
        ],
        "limitations": [
            {"text": "Alerts by SMS (it needs a paid service).", "kind": "deferred", "source": "docs/plans/r2-1-fixture-beta.md", "release": "R2.1"},
            {"text": "Voice, the home camera.", "kind": "not_in_plan", "source": "docs/plans/r1-fixture-alpha.md", "release": "R1"},
        ],
        "costs": {
            "usd_inr": 95.24,
            "rate_date": "2026-11-10",
            "items": [
                {"id": "balanced_in", "label": "Balanced brain, input", "kind": "model", "unit": "1M input tokens", "inr": 190.48},
                {"id": "cloud_run", "label": "Cloud Run", "kind": "cloud", "unit": "month", "inr": 0.0, "free": "2 million requests a month"},
            ],
        },
        "decisions": [
            {"plan": "docs/plans/r1-fixture-alpha.md", "release": "R1", "title": "Release R1 — Alpha: the core loop answers and remembers the conversation", "decisions": ["D1 · One loop.", "D2 · Sessions sealed."]},
            {"plan": "docs/plans/r2-1-fixture-beta.md", "release": "R2.1", "title": "R2.1 — Beta: alerts reach the owner", "decisions": ["D1 · Fixed texts."]},
        ],
    }  # fmt: skip


def _show() -> dict[str, Any]:
    scenes = []
    for n, sid, title in model.SHOW_SCENES[: model.BOOK_SCENES]:
        beats = [{"id": f"s{n:02d}b01", "text": f"{title}: release R2.1 of the fixture."}]
        if n == 2:
            beats.append(
                {"id": "s02b02", "text": "The core loop sits in layer four.", "focus": "L4"}
            )
        facts = [{"label": "Core reasoning", "value": "L4", "n": 2.0}] if n == 2 else []
        scenes.append({"n": n, "id": sid, "title": title, "beats": beats, "facts": facts})
    return {"scenes": scenes}


def build_book() -> Book:
    ref = {"id": RID, "sha": SHA, "label": "R2.1", "committed_at": COMMITTED}
    digest = {
        "overview": "JARVIS (fixture) has a core loop, sealed storage and fixed-text alerts.",
        "chunks": [
            {
                "id": "c001",
                "section": "architecture",
                "text": "core (L4), vault (L7), notify (L8).",
            },
            {"id": "c002", "section": "workflows", "text": "A turn: Loop.turn, then the reply."},
        ],
    }
    return Book.model_validate(
        {"v": 1, "release": ref, **_sections(), "show": _show(), "digest": digest}
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    book, source = canonical_bytes(build_book()), _source_zip()
    release = Release(
        id=RID,
        sha=SHA,
        label="R2.1",
        committed_at=COMMITTED,
        book_sha256=hashlib.sha256(book).hexdigest(),
        source_sha256=hashlib.sha256(source).hexdigest(),
        source_bytes=len(source),
        skipped=0,
    )
    (OUT / "book.json").write_bytes(book)
    (OUT / "source.zip").write_bytes(source)
    text = release.model_dump_json(indent=2) + "\n"
    (OUT / "release.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
