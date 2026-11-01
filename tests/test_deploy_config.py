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
