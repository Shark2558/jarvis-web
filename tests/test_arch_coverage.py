# tests/test_arch_coverage.py
"""R6.1 D6: scripts/arch_coverage.py — the guide's component catalogue covers every package,
console module, Scheduler job, outside service and Firestore collection INSIDE its cards' fields;
every path a card cites and every diagram file the guide links exists; every card has its 11
fields and every technology row its 8 cells; the version line, change log, diagram captions and
the R6 secret scan pass. Small fixture repos and guides; one test runs the real guide."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "arch_coverage.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("arch_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["arch_coverage"] = mod
    spec.loader.exec_module(mod)
    return mod


ac = _load()

CONFIG = """
from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    api_token: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"
"""
ALPHA = '''
"""Alpha. Layout: {prefix}alpha_items/{uid}."""
URL = "https://api.tavily.com/search"


def path(prefix: str, uid: str) -> str:
    return f"{prefix}alpha_items/{uid}"
'''
DEPLOY = """#!/usr/bin/env bash
BRIEF_JOB="jarvis-morning-brief"
gcloud scheduler jobs create http "$BRIEF_JOB" --schedule "0 4 * * *"
gcloud scheduler jobs create http "${HOME_JOB:-jarvis-home-watchdog}" --schedule "*/5 * * * *"
"""


def _repo(tmp: Path) -> Path:
    files = {
        "src/jarvis/__init__.py": "",
        "src/jarvis/config.py": CONFIG,
        "src/jarvis/ticks.py": '"""Ticks."""\n',
        "src/jarvis/alpha/__init__.py": ALPHA,
        "src/jarvis/beta/__init__.py": '"""Beta."""\n',
        "src/jarvis/api/__init__.py": "",
        "src/jarvis/api/static/console.js": "",
        "src/jarvis/api/static/console-foo.js": "",
        "src/jarvis/api/static/book.html": "",
        "deploy/cloudrun.sh": DEPLOY,
    }
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    drawn = tmp / "docs/architecture/diagrams"
    drawn.mkdir(parents=True)
    for name in ac.DIAGRAMS:  # what Part C exports beside each .markdy
        (drawn / f"{name}.svg").write_text("<svg><text>A picture</text></svg>\n", encoding="utf-8")
        (drawn / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp


FIELDS = (
    ("Name", "{name}"),
    ("What it does", "Does one thing."),
    ("Layer", "L5 Skills"),
    ("Skill", "Research & Intel"),
    ("Where in the code", "{code}"),
    ("Depends on", "nothing"),
    ("Data it keeps", "{data}"),
    ("Outside services", "{services}"),
    ("Cost (₹ a month)", "₹0"),
    ("When it fails", "Says so."),
    ("Since", "R1"),
)
TECH_HEAD = (
    "| Area | Technology | What it does (plain words) | Why we chose it | "
    "Alternatives we could use | Why not those (today) | Cost per month (₹) | Since |"
)


def card(name: str, code: str, data: str = "none", services: str = "none") -> str:
    rows = "\n".join(
        f"| {k} | {v.format(name=name, code=code, data=data, services=services)} |"
        for k, v in FIELDS
    )
    return f"#### {name}\n\n| Field | Value |\n|---|---|\n{rows}\n"


def guide(cards: str | None = None, tech_row: str | None = None, version: str | None = None) -> str:
    default_cards = "\n".join(
        (
            card("Alpha", "`src/jarvis/alpha/`", data="`alpha_items/{uid}`", services="Tavily"),
            card("Beta", "`src/jarvis/beta/`, `src/jarvis/ticks.py`"),
            card("Config", "`src/jarvis/config.py`", services="Redis"),
            card("Web", "`src/jarvis/api/`, `console.js`, `console-foo.js`"),
            card("Clock", "jobs `jarvis-morning-brief` and `jarvis-home-watchdog`"),
        )
    )
    row = tech_row or "| Data | Redis | Keeps chats | Fast | Memcached | Less able | ₹0 | R0 |"
    figures = "\n\n".join(
        f"![Figure {int(n[:2])}](diagrams/{n}.svg)\n\n*Figure {int(n[:2])}. A picture.*"
        for n in ac.DIAGRAMS
    )
    return (
        (
            version
            or "Version v6.1.1 · 11 Nov 2026, 12:00 IST · Release R6.1 · Status: Current"
            " · Owner: 🛠 Mark XIII"
        )
        + "\n\n# Guide\n\n## 3. Component catalogue\n\n"
        + (default_cards if cards is None else cards)
        + "\n## 4. Diagrams\n\n"
        + figures
        + "\n\n## 5. Technology\n\n### 5.1 Technology table\n\n"
        + TECH_HEAD
        + "\n|---|---|---|---|---|---|---|---|\n"
        + row
        + "\n\n## Change log\n\n| Version | Date | Release | What changed | By |\n"
        + "|---|---|---|---|---|\n| v6.1.1 | 11 Nov 2026 | R6.1 | First | 🛠 Mark XIII |\n"
    )


def run(repo: Path, text: str) -> tuple[int, list[str]]:
    path = repo / "docs/architecture/JARVIS-Architecture.md"
    path.write_text(text, encoding="utf-8")
    problems = ac.check_all(repo, path, repo / "docs/architecture")
    return (1 if problems else 0), problems


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repo(tmp_path)


def test_inventory_finds_every_kind(repo: Path) -> None:
    inv = ac.inventory(repo)
    assert set(inv.code) == {
        "src/jarvis/alpha",
        "src/jarvis/beta",
        "src/jarvis/api",
        "src/jarvis/config.py",
        "src/jarvis/ticks.py",
    }
    assert set(inv.console) == {"console.js", "console-foo.js"}
    assert set(inv.jobs) == {"jarvis-morning-brief", "jarvis-home-watchdog"}
    assert set(inv.services) == {"Tavily", "Redis"}
    assert set(inv.collections) == {"alpha_items"}


def test_a_complete_guide_passes(repo: Path) -> None:
    assert run(repo, guide()) == (0, [])


def test_a_missing_package_fails_and_names_it(repo: Path) -> None:
    cards = "\n".join(
        (
            card("Alpha", "`src/jarvis/alpha/`", data="`alpha_items`", services="Tavily"),
            card("Beta", "`src/jarvis/ticks.py`"),  # src/jarvis/beta left out
            card("Config", "`src/jarvis/config.py`", services="Redis"),
            card("Web", "`src/jarvis/api/`, `console.js`, `console-foo.js`"),
            card("Clock", "`jarvis-morning-brief`, `jarvis-home-watchdog`"),
        )
    )
    code, problems = run(repo, guide(cards))
    assert code == 1
    assert any("src/jarvis/beta" in p for p in problems)


def test_a_package_named_only_outside_the_code_field_does_not_count(repo: Path) -> None:
    text = (
        guide()
        .replace("`src/jarvis/beta/`, ", "")
        .replace("| What it does | Does one thing. |", "| What it does | See src/jarvis/beta. |", 1)
    )
    code, problems = run(repo, text)
    assert code == 1 and any("src/jarvis/beta" in p for p in problems)


def test_a_package_prefix_never_covers_a_longer_name(repo: Path) -> None:
    (repo / "src/jarvis/alpha_two").mkdir()
    (repo / "src/jarvis/alpha_two/__init__.py").write_text("", encoding="utf-8")
    code, problems = run(repo, guide())
    assert code == 1 and any("src/jarvis/alpha_two" in p for p in problems)


def test_a_missing_console_module_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace(", `console-foo.js`", ""))
    assert code == 1 and any("console-foo.js" in p for p in problems)


def test_a_missing_scheduler_job_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace(" and `jarvis-home-watchdog`", ""))
    assert code == 1 and any("jarvis-home-watchdog" in p for p in problems)


def test_a_missing_outside_service_fails(repo: Path) -> None:
    code, problems = run(
        repo, guide().replace("| Outside services | Tavily |", "| Outside services | none |")
    )
    assert code == 1 and any("Tavily" in p for p in problems)


def test_a_secret_setting_with_no_known_service_fails(repo: Path) -> None:
    cfg = repo / "src/jarvis/config.py"
    cfg.write_text(CONFIG + "    acme_api_key: SecretStr | None = None\n", encoding="utf-8")
    code, problems = run(repo, guide())
    assert code == 1 and any("acme_api_key" in p for p in problems)


def test_an_unknown_api_host_in_code_fails(repo: Path) -> None:
    beta = repo / "src/jarvis/beta/__init__.py"
    beta.write_text('"""Beta."""\nURL = "https://api.acme.example/v1"\n', encoding="utf-8")
    code, problems = run(repo, guide())
    assert code == 1 and any("api.acme.example" in p for p in problems)


def test_a_missing_collection_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace("`alpha_items/{uid}`", "none"))
    assert code == 1 and any("alpha_items" in p for p in problems)


def test_collections_found_through_every_idiom(repo: Path) -> None:
    (repo / "src/jarvis/beta/store.py").write_text(
        'LEASE_COLLECTION = "beta_lease"\n'
        "class S:\n"
        "    def a(self, uid):\n"
        '        return self._path("beta_rate", uid), f"{self._p}beta_held/{uid}"\n',
        encoding="utf-8",
    )
    assert {"beta_lease", "beta_rate", "beta_held"} <= set(ac.inventory(repo).collections)


def test_a_card_with_an_empty_field_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace("| Since | R1 |", "| Since | — |", 1))
    assert code == 1 and any("Alpha" in p and "Since" in p for p in problems)


def test_a_card_missing_a_field_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace("| Skill | Research & Intel |\n", "", 1))
    assert code == 1 and any("Alpha" in p and "Skill" in p for p in problems)


def test_a_short_technology_row_fails(repo: Path) -> None:
    code, problems = run(
        repo, guide(tech_row="| Data | Redis | Keeps chats | Fast | Memcached | ₹0 | R0 |")
    )
    assert code == 1 and any("Redis" in p and "8" in p for p in problems)


def test_an_empty_technology_cell_fails(repo: Path) -> None:
    code, problems = run(
        repo, guide(tech_row="| Data | Redis | Keeps chats |  | Memcached | Less | ₹0 | R0 |")
    )
    assert code == 1 and any("Redis" in p for p in problems)


def test_wrong_technology_columns_fail(repo: Path) -> None:
    code, problems = run(repo, guide().replace("Cost per month (₹)", "Cost"))
    assert code == 1 and any("columns" in p for p in problems)


def test_a_bad_version_line_fails(repo: Path) -> None:
    code, problems = run(repo, guide(version="Version 6.1 · today"))
    assert code == 1 and any("version line" in p for p in problems)


def test_a_missing_change_log_fails(repo: Path) -> None:
    code, problems = run(repo, guide().split("## Change log")[0])
    assert code == 1 and any("change log" in p for p in problems)


def test_a_diagram_without_its_caption_fails(repo: Path) -> None:
    code, problems = run(repo, guide().replace("*Figure 7. A picture.*", ""))
    assert code == 1 and any("07-memory" in p for p in problems)


def test_the_secret_scan_catches_an_email_and_a_key(repo: Path) -> None:
    leak = repo / "docs/architecture/notes.md"
    leak.write_text("mail someone@example.com\nkey AIza" + "A" * 35 + "\n", encoding="utf-8")
    code, problems = run(repo, guide())
    assert code == 1
    assert any("notes.md:1" in p and "email" in p for p in problems)
    assert any("notes.md:2" in p and "secret" in p for p in problems)
    assert not any("someone@example.com" in p for p in problems)  # kinds only, never the text


def test_the_secret_scan_reads_only_the_words_of_an_svg(repo: Path) -> None:
    svg = repo / "docs/architecture/diagrams/01-context.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        '<path d="M 1120 550 L 1138 550 Q 1152 550 1152 564 L 1152 654"/>\n'
        '<text x="48" y="44">The console</text>\n'
        "</svg>\n",
        encoding="utf-8",
    )
    (repo / "docs/architecture/diagrams/exports.json").write_text(
        '{"svg": "' + "1234567890" * 6 + 'abcd"}\n', encoding="utf-8"
    )
    assert run(repo, guide()) == (0, [])  # geometry and SHA-256 hashes are not personal
    svg.write_text(
        '<svg>\n<text x="1"\n y="2">mail someone@example.com</text>\n'
        '<path d="AIza' + "B" * 35 + '"/>\n</svg>\n',
        encoding="utf-8",
    )
    code, problems = run(repo, guide())
    assert code == 1
    assert any("01-context.svg:3" in p and "email" in p for p in problems)
    assert any("01-context.svg:4" in p and "secret" in p for p in problems)


def test_main_exits_non_zero_with_a_list(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "docs/architecture/JARVIS-Architecture.md").write_text(
        guide().replace(", `console-foo.js`", ""), encoding="utf-8"
    )
    assert ac.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "console-foo.js" in out and "FAILED" in out


def test_main_exits_two_without_a_guide(repo: Path) -> None:
    assert ac.main(["--repo", str(repo)]) == 2


CLOCK_CODE = "| Where in the code | jobs `jarvis-morning-brief` and `jarvis-home-watchdog` |"


def test_a_scheduler_job_outside_a_cards_code_field_does_not_count(repo: Path) -> None:
    text = (
        guide()
        .replace(CLOCK_CODE, "| Where in the code | `src/jarvis/ticks.py` |")
        .replace(
            "| What it does | Does one thing. |",
            "| What it does | Runs `jarvis-morning-brief` and `jarvis-home-watchdog`. |",
        )
        .replace(
            "## 4. Diagrams", "### The jobs `jarvis-morning-brief`, `jarvis-home-watchdog`\n\n## 4."
        )
    )
    code, problems = run(repo, text)
    jobs = [p for p in problems if "Scheduler job" in p]
    assert code == 1 and len(jobs) == 2, problems


def test_a_file_inside_a_package_does_not_cover_the_package(repo: Path) -> None:
    (repo / "src/jarvis/beta/store.py").write_text("", encoding="utf-8")
    code, problems = run(
        repo, guide().replace("`src/jarvis/beta/`, ", "`src/jarvis/beta/store.py`, ")
    )
    assert code == 1 and any("package/module" in p and "`src/jarvis/beta`" in p for p in problems)


@pytest.mark.parametrize("field", ["Redisplay", "Cloud (Redis later)", "none; see the Redis notes"])
def test_an_outside_service_counts_only_as_an_item_of_the_field(repo: Path, field: str) -> None:
    code, problems = run(
        repo, guide().replace("| Outside services | Redis |", f"| Outside services | {field} |")
    )
    assert code == 1 and any("outside service" in p and "`Redis`" in p for p in problems)


def test_service_names_split_a_field_into_its_items() -> None:
    names = ac.service_names(
        "Tavily; Anthropic (one call, at most), Google Maps Platform (Places API (New), Routes "
        "API), Google Calendar and Google Tasks (to restore), and each probed service"
    )
    assert {
        "tavily",
        "anthropic",
        "google maps platform",
        "google calendar",
        "google tasks",
    } <= names
    assert not {"places api", "routes api", "redis"} & names


def test_a_cited_path_that_does_not_exist_fails(repo: Path) -> None:
    text = guide().replace(
        "`src/jarvis/ticks.py`", "`src/jarvis/ticks.py`, `src/jarvis/beta/gone.py`, `deploy/no.sh`"
    )
    code, problems = run(repo, text)
    assert code == 1
    assert any("`Beta`" in p and "`src/jarvis/beta/gone.py`" in p for p in problems)
    assert any("`deploy/no.sh`" in p for p in problems)


def test_a_bare_file_name_is_found_next_to_the_path_before_it(repo: Path) -> None:
    (repo / "src/jarvis/beta/store.py").write_text("", encoding="utf-8")
    good = guide().replace("`src/jarvis/beta/`, ", "`src/jarvis/beta/` (`store.py`), ")
    assert run(repo, good) == (0, [])
    bad = guide().replace("`src/jarvis/beta/`, ", "`src/jarvis/beta/` (`stores.py`), ")
    code, problems = run(repo, bad)
    assert code == 1 and any("`stores.py`" in p for p in problems)


def test_a_cited_console_module_that_does_not_exist_fails(repo: Path) -> None:
    code, problems = run(
        repo, guide().replace("`console-foo.js`", "`console-foo.js`, `console-x.js`")
    )
    assert code == 1 and any("`console-x.js`" in p for p in problems)


def test_a_linked_diagram_file_that_does_not_exist_fails(repo: Path) -> None:
    (repo / "docs/architecture/diagrams/07-memory.png").unlink()
    code, problems = run(repo, guide() + "\n![More](diagrams/99-extra.svg)\n")
    assert code == 1
    assert any("07-memory.png" in p for p in problems)
    assert any("99-extra.svg" in p for p in problems)


def test_the_diagrams_folder_must_exist(repo: Path) -> None:
    shutil.rmtree(repo / "docs/architecture/diagrams")
    assert run(repo, guide()) == (1, [ac.NO_DIAGRAMS])


@pytest.mark.parametrize("value", ["TBC", "todo", "...", "…", "None"])
def test_a_placeholder_counts_as_empty(repo: Path, value: str) -> None:
    code, problems = run(repo, guide().replace("| Since | R1 |", f"| Since | {value} |", 1))
    assert code == 1 and any("Alpha" in p and "Since" in p for p in problems)


def test_none_is_a_real_answer_where_nothing_is_kept_or_needed(repo: Path) -> None:
    assert run(repo, guide().replace("| Depends on | nothing |", "| Depends on | None |")) == (
        0,
        [],
    )


@pytest.mark.parametrize("line", ["acme_key: str = ''", "acme_token: str | None = None"])
def test_a_plain_key_or_token_setting_with_no_known_service_fails(repo: Path, line: str) -> None:
    (repo / "src/jarvis/config.py").write_text(CONFIG + f"    {line}\n", encoding="utf-8")
    code, problems = run(repo, guide())
    assert code == 1 and any("acme_" in p for p in problems)


def test_a_package_without_an_init_file_is_still_a_package(repo: Path) -> None:
    (repo / "src/jarvis/gamma").mkdir()
    (repo / "src/jarvis/gamma/x.py").write_text("", encoding="utf-8")
    (repo / "src/jarvis/__pycache__").mkdir()
    code = ac.inventory(repo).code
    assert "src/jarvis/gamma" in code and "src/jarvis/__pycache__" not in code


def test_collections_named_in_a_collection_call_are_found(repo: Path) -> None:
    (repo / "src/jarvis/beta/fs.py").write_text(
        "def a(c, prefix):\n"
        '    return c.collection(f"{prefix}beta_col"), c.collection("beta_plain")\n',
        encoding="utf-8",
    )
    assert {"beta_col", "beta_plain"} <= set(ac.inventory(repo).collections)


def test_main_exits_two_when_the_code_cannot_be_read(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "docs/architecture/JARVIS-Architecture.md").write_text(guide(), encoding="utf-8")
    (repo / "src/jarvis/config.py").write_text("class Settings(:\n", encoding="utf-8")
    assert ac.main(["--repo", str(repo)]) == 2
    assert "ERROR" in capsys.readouterr().out


def test_main_exits_two_on_a_file_that_is_not_utf8(repo: Path) -> None:
    (repo / "docs/architecture/JARVIS-Architecture.md").write_text(guide(), encoding="utf-8")
    (repo / "docs/architecture/notes.md").write_bytes(b"\xff\xfe not text")
    assert ac.main(["--repo", str(repo)]) == 2


def test_the_real_guide_passes() -> None:
    guide_path = ROOT / ac.GUIDE
    problems = ac.check_all(ROOT, guide_path, guide_path.parent)
    if not (guide_path.parent / "diagrams").is_dir():
        # Part D's branch alone: Part C's exported diagrams join at integration
        # (docs/plans/r6-1-integration/INTEGRATION-D.md)
        assert problems == [ac.NO_DIAGRAMS], problems
    else:
        assert problems == [], problems


def test_ci_runs_it_once_in_the_docs_check_job_after_the_install_never_before_a_deploy() -> None:
    """R6.1 code review M1: a feature not yet in the guide never blocks a deploy or a hotfix. The
    check imports jarvis (the scrubber, the settings), so its job installs the package first."""
    import yaml

    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))["jobs"]
    runs = {n: [str(s.get("run", "")) for s in j.get("steps", [])] for n, j in jobs.items()}
    assert [n for n, r in runs.items() if "python scripts/arch_coverage.py" in r] == ["docs-check"]
    steps = runs["docs-check"]
    assert steps.index('pip install -e ".[dev]"') < steps.index("python scripts/arch_coverage.py")
    assert "docs-check" not in jobs["deploy"]["needs"] and "strategy" not in jobs["docs-check"]
    assert "docs-check" not in str([j.get("needs", []) for j in jobs.values()])  # nothing waits


def _c01_panels(guide: str) -> list[str]:
    """The panels card C01 lists, in its order ("the dock of panels (in its order: ...)")."""
    m = re.search(
        r"\| What it does \| The page you use JARVIS from[^|]*?the dock of panels \(([^)]*)\)",
        guide,
    )
    assert m, "C01 no longer lists the dock's panels"
    return [p.strip() for p in m.group(1).removeprefix("in its order:").split(",")]


def test_card_c01_lists_the_panels_in_the_dock_s_order() -> None:
    """R6.1 code review L3: C01 says the buttons keep their order, so its list follows the dock."""
    html = (ROOT / "src/jarvis/api/static/console.html").read_text(encoding="utf-8")
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    labels = re.findall(r'data-open="\w+"[^>]*>.*?<span(?: class="full")?>([^<]+)</span>', dock)
    assert len(labels) == len(re.findall(r'data-open="\w+"', dock)) == 20
    assert _c01_panels((ROOT / ac.GUIDE).read_text(encoding="utf-8")) == labels
