# tests/test_r63_seams.py -- R6.3 I0 (docs/plans/r6-3-book-content.md "The I0 seam list" 1-17,
# "Size guards"): the pins of what I0 built and of what R6.3 must leave alone. Each seam's own
# behaviour is tested in its file (test_r63_write, _types, _modules, _gen_joins, _wiring, _serve,
# _console_seams, _scrub_kinds, _static, _fakes, _fake_server, _refs_services, _redact); here: the
# version, the staged eval runner, the files no part edits, the sizes, the keyring and the guide.
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
    assert jarvis.__version__ == "6.3.0"  # R6.3 I0 (13.1.0 at R13.1); the persona is unchanged
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R6.3"
    assert plans.plan_paths(repo)[0] == "docs/plans/r6-3-book-content.md"


# ---- 12 · the staged eval runner ----------------------------------------------------------------
def test_the_eval_runner_is_staged_until_i1_and_gated() -> None:
    runner = _load(ROOT / "evals" / "r6_3" / "run.py", "r6_3_run_pin")
    assert runner.STUBS_PASS is True  # I1 flips it to False (and this pin with it)
    assert runner.PARTS == ("facts", "writer", "console", "tour", "needles", "e2e", "contract")
    contract = _load(ROOT / "evals" / "r6_3" / "contract.py", "r6_3_contract_pin")
    assert contract.BUILT is True  # I0's own part, with its own control (L12)
    gate = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    assert (
        '("r6_3 (gated)", [sys.executable, str(HERE / "r6_3" / "run.py"), "--mock"], True)' in gate
    )


# ---- 3, D0, M4 · what R6.3 never edits ----------------------------------------------------------
UNTOUCHED = {  # 47ee8fc's SHA-256, under src/jarvis/
    "api/static/console.html": "9f4c0c68f45e46fe150e65e182f4d2ba1132eb556b3ddee0ba3491e4c85450a2",
    "buildbook/seal_index.py": "7ebe40dc6928429baaf8ea617e2e13aeb7690f874ed8ed50739a8fe15a86deb4",
    "buildbook/seal.py": "e87770535b78bd3e6e3845ddac4267232d055ba541841980d9300169efe2ac85",
    "buildbook/ports.py": "949354c269f8750488f1662ab6c82dd1b28ee321599563f9a967fa3ec3c3bdbf",
    "buildbook/sealer.py": "d4345c7c8431fd826ec3e15619a2b1f818fce0bd01e9ce0b533aac67e00a54ff",
    "buildbook/seal_notices.py": "0d9c979d104a180fc9e5a9f838fc00d51ac86e5154dc160d70d378a73b5d3b49",
    "buildbook/seal_words.py": "a7fc7c409ab81af066a905ddf55a2e7fb0fe55a032fe56da3125958a28bd1f27",
    "buildbook/privacy.py": "ddd4fad71ea41c7a7885193fb0722d6180ac85cc0f3a32de92cee7f99a324f73",
    "api/book.py": "856e2f5276d6cb59f98aa947146a932ed888277acff8682294c0848be809e1fe",
}


def test_r6s_sealing_files_privacy_rows_routes_and_console_html_are_untouched() -> None:
    for rel, sha in UNTOUCHED.items():
        assert hashlib.sha256((SRC / rel).read_bytes()).hexdigest() == sha, rel
    evals = _load(ROOT / "evals" / "r6_3" / "contract.py", "r6_3_contract_pin2")
    assert evals.UNTOUCHED == {f"src/jarvis/{k}": v for k, v in UNTOUCHED.items()}  # one list


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
    assert _lines(SRC / "llm" / "write.py") <= 160
    for path in [
        *(SRC / "buildbook" / "writer").glob("*.py"),
        SRC / "buildbook" / "facts_model.py",
    ]:
        assert _lines(path) <= 400, path.name
    for name in ("console-book.js",):
        assert _lines(STATIC / name) <= 390


def test_the_writers_collections_are_flat_and_the_books_own() -> None:
    assert all(c.startswith("book_") for c in COLLECTIONS) and len(set(COLLECTIONS)) == 6
    assert "book" not in COLLECTIONS  # R6's own index is never the writer's


# ---- 14, 15 · the guide -------------------------------------------------------------------------
def test_the_guide_names_the_writer_its_data_and_the_roadmap() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    assert guide.splitlines()[0].startswith("Version v6.3.") and "Release R6.3" in guide[:200]
    c57 = guide[guide.index("#### C57 · Build book") : guide.index("#### C58")]
    for name in COLLECTIONS:
        assert f"`{name}`" in c57, name
    assert "Gemini (free)" in c57 and "only after the owner's typed YES" in c57
    assert "Outside services | Anthropic (the talk-through only)" not in c57  # G2 closed
    roadmap = guide[guide.index("## 11. Roadmap") : guide.index("## 12. Glossary")]
    assert "R6.3.1" in roadmap and "R6.4" in roadmap
