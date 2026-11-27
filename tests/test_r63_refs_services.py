# tests/test_r63_refs_services.py -- R6.3 I0 seam 17 (docs/plans/r6-3-book-content.md D2, D3, D10
# G3, plan review H5, M7): ONE rule for the guide's references and ONE list of outside services.
# `buildbook/gen/refs.py` is `scripts/arch_files.py`'s resolver, moved unchanged (the guide's check
# calls it); `buildbook/gen/services.py` is `scripts/arch_inventory.py`'s services half, moved
# unchanged (the coverage checker calls it). The real guide: every reference resolves, 35 services
# (R18: the inventory reads `Settings`' jarvis base class too, as `gen/code.py` does).
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from jarvis.buildbook.gen import refs, services

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GEN = ROOT / "src" / "jarvis" / "buildbook" / "gen"


def _script(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp: Path) -> Path:
    for rel in (
        "src/jarvis/voice/service.py",
        "src/jarvis/voice/words.py",
        "src/jarvis/api/static/console.js",
        "src/jarvis/api/routes.py",
        "src/jarvis/config.py",
        "src/jarvis/llm/a.py",
        "src/jarvis/llm/b.py",
        "deploy/cloudrun.sh",
        "Dockerfile",
    ):
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text("x = 1\n", encoding="utf-8")
    return tmp


def test_a_bare_name_resolves_next_to_the_path_before_it_then_static_api_jarvis_root(
    tmp_path: Path,
) -> None:
    repo = _tree(tmp_path)
    where = (
        "`src/jarvis/voice/` (`service.py`, `words.py`); `console.js`; `routes.py`; "
        "`config.py`; `llm/*.py`; `Dockerfile`; `deploy/cloudrun.sh`; `ghost.py`; `plain words`"
    )
    assert refs.resolve(repo, where) == [
        ("src/jarvis/voice/", "src/jarvis/voice/"),
        ("service.py", "src/jarvis/voice/service.py"),
        ("words.py", "src/jarvis/voice/words.py"),
        ("console.js", "src/jarvis/api/static/console.js"),
        ("routes.py", "src/jarvis/api/routes.py"),
        ("config.py", "src/jarvis/config.py"),
        ("llm/*.py", "src/jarvis/llm/*.py"),
        ("Dockerfile", "Dockerfile"),
        ("deploy/cloudrun.sh", "deploy/cloudrun.sh"),
        ("ghost.py", None),
    ]


def test_the_guide_check_uses_the_moved_resolver(tmp_path: Path) -> None:
    files = _script("arch_files")
    assert files.resolve is refs.resolve
    repo = _tree(tmp_path)
    assert files.cited(repo, "C05", "`src/jarvis/voice/` (`service.py`)") == []
    assert files.cited(repo, "C05", "`src/jarvis/voice/` (`gone.py`)") == [
        "card `C05`: cited path `gone.py` does not exist"
    ]
    source = (SCRIPTS / "arch_files.py").read_text(encoding="utf-8")
    assert "def _candidates" not in source and "_ROOTS" not in source  # one copy of the rule


def test_every_reference_of_the_real_guide_resolves() -> None:
    cov = _script("arch_coverage")
    text = (ROOT / cov.GUIDE).read_text(encoding="utf-8")
    cards = cov.cards(cov._section(text, "Component catalogue"))
    assert len(cards) == 83  # R18: C74-C78; R5.2: C79-C83
    found = [
        (c.name, s, p) for c in cards for s, p in refs.resolve(ROOT, c.fields["Where in the code"])
    ]
    assert len(found) > 600 and [f for f in found if f[2] is None] == []


def test_the_real_repository_has_the_coverage_checkers_35_services() -> None:
    got = services.inventory(ROOT)
    assert len(got.names) == 35 and got.problems == ()
    assert {"Anthropic", "Gemini", "Telegram", "Firestore"} <= set(got.names)
    # R18: Azure, Sarvam and Bhashini by their `config_calls.py` settings, Hugging Face by its host
    assert {"Microsoft Azure Speech", "Sarvam", "Bhashini", "Hugging Face"} <= set(got.names)
    assert list(got.names) == sorted(set(got.names))
    inv = _script("arch_inventory").inventory(ROOT)
    assert inv.services == got.names and inv.problems == got.problems


def test_an_unknown_secret_setting_or_api_host_is_a_problem(tmp_path: Path) -> None:
    cfg = tmp_path / "src/jarvis/config.py"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "class Settings:\n    tavily_api_key: SecretStr | None = None\n    weird_token: str = ''\n",
        encoding="utf-8",
    )
    (tmp_path / "src/jarvis/x.py").write_text(
        'A = "https://api.tavily.com/v1"\nB = "https://api.unknown.example/v1"\n', encoding="utf-8"
    )
    table = {"service_fields": [["tavily_", ["Tavily"]]], "api_hosts": {"api.tavily.com": "Tavily"}}
    got = services.inventory(tmp_path, table)
    assert got.names == ("Tavily",)
    assert [p.split(" ")[0:2] for p in got.problems] == [
        ["setting", "`weird_token`"],
        ["API", "host"],
    ]
    with pytest.raises(ValueError, match="arch_coverage.json"):
        services.inventory(tmp_path)  # no table in this repository


def test_a_settings_base_class_from_a_jarvis_module_is_read_too(tmp_path: Path) -> None:
    # R18: `class Settings(CallsConfig, BaseSettings)`, its calls keys in `config_calls.py`. The
    # inventory reads them as `gen/code.py`'s `settings_nodes` does, so a secret there is seen.
    src = tmp_path / "src/jarvis"
    src.mkdir(parents=True)
    (src / "config.py").write_text(
        "from jarvis.config_calls import CallsConfig\n"
        "from pydantic_settings import BaseSettings\n\n"
        "class Settings(CallsConfig, BaseSettings):\n    tavily_api_key: SecretStr | None = None\n",
        encoding="utf-8",
    )
    (src / "config_calls.py").write_text(
        "class CallsConfig(BaseModel):\n    sarvam_api_key: SecretStr | None = None\n"
        "    azure_speech_key: SecretStr | None = None\n    calls_enabled: bool = True\n",
        encoding="utf-8",
    )
    table = {"service_fields": [["tavily_", ["Tavily"]], ["sarvam_", ["Sarvam"]]]}
    assert [n for n, _ in services.settings_fields(tmp_path)] == [
        "sarvam_api_key", "azure_speech_key", "calls_enabled", "tavily_api_key",
    ]  # fmt: skip
    got = services.inventory(tmp_path, table)
    assert got.names == ("Sarvam", "Tavily")
    assert [p.split(" ")[0:2] for p in got.problems] == [["setting", "`azure_speech_key`"]]


@pytest.mark.parametrize("name", ["refs.py", "services.py", "modules.py"])
def test_the_moved_modules_are_standard_library_only(name: str) -> None:
    tree = ast.parse((GEN / name).read_text(encoding="utf-8"))
    mods = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    mods |= {
        n.module.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0
    }
    assert mods - {"__future__", "jarvis"} <= set(sys.stdlib_module_names), mods
    jarvis = {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("jarvis")
    }
    assert jarvis <= {"jarvis.buildbook.gen.repo"}, jarvis
