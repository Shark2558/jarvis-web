# tests/test_llm_sdk_boundary.py -- CLAUDE.md "Nothing outside `jarvis.llm` imports a vendor SDK"
# (principle P7, ADR-02 and follow-up F1 of the Architecture Design Document, kept privately on
# the owner's Drive).
# A syntax-tree scan of every module under src/jarvis/: an AI vendor's SDK may be imported only
# inside src/jarvis/llm/. Plain `import x`, `from x import y`, a function-local import, an import
# under `if TYPE_CHECKING:` and `importlib.import_module("x")` / `__import__("x")` with a literal
# name all count. Google's platform clients (Firestore, google-auth) are not AI SDKs and stay
# allowed where the ADD says they are (chapter 01, P7).
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "jarvis"
ALLOWED = PACKAGE / "llm"
# Top-level names of AI vendors' SDKs and of the frameworks that wrap them. A dotted entry bans
# that module and everything below it, not its parent (`google.genai`, never all of `google`).
VENDOR_SDKS = (
    "anthropic",
    "openai",
    "google.genai",
    "google.generativeai",
    "google.ai.generativelanguage",
    "google.cloud.aiplatform",
    "vertexai",
    "cohere",
    "mistralai",
    "groq",
    "ollama",
    "litellm",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langgraph",
    "llama_index",
    "together",
    "replicate",
    "huggingface_hub",
    "elevenlabs",
    "deepgram",
)
DYNAMIC = frozenset({"import_module", "__import__"})


def is_vendor(module: str) -> bool:
    return any(module == sdk or module.startswith(sdk + ".") for sdk in VENDOR_SDKS)


def imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, module) for every import in the tree, dynamic imports with a literal name included."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
            found.extend((node.lineno, f"{node.module}.{a.name}") for a in node.names)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            first = node.args[0]
            if name in DYNAMIC and isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((node.lineno, first.value))
    return found


def offenders(package: Path, allowed: Path) -> list[str]:
    """`path:line module` for each vendor-SDK import outside `allowed`."""
    out: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if path.is_relative_to(allowed) or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(package.parents[1]).as_posix()
        out.extend(f"{rel}:{line} {mod}" for line, mod in imported_modules(tree) if is_vendor(mod))
    return sorted(set(out))


# ---- the scanner itself -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "source",
    [
        "import anthropic\n",
        "import openai.types as t\n",
        "from google import genai\n",
        "from google.genai import types\n",
        "import vertexai\n",
        "def f():\n    import cohere\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from anthropic import Client\n",
        "import importlib\nm = importlib.import_module('openai')\n",
        "m = __import__('langchain_core.messages')\n",
    ],
)
def test_every_import_form_of_a_vendor_sdk_is_caught(source: str) -> None:
    mods = [m for _, m in imported_modules(ast.parse(source))]
    assert any(is_vendor(m) for m in mods), mods


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\n",
        "from google.cloud import firestore\n",  # a platform client, not an AI SDK
        "import google.auth\n",
        "from jarvis.llm.base import LLMProvider\n",
        "from . import anthropic_names\n",  # a relative import of JARVIS's own module
        "import openai_compat_helpers\n",  # a name that merely starts like one
        "import importlib\nm = importlib.import_module(name)\n",  # not a literal: out of reach
    ],
)
def test_other_imports_are_not_vendor_sdks(source: str) -> None:
    mods = [m for _, m in imported_modules(ast.parse(source))]
    assert not any(is_vendor(m) for m in mods), mods


def test_the_scan_reports_an_offender_outside_llm_and_ignores_llm_itself(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "jarvis"
    (pkg / "llm").mkdir(parents=True)
    (pkg / "tools").mkdir()
    (pkg / "llm" / "anthropic_provider.py").write_text("import anthropic\n", encoding="utf-8")
    (pkg / "tools" / "sneaky.py").write_text("x = 1\nimport openai\n", encoding="utf-8")
    assert offenders(pkg, pkg / "llm") == ["src/jarvis/tools/sneaky.py:2 openai"]


# ---- this repository ----------------------------------------------------------------------------
def test_the_llm_package_is_where_the_one_sdk_lives() -> None:
    """The scan is not vacuous: the Anthropic provider inside jarvis.llm imports its SDK."""
    tree = ast.parse((ALLOWED / "anthropic_provider.py").read_text(encoding="utf-8"))
    assert any(is_vendor(m) for _, m in imported_modules(tree))


def test_no_module_outside_jarvis_llm_imports_an_ai_vendor_sdk() -> None:
    assert offenders(PACKAGE, ALLOWED) == []
