# tests/test_r131_i1_deploy.py -- R13.1 I1, the integrated security review on the deploy
# (`deploy/cloudrun.sh`, seam 13), by BEHAVIOUR: each try-on block of the script is cut out and
# run in bash with `gcloud`, `curl` and `try_bind` as stubs (nothing reaches Google; nothing is
# charged), then its variables are read back.
#   - finding 1 (MEDIUM): the consent's "Google's cache is switched off" is true only when the
#     cache PATCH succeeded AND a read-back says `disableCache: true`; every other path leaves
#     `TRYON_CACHE=true` (fail toward disclosure), including a run whose role step failed;
#   - finding 5 (LOW): the role step fails closed: an existing `jarvisTryOn` that can't be set
#     back to prompt requests only is never bound, nor kept bound from an earlier run (its
#     binding to JARVIS's account is taken off), and there is no fallback to the broad
#     `roles/aiplatform.user`;
#   - finding 6 (LOW): the budget alert names its currency (`300INR`), so a USD account refuses
#     it (a note) instead of setting $300.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SH = (Path(__file__).resolve().parents[1] / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
ROLE = ("# R13.1 (plan review M6): a custom role", "# Google's own 24-hour cache")
CACHE = ("# Google's own 24-hour cache", "# A budget alert at the try-on cap")
STUBS = r"""
calls() { printf '%s\n' "$*" >> "$LOG"; }
gcloud() {
  calls "gcloud $*"
  case "$*" in
    "iam roles describe"*) [ "$ROLE_EXISTS" = yes ] ;;
    "iam roles update"*) [ "$ROLE_UPDATE" = ok ] ;;
    "iam roles create"*) [ "$ROLE_CREATE" = ok ] ;;
    "auth print-access-token"*) [ -n "$TOKEN" ] && printf '%s\n' "$TOKEN" ;;
    "projects remove-iam-policy-binding"*) [ "$UNBIND" = ok ] || { echo "$UNBIND" >&2; false; } ;;
    *) return 0 ;;
  esac
}
try_bind() { calls "bind $2"; [ "$BIND" = ok ]; }
curl() {
  cat >/dev/null  # the token's config on stdin
  case "$*" in
    *"-X PATCH"*) calls "curl PATCH"; [ "$PATCH" = ok ] ;;
    *) calls "curl GET"; [ "$GET" != fail ] && printf '%s\n' "$GET" ;;
  esac
}
"""


def _block(marks: tuple[str, str]) -> str:
    start, end = SH.index(marks[0]), SH.index(marks[1])
    assert start < end
    return SH[start:end]


def _shell(block: str, tmp: Path, **env: str) -> tuple[str, list[str]]:
    """The block run with the stubs: what it printed, and the commands it called."""
    log = tmp / "calls.log"
    log.write_text("")
    script = STUBS + block + '\necho "STATE=$TRYON_STATE"; echo "CACHE=${TRYON_CACHE:-}"\n'
    base = {"PROJECT": "demo-project", "RUN_SA": "jarvis-run@demo.example", "LOG": str(log),
            "TRYON_API": "on", "ROLE_EXISTS": "no", "ROLE_UPDATE": "ok", "ROLE_CREATE": "ok",
            "BIND": "ok", "UNBIND": "ok", "TOKEN": "a-made-up-token", "PATCH": "ok",
            "GET": '{"name": "projects/demo-project/cacheConfig", "disableCache": true}',
            "PATH": "/usr/bin:/bin"}  # fmt: skip
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30,
                         env={**base, **env}, check=False)  # fmt: skip
    assert got.returncode == 0, got.stderr
    return got.stdout, log.read_text().splitlines()


def _run(block: str, tmp: Path, **env: str) -> tuple[dict[str, str], list[str]]:
    said, calls = _shell(block, tmp, **env)
    out = dict(ln.split("=", 1) for ln in said.splitlines() if "=" in ln[:6])
    return out, calls


def _unbinds(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("gcloud projects remove-iam-policy-binding")]


# ---- finding 1: the cache claim ---------------------------------------------------------------
def test_the_cache_is_said_off_only_when_the_patch_worked_and_google_reads_it_back(
    tmp_path: Path,
) -> None:
    got, calls = _run(_block(CACHE), tmp_path, TRYON_STATE="true")
    assert got["CACHE"] == "false" and calls == ["gcloud auth print-access-token", "curl PATCH",
                                                 "curl GET"]  # fmt: skip


@pytest.mark.parametrize(
    "env",
    [
        {"TRYON_STATE": "false"},  # the API or the role failed this run: no PATCH was ever sent
        {"TRYON_STATE": "true", "TOKEN": ""},
        {"TRYON_STATE": "true", "PATCH": "fail"},
        {"TRYON_STATE": "true", "GET": "fail"},
        {"TRYON_STATE": "true", "GET": '{"name": "x/cacheConfig", "disableCache": false}'},
        {"TRYON_STATE": "true", "GET": '{"name": "x/cacheConfig"}'},  # not said: not proved
    ],
    ids=["no-role", "no-token", "patch-refused", "read-back-failed", "read-back-false", "unsaid"],
)
def test_every_other_path_leaves_the_consent_saying_google_may_keep_requests(
    tmp_path: Path, env: dict[str, str]
) -> None:
    got, _ = _run(_block(CACHE), tmp_path, **env)
    assert got["CACHE"] == "true", env


def test_the_cache_block_starts_true_and_says_false_once_after_the_read_back() -> None:
    block = _block(CACHE)
    sets = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("TRYON_CACHE=")]
    assert sets == ["TRYON_CACHE=true", "TRYON_CACHE=false"]
    assert block.index("\nTRYON_CACHE=true") < block.index('if [ "$TRYON_STATE" = true ]')
    assert block.index('disableCache": *true') < block.index("    TRYON_CACHE=false")
    assert SH.count("TRYON_CACHE=false") == 1  # nowhere else in the deploy


# ---- finding 5: the role fails closed ----------------------------------------------------------
def test_a_new_prompt_only_role_is_made_bound_and_switches_pictures_on(tmp_path: Path) -> None:
    got, calls = _run(_block(ROLE), tmp_path)
    assert got["STATE"] == "true"
    assert [c for c in calls if c.startswith("bind")] == ["bind projects/demo-project/roles/"
                                                          "jarvisTryOn"]  # fmt: skip


def test_an_existing_role_set_back_to_prompts_only_is_bound(tmp_path: Path) -> None:
    got, calls = _run(_block(ROLE), tmp_path, ROLE_EXISTS="yes")
    assert got["STATE"] == "true" and any(c.startswith("gcloud iam roles update") for c in calls)


@pytest.mark.parametrize(
    "env",
    [{"ROLE_EXISTS": "yes", "ROLE_UPDATE": "fail"},  # unknown, broader or soft-deleted
     {"ROLE_CREATE": "fail"},  # can't be made: never the broad Agent Platform User
     {"BIND": "fail"}],
    ids=["update-failed", "create-failed", "bind-failed"],
)  # fmt: skip
def test_the_role_step_fails_closed_and_binds_nothing_broader(
    tmp_path: Path, env: dict[str, str]
) -> None:
    got, calls = _run(_block(ROLE), tmp_path, **env)
    assert got["STATE"] == "false", env
    binds = [c for c in calls if c.startswith("bind")]
    assert all(b.endswith("roles/jarvisTryOn") for b in binds), binds
    if env.get("ROLE_UPDATE") == "fail":
        assert binds == []  # a role of unknown permissions is never bound
    assert "roles/aiplatform.user" not in SH


def test_a_role_that_cant_be_set_back_is_not_kept_bound_from_an_earlier_run(
    tmp_path: Path,
) -> None:
    got, calls = _run(_block(ROLE), tmp_path, ROLE_EXISTS="yes", ROLE_UPDATE="fail")
    assert got["STATE"] == "false"
    (unbind,) = _unbinds(calls)  # exactly once, JARVIS's own account, the try-on role only
    assert "--member=serviceAccount:jarvis-run@demo.example" in unbind
    assert "--role=projects/demo-project/roles/jarvisTryOn" in unbind
    update = [i for i, c in enumerate(calls) if c.startswith("gcloud iam roles update jarvisTryOn")]
    assert update and update[0] < calls.index(unbind)  # only once it couldn't be set back


@pytest.mark.parametrize(
    ("answer", "noted"),
    [("ok", False),
     ("ERROR: Policy binding with the specified principal, role, and condition not found!", False),
     ("ERROR: (gcloud.projects.remove-iam-policy-binding) PERMISSION_DENIED", True)],
    ids=["taken-off", "was-not-bound", "refused"],
)  # fmt: skip
def test_a_binding_that_cant_be_taken_off_is_said_in_words(
    tmp_path: Path, answer: str, noted: bool
) -> None:
    said, _ = _shell(_block(ROLE), tmp_path, ROLE_EXISTS="yes", ROLE_UPDATE="fail", UNBIND=answer)
    assert "STATE=false" in said
    assert ("could not take the try-on role jarvisTryOn off JARVIS's account" in said) is noted
    assert "PERMISSION_DENIED" not in said  # a note in plain words, never gcloud's own text


@pytest.mark.parametrize(
    "env",
    [{}, {"ROLE_EXISTS": "yes"}, {"ROLE_CREATE": "fail"}, {"BIND": "fail"}],
    ids=["made", "set-back", "create-failed", "bind-failed"],
)
def test_a_role_that_is_prompt_only_or_never_existed_is_never_unbound(
    tmp_path: Path, env: dict[str, str]
) -> None:
    _, calls = _run(_block(ROLE), tmp_path, **env)
    assert _unbinds(calls) == []


# ---- finding 6: the budget alert's currency ----------------------------------------------------
def test_the_budget_alert_is_in_rupees_and_says_so_when_the_account_isnt() -> None:
    assert "--budget-amount=300INR" in SH and "--budget-amount=300 " not in SH
    budget = SH[SH.index("# A budget alert at the try-on cap") : SH.index("grant_failed() {")]
    assert "in its own currency" in budget
