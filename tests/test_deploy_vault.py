# tests/test_deploy_vault.py -- R2 deploy: the vault needs no new secret, the token key is never
# overwritten, the index exemptions are non-fatal, and the summary says to keep the key.
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "cloudrun.sh"
GROUPS = (
    "vault_chunks",
    "jarvis_vault",
    "jarvis_kb_shards",
    "jarvis_belongings",
    "jarvis_belongings_history",
)


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_still_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_the_token_key_is_created_once_and_never_overwritten(script: str) -> None:
    lines = [ln for ln in script.splitlines() if "put_secret jarvis-token-key" in ln]
    assert lines == ['secret_exists jarvis-token-key || put_secret jarvis-token-key "$(rand_key)"']
    assert "versions add jarvis-token-key" not in script
    assert not re.search(
        r"gcloud secrets (delete|versions (destroy|disable))\s+\S*token-key", script
    )


def test_no_new_secret_for_r2(script: str) -> None:
    secrets = set(re.findall(r"jarvis-[a-z0-9-]+-(?:key|secret|token)\b", script))
    assert not {s for s in secrets if "vault" in s or "notes" in s or "belongings" in s}
    assert "JARVIS_VAULT" not in script  # on by default; no env var is required


def test_index_exemptions_cover_the_five_groups_and_are_non_fatal(script: str) -> None:
    loop = script[
        script.index("VAULT_INDEX_FAILED=no") : script.index("VAULT_INDEX_FAILED=no") + 700
    ]
    for g in GROUPS:
        assert g in loop
    assert "firestore indexes fields update blob" in loop
    assert "--disable-indexes" in loop and "--async" in loop
    assert "|| VAULT_INDEX_FAILED=yes" in loop  # a failure never stops the deploy
    assert "couldn't exempt vault fields from indexing (uses a little more free storage" in script


def test_the_summary_tells_him_to_keep_the_key(script: str) -> None:
    assert "VAULT: on - files encrypted in Firestore (Mumbai) with jarvis-token-key." in script
    assert "Keep that secret: without it" in script
    assert "the vault can't be opened" in script
