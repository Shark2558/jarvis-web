# tests/test_r18_review_deploy_speech.py -- R18 combined review (the ADD writer's item 2): the
# calls' optional speech keys (Azure's free tier F0, Sarvam, Bhashini) had no deploy step.
# `cloudrun.sh` mounts each from Secret Manager only when its secret exists (the owner stores it
# himself: deploy/calldesk/README.txt, "On the server"), in both deploy paths; the grant loop lets
# JARVIS's account read it (a failed grant leaves that key out, never fatal); a quick re-run
# unmounts one whose secret is gone. No value is ever in the repository.
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"
KEYS = {
    "JARVIS_AZURE_SPEECH_KEY": "jarvis-azure-speech-key",
    "JARVIS_SARVAM_API_KEY": "jarvis-sarvam-key",
    "JARVIS_BHASHINI_API_KEY": "jarvis-bhashini-key",
}


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(script: str, name: str) -> str:
    start = script.index(f"{name}() {{")
    return script[start : script.index("\n}\n", start) + 3]


def _keys(script: str) -> str:
    return next(ln for ln in script.splitlines() if ln.startswith("SPEECH_KEYS=")) + "\n"


def test_review_the_keys_reach_both_deploy_paths_and_the_grant_loop(script: str) -> None:
    assert "\nspeech_keys\n" in script
    assert script.index("\nspeech_keys\n") < script.index("gcloud run deploy")
    lines = [ln for ln in script.splitlines() if "--set-secrets" in ln or "--update-secrets" in ln]
    assert len(lines) == 2 and all("${SPEECH_SECRET}" in ln for ln in lines)
    assert '"${SPEECH_REMOVE[@]}"' in script
    grant_loop = script.split("for secret in", 1)[1].split("; do", 1)[0]
    assert all(name in grant_loop for name in KEYS.values())


def test_review_a_failed_grant_leaves_the_key_out_and_is_not_fatal(script: str) -> None:
    block = _function(script, "grant_failed").split("jarvis-azure-speech-key", 1)[1].split(";;")[0]
    assert "speech_unmount" in block and "die" not in block


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
@pytest.mark.parametrize(
    ("stored", "live", "mounted", "removed"),
    [
        ((), "", "", ""),
        (("jarvis-sarvam-key",), "", "JARVIS_SARVAM_API_KEY=jarvis-sarvam-key:latest,", ""),
        (
            ("jarvis-azure-speech-key", "jarvis-bhashini-key"),
            '{"JARVIS_SARVAM_API_KEY": 1}',
            "JARVIS_AZURE_SPEECH_KEY=jarvis-azure-speech-key:latest,"
            "JARVIS_BHASHINI_API_KEY=jarvis-bhashini-key:latest,",
            "--remove-secrets JARVIS_SARVAM_API_KEY",
        ),
    ],
)
def test_review_only_a_stored_key_is_mounted(
    script: str, stored: tuple[str, ...], live: str, mounted: str, removed: str
) -> None:
    exists = " ".join(stored)
    body = (
        f'secret_exists() {{ case " {exists} " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }}\n'
        f"SVC_JSON='{live}'\n"
        + _keys(script)
        + _function(script, "speech_keys")
        + _function(script, "speech_unmount")
        + 'speech_keys\nprintf "%s|%s" "$SPEECH_SECRET" "${SPEECH_REMOVE[*]}"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=True)
    got_mounted, got_removed = done.stdout.split("|", 1)
    assert (got_mounted, got_removed) == (mounted, removed)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_review_a_key_whose_grant_failed_is_left_out(script: str) -> None:
    body = (
        'secret_exists() { return 0; }\nSVC_JSON=""\n'
        + _keys(script)
        + _function(script, "speech_keys")
        + _function(script, "speech_unmount")
        + 'speech_keys\nspeech_unmount jarvis-sarvam-key\nprintf "%s" "$SPEECH_SECRET"\n'
    )
    done = subprocess.run(["bash", "-c", body], capture_output=True, text=True, check=True)
    assert "SARVAM" not in done.stdout and "AZURE" in done.stdout and "BHASHINI" in done.stdout


def test_review_no_speech_key_value_is_in_the_repository() -> None:
    for rel in ("deploy/cloudrun.sh", "deploy/calldesk/README.txt"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "JARVIS_SARVAM_API_KEY=" not in text.replace("JARVIS_SARVAM_API_KEY=jarvis-", "")
