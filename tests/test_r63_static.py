# tests/test_r63_static.py -- R6.3 I0 seam 13 (docs/plans/r6-3-book-content.md D1, D4, L3): static
# guards over the writer's files, written at I0 so every module B adds is held to them.
#
# - D4: the writer imports nothing that reaches the owner's data or the brain's core (memory, vault,
#   mail, contacts, documents, tools, core, integrations, the app) and no vendor SDK; from
#   `jarvis.llm` only `write`, `brains`, `router` (its `ModelTier`) and `base` (its `ChatMessage`,
#   I1: INTEGRATION-B, instead of reaching it through `vars(write)`).
# - D1, L3: no model id, vendor name or price in a string literal of the writer's files (the brain
#   is asked by tier; who it is comes from the registry and `jarvis.llm.write.maker`).
# - No real clock in the writer or `llm/write.py` (every test takes a fixed clock).
from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
WRITER = sorted((SRC / "buildbook" / "writer").glob("*.py"))
# D1's list (L3: not all of buildbook/, whose hear.py, plain.py and gen/scrub.py name vendors)
WRITER_FILES = [
    *WRITER,
    SRC / "buildbook" / "tour_serve.py",
    SRC / "buildbook" / "gen" / "tour.py",
    SRC / "api" / "book_writer.py",
    SRC / "api" / "book_pages.py",
]
FORBIDDEN = (
    "jarvis.memory",
    "jarvis.vault",
    "jarvis.integrations",
    "jarvis.documents",
    "jarvis.tools",
    "jarvis.core",
    "jarvis.contacts",
    "jarvis.api",
    "jarvis.drive",
    "jarvis.photos",
    "jarvis.recall",
    "anthropic",
    "google",
    "openai",
    "httpx",
)
LLM_OK = {"jarvis.llm.write", "jarvis.llm.brains", "jarvis.llm.router", "jarvis.llm.base"}
MODEL_ID = re.compile(r"\b(?:claude-|gemini-\d|gpt-\d|o\d-|llama|mistral)", re.IGNORECASE)
VENDOR = re.compile(r"\b(?:Anthropic|Claude|Gemini|Google|OpenAI|Sonnet|Opus|Haiku|Groq|Ollama)\b")
PRICE = re.compile(r"(?:US)?\$\s?\d|\bper million\b|\bmtok\b|\busd\b", re.IGNORECASE)
CLOCK = re.compile(
    r"datetime\.now\(|date\.today\(|time\.time\(|time\.monotonic\(|utcnow|perf_counter\("
)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _literals(path: Path) -> Iterator[str]:
    """String constants that are not docstrings (what can reach the owner or a model)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            yield n.value


def test_the_writer_files_are_there() -> None:
    names = {p.name for p in WRITER}
    assert {"model.py", "http.py", "ports.py", "part.py", "job.py", "privacy.py"} <= names
    assert all(p.is_file() for p in WRITER_FILES)


@pytest.mark.parametrize("path", WRITER_FILES, ids=lambda p: p.name)
def test_the_writer_imports_nothing_that_reaches_the_owner(path: Path) -> None:
    mods = _imports(path)
    if path.parent.name == "api":  # a route file reads the app's auth and gate, nothing else of it
        mods = {m for m in mods if not m.startswith(("jarvis.api.auth", "jarvis.api.book_"))}
    bad = [m for m in mods if any(m == b or m.startswith(b + ".") for b in FORBIDDEN)]
    assert bad == [], (path.name, bad)
    llm = {m for m in mods if m.startswith("jarvis.llm")}
    assert llm <= LLM_OK, (path.name, llm)


def test_from_the_router_only_the_tier() -> None:
    for path in WRITER_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "jarvis.llm.router":
                assert [a.name for a in node.names] == ["ModelTier"], path.name


def test_from_the_base_only_the_message_type_and_no_module_reached_into() -> None:
    for path in WRITER_FILES:
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module == "jarvis.llm.base":
                assert [a.name for a in node.names] == ["ChatMessage"], path.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "vars", path.name  # a module's own imports, reached into


@pytest.mark.parametrize("path", WRITER_FILES, ids=lambda p: p.name)
def test_no_model_id_vendor_or_price_in_a_literal(path: Path) -> None:
    for lit in _literals(path):
        assert not MODEL_ID.search(lit), (path.name, lit[:60])
        assert not VENDOR.search(lit), (path.name, lit[:60])
        assert not PRICE.search(lit), (path.name, lit[:60])


@pytest.mark.parametrize("path", [*WRITER, SRC / "llm" / "write.py"], ids=lambda p: p.name)
def test_no_real_clock(path: Path) -> None:
    assert not CLOCK.search(path.read_text(encoding="utf-8")), path.name


def test_the_guards_catch_what_they_guard() -> None:
    """Each guard's own control: the patterns find what they are for."""
    assert MODEL_ID.search("claude-sonnet-5-5") and MODEL_ID.search("gemini-3.8-flash")
    assert VENDOR.search("Your Anthropic bill") and not VENDOR.search("Your {maker} bill")
    assert PRICE.search("US$2 per million") and PRICE.search("$0.10") and not PRICE.search("Rs 40")
    assert CLOCK.search("datetime.now(UTC)") and not CLOCK.search("ctx.clock()")
