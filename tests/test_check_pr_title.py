# tests/test_check_pr_title.py -- R6.1 D4: every pull request is titled
# "v6.1.0 · R6.1 Short name · Mark XIII" (scripts/check_pr_title.py), checked by CI's `pr-title`
# job on pull requests only, Dependabot's exempt, never something the deploy job waits for.
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pr_title.py"
BACKFILL = ROOT / "docs" / "github-backfill.tsv"
CI = ROOT / ".github" / "workflows" / "ci.yml"
TEMPLATE = ROOT / ".github" / "pull_request_template.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pr_title", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cpt = _load()


def _backfill_titles() -> list[str]:
    rows = [ln.split("\t") for ln in BACKFILL.read_text(encoding="utf-8").splitlines()]
    return [r[2] for r in rows if r and r[0] and not r[0].startswith("#")]


def test_the_pattern_is_the_rules_one() -> None:
    assert cpt.TITLE == r"^v\d+\.\d+\.\d+ · .+ · Mark [IVXLC]+(–[IVXLC]+)?$"


def test_every_back_filled_title_passes() -> None:
    titles = _backfill_titles()
    assert len(titles) == 21
    assert [t for t in titles if not cpt.check(t)] == []


@pytest.mark.parametrize(
    "good",
    [
        "v6.1.0 · R6.1 The Architecture Guide & versioning · Mark XIII",
        "v0.12.0 · Slice 12 Drive, Maps · Mark VII–VIII",
        "v10.0.0 · R10 Vision · Mark XL",
        "v5.1.1 · R5.1 hotfix 1 — reliable mic test · Mark XII",
        "v9.0.0 · R9 Mark II of the deck · Mark IX–XIV",  # "Mark" inside the name is fine
        "v1.0.0 · R1 Small · Mark I",
        "v1.0.0 · R1 Large · Mark CCCXCIX",
    ],
)
def test_good_titles_pass(good: str) -> None:
    assert cpt.check(good)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "R6.1: The Architecture Guide & versioning",
        "Slice 5: conversations, approvals and audit survive scale-to-zero (Firestore)",
        "Bump actions/checkout from 6 to 7",
        "v6.1 · R6.1 The Architecture Guide · Mark XIII",  # two numbers
        "6.1.0 · R6.1 The Architecture Guide · Mark XIII",  # no v
        "v6.1.0 - R6.1 The Architecture Guide - Mark XIII",  # hyphens, not the middle dot
        "v6.1.0 · R6.1 The Architecture Guide · Mark 13",  # not a Roman numeral
        "v6.1.0 · R6.1 The Architecture Guide · Mark XIII ",  # trailing space
        "v6.1.0 · R6.1 The Architecture Guide · Mark XIII\n",  # trailing newline
        "v6.1.0 · R6.1 The Architecture Guide · Mark VII-VIII",  # a hyphen, not the en dash
        "v6.1.0 · R6.1 The Architecture Guide · mark XIII",
        "v6.1.0 · · Mark XIII",  # no name
        "v6.1.0 · R6.1 The Architecture Guide",  # no Mark
        "v٦.1.0 · R6.1 The Architecture Guide · Mark XIII",  # a non-ASCII digit
    ],
)
def test_bad_titles_fail(bad: str) -> None:
    assert not cpt.check(bad)


@pytest.mark.parametrize(
    "mark",
    ["IIII", "VX", "IIV", "IC", "XXXX", "VV", "LL", "CCCC", "VIII–VII", "XIII–XIII", "I–IIII"],
)
def test_a_mark_that_is_not_a_roman_numeral_or_runs_backwards_fails(mark: str) -> None:
    """R6.1 review L4: the rule's pattern takes any run of I V X L C; the check also wants a
    well-formed numeral, and two Marks in rising order."""
    title = f"v6.1.0 · R6.1 The Architecture Guide · Mark {mark}"
    assert cpt.PATTERN.fullmatch(title)  # the rule's own pattern lets it through
    assert not cpt.check(title)


def test_the_roman_numerals_read_as_numbers() -> None:
    values = {"I": 1, "IV": 4, "IX": 9, "XIII": 13, "XIV": 14, "XL": 40, "XC": 90, "CCCXCIX": 399}
    assert {m: cpt.roman(m) for m in values} == values


def test_the_cli_says_ok_or_what_is_wanted(capsys: pytest.CaptureFixture[str]) -> None:
    assert cpt.main(["v6.1.0 · R6.1 The Architecture Guide & versioning · Mark XIII"]) == 0
    assert "OK" in capsys.readouterr().out
    assert cpt.main(["R6.1 the guide"]) == 1
    out = capsys.readouterr().out
    assert "v6.1.0 · R6.1 Short name · Mark XIII" in out and "::error" in out
    assert cpt.main(["v6.1.0 · R6.1 The guide · Mark VIII–VII"]) == 1
    assert "rising order" in capsys.readouterr().out
    assert not any(ln.startswith("::") and "R6.1 the guide" in ln for ln in out.splitlines())
    assert cpt.main([]) == 2 and cpt.main(["a", "b"]) == 2


def test_the_script_runs_with_the_standard_library_alone() -> None:
    title = "v6.1.0 · R6.1 The Architecture Guide & versioning · Mark XIII"
    ok = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), title], capture_output=True, text=True, timeout=30
    )
    bad = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "x"], capture_output=True, text=True, timeout=30
    )
    assert (ok.returncode, bad.returncode) == (0, 1), (ok.stderr, bad.stderr)


# ---- CI ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return data


def test_the_title_job_runs_on_pull_requests_only_and_exempts_dependabot(
    ci: dict[str, Any],
) -> None:
    job = ci["jobs"]["pr-title"]
    cond = " ".join(job["if"].split())
    assert "github.event_name == 'pull_request'" in cond
    assert "github.actor != 'dependabot[bot]'" in cond
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in cond
    assert "needs" not in job


def test_the_deploy_job_never_waits_for_the_title_check(ci: dict[str, Any]) -> None:
    def needs(name: str) -> set[str]:
        raw = ci["jobs"][name].get("needs", [])
        return {raw} if isinstance(raw, str) else set(raw)

    seen, todo = set(), ["deploy"]
    while todo:  # every job deploy waits for, directly or through another job
        for dep in needs(todo.pop()) - seen:
            seen.add(dep)
            todo.append(dep)
    assert "pr-title" not in seen
    assert "check_pr_title" not in yaml.safe_dump(ci["jobs"]["deploy"])


def test_the_title_reaches_the_script_as_data_never_as_shell_code(ci: dict[str, Any]) -> None:
    job = ci["jobs"]["pr-title"]
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "scripts/check_pr_title.py" in runs
    assert "${{" not in runs  # the title comes in through env, quoted
    env = next(s["env"] for s in job["steps"] if "env" in s)
    assert env["PR_TITLE"] == "${{ github.event.pull_request.title }}"
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_the_title_job_leaves_no_token_on_disk_and_checks_out_only_the_script(
    ci: dict[str, Any],
) -> None:
    """R6.1 security review L1: the job runs the pull request's own script, so the checkout
    keeps no credentials in .git/config (GH_TOKEN reaches `gh api` through env alone)."""
    steps = ci["jobs"]["pr-title"]["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1
    opts = checkouts[0]["with"]
    assert opts["persist-credentials"] is False
    assert opts["sparse-checkout"].split() == ["scripts/check_pr_title.py"]
    assert opts["sparse-checkout-cone-mode"] is False


# ---- the pull request template ------------------------------------------------------------------
def test_the_template_starts_with_the_header_lines_and_has_the_sections() -> None:
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    assert lines[0] == (
        "**Version:** v6.1.0 · **Release:** R6.1 The Architecture Guide & versioning · "
        "**Built in:** 🛠 Mark XIII"
    )
    assert lines[1].startswith("**Plan:**")
    assert "**Build log:**" in lines[1] and "**Your steps:**" in lines[1]
    heads = [ln for ln in lines if ln.startswith("## ")]
    assert heads == [
        "## What you get",
        "## Cost (₹)",
        "## Checks",
        "## Reviews",
        "## Not verified live",
    ]


def test_the_template_holds_nothing_private() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "claude.ai" not in text and "@" not in text and "http" not in text
