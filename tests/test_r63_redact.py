# tests/test_r63_redact.py -- R6.3 I0 M8 (docs/plans/r6-3-book-content.md D4, seam 17): the owner's
# locality, workplace and employer words join the build book's redact list as SHA-256 hashes ONLY
# (`scripts/redact_add.py`), so the scrubber removes them from book.json, facts.json and every
# reading pack the writer's brains are sent. Tested with MADE-UP words: the script writes hashes,
# never a word; prints counts only; is idempotent; and the scrubber then removes the words in any
# case or accent. The real list stays valid, sorted and unique.
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from jarvis.buildbook.gen import scrub

ROOT = Path(__file__).resolve().parents[1]
REDACT = ROOT / "src" / "jarvis" / "buildbook" / "gen" / "redact.json"
MADE_UP = ("Zorblaxton", "Quimbledorf Works", "Xy")  # a locality, a workplace (two words), a short


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("redact_add", ROOT / "scripts" / "redact_add.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["redact_add"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    words = tmp_path / "words.txt"
    words.write_text("\n".join(MADE_UP) + "\n", encoding="utf-8")
    redact = tmp_path / "redact.json"
    shutil.copy(REDACT, redact)
    return words, redact


def test_the_words_become_hashes_only_and_the_scrubber_removes_them(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    words, redact = files
    before = set(json.loads(redact.read_text())["sha256"])
    assert _script().main([str(words), "--redact", str(redact)]) == 0
    out = capsys.readouterr()
    text = redact.read_text(encoding="utf-8")
    for w in ("Zorblaxton", "Quimbledorf", "Works"):
        assert (
            w.lower() not in text.lower() and w not in out.out + out.err
        )  # never written, never said
    data = json.loads(text)
    assert data["sha256"] == sorted(set(data["sha256"])) and len(data["sha256"]) == len(before) + 3
    assert hashlib.sha256(b"zorblaxton").hexdigest() in data["sha256"]
    assert "3 word hashes, 3 new, 1 short words skipped" in out.out
    s = scrub.Scrubber(scrub.load_redact(redact))
    for text_in in ("near ZORBLAXTON today", "at Quimbledorf Works", "Zörblaxton2026"):
        assert "name" in s.findings(text_in) and scrub.REMOVED in s.clean(text_in), text_in


def test_a_second_run_adds_nothing(files: tuple[Path, Path]) -> None:
    words, redact = files
    mod = _script()
    first = mod.add(words, redact)
    again = mod.add(words, redact)
    assert first["added"] == 3 and again["added"] == 0 and again["total"] == first["total"]


def test_a_missing_words_file_writes_nothing(tmp_path: Path) -> None:
    redact = tmp_path / "redact.json"
    shutil.copy(REDACT, redact)
    before = redact.read_bytes()
    assert _script().main([str(tmp_path / "absent.txt"), "--redact", str(redact)]) == 2
    assert redact.read_bytes() == before


def test_the_real_list_is_valid_sorted_and_unique() -> None:
    data = json.loads(REDACT.read_text(encoding="utf-8"))
    hashes = data["sha256"]
    assert hashes == sorted(set(hashes)) and len(hashes) >= 4
    assert scrub.load_redact(REDACT) == frozenset(hashes)
    assert "locality" in data["about"] and "employer" in data["about"]  # what the hashes are
