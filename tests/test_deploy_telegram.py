# tests/test_deploy_telegram.py -- R1 deploy: deploy/cloudrun.sh asks ONLY the Telegram question,
# and only when there is no saved answer (Enter = skip, remembered as JARVIS_TELEGRAM=off); the
# bot token
# lives in Secret Manager (jarvis-telegram-bot-token) next to a webhook secret made once
# (jarvis-telegram-webhook-secret); both are mounted and granted; a failed grant turns Telegram off
# for this deploy; the webhook is registered by a NON-FATAL step that never puts the token on a
# command line or in the output.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"
TOKEN = "123456:AAH-bot-token-value"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    return script[start : script.index("\n}\n", start) + 3]


def _answer(
    script: str,
    tmp: Path,
    *,
    quick: str,
    secrets: tuple[str, ...] = (),
    svc_json: str = "",
    ask: str = "no",
    typed: str = "",
) -> dict[str, str]:
    stored = tmp / "stored"
    have = " ".join(secrets)
    prelude = (
        "set -euo pipefail\n"
        f"QUICK={quick} ASK_TG={ask}\n"
        + (f"SVC_JSON='{svc_json}'\n" if svc_json else "")
        + f"secret_exists() {{ case ' {have} ' in *\" $1 \"*) return 0;; esac; return 1; }}\n"
        f"put_secret() {{ printf '%s=%s\\n' \"$1\" \"$2\" >> '{stored}'; }}\n"
        "rand() { echo RANDOMSECRET0123456789; }\n"
        'die() { echo "DIE $*" >&2; exit 9; }\n'
        "TG_SECRET=''; TG_ENV='JARVIS_TELEGRAM=off'; TG_REMOVE=()\n"
    )
    body = (
        prelude + _function(script, "telegram_answer") + "telegram_answer\n"
        'printf "\\nSECRET=%s\\nENV=%s\\n" "$TG_SECRET" "$TG_ENV"\n'
    )
    done = subprocess.run(
        ["bash", "-c", body], input=typed, capture_output=True, text=True, check=True
    )
    out = done.stdout + done.stderr
    lines = dict(ln.split("=", 1) for ln in done.stdout.splitlines() if ln[:4] in ("SECR", "ENV="))
    return {
        "secret": lines.get("SECRET", ""),
        "env": lines.get("ENV", ""),
        "asked": str("BotFather" in out),
        "stored": stored.read_text() if stored.exists() else "",
        "out": out,
    }


BOUND = (
    "JARVIS_TELEGRAM_BOT_TOKEN=jarvis-telegram-bot-token:latest,"
    "JARVIS_TELEGRAM_WEBHOOK_SECRET=jarvis-telegram-webhook-secret:latest,"
)
ON, OFF = "JARVIS_TELEGRAM=on", "JARVIS_TELEGRAM=off"
BOTH = ("jarvis-telegram-bot-token", "jarvis-telegram-webhook-secret")


def test_quick_rerun_with_a_saved_token_asks_nothing_and_binds_both(
    script: str, tmp_path: Path
) -> None:
    r = _answer(script, tmp_path, quick="yes", secrets=BOTH)
    assert (r["secret"], r["env"], r["asked"], r["stored"]) == (BOUND, ON, "False", "")


def test_quick_rerun_after_a_recorded_skip_asks_nothing(script: str, tmp_path: Path) -> None:
    svc = '{"env": [{"name": "JARVIS_TELEGRAM", "value": "off"}]}'
    r = _answer(script, tmp_path, quick="yes", svc_json=svc)
    assert (r["secret"], r["env"], r["asked"]) == ("", OFF, "False")


def test_quick_rerun_without_an_answer_asks_once_and_enter_skips(
    script: str, tmp_path: Path
) -> None:
    r = _answer(script, tmp_path, quick="yes", svc_json='{"env": []}', typed="\n")
    assert (r["secret"], r["env"], r["asked"], r["stored"]) == ("", OFF, "True", "")


def test_a_pasted_token_is_stored_and_a_webhook_secret_made_once(
    script: str, tmp_path: Path
) -> None:
    r = _answer(script, tmp_path, quick="yes", ask="yes", typed=TOKEN + "\n")
    assert f"jarvis-telegram-bot-token={TOKEN}" in r["stored"]
    assert "jarvis-telegram-webhook-secret=RANDOMSECRET0123456789" in r["stored"]
    assert (r["secret"], r["env"], r["asked"]) == (BOUND, ON, "True")
    assert TOKEN not in r["out"]  # never echoed


def test_an_existing_webhook_secret_is_not_rotated(script: str, tmp_path: Path) -> None:
    r = _answer(
        script, tmp_path, quick="yes", ask="yes", secrets=("jarvis-telegram-webhook-secret",),
        typed=TOKEN + "\n",
    )  # fmt: skip
    assert "webhook-secret" not in r["stored"] and r["env"] == ON


def test_full_setup_asks_and_enter_keeps_a_saved_token(script: str, tmp_path: Path) -> None:
    r = _answer(script, tmp_path, quick="no", secrets=BOTH, ask="yes", typed="\n")
    assert (r["secret"], r["env"], r["asked"], r["stored"]) == (BOUND, ON, "True", "")
    r = _answer(script, tmp_path, quick="no", secrets=BOTH, ask="yes", typed="skip\n")
    assert (r["secret"], r["env"]) == ("", OFF)


def _top_level_depth_at(script: str, needle: str) -> int:
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
    call = script.index("\ntelegram_answer\n")
    assert script.index("QUICK=no") < call < script.index("gcloud run deploy")
    assert _top_level_depth_at(script, "telegram_answer") == 0


def test_the_flag_exists_and_is_documented(script: str) -> None:
    assert "--telegram) ASK_TG=yes" in script
    assert "[--telegram]" in script


def test_the_bindings_reach_both_deploy_paths_and_the_grant_loop(script: str) -> None:
    assert 'INFRA_ENV="${INFRA_ENV},${TG_ENV}"' in script
    for ln in script.splitlines():
        if "--set-secrets" in ln or "--update-secrets" in ln:
            assert "${TG_SECRET}" in ln, ln
    assert '"${TG_REMOVE[@]}"' in script
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert (
        "jarvis-telegram-bot-token" in grant_loop and "jarvis-telegram-webhook-secret" in grant_loop
    )


def test_a_failed_grant_turns_telegram_off_and_is_not_fatal(script: str) -> None:
    grant = _function(script, "grant_failed")
    block = grant.split("jarvis-telegram-bot-token", 1)[1].split(";;", 1)[0]
    assert 'TG_ENV="JARVIS_TELEGRAM=off"' in block and "--remove-secrets" in block
    assert "die" not in block


# ---- the webhook step -------------------------------------------------------------------------


def _webhook(
    script: str, tmp: Path, *, env: str = "JARVIS_TELEGRAM=on", reply: str, fail: bool = False
) -> subprocess.CompletedProcess[str]:
    log = tmp / "curl.log"
    cfg = tmp / "curl.cfg"
    body = (
        "set -euo pipefail\n"
        f"TG_ENV='{env}'; BASE_URL='https://jarvis-1.asia-south1.run.app'\n"
        'gcloud() { case "$*" in *bot-token*) printf "%s" "' + TOKEN + '";; '
        '*) printf "%s" "HOOKSECRET";; esac; }\n'
        f"curl() {{ printf '%s\\n' \"$*\" >> '{log}'; cat >> '{cfg}'; "
        + ("return 22; " if fail else f"printf '%s' '{reply}'; ")
        + "}\n"
        + _function(script, "telegram_webhook")
        + "if telegram_webhook; then echo RESULT=ok; else echo RESULT=failed; fi\n"
        'echo "TOKENVAR=${tok-unset}"\n'
    )
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=False)


def test_the_webhook_is_registered_and_the_token_stays_off_the_command_line(
    script: str, tmp_path: Path
) -> None:
    r = _webhook(script, tmp_path, reply='{"ok":true,"result":{"username":"my_bot"}}')
    assert "RESULT=ok" in r.stdout
    assert "TELEGRAM: ready (@my_bot)" in r.stdout and "Integrations" in r.stdout
    argv = (tmp_path / "curl.log").read_text()
    assert TOKEN not in argv and "HOOKSECRET" not in argv  # only on stdin
    assert "--config -" in argv and "--max-time 20" in argv
    cfg = (tmp_path / "curl.cfg").read_text()
    assert f"bot{TOKEN}/setWebhook" in cfg and f"bot{TOKEN}/getMe" in cfg
    for needle in ("telegram/webhook", "HOOKSECRET", "allowed_updates", "message", "callback_query",
                   "max_connections", "drop_pending_updates"):  # fmt: skip
        assert needle in cfg
    assert TOKEN not in r.stdout + r.stderr and "HOOKSECRET" not in r.stdout + r.stderr
    assert "TOKENVAR=unset" in r.stdout  # unset afterwards


def test_a_failed_registration_is_a_plain_note_not_an_error(script: str, tmp_path: Path) -> None:
    r = _webhook(script, tmp_path, reply="", fail=True)
    assert r.returncode == 0
    assert "couldn't register the webhook; re-run this script" in r.stdout
    assert TOKEN not in r.stdout + r.stderr


def test_not_ok_answer_is_also_a_plain_note(script: str, tmp_path: Path) -> None:
    r = _webhook(script, tmp_path, reply='{"ok":false,"description":"Unauthorized"}')
    assert "couldn't register the webhook" in r.stdout and "Unauthorized" not in r.stdout


def test_nothing_happens_when_telegram_is_off(script: str, tmp_path: Path) -> None:
    r = _webhook(script, tmp_path, env="JARVIS_TELEGRAM=off", reply="{}")
    assert not (tmp_path / "curl.log").exists() and "RESULT=ok" in r.stdout


def test_the_step_never_traces_and_runs_after_the_deploy(script: str) -> None:
    fn = _function(script, "telegram_webhook")
    assert "set +x" in fn and "unset" in fn and 'echo "$tok"' not in fn
    call = script.index("\nif telegram_webhook")
    assert script.index("gcloud run deploy") < call < script.index('say "DONE')


def test_the_summary_says_whether_telegram_is_on(script: str) -> None:
    done = script.split('say "DONE', 1)[1]
    assert "TELEGRAM" in done and "jarvis-telegram-bot-token" in done


def test_script_still_parses() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
