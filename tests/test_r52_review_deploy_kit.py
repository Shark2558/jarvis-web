# tests/test_r52_review_deploy_kit.py -- R5.2 combined review (the Workshop's notes): the laptop
# speech kit is an optional part of `deploy/cloudrun.sh`, and an optional part never stops the
# deploy (I1-NOTES section 2). A bad kit address, a short key or a key Secret Manager would not
# store used to `die` halfway through the run; each now says why in plain words, leaves the kit
# off for this deploy (voice uses Google, then the browser) and lets the deploy go on. Bash runs
# the script's own functions with `gcloud`'s parts stubbed; no value reaches the repository.
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "cloudrun.sh"
URL = "https://my-laptop.tail1234.ts.net:10000"
KEY = "k" * 43
OFF = "JARVIS_LOCAL_SPEECH_ENABLED=false"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")


def _function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    return script[start : script.index("\n}\n", start) + 3]


def _answer(
    stdin: str, *, stored: bool = False, store_fails: bool = False
) -> subprocess.CompletedProcess[str]:
    script = SCRIPT.read_text(encoding="utf-8")
    body = (
        "set -euo pipefail\n"
        "die() { printf 'DIED: %s\\n' \"$*\" >&2; exit 1; }\n"
        f"secret_exists() {{ {'return 0' if stored else 'return 1'}; }}\n"
        f'put_secret() {{ echo "stored $1" >&2; {"return 1" if store_fails else "return 0"}; }}\n'
        'QUICK=no; ASK_SPEECH=no; SVC_JSON=""\n'
        'LS_SECRET=""; LS_ENV="JARVIS_LOCAL_SPEECH_ENABLED=false"; LS_REMOVE=()\n'
        + _function(script, "ls_url_ok")
        + _function(script, "ls_unmount")
        + _function(script, "ls_skip")
        + _function(script, "local_speech_answer")
        + 'local_speech_answer\nprintf "%s|%s|%s\\n" "$LS_ENV" "$LS_SECRET" "${LS_REMOVE[*]}"\n'
        + "echo DEPLOY-GOES-ON\n"
    )
    return subprocess.run(
        ["bash", "-c", body], input=stdin, capture_output=True, text=True, check=False, timeout=30
    )


@pytest.mark.parametrize(
    "address",
    [
        "http://my-laptop.tail1234.ts.net:10000",
        "https://evil.example.com:10000",
        "https://my-laptop.tail1234.ts.net:1234",
    ],
)
def test_review_a_bad_kit_address_warns_and_skips_the_kit(address: str) -> None:
    done = _answer(f"{address}\n{KEY}\n")
    assert done.returncode == 0, done.stderr
    assert "DIED" not in done.stderr and "DEPLOY-GOES-ON" in done.stdout
    assert f"{OFF}||" in done.stdout  # off, no secret mounted
    assert "stays off" in done.stdout and "stored" not in done.stderr


def test_review_a_short_key_warns_skips_the_kit_and_stores_nothing() -> None:
    done = _answer(f"{URL}\n{'k' * 31}\n")
    assert done.returncode == 0, done.stderr
    assert "DIED" not in done.stderr and "DEPLOY-GOES-ON" in done.stdout
    assert f"{OFF}||" in done.stdout and "stored" not in done.stderr
    assert "32 characters" in done.stdout and "stays off" in done.stdout
    assert "k" * 31 not in done.stdout + done.stderr  # never echoed


def test_review_a_key_secret_manager_refuses_warns_and_skips_the_kit() -> None:
    done = _answer(f"{URL}\n{KEY}\n", store_fails=True)
    assert done.returncode == 0, done.stderr
    assert "DIED" not in done.stderr and "DEPLOY-GOES-ON" in done.stdout
    assert f"{OFF}||" in done.stdout and "stays off" in done.stdout


def test_review_a_good_address_and_key_still_turn_the_kit_on() -> None:
    done = _answer(f"{URL}/\n{KEY}\n")
    assert done.returncode == 0, done.stderr
    assert (
        f"JARVIS_LOCAL_SPEECH_ENABLED=true,JARVIS_LOCAL_SPEECH_URL={URL}|"
        "JARVIS_LOCAL_SPEECH_KEY=jarvis-local-speech-key:latest,|" in done.stdout
    )
    assert "stored jarvis-local-speech-key" in done.stderr and KEY not in done.stdout


def test_review_nothing_in_the_kits_step_can_stop_the_deploy() -> None:
    block = _function(SCRIPT.read_text(encoding="utf-8"), "local_speech_answer")
    assert "die " not in block and "exit" not in block
