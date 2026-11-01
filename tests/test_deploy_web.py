# tests/test_deploy_web.py — slice 10 B: deploy/cloudrun.sh asks ONLY the new web-search question,
# and only when there is no saved answer (Enter = skip); the key lives in Secret Manager
# (jarvis-tavily-key), is bound as JARVIS_TAVILY_API_KEY on both deploy paths and readable by
# jarvis-run; a recorded "skip" keeps re-runs question-free.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(script: str) -> str:
    start = script.index("web_search_answer() {")
    return script[start : script.index("\n}\n", start) + 3]


def _run(
    script: str,
    tmp: Path,
    *,
    quick: str,
    secret: bool,
    svc_json: str = "",
    reconfigure: str = "no",
    typed: str = "",
) -> dict[str, str]:
    """Run the function with gcloud-free stubs; returns WEB_SECRET, WEB_ENV, prompts, stored."""
    stored = tmp / "stored"
    prelude = (
        "set -euo pipefail\n"
        f"QUICK={quick} RECONFIGURE={reconfigure}\n"
        + (f"SVC_JSON='{svc_json}'\n" if svc_json else "")
        + f"secret_exists() {{ [ '{'yes' if secret else 'no'}' = yes ]; }}\n"
        f"put_secret() {{ printf '%s=%s' \"$1\" \"$2\" > '{stored}'; }}\n"
        'die() { echo "DIE $*" >&2; exit 9; }\n'
        "WEB_SECRET=''; WEB_ENV='JARVIS_WEB_SEARCH_ENABLED=false'\n"
    )
    body = (
        prelude + _function(script) + "web_search_answer\n"
        'printf "\\nSECRET=%s\\nENV=%s\\n" "$WEB_SECRET" "$WEB_ENV"\n'
    )
    done = subprocess.run(
        ["bash", "-c", body], input=typed, capture_output=True, text=True, check=True
    )
    out = done.stdout + done.stderr
    lines = dict(ln.split("=", 1) for ln in done.stdout.splitlines() if ln[:4] in ("SECR", "ENV="))
    return {
        "secret": lines.get("SECRET", ""),
        "env": lines.get("ENV", ""),
        "asked": str("Tavily API key" in out),
        "stored": stored.read_text() if stored.exists() else "",
    }


BOUND = "JARVIS_TAVILY_API_KEY=jarvis-tavily-key:latest,"
ON, OFF = "JARVIS_WEB_SEARCH_ENABLED=true", "JARVIS_WEB_SEARCH_ENABLED=false"


def test_quick_rerun_with_a_saved_key_asks_nothing_and_binds_it(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, quick="yes", secret=True)
    assert r == {"secret": BOUND, "env": ON, "asked": "False", "stored": ""}


def test_quick_rerun_after_a_recorded_skip_asks_nothing(script: str, tmp_path: Path) -> None:
    svc = '{"env": [{"name": "JARVIS_WEB_SEARCH_ENABLED", "value": "false"}]}'
    r = _run(script, tmp_path, quick="yes", secret=False, svc_json=svc)
    assert r == {"secret": "", "env": OFF, "asked": "False", "stored": ""}


def test_quick_rerun_without_an_answer_asks_once_and_enter_skips(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, quick="yes", secret=False, svc_json='{"env": []}', typed="\n")
    assert r == {"secret": "", "env": OFF, "asked": "True", "stored": ""}


def test_a_pasted_key_is_stored_in_secret_manager_and_bound(script: str, tmp_path: Path) -> None:
    r = _run(script, tmp_path, quick="yes", secret=False, typed="tvly-abc123\n")
    assert r["stored"] == "jarvis-tavily-key=tvly-abc123"
    assert (r["secret"], r["env"], r["asked"]) == (BOUND, ON, "True")


def test_full_setup_asks_and_enter_keeps_a_saved_key(script: str, tmp_path: Path) -> None:
    r = _run(script, tmp_path, quick="no", secret=True, reconfigure="yes", typed="\n")
    assert (r["secret"], r["env"], r["asked"], r["stored"]) == (BOUND, ON, "True", "")
    r = _run(script, tmp_path, quick="no", secret=True, reconfigure="yes", typed="skip\n")
    assert (r["secret"], r["env"]) == ("", OFF)


def _top_level_depth_at(script: str, needle: str) -> int:
    """if/fi nesting (column 0 only) at the first line equal to `needle`."""
    depth = 0
    for line in script.splitlines():
        if line == needle:
            return depth
        if line.startswith("if ") and not line.rstrip().endswith("fi"):
            depth += 1
        elif line.startswith("fi"):
            depth -= 1
    raise AssertionError(f"{needle!r} not found")


def test_the_answer_is_found_on_both_paths_before_any_deploy(script: str) -> None:
    call = script.index("\nweb_search_answer\n")
    assert script.index("QUICK=no") < call < script.index("gcloud run deploy")
    # top level (not inside the "Your details" block): quick re-runs run it too
    assert _top_level_depth_at(script, "web_search_answer") == 0


def test_the_binding_and_the_switch_reach_both_deploy_paths(script: str) -> None:
    assert 'INFRA_ENV="${INFRA_ENV},${WEB_ENV}"' in script
    for ln in script.splitlines():
        if "--set-secrets" in ln or "--update-secrets" in ln:
            assert "${WEB_SECRET}JARVIS_" in ln, ln
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert "jarvis-tavily-key" in grant_loop


def test_the_closing_summary_says_whether_web_search_is_on(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    assert "WEB SEARCH" in done and "jarvis-tavily-key" in done
    assert "$" not in done.split("WEB SEARCH", 1)[1].split("MSG", 1)[0].replace("${", "")


def test_script_still_parses() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
