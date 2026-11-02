# tests/test_deploy_config.py — slice 5c: deploy-on-merge is gated, keyless and least-privilege.
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
SCRIPT = ROOT / "deploy" / "cloudrun.sh"


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _deploy(ci: dict[str, Any]) -> dict[str, Any]:
    job: dict[str, Any] = ci["jobs"]["deploy"]
    return job


def test_deploy_runs_only_after_tests_pass_on_main_pushes_when_switched_on(
    ci: dict[str, Any],
) -> None:
    job = _deploy(ci)
    assert set(job["needs"]) >= {"test", "firestore"}
    cond = job["if"]
    assert "vars.AUTODEPLOY == 'on'" in cond
    assert "github.ref == 'refs/heads/main'" in cond
    assert "github.event_name == 'push'" in cond
    assert "pull_request" not in cond  # a PR (or a fork's PR) can never deploy


def test_only_the_deploy_job_can_mint_a_google_token(ci: dict[str, Any]) -> None:
    assert _deploy(ci)["permissions"] == {"contents": "read", "id-token": "write"}
    assert "id-token" not in str(ci["permissions"])
    for name, job in ci["jobs"].items():
        if name != "deploy":
            assert "id-token" not in str(job.get("permissions", {})), name


def test_deploy_is_keyless_and_never_runs_two_at_once(ci: dict[str, Any]) -> None:
    job = _deploy(ci)
    text = yaml.safe_dump(job)
    assert "secrets." not in text  # Workload Identity Federation: no stored key anywhere
    assert "credentials_json" not in text
    auth = next(
        s for s in job["steps"] if str(s.get("uses", "")).startswith("google-github-actions/auth@")
    )
    assert "workload_identity_provider" in auth["with"]
    assert job["concurrency"]["cancel-in-progress"] is False


def test_every_action_is_pinned_to_a_full_commit_sha(ci: dict[str, Any]) -> None:
    # a moved tag must never run inside a job that can mint a Google token or holds a key
    for name, job in ci["jobs"].items():
        for s in job.get("steps", []):
            if "uses" in s:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", s["uses"]), (name, s["uses"])


def test_workflow_default_token_is_read_only(ci: dict[str, Any]) -> None:
    assert ci["permissions"] == {"contents": "read"}


def test_deploy_ships_the_tested_commit_and_checks_health(ci: dict[str, Any]) -> None:
    run = "\n".join(str(s.get("run", "")) for s in _deploy(ci)["steps"])
    assert "github.sha" in run or "GITHUB_SHA" in run
    assert "gcloud run deploy" in run and "--image" in run
    # new code gets no traffic until it is healthy; a re-run of an old job can't roll back main
    assert "--no-traffic" in run and "--tag" in run and "--to-latest" in run
    assert "git ls-remote" in run
    # settings and secrets stay as the owner configured them: never re-set from CI
    assert "--set-env-vars" not in run and "--set-secrets" not in run
    assert "--allow-unauthenticated" not in run
    assert "/health" in run


def test_script_trusts_only_this_repo_on_main(script: str) -> None:
    assert re.search(r"GH_REPO_ID=\"\d+\"", script)
    assert "assertion.repository_id==" in script
    assert "assertion.ref=='refs/heads/main'" in script
    assert (
        "assertion.event_name in ['push','workflow_dispatch']" in script
    )  # no pull_request_target
    assert 'GH_REPO="Shark2558/jarvis-web"' in script
    assert (
        "assertion.job_workflow_ref=='${GH_REPO}/.github/workflows/ci.yml@refs/heads/main'"
        in script
    )
    assert "assertion.runner_environment=='github-hosted'" in script
    assert "principalSet://" in script and "attribute.repository_id/" in script


def test_deployer_gets_narrow_roles_only(script: str) -> None:
    for role in (
        "roles/run.developer",
        "roles/artifactregistry.writer",
        "roles/iam.serviceAccountUser",
    ):
        assert role in script
    for broad in (
        "roles/owner",
        "roles/editor",
        "roles/run.admin",
        "roles/iam.serviceAccountTokenCreator",
    ):
        assert broad not in script


def test_rerun_reuses_saved_answers_and_can_reconfigure(script: str) -> None:
    assert "--reconfigure" in script
    assert "--update-env-vars" in script  # quick update keeps owner-specific settings + secrets
    assert "--update-secrets" in script
    assert "JARVIS_OWNER_EMAILS" in script.split("QUICK=yes")[0]  # only a fully set-up service


def test_image_cleanup_never_ages_out_recent_images(script: str) -> None:
    assert '"keepCount":10' in script


def test_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_script_passes_shellcheck() -> None:
    subprocess.run(["shellcheck", "-S", "warning", str(SCRIPT)], check=True)


# ---- slice 6: Google tools need a vault key, two more APIs and consent-screen scopes ----------


def test_token_key_secret_is_generated_bound_and_granted(script: str) -> None:
    assert "jarvis-token-key" in script
    # generated (32 random bytes, base64) only when missing — never overwritten on a re-run
    assert re.search(r"secret_exists jarvis-token-key \|\| put_secret jarvis-token-key", script)
    assert "head -c 32 /dev/urandom | base64" in script
    # both the full set-up and the quick path bind it, and the runtime account may read it
    set_secrets = [ln for ln in script.splitlines() if "--set-secrets" in ln]
    update_secrets = [ln for ln in script.splitlines() if "--update-secrets" in ln]
    assert set_secrets and all(
        "JARVIS_TOKEN_KEY=jarvis-token-key:latest" in ln for ln in set_secrets
    )
    assert update_secrets and all(
        "JARVIS_TOKEN_KEY=jarvis-token-key:latest" in ln for ln in update_secrets
    )
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert "jarvis-token-key" in grant_loop


def test_calendar_and_gmail_apis_are_enabled(script: str) -> None:
    enable = script.split("gcloud services enable", 1)[1].split("--quiet", 1)[0]
    assert "calendar-json.googleapis.com" in enable and "gmail.googleapis.com" in enable


def test_script_prints_consent_scopes_and_test_user_reminder(script: str) -> None:
    for scope in (
        "auth/calendar.events",
        "auth/calendar.readonly",
        "auth/gmail.readonly",
        "auth/gmail.compose",
    ):
        assert scope in script
    # gmail.compose already allows messages.send: the redundant scope is not asked for
    assert "auth/gmail.send" not in script
    # slice 7: the morning brief's inbox delivery is the one optional scope
    insert = next(ln for ln in script.splitlines() if "auth/gmail.insert" in ln)
    assert "optional" in insert and "brief in your inbox" in insert
    assert "Test users" in script or "test user" in script.lower()
    assert "7 days" in script  # Testing-mode refresh tokens expire weekly
    assert "/connect/google/callback" in script  # second redirect URI


def test_the_tasks_api_is_switched_on_and_its_scope_is_printed_as_optional(script: str) -> None:
    """Slice 10 C: the to-do list. Without the API switched on in the project Google answers
    403 even with the scope granted; the scope itself is optional (Integrations → Grant)."""
    enable = script.split("gcloud services enable", 1)[1].split("--quiet", 1)[0]
    assert "tasks.googleapis.com" in enable
    line = next(ln for ln in script.splitlines() if "auth/tasks" in ln)
    assert "optional" in line and "to-do" in line
    assert "Grant" in script


def test_default_brain_prompt_accepts_claude(script: str) -> None:
    assert "claude|Claude|CLAUDE) DEFAULT_BRAIN=anthropic" in script


def _top_level_depth_at(script: str, needle: str) -> int:
    """if/fi nesting (column 0 only) at the first line containing `needle`."""
    depth = 0
    for line in script.splitlines():
        if needle in line:
            return depth
        if re.match(r"if\b", line) and not re.search(r";\s*fi\s*$", line):
            depth += 1
        elif re.match(r"fi\b", line):
            depth -= 1
    raise AssertionError(f"{needle!r} not found")


def test_quick_path_also_creates_and_binds_the_token_key(script: str) -> None:
    """Rollout: an auto-deploy keeps the old secrets, so the first deploy of slice 6 runs without
    JARVIS_TOKEN_KEY (Google tools off, app healthy). Either re-run path must then create the
    secret if it is missing and bind it — the quick path with --update-secrets."""
    line = "secret_exists jarvis-token-key || put_secret jarvis-token-key"
    assert _top_level_depth_at(script, line) == 0  # runs on the quick AND the full path
    quick = script.split('if [ "$QUICK" = yes ]; then\n  CONFIG_FLAGS=(', 1)[1].split("else", 1)[0]
    assert "--update-secrets" in quick and "JARVIS_TOKEN_KEY=jarvis-token-key:latest" in quick


# ---- slice 7: the morning brief's clock (step 8/8) ---------------------------------------------


def _step8(script: str) -> str:
    return script.split('say "8/8', 1)[1].split('say "DONE', 1)[0]


def test_steps_are_numbered_one_to_eight_in_order(script: str) -> None:
    steps = re.findall(r'^say "(\d+)/(\d+) ', script, re.M)
    numbers = [int(n) for n, _ in steps]
    assert {total for _, total in steps} == {"8"}
    assert sorted(set(numbers)) == list(range(1, 9))
    assert numbers == sorted(numbers)  # 3/8 twice: quick path and full set-up


def test_brief_clock_is_created_or_updated_without_questions(script: str) -> None:
    s = _step8(script)
    assert "gcloud services enable cloudscheduler.googleapis.com" in s
    assert 'BRIEF_JOB="jarvis-morning-brief"' in script
    assert 'gcloud scheduler jobs describe "$BRIEF_JOB" --location "$REGION"' in s
    assert 'gcloud scheduler jobs update http "$BRIEF_JOB"' in s
    assert 'gcloud scheduler jobs create http "$BRIEF_JOB"' in s
    assert '--location "$REGION"' in s
    assert '--schedule "0,30 4-11 * * *"' in s
    assert 'BRIEF_TZ="${BRIEF_TZ:-Asia/Kolkata}"' in script and '--time-zone "$BRIEF_TZ"' in s
    assert 'TICK_URL="${BASE_URL}/internal/brief/tick"' in s
    assert "--http-method POST" in s and "--attempt-deadline 180s" in s
    # signed for the clock account, for exactly this address (useless anywhere else)
    assert '--oidc-service-account-email "$SCHED_SA"' in s
    assert '--uri "$TICK_URL"' in s and '--oidc-token-audience "$TICK_URL"' in s
    assert "read " not in s  # re-runs ask nothing


def test_brief_clock_account_has_no_project_roles(script: str) -> None:
    assert 'SCHED_SA="jarvis-scheduler@${PROJECT}.iam.gserviceaccount.com"' in script
    s = _step8(script)
    assert "gcloud iam service-accounts create jarvis-scheduler" in s
    assert 'gcloud iam service-accounts describe "$SCHED_SA"' in s  # only when missing
    assert "add-iam-policy-binding" not in s
    for line in script.splitlines():
        if "add-iam-policy-binding" in line or "--member" in line or line.startswith("  bind "):
            assert "SCHED_SA" not in line and "jarvis-scheduler" not in line, line


def test_brief_clock_failure_is_never_fatal(script: str) -> None:
    s = _step8(script)
    body = s.split("setup_brief_clock() {", 1)[1].split("\n}\n", 1)[0]
    assert "die " not in body and "exit" not in body  # every failure returns 1 instead
    assert "if setup_brief_clock; then" in s
    assert "Note: the morning-brief clock could not be set up" in s
    assert "open the Brief panel" in s  # says what still works
    # the scheduler API is not in step 2's must-succeed list
    first_enable = script.split("gcloud services enable", 1)[1].split("--quiet", 1)[0]
    assert "cloudscheduler" not in first_enable


def test_scheduler_account_reaches_the_app_on_both_deploy_paths(script: str) -> None:
    infra = next(ln for ln in script.splitlines() if ln.startswith("INFRA_ENV="))
    assert "JARVIS_BRIEF_SCHEDULER_SA=${SCHED_SA}" in infra
    assert '--update-env-vars "$INFRA_ENV"' in script  # quick re-run
    assert '--set-env-vars "${INFRA_ENV},' in script  # full set-up
    # the address exists before the deploy uses it; the account and the job come after the deploy
    deploy = script.index("gcloud run deploy")
    assert script.index('SCHED_SA="') < deploy
    assert deploy < script.index("gcloud iam service-accounts create jarvis-scheduler")
    assert deploy < script.index("gcloud scheduler jobs create http")


def _brief_outcome(script: str) -> str:
    """Step 8's outcome through the morning-brief part of the closing summary."""
    start = script.index("BRIEF_CLOCK_OK=no")
    return script[start : script.index('if [ "$AUTODEPLOY_OK" = yes ]', start)]


def _run_brief_outcome(script: str, tmp: Path, setup_rc: int, run_rc: int) -> tuple[str, str]:
    """Run that part in bash with step 8 and gcloud stubbed; returns (output, gcloud calls)."""
    log = tmp / "gcloud.log"
    log.touch()
    prelude = (
        "set -euo pipefail\n"
        "say() { printf '\\n%s\\n' \"$*\"; }\n"
        f"setup_brief_clock() {{ return {setup_rc}; }}\n"
        f"gcloud() {{ printf '%s\\n' \"$*\" >> '{log}'; return {run_rc}; }}\n"
        "BRIEF_JOB=jarvis-morning-brief REGION=asia-south1 BRIEF_TZ=Asia/Kolkata\n"
        "BASE_URL=https://jarvis.example\n"
    )
    done = subprocess.run(
        ["bash", "-c", prelude + _brief_outcome(script)],
        capture_output=True,
        text=True,
        check=True,  # a failed test run must never stop the script (set -e)
    )
    return done.stdout, log.read_text(encoding="utf-8")


def test_summary_says_plainly_when_the_brief_schedule_was_not_set_up(
    script: str, tmp_path: Path
) -> None:
    """Review L6: a failed step 8 is named in the closing summary, with what still works."""
    out, calls = _run_brief_outcome(script, tmp_path, setup_rc=1, run_rc=0)
    assert "Morning brief: NOT scheduled" in out
    assert "open the Brief panel" in out  # what still works
    assert "Re-run this script" in out
    assert "Morning brief: ready" not in out and "Scheduler accepted it" not in out
    assert "scheduler jobs run" not in calls  # nothing to test


def test_a_working_schedule_is_test_run_once_and_said_to_answer(
    script: str, tmp_path: Path
) -> None:
    out, calls = _run_brief_outcome(script, tmp_path, setup_rc=0, run_rc=0)
    [call] = calls.splitlines()  # exactly once
    assert call.startswith("scheduler jobs run jarvis-morning-brief --location asia-south1")
    assert "Morning brief: ready" in out
    assert "Scheduler accepted it" in out
    assert "NOT scheduled" not in out


def test_a_failed_test_run_is_not_fatal_and_not_called_an_answer(
    script: str, tmp_path: Path
) -> None:
    out, calls = _run_brief_outcome(script, tmp_path, setup_rc=0, run_rc=1)
    assert len(calls.splitlines()) == 1  # tried once, never retried in a loop
    assert "Morning brief: ready" in out
    assert "Scheduler accepted it" not in out
    assert "test run" in out  # says the check didn't go through, in plain words


def test_the_test_run_is_harmless_because_the_app_decides_what_is_due(script: str) -> None:
    s = _step8(script)
    run = next(ln for ln in s.splitlines() if "gcloud scheduler jobs run" in ln)
    assert 'gcloud scheduler jobs run "$BRIEF_JOB" --location "$REGION"' in run
    assert run.lstrip().startswith("if ")  # its failure is a branch, never an exit
    assert "JARVIS decides" in s  # the comment says why a test run makes nothing twice


# ---- security review M5: nothing unhashed reaches the image; CI pins what it installs ---------

DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "requirements.lock"


def test_image_installs_only_hash_checked_artifacts() -> None:
    df = DOCKERFILE.read_text(encoding="utf-8")
    assert "--upgrade pip" not in df  # an unpinned, unhashed pip straight from the index
    assert "pip install --require-hashes -r requirements.lock" in df
    # the app builds with the LOCKED setuptools/wheel: no isolated env fetching them unhashed
    assert "pip install --no-build-isolation --no-deps ." in df
    for line in df.splitlines():
        if line.startswith("RUN") and "pip install" in line:
            assert "--require-hashes" in line or "--no-build-isolation --no-deps" in line, line


def test_lock_pins_pip_and_the_build_backend_with_hashes() -> None:
    lock = LOCK.read_text(encoding="utf-8")
    for pkg in ("pip", "setuptools", "wheel"):
        assert re.search(
            rf"^{pkg}==[0-9][0-9.]* \\\n\s+--hash=sha256:[0-9a-f]{{64}}", lock, re.M
        ), pkg
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==", lock, re.M)
    assert len(pins) == len(re.findall(r"^[A-Za-z0-9_.-]+==[^\n]* \\\n\s+--hash=", lock, re.M))


def test_browser_job_pins_playwright(ci: dict[str, Any]) -> None:
    run = "\n".join(str(s.get("run", "")) for s in ci["jobs"]["browser"]["steps"])
    assert "playwright==1.63.0" in run
    assert not re.search(r"\bplaywright(?!==)(\s|$)", run.split("playwright install")[0])


# ---- slice 9: voice needs the two speech APIs and lets jarvis-run use them --------------------


def _runtime_roles(script: str) -> str:
    return script.split("for role in roles/datastore.user", 1)[1].split("; do", 1)[0]


def _command(script: str, needle: str) -> str:
    """The whole (backslash-continued) command line that contains `needle`."""
    lines = script.splitlines()
    i = next(n for n, ln in enumerate(lines) if needle in ln)
    while i > 0 and lines[i - 1].endswith("\\"):
        i -= 1
    out = [lines[i]]
    while out[-1].endswith("\\"):
        i += 1
        out.append(lines[i])
    return "\n".join(out)


def test_speech_apis_are_enabled_on_their_own_and_never_stop_the_deploy(script: str) -> None:
    """Review item 8: under `set -euo pipefail`, an org policy that blocks the speech APIs used
    to stop the whole deploy. They are enabled in their own command that may fail."""
    required = script.split("gcloud services enable", 1)[1].split("--quiet", 1)[0]
    assert "texttospeech" not in required and "speech.googleapis.com" not in required
    # step 2 runs on every path (quick re-runs too): the first enable is at the top level
    assert _top_level_depth_at(script, "gcloud services enable run.googleapis.com") == 0
    voice = _command(script, "gcloud services enable texttospeech.googleapis.com")
    assert "speech.googleapis.com" in voice and "--quiet" in voice
    assert "||" in voice and "browser voice will be used" in voice
    assert _top_level_depth_at(script, "gcloud services enable texttospeech") == 0


def test_runtime_account_may_consume_the_projects_services_without_stopping_the_deploy(
    script: str,
) -> None:
    """Kept (decision in the plan §9): it only lets jarvis-run use APIs that are already on, and
    saves the owner a second step if Google requires it. A failure is a note, not a stop."""
    assert "serviceUsageConsumer" not in _runtime_roles(script)  # not in the must-succeed loop
    grant = _command(script, "roles/serviceusage.serviceUsageConsumer")
    assert grant.startswith("try_bind") and '"serviceAccount:${RUN_SA}"' in grant
    assert "||" in grant
    helper = script.split("try_bind() {", 1)[1].split("\n}", 1)[0]
    assert "die" not in helper and "return 1" in helper and "add-iam-policy-binding" in helper
    # granted with the idempotent binding helper, never removed again
    removed = script.split("remove-iam-policy-binding", 1)[0].rsplit("for role in", 1)[1]
    assert "serviceUsageConsumer" not in removed
    assert _top_level_depth_at(script, 'try_bind "serviceAccount:${RUN_SA}"') == 0


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_deploy_script_still_parses(script: str) -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_voice_needs_no_new_secret_or_env(script: str) -> None:
    # ADC as jarvis-run: no key, no secret; JARVIS_VOICE_CLOUD defaults on in the app
    assert "jarvis-voice" not in script and "JARVIS_VOICE_" not in script
    assert "texttospeech" in script.split('say "DONE', 1)[1]  # the one-time fix is printed
