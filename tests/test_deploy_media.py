# tests/test_deploy_media.py — slice 12 D2: deploy/cloudrun.sh switches on the Maps and YouTube
# APIs, creates (or reuses) ONE API key `jarvis-maps-yt` restricted to Places, Routes and YouTube
# (no Geocoding: Routes geocodes address waypoints itself), reads its restrictions back and keeps
# Maps and YouTube off for the deploy when they are not exactly those three; keeps its string only
# in Secret Manager (`jarvis-google-api-key`, readable by jarvis-run through the per-secret grant
# loop) and mounts it as JARVIS_GOOGLE_API_KEY on both deploy paths. It sets JARVIS_MAPS_PRICING
# to india only when the billing account bills in INR (global otherwise, with a plain note), and
# adds a 1-unit budget alert that emails the billing admins. Every step is non-fatal; the key is
# never printed. Run with gcloud stubbed out.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"
SERVICES = ("places.googleapis.com", "routes.googleapis.com", "youtube.googleapis.com")
ALLOWED = ";".join(SERVICES)
KEY = "AIzaSyFAKE-not-a-real-key_0123456789abc"
BOUND = "JARVIS_GOOGLE_API_KEY=jarvis-google-api-key:latest,"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    return script[start : script.index("\n}\n", start) + 3]


def _fake_gcloud(tmp: Path, cases: str, fail: str) -> Path:
    log = tmp / "gcloud.log"
    fake = tmp / "gcloud"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        f'case "$*" in *"{fail or "@@never@@"}"*) exit 1 ;; esac\n'
        'case "$*" in\n' + cases + "esac\nexit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return log


def _run(
    script: str,
    tmp: Path,
    *,
    existing: bool,
    secret: str = "",
    fail: str = "",
    allowed: str = ALLOWED,
    put_fails: bool = False,
) -> dict[str, str]:
    """Run setup_maps_key with a fake gcloud that logs every call. `existing`: the key already
    exists; `secret`: the saved secret's value ('' = no secret); `fail`: a gcloud subcommand
    that fails; `allowed`: what the key's restrictions read back as; `put_fails`: storing the
    key in Secret Manager fails."""
    stored = tmp / "stored"
    listed = "echo projects/p/locations/global/keys/k1" if existing else "true"
    log = _fake_gcloud(
        tmp,
        f'  "services api-keys list"*) {listed} ;;\n'
        '  "services api-keys create"*) echo projects/p/locations/global/keys/k1 ;;\n'
        f'  "services api-keys describe"*) echo "{allowed}" ;;\n'
        f'  "services api-keys get-key-string"*) echo "{KEY}" ;;\n'
        f'  "secrets versions access"*) {"echo " + secret if secret else "exit 1"} ;;\n',
        fail,
    )
    prelude = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\n'
        f"secret_exists() {{ [ '{'yes' if secret else 'no'}' = yes ] || [ -s '{stored}' ]; }}\n"
        + (
            "put_secret() { return 1; }\n"
            if put_fails
            else f"put_secret() {{ printf '%s=%s' \"$1\" \"$2\" > '{stored}'; }}\n"
        )
        + 'die() { echo "DIE $*" >&2; exit 9; }\n'
        "MAPS_SECRET=''; MAPS_STATE=off; MAPS_REMOVE=()\n"
        f"MAPS_APIS='{' '.join(SERVICES)}'\n"
    )
    body = (
        prelude
        + _function(script, "maps_key_allows_only")
        + _function(script, "maps_off")
        + _function(script, "maps_key_name")
        + _function(script, "setup_maps_key")
        + 'setup_maps_key\nprintf "\\nSECRET=%s\\nSTATE=%s\\nREMOVE=%s\\n" '
        '"$MAPS_SECRET" "$MAPS_STATE" "${MAPS_REMOVE[*]:-}"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    out = done.stdout + done.stderr
    lines = dict(
        ln.split("=", 1)
        for ln in done.stdout.splitlines()
        if ln.startswith(("SECRET=", "STATE=", "REMOVE="))
    )
    return {
        "rc": str(done.returncode),
        "out": out,
        "calls": log.read_text() if log.exists() else "",
        "stored": stored.read_text() if stored.exists() else "",
        "secret": lines.get("SECRET", ""),
        "state": lines.get("STATE", ""),
        "remove": lines.get("REMOVE", ""),
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
    assert "geocoding" not in r["calls"]  # not enabled, not allowed on the key
    create = next(c for c in calls if c.startswith("services api-keys create"))
    assert "--display-name=jarvis-maps-yt" in create
    assert [t for t in create.split() if t.startswith("--api-target=")] == [
        f"--api-target=service={s}" for s in SERVICES
    ]
    assert any(c.startswith("services api-keys describe") for c in calls)  # read back
    assert r["stored"] == f"jarvis-google-api-key={KEY}"
    assert (r["secret"], r["state"], r["remove"]) == (BOUND, "on", "")
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
    assert "geocoding" not in update
    assert r["stored"] == ""  # the same string: no new secret version
    assert (r["secret"], r["state"]) == (BOUND, "on")
    assert KEY not in r["out"]


@pytest.mark.parametrize(
    "allowed",
    [
        "places.googleapis.com;routes.googleapis.com;geocoding-backend.googleapis.com;"
        "youtube.googleapis.com",  # the old key, not narrowed
        "places.googleapis.com;routes.googleapis.com",  # missing one
        "",  # no restriction at all, or it could not be read
    ],
)
def test_a_key_whose_restrictions_read_back_wrong_keeps_maps_off_for_this_deploy(
    script: str, tmp_path: Path, allowed: str
) -> None:
    r = _run(script, tmp_path, existing=True, secret=KEY, allowed=allowed)
    assert r["rc"] == "0" and "DIE" not in r["out"]
    assert (r["secret"], r["state"]) == ("", "off")
    assert r["remove"] == "--remove-secrets JARVIS_GOOGLE_API_KEY"  # unmounted on a quick re-run
    assert "Note:" in r["out"] and "Places, Routes and YouTube" in r["out"]
    assert KEY not in r["out"] and "get-key-string" not in r["calls"]


def test_the_restrictions_compare_as_a_set_whatever_the_separator(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, existing=True, secret=KEY, allowed=",".join(reversed(SERVICES)))
    assert (r["secret"], r["state"]) == (BOUND, "on")


@pytest.mark.parametrize(
    "fail",
    [
        "services enable",
        "services api-keys create",
        "services api-keys get-key-string",
        "services api-keys describe",
    ],
)
def test_any_failure_is_not_fatal_and_maps_stays_off(
    script: str, tmp_path: Path, fail: str
) -> None:
    r = _run(script, tmp_path, existing=False, fail=fail)
    assert r["rc"] == "0", r["out"]
    assert "DIE" not in r["out"]
    assert (r["secret"], r["state"], r["remove"]) == (
        "",
        "off",
        "--remove-secrets JARVIS_GOOGLE_API_KEY",
    )
    assert "Note:" in r["out"] and "Maps and YouTube are off for this deploy" in r["out"]


# ---- final review: a key is mounted only when THIS run confirmed it ------------------------


@pytest.mark.parametrize(
    "fail",
    [
        "services enable",  # the API Keys service could not be switched on
        "services api-keys get-key-string",  # the key string could not be read
        "services api-keys describe",  # the restrictions could not be read back
    ],
)
def test_a_saved_key_is_never_mounted_when_this_run_could_not_confirm_it(
    script: str, tmp_path: Path, fail: str
) -> None:
    """A secret saved by an earlier deploy is not enough: unless this run read the key's
    restrictions back as exactly the three APIs AND the stored secret is that key's string,
    the key is unmounted and the summary says Maps and YouTube are off."""
    r = _run(script, tmp_path, existing=True, secret=KEY, fail=fail)
    assert r["rc"] == "0" and "DIE" not in r["out"], r["out"]
    assert (r["secret"], r["state"], r["remove"]) == (
        "",
        "off",
        "--remove-secrets JARVIS_GOOGLE_API_KEY",
    )
    notes = [ln for ln in r["out"].splitlines() if "Note:" in ln]
    assert notes and "Maps and YouTube are off for this deploy" in notes[-1]
    assert KEY not in r["out"]


def test_an_empty_key_list_and_a_failed_create_unmount_the_saved_key(
    script: str, tmp_path: Path
) -> None:
    r = _run(script, tmp_path, existing=False, secret=KEY, fail="services api-keys create")
    assert (r["secret"], r["state"], r["remove"]) == (
        "",
        "off",
        "--remove-secrets JARVIS_GOOGLE_API_KEY",
    )
    assert "describe" not in r["calls"]  # no key to read back


def test_a_key_that_can_not_be_stored_is_not_mounted(script: str, tmp_path: Path) -> None:
    r = _run(script, tmp_path, existing=True, secret="an-older-key-string", put_fails=True)
    assert r["rc"] == "0" and "DIE" not in r["out"]
    assert (r["secret"], r["state"], r["remove"]) == (
        "",
        "off",
        "--remove-secrets JARVIS_GOOGLE_API_KEY",
    )
    assert "Secret Manager" in r["out"] and KEY not in r["out"]


def test_mounted_only_after_the_read_back_and_with_the_stored_string(
    script: str, tmp_path: Path
) -> None:
    calls = _run(script, tmp_path, existing=True, secret=KEY)["calls"].splitlines()
    describe = next(i for i, c in enumerate(calls) if c.startswith("services api-keys describe"))
    string = next(i for i, c in enumerate(calls) if c.startswith("services api-keys get-key"))
    assert describe < string  # the string is read only for a key that passed the read-back


def test_the_summary_claims_the_restriction_only_when_the_key_is_on(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    on, off = done.split('if [ "$MAPS_STATE" = on ]; then', 1)[1].split("\nelse\n", 1)
    assert "restricted to Places, Routes and YouTube" in on
    assert "restricted" not in off.split("\nfi\n", 1)[0]
    assert script.count("restricted to Places, Routes and YouTube") == 1


def test_the_step_runs_before_the_grants_and_the_deploy(script: str) -> None:
    call = script.index("\nsetup_maps_key\n")
    assert call < script.index("for secret in") < script.index("gcloud run deploy")
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert "jarvis-google-api-key" in grant_loop


def test_the_binding_reaches_both_deploy_paths(script: str) -> None:
    for ln in script.splitlines():
        if "--set-secrets" in ln or "--update-secrets" in ln:
            assert "${MAPS_SECRET}" in ln, ln
    quick = script.split('if [ "$QUICK" = yes ]; then\n  CONFIG_FLAGS=(', 1)[1].split(")", 1)[0]
    assert '"${MAPS_REMOVE[@]}"' in quick  # an unconfirmed key is unmounted on a quick re-run
    # until setup_maps_key confirms the key, the default is to unmount it
    assert (
        "MAPS_REMOVE=(--remove-secrets JARVIS_GOOGLE_API_KEY)"
        in script.split("setup_maps_key() {", 1)[0]
    )


# ---- price list (F2) ------------------------------------------------------------------------


def _pricing(script: str, tmp: Path, *, currency: str, fail: str = "") -> dict[str, str]:
    log = _fake_gcloud(
        tmp,
        '  "billing projects describe"*) echo billingAccounts/0X0X0X-111111-222222 ;;\n'
        f'  "billing accounts describe"*) echo "{currency}" ;;\n',
        fail,
    )
    body = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\nPROJECT=p\nMAPS_PRICING=global; BILLING_ACCOUNT=""\n'
        + _function(script, "maps_pricing")
        + "maps_pricing\n"
        + 'printf "\\nPRICING=%s\\nACCOUNT=%s\\n" "$MAPS_PRICING" "$BILLING_ACCOUNT"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    lines = dict(
        ln.split("=", 1) for ln in done.stdout.splitlines() if ln.startswith(("PRICING", "ACCOUNT"))
    )
    return {
        "rc": str(done.returncode),
        "out": done.stdout + done.stderr,
        "calls": log.read_text() if log.exists() else "",
        "pricing": lines.get("PRICING", ""),
        "account": lines.get("ACCOUNT", ""),
    }


def test_india_pricing_only_for_a_billing_account_that_bills_in_inr(
    script: str, tmp_path: Path
) -> None:
    r = _pricing(script, tmp_path, currency="INR")
    assert r["rc"] == "0" and r["pricing"] == "india", r["out"]
    assert r["account"] == "0X0X0X-111111-222222"
    describe = next(c for c in r["calls"].splitlines() if c.startswith("billing accounts describe"))
    assert "0X0X0X-111111-222222" in describe and "--format=value(currencyCode)" in describe


@pytest.mark.parametrize(
    ("currency", "fail"),
    [("USD", ""), ("EUR", ""), ("", ""), ("INR", "billing accounts describe")],
)
def test_otherwise_the_safe_global_price_list_with_a_plain_note(
    script: str, tmp_path: Path, currency: str, fail: str
) -> None:
    r = _pricing(script, tmp_path, currency=currency, fail=fail)
    assert r["rc"] == "0" and r["pricing"] == "global", r["out"]
    assert "Note:" in r["out"] and "global" in r["out"] and "India" in r["out"]


def test_the_price_list_reaches_the_service(script: str) -> None:
    assert "JARVIS_MAPS_PRICING=${MAPS_PRICING}" in script
    assert script.index("\nmaps_pricing\n") < script.index("INFRA_ENV=")


# ---- the budget alert (F4) ------------------------------------------------------------------


def _budget(script: str, tmp: Path, *, listed: str = "", fail: str = "") -> dict[str, str]:
    log = _fake_gcloud(tmp, f'  "billing budgets list"*) echo "{listed}" ;;\n', fail)
    body = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\nPROJECT=p\nBILLING_ACCOUNT=0X0X0X-111111-222222\n'
        + _function(script, "setup_budget_alert")
        + "setup_budget_alert\necho RC_OK\n"
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    return {
        "out": done.stdout + done.stderr,
        "calls": log.read_text() if log.exists() else "",
    }


def test_a_one_unit_budget_alert_emails_the_billing_admins_once(
    script: str, tmp_path: Path
) -> None:
    r = _budget(script, tmp_path)
    assert "RC_OK" in r["out"]
    create = next(c for c in r["calls"].splitlines() if c.startswith("billing budgets create"))
    assert "--billing-account=0X0X0X-111111-222222" in create
    assert "--budget-amount=1 " in create + " "  # the account's own currency: ₹1 in India
    assert "--filter-projects=projects/p" in create
    assert "--threshold-rule=percent=" in create
    assert "--disable-default-iam-recipients" not in create  # billing admins get the email
    assert "billingbudgets.googleapis.com" in r["calls"]


def test_an_existing_alert_is_not_made_twice(script: str, tmp_path: Path) -> None:
    r = _budget(script, tmp_path, listed="billingAccounts/x/budgets/b1")
    assert "RC_OK" in r["out"] and "billing budgets create" not in r["calls"]


@pytest.mark.parametrize("fail", ["billing budgets create", "services enable"])
def test_a_budget_failure_is_one_plain_line_and_never_fatal(
    script: str, tmp_path: Path, fail: str
) -> None:
    r = _budget(script, tmp_path, fail=fail)
    assert "RC_OK" in r["out"]
    notes = [ln for ln in r["out"].splitlines() if "Note:" in ln]
    assert len(notes) == 1 and "budget" in notes[0]


def test_the_budget_step_runs_before_the_deploy(script: str) -> None:
    assert script.index("\nsetup_budget_alert\n") < script.index("gcloud run deploy")


# ---- summary --------------------------------------------------------------------------------


def test_the_summary_is_plain_and_says_where_india_pricing_applies(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    block = done.split("MAPS + YOUTUBE", 1)[1].split("MSG", 1)[0]
    assert "India" in block and "billing account" in block
    assert "${MAPS_STOPS}" in block and "90" in block
    assert "Geocoding" not in block
    assert "$" not in block.replace("${", "") and "₹" not in block
    stops = script.split("MAPS_STOPS=", 1)[1]
    assert "31,500" in stops and "4,500" in stops


def test_script_still_parses() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


# ---- code review CR-5 / security review SEC-2 -----------------------------------------------


def test_a_failed_key_list_is_not_an_empty_one_and_never_creates_a_second_key(
    script: str, tmp_path: Path
) -> None:
    """`api-keys list` failing must not read as "no key yet": a re-run would make a duplicate
    jarvis-maps-yt. A failed list skips creating, with a plain note; Maps stays off."""
    r = _run(script, tmp_path, existing=True, secret=KEY, fail="services api-keys list")
    assert r["rc"] == "0" and "DIE" not in r["out"]
    assert "services api-keys create" not in r["calls"]
    assert (r["secret"], r["state"]) == ("", "off")
    assert r["remove"] == "--remove-secrets JARVIS_GOOGLE_API_KEY"
    assert "Note:" in r["out"] and "re-run" in r["out"].lower()


@pytest.mark.parametrize(
    "fail",
    ["services enable", "services api-keys list", "services api-keys describe"],
)
def test_a_saved_key_is_mounted_only_after_this_runs_read_back(
    script: str, tmp_path: Path, fail: str
) -> None:
    """SEC-2: an existing jarvis-google-api-key secret is mounted only when THIS run read the
    key's restrictions back as exactly the three APIs; otherwise it is unmounted and Maps and
    YouTube are off for this deploy, with a plain note (`maps_off`)."""
    r = _run(script, tmp_path, existing=True, secret=KEY, fail=fail)
    assert r["rc"] == "0" and "DIE" not in r["out"]
    assert (r["secret"], r["state"]) == ("", "off")
    assert r["remove"] == "--remove-secrets JARVIS_GOOGLE_API_KEY"
    assert "off for this deploy" in r["out"] and KEY not in r["out"]


def test_the_summary_says_maps_is_off_unless_the_key_was_confirmed(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    off = done.split('if [ "$MAPS_STATE" = on ]', 1)[1].split("fi\n", 1)[0].split("else", 1)[1]
    assert "MAPS + YOUTUBE: off" in off and "re-run" in off.lower()


def _grants(
    script: str, tmp: Path, *, fail_secret: str, maps_secret: str, web_secret: str
) -> dict[str, str]:
    """The step-5 grant loop with a fake gcloud whose grant for `fail_secret` always fails."""
    log = _fake_gcloud(
        tmp, f'  *"add-iam-policy-binding {fail_secret} "*) exit 1 ;;\n', "@@never@@"
    )
    loop = script[script.index("grant_failed() {") :]
    loop = loop[: loop.index("\ndone\n", loop.index("for secret in jarvis-google-client")) + 6]
    body = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\nRUN_SA=run@p\nsleep() {{ :; }}\n'
        "secret_exists() { true; }\n"
        'die() { echo "DIE $*" >&2; exit 9; }\n'
        + _function(script, "maps_off")
        + f"MAPS_SECRET='{maps_secret}'; MAPS_STATE=on; MAPS_REMOVE=()\n"
        f"WEB_SECRET='{web_secret}'; WEB_ENV=JARVIS_WEB_SEARCH_ENABLED=true\n"
        + loop
        + '\nprintf "\\nMAPS=%s\\nSTATE=%s\\nREMOVE=%s\\nWEB=%s\\nWEBENV=%s\\n" '
        '"$MAPS_SECRET" "$MAPS_STATE" "${MAPS_REMOVE[*]:-}" "$WEB_SECRET" "$WEB_ENV"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    lines = dict(
        ln.split("=", 1)
        for ln in done.stdout.splitlines()
        if ln.startswith(("MAPS=", "STATE=", "REMOVE=", "WEB=", "WEBENV="))
    )
    return {"rc": str(done.returncode), "out": done.stdout + done.stderr, **lines,
            "calls": log.read_text() if log.exists() else ""}  # fmt: skip


@pytest.mark.parametrize("secret", ["jarvis-google-api-key", "jarvis-tavily-key"])
def test_an_optional_secret_that_cant_be_granted_never_stops_the_deploy(
    script: str, tmp_path: Path, secret: str
) -> None:
    """CR-5 (a): an optional part never stops the deploy — a grant that fails for the Maps key
    or the Tavily key is a plain note, and that secret is not mounted."""
    r = _grants(script, tmp_path, fail_secret=secret, maps_secret=BOUND,
                web_secret="JARVIS_TAVILY_API_KEY=jarvis-tavily-key:latest,")  # fmt: skip
    assert r["rc"] == "0" and "DIE" not in r["out"], r["out"]
    assert "Note:" in r["out"] and secret in r["out"]
    if secret == "jarvis-google-api-key":
        assert (r["MAPS"], r["STATE"]) == ("", "off")
        assert r["REMOVE"] == "--remove-secrets JARVIS_GOOGLE_API_KEY"
        assert r["WEB"] != ""
    else:
        assert (r["WEB"], r["WEBENV"]) == ("", "JARVIS_WEB_SEARCH_ENABLED=false")
        assert r["MAPS"] == BOUND


def test_a_required_secret_that_cant_be_granted_still_stops_the_deploy(
    script: str, tmp_path: Path
) -> None:
    r = _grants(script, tmp_path, fail_secret="jarvis-token-key", maps_secret=BOUND, web_secret="")
    assert r["rc"] == "9" and "DIE" in r["out"] and "jarvis-token-key" in r["out"]


def test_the_web_search_off_is_unmounted_on_a_quick_re_run(script: str) -> None:
    quick = script.split('if [ "$QUICK" = yes ]; then\n  CONFIG_FLAGS=(', 1)[1].split(")", 1)[0]
    assert '"${WEB_REMOVE[@]}"' in quick


# ---- security review SEC-4: other projects on the billing account ---------------------------


def _shared(script: str, tmp: Path, *, listed: str, fail: str = "") -> dict[str, str]:
    log = _fake_gcloud(tmp, f'  "billing projects list"*) printf "{listed}" ;;\n', fail)
    body = (
        "set -euo pipefail\n"
        f'PATH="{tmp}:$PATH"\nPROJECT=p\nBILLING_ACCOUNT=0X0X0X-111111-222222\n'
        "SHARED_BILLING=no\n"
        + _function(script, "billing_shared")
        + 'billing_shared\nprintf "\\nSHARED=%s\\n" "$SHARED_BILLING"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)
    shared = next(
        (ln.split("=", 1)[1] for ln in done.stdout.splitlines() if ln.startswith("SHARED=")), ""
    )
    return {"rc": str(done.returncode), "out": done.stdout + done.stderr, "shared": shared,
            "calls": log.read_text() if log.exists() else ""}  # fmt: skip


@pytest.mark.parametrize(
    ("listed", "fail", "shared"),
    [
        ("p\\n", "", "no"),  # only this project
        ("p\\nother-project\\n", "", "yes"),
        ("", "billing projects list", "unknown"),  # can't tell: never stops the deploy
    ],
)
def test_other_projects_on_the_billing_account_are_noticed(
    script: str, tmp_path: Path, listed: str, fail: str, shared: str
) -> None:
    r = _shared(script, tmp_path, listed=listed, fail=fail)
    assert r["rc"] == "0" and r["shared"] == shared, r["out"]
    call = next(c for c in r["calls"].splitlines() if c.startswith("billing projects list"))
    assert "--billing-account=0X0X0X-111111-222222" in call


def test_the_summary_warns_when_other_projects_share_the_billing_account(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    block = done.split('if [ "$SHARED_BILLING" = yes ]', 1)[1].split("fi\n", 1)[0]
    assert "Other projects share this billing account" in block
    assert "can't see their use" in block and "budget alert" in block
    assert "$" not in block.split("MSG", 1)[1].split("MSG", 1)[0]  # never a dollar sign
    assert script.index("\nbilling_shared\n") < script.index("gcloud run deploy")


def test_the_plan_says_the_counter_is_per_deployment(script: str) -> None:
    plan = (ROOT / "docs" / "plans" / "phase2-slice12-integrations.md").read_text(encoding="utf-8")
    d2 = plan.split("**D2 ·", 1)[1].split("**D3 ·", 1)[0]
    assert "billing account" in d2 and "other projects" in d2.lower()


# ---- the budget alert: a failed list is not an empty one (CR-5 b) ---------------------------


def test_a_failed_budget_list_never_creates_a_second_alert(script: str, tmp_path: Path) -> None:
    r = _budget(script, tmp_path, fail="billing budgets list")
    assert "RC_OK" in r["out"] and "billing budgets create" not in r["calls"]
    notes = [ln for ln in r["out"].splitlines() if "Note:" in ln]
    assert len(notes) == 1 and "budget" in notes[0] and "re-run" in notes[0].lower()


def test_the_lists_tell_a_failure_from_an_empty_answer(script: str) -> None:
    """No list whose failure decides whether something is CREATED may end in `|| true`."""
    for fn in ("setup_maps_key", "setup_budget_alert"):
        body = _function(script, fn)
        for ln in body.splitlines():
            if " list " in ln and ("api-keys" in ln or "budgets" in ln):
                assert "|| true" not in ln, ln


def test_deploy_script_passes_shellcheck() -> None:
    import shutil
    import sys

    found = shutil.which("shellcheck") or str(Path(sys.executable).with_name("shellcheck"))
    if not Path(found).exists():
        pytest.skip("shellcheck not installed")
    subprocess.run([found, "-S", "warning", str(SCRIPT)], check=True)
