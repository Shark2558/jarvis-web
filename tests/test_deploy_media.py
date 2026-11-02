# tests/test_deploy_media.py — slice 12 D2: deploy/cloudrun.sh switches on the Maps and YouTube
# APIs, creates (or reuses) ONE API key `jarvis-maps-yt` restricted to Places, Routes, Geocoding and
# YouTube, keeps its string only in Secret Manager (`jarvis-google-api-key`, readable by jarvis-run
# through the per-secret grant loop) and mounts it as JARVIS_GOOGLE_API_KEY on both deploy paths.
# Every step is non-fatal; the key is never printed; the summary is one plain block that says India
# pricing applies only with an India billing account. Run with gcloud stubbed out.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"
SERVICES = (
    "places.googleapis.com",
    "routes.googleapis.com",
    "geocoding-backend.googleapis.com",
    "youtube.googleapis.com",
)
KEY = "AIzaSyFAKE-not-a-real-key_0123456789abc"
BOUND = "JARVIS_GOOGLE_API_KEY=jarvis-google-api-key:latest,"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(script: str) -> str:
    start = script.index("setup_maps_key() {")
    return script[start : script.index("\n}\n", start) + 3]


def _run(
    script: str, tmp: Path, *, existing: bool, secret: str = "", fail: str = ""
) -> dict[str, str]:
    """Run setup_maps_key with a fake gcloud that logs every call. `existing`: the key already
    exists; `secret`: the saved secret's value ('' = no secret); `fail`: a gcloud subcommand
    that fails."""
    log, stored = tmp / "gcloud.log", tmp / "stored"
    fake = tmp / "gcloud"
    listed = "echo projects/p/locations/global/keys/k1" if existing else "true"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        f'case "$*" in *"{fail or "@@never@@"}"*) exit 1 ;; esac\n'
        'case "$*" in\n'
        f'  "services api-keys list"*) {listed} ;;\n'
        '  "services api-keys create"*) echo projects/p/locations/global/keys/k1 ;;\n'
        f'  "services api-keys get-key-string"*) echo "{KEY}" ;;\n'
        f'  "secrets versions access"*) {"echo " + secret if secret else "exit 1"} ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    prelude = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\n'
        f"secret_exists() {{ [ '{'yes' if secret else 'no'}' = yes ] || [ -s '{stored}' ]; }}\n"
        f"put_secret() {{ printf '%s=%s' \"$1\" \"$2\" > '{stored}'; }}\n"
        'die() { echo "DIE $*" >&2; exit 9; }\n'
        "MAPS_SECRET=''; MAPS_STATE=off\n"
    )
    body = (
        prelude
        + _function(script)
        + 'setup_maps_key\nprintf "\\nSECRET=%s\\nSTATE=%s\\n" "$MAPS_SECRET" "$MAPS_STATE"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    out = done.stdout + done.stderr
    lines = dict(
        ln.split("=", 1) for ln in done.stdout.splitlines() if ln[:6] in ("SECRET", "STATE=")
    )
    return {
        "rc": str(done.returncode),
        "out": out,
        "calls": log.read_text() if log.exists() else "",
        "stored": stored.read_text() if stored.exists() else "",
        "secret": lines.get("SECRET", ""),
        "state": lines.get("STATE", ""),
    }


def test_first_run_enables_the_apis_creates_a_restricted_key_and_stores_it(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, existing=False)
    assert r["rc"] == "0", r["out"]
    calls = r["calls"].splitlines()
    enable = next(c for c in calls if c.startswith("services enable"))
    for s in (*SERVICES, "apikeys.googleapis.com"):
        assert s in enable
    create = next(c for c in calls if c.startswith("services api-keys create"))
    assert "--display-name=jarvis-maps-yt" in create
    assert [t for t in create.split() if t.startswith("--api-target=")] == [
        f"--api-target=service={s}" for s in SERVICES
    ]
    assert r["stored"] == f"jarvis-google-api-key={KEY}"
    assert (r["secret"], r["state"]) == (BOUND, "on")
    assert KEY not in r["out"]  # never printed


def test_a_rerun_reuses_the_key_keeps_its_restrictions_and_stores_nothing_new(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, existing=True, secret=KEY)
    assert r["rc"] == "0", r["out"]
    assert "services api-keys create" not in r["calls"]
    update = next(c for c in r["calls"].splitlines() if c.startswith("services api-keys update"))
    assert "projects/p/locations/global/keys/k1" in update
    for s in SERVICES:
        assert f"--api-target=service={s}" in update
    assert r["stored"] == ""  # the same string: no new secret version
    assert (r["secret"], r["state"]) == (BOUND, "on")
    assert KEY not in r["out"]


@pytest.mark.parametrize(
    "fail", ["services enable", "services api-keys create", "services api-keys get-key-string"]
)
def test_any_failure_is_not_fatal_and_maps_stays_off(
    script: str, tmp_path: Path, fail: str
) -> None:
    r = _run(script, tmp_path, existing=False, fail=fail)
    assert r["rc"] == "0", r["out"]
    assert "DIE" not in r["out"]
    assert (r["secret"], r["state"]) == ("", "off")
    assert "Note:" in r["out"]


def test_a_failure_after_an_earlier_success_keeps_the_saved_key_bound(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, existing=True, secret=KEY, fail="services api-keys get-key-string")
    assert r["rc"] == "0" and (r["secret"], r["state"]) == (BOUND, "on")


def test_the_step_runs_before_the_grants_and_the_deploy(script: str) -> None:
    call = script.index("\nsetup_maps_key\n")
    assert call < script.index("for secret in") < script.index("gcloud run deploy")
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert "jarvis-google-api-key" in grant_loop


def test_the_binding_reaches_both_deploy_paths(script: str) -> None:
    for ln in script.splitlines():
        if "--set-secrets" in ln or "--update-secrets" in ln:
            assert "${MAPS_SECRET}" in ln, ln


def test_the_summary_is_plain_and_says_where_india_pricing_applies(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    block = done.split("MAPS + YOUTUBE", 1)[1].split("MSG", 1)[0]
    assert "India" in block and "billing account" in block
    assert "31,500" in block and "90" in block
    assert "$" not in block.replace("${", "") and "₹" not in block


def test_script_still_parses() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
