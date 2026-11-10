# tests/book_gen_fakes.py
"""Helpers for builder A's generator tests and the `gen` eval (R6 D2-D5).

- `fixture_repo(tmp)`: the I0 fixture repo (tests/fixtures/book/repo) copied into `tmp` and
  committed into a fresh git repository with fixed dates, so its commit id never changes.
- `fixture_needles()`: the fixture's e-mail, phone and name, READ from its plan at run time (this
  file never spells them out).
- `plant_personal(repo)`: adds a plan whose extracted lines hold those needles (a D-heading, a
  risk, a "Not in this plan"), so a build with the scrub off would leak them.
- `fake_secret(kind)`: a secret-SHAPED string built at run time; no tracked file holds one, so
  the real repo's snapshot scan never trips on these tests.
- `FIXTURE_FLOWS`: ten flows naming the fixture's own symbols (`gen.flows.Flow` shape).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "book" / "repo"
COMMIT_DATE = "2026-11-10T09:00:00+05:30"
_PLAN = FIXTURE / "docs" / "plans" / "r1-fixture-alpha.md"

FIXTURE_FLOWS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("chat_turn", "One conversation turn", (("The loop answers", "core.loop:Loop.turn"),)),
    ("approval", "Confirm before commit", (("The loop", "core.loop:Loop"),)),
    ("learning", "Learning after a turn", (("The loop module", "core.loop"),)),
    ("voice_turn", "A spoken turn", (("The loop answers", "core.loop:Loop.turn"),)),
    ("morning_tick", "The morning tick", (("A fixed text", "notify.ports:text_for"),)),
    ("vault_open", "Opening the vault", (("Sealed storage", "vault.store:seal"),)),
    ("home_alert", "A home alert", (("The templates", "notify.ports:TEMPLATES"),)),
    ("systems_check", "The systems check", (("The alerts module", "notify.ports"),)),
    ("no_ai", "No-AI mode", (("The loop module", "core.loop"),)),
    ("build_book", "The build book", (("Sealed storage", "vault.store"),)),
)


def git(root: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": COMMIT_DATE,
        "GIT_COMMITTER_DATE": COMMIT_DATE,
    }
    out = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def commit_all(root: Path, message: str = "fixture") -> None:
    if not (root / ".git").exists():
        git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def fixture_repo(tmp: Path, name: str = "repo") -> Path:
    dest = tmp / name
    shutil.copytree(FIXTURE, dest)
    commit_all(dest)
    return dest


def fixture_needles() -> tuple[str, str, str]:
    """(e-mail, phone, name) as the fixture plan writes them."""
    text = _PLAN.read_text(encoding="utf-8")
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+\w", text)
    phone = re.search(r"\+91 ?[6-9]\d{9}", text)
    name = re.search(r"Reviewed with ([A-Z][a-z]+ [A-Z][a-z]+)", text)
    assert email and phone and name, "the fixture plan changed"
    return email.group(0), phone.group(0), name.group(1)


def plant_personal(repo: Path) -> None:
    """A plan whose EXTRACTED text holds the fixture's e-mail, phone and name."""
    email, phone, name = fixture_needles()
    text = (
        "# R1.1 — Planted: personal data in extracted places\n\n"
        f"Status: test. Not in this plan: calls to {phone}.\n\n"
        "## Decisions\n\n"
        f"**D1 · Mail {email} about it.** Body.\n\n"
        "## Risks\n"
        f"- {name} reads every alert.\n"
    )
    (repo / "docs" / "plans" / "r1-1-planted.md").write_text(text, encoding="utf-8")
    commit_all(repo, "plant")


def fake_secret(kind: str) -> str:
    """A secret-shaped FAKE, assembled at run time so no tracked file holds the shape."""
    parts = {
        "google": ("AIza", "Sy" + "Q" * 33),
        "anthropic": ("sk-" + "ant-", "api03-" + "x" * 40),
        "github": ("gh" + "p_", "Z" * 36),
        "aws": ("AK" + "IA", "Q" * 16),
        "telegram": ("123456789" + ":", "A" * 35),
        "pem": ("-----BEGIN RSA " + "PRIVATE", " KEY-----"),
    }
    head, tail = parts[kind]
    return head + tail


__all__ = [
    "COMMIT_DATE",
    "FIXTURE",
    "FIXTURE_FLOWS",
    "ROOT",
    "commit_all",
    "fake_secret",
    "fixture_needles",
    "fixture_repo",
    "git",
    "plant_personal",
]
