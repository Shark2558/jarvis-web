# src/jarvis/backup/texts.py
"""Part A's fixed alert texts (docs/plans/r14-hardening.md D4, D5): `backup_problem` by cause,
`backup_ok` for a passed drill, and a failed drill's reason in fixed words. No name, no amount,
no vendor text; each at most 300 characters (a test). Sent only by `status.Teller`.
"""

from __future__ import annotations

from collections.abc import Mapping

TEXTS: Mapping[str, str] = {
    "stale": (
        "Backups: Google has made no new copy of your data for longer than expected. JARVIS "
        "checks again tomorrow; if it stays, send the Backups line in Vitals to the Workshop."
    ),
    "no_schedule": (
        "Backups: the daily backup schedule, or JARVIS's access to it, is gone, so no new copies "
        "are made. Run bash deploy/backup_setup.sh again in Cloud Shell."
    ),
    "key_changed": (
        "Backups: JARVIS's encryption key changed, so copies made before the change may not open "
        "with it. JARVIS says so each day until a restore drill passes; send this to the Workshop."
    ),
    "copy_left": (
        "Restore drill: its throw-away test copy could not be deleted, and Google charges for it "
        "while it stays. Send this to the Workshop."
    ),
    "no_access": (
        "Restore drill: JARVIS has lost its access to the drill's throw-away copy, so it can't "
        "look for one or delete it. Run bash deploy/backup_setup.sh again in Cloud Shell."
    ),
    "drill_ok": (
        "Restore drill passed: the newest backup opened in a throw-away copy, everything was "
        "there, your locked documents opened, and the copy is deleted."
    ),
}
FAILED_TEXT = (
    "Restore drill failed: {why}. Your live data was not touched and JARVIS deletes the test "
    'copy. Say "test my backup" to try again; if it fails twice, send this to the Workshop.'
)
REASON_WORDS: Mapping[str, str] = {
    "count_mismatch": "the copy's document count did not match the backup",
    "canary_missing": "the daily check mark was missing from the copy",
    "canary_mismatch": "the daily check mark in the copy did not match",
    "key": "today's key could not open the copy",
    "vault_missing": "your vault was missing from the copy",
    "vault_mismatch": "a vault item in the copy differed",
    "vault_file": "a locked document in the copy did not open",
    "live_unreadable": "your live vault could not be read to compare",
    "sample_mismatch": "a document in the copy differed",
    "nothing_compared": "nothing could be compared",
    "restore": "Google could not make the copy",
    "over_cap": "the copy would cost more than the drill's limit",
    "stuck": "it took more than three days",
    "no_key": "this server has no encryption key",
    "no_access": (
        "JARVIS has no permission to run it (run bash deploy/backup_setup.sh again in Cloud Shell)"
    ),
    "no_backup": "Google had no finished backup to test for two days",
    "interrupted": "it was cut off while Google made the copy",
    "unknown": "an unexpected error",
}


__all__ = ["FAILED_TEXT", "REASON_WORDS", "TEXTS"]
