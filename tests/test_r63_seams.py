# tests/test_r63_seams.py -- R6.3 I0 (docs/plans/r6-3-book-content.md "The I0 seam list" 1-17,
# "Size guards"): the pins of what I0 built and of what R6.3 must leave alone. Each seam's own
# behaviour is tested in its file (test_r63_types, _modules, _gen_joins, _serve, _console_seams,
# _scrub_kinds, _static, _fakes, _refs_services, _redact; R6.3.1: test_r631_*); here: the version,
# the staged eval runner, the files no part edits, the sizes, the keyring and the guide.
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import jarvis
from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.writer.model import COLLECTIONS
from jarvis.keyring import PURPOSES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 1 · the version and the release ------------------------------------------------------------
def test_the_version_is_six_point_three() -> None:
    # R6.4 (6.3.2 at R6.3.1, 13.1.0 at R13.1); the persona is unchanged
    assert jarvis.__version__ == "6.4.0"
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R6.4"
    assert plans.plan_paths(repo)[0] == "docs/plans/r6-4-book-look.md"


# ---- 12 · the staged eval runner ----------------------------------------------------------------
def test_the_eval_runner_is_staged_until_i1_and_gated() -> None:
    runner = _load(ROOT / "evals" / "r6_3" / "run.py", "r6_3_run_pin")
    assert runner.STUBS_PASS is False  # I1 flipped it: a stub never reads as green
    for part in runner.PARTS:  # and every part is built (I1: console, needles, e2e)
        assert _load(ROOT / "evals" / "r6_3" / f"{part}.py", f"r6_3_{part}_pin").BUILT is True, part
    assert runner.PARTS == ("facts", "tour", "authored")  # R6.3.1 D8: the writer's parts went
    gate = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    assert (
        '("r6_3 (gated)", [sys.executable, str(HERE / "r6_3" / "run.py"), "--mock"], True)' in gate
    )


# ---- 3, D0, M4 · what R6.3 never edits ----------------------------------------------------------
# R6.3.1 D7 seals each release's pages and flows with its book and code, so `seal_index.py`,
# `seal.py` and `sealer.py` changed on purpose (tests/test_r631_e_serve.py); the rest still holds.
UNTOUCHED = {  # 47ee8fc's SHA-256, under src/jarvis/
    "api/static/console.html": "9f4c0c68f45e46fe150e65e182f4d2ba1132eb556b3ddee0ba3491e4c85450a2",
    "buildbook/ports.py": "949354c269f8750488f1662ab6c82dd1b28ee321599563f9a967fa3ec3c3bdbf",
    "buildbook/seal_notices.py": "0d9c979d104a180fc9e5a9f838fc00d51ac86e5154dc160d70d378a73b5d3b49",
    "buildbook/seal_words.py": "a7fc7c409ab81af066a905ddf55a2e7fb0fe55a032fe56da3125958a28bd1f27",
    "buildbook/privacy.py": "ddd4fad71ea41c7a7885193fb0722d6180ac85cc0f3a32de92cee7f99a324f73",
    "api/book.py": "856e2f5276d6cb59f98aa947146a932ed888277acff8682294c0848be809e1fe",
}


def test_r6s_sealing_files_privacy_rows_routes_and_console_html_are_untouched() -> None:
    for rel, sha in UNTOUCHED.items():
        assert hashlib.sha256((SRC / rel).read_bytes()).hexdigest() == sha, rel


def test_the_keyring_keeps_its_26_purposes() -> None:
    assert len(PURPOSES) == 26  # the pages index is sealed under `book_index` (fact 16)


# ---- the size guards -----------------------------------------------------------------------------
def test_the_size_guards_hold() -> None:
    assert _lines(SRC / "api" / "app.py") == 732  # not edited
    assert _lines(SRC / "tools" / "gateway.py") == 760  # not edited
    assert _lines(SRC / "core" / "brain.py") == 713  # not edited
    assert _lines(SRC / "config.py") == 789  # not edited (790 is its guard)
    assert _lines(STATIC / "console.html") == 782
    assert _lines(SRC / "api" / "r6_wiring.py") <= 300
    assert _lines(SRC / "api" / "console.py") <= 473
    assert _lines(SRC / "buildbook" / "model.py") <= 420
    assert _lines(SRC / "buildbook" / "service.py") <= 400
    assert _lines(SRC / "buildbook" / "tour_model.py") <= 200
    for path in [
        *(SRC / "buildbook" / "writer").glob("*.py"),
        SRC / "buildbook" / "facts_model.py",
    ]:
        assert _lines(path) <= 400, path.name
    for name in ("console-book.js",):
        assert _lines(STATIC / name) <= 390


def test_the_old_writers_collections_are_flat_and_the_books_own() -> None:
    assert all(c.startswith("book_") for c in COLLECTIONS) and len(set(COLLECTIONS)) == 6
    assert "book" not in COLLECTIONS  # R6's own index is never the writer's


# ---- 14, 15 · the guide -------------------------------------------------------------------------
def test_the_guide_names_the_full_book_the_old_writers_data_and_the_roadmap() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    # the guide moves forward with each release (v6.3.x / R6.3 at R6.3, v6.4.x / R6.4 at R6.4)
    now = ".".join(jarvis.__version__.split(".")[:2])
    assert guide.splitlines()[0].startswith(f"Version v{now}.") and f"Release R{now}" in guide[:200]
    c57 = guide[guide.index("#### C57 · Build book") : guide.index("#### C58")]
    for name in COLLECTIONS:
        assert f"`{name}/" in c57, name  # each with its document id, as the card names R6's
    assert "Book writer (old trial)" in c57 and "`pages.json.gz`" in c57  # R6.3.1 D4, D9
    assert "Gemini (free)" not in c57 and "`src/jarvis/llm/write.py`" not in c57  # D8
    roadmap = guide[guide.index("## 11. Roadmap") : guide.index("## 12. Glossary")]
    assert "R6.3.1" in roadmap and "R6.4" in roadmap  # both named as built in its opening
    rows = [ln for ln in roadmap.splitlines() if ln.startswith("| ")]
    # R6.4 review: a built release is no PLANNED row (the tour's "next" reads the first two)
    assert not any(ln.startswith(("| R6.3.1 ", "| R6.4 ")) for ln in rows), rows
