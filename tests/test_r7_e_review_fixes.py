# tests/test_r7_e_review_fixes.py -- R7 Part E, the two fresh-context reviews' findings, held by
# static reads of the Kotlin, the manifest, the layout and OWNER-STEPS.md (CI compiles and runs
# `core`; these hold what a JVM test cannot see). Every rule is a small function with a negative
# control that feeds it the broken shape and expects it to say so.
from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app" / "src" / "main"
SRC = APP / "java" / "io" / "github" / "shark2558" / "jarvis"
CORE = (
    ROOT
    / "android"
    / "core"
    / "src"
    / "main"
    / "kotlin"
    / "io"
    / "github"
    / "shark2558"
    / "jarvis"
    / "core"
)
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
STEPS = ROOT / "docs" / "plans" / "r7-integration" / "OWNER-STEPS.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code(text: str) -> str:
    """Kotlin without its comments."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(?:^|\s)//\s.*$", "", line) for line in text.splitlines())


SOS = read(SRC / "sos" / "SosActivity.kt")
MANIFEST = read(APP / "AndroidManifest.xml")


def sos_manifest_entry(manifest: str) -> str:
    m = re.search(r"<activity\s[^>]*?\.sos\.SosActivity[^>]*?/>", manifest, flags=re.S)
    assert m, "SosActivity is declared"
    return m.group(0)


# ---- H1: a new press always leads to a live SOS flow ----------------------------------------
def stale_screen_risk(manifest_entry: str, kotlin: str) -> bool:
    """singleTop without onNewIntent leaves a finished screen standing for the next press."""
    single_top = 'launchMode="singleTop"' in manifest_entry
    handles = re.search(r"override fun onNewIntent\(", code(kotlin)) is not None
    return single_top and not handles


def test_a_second_press_cannot_land_on_a_stale_screen() -> None:
    assert not stale_screen_risk(sos_manifest_entry(MANIFEST), SOS)


def test_control_singletop_without_onnewintent_is_caught() -> None:
    assert stale_screen_risk(sos_manifest_entry(MANIFEST), SOS.replace("onNewIntent", "onOther"))
    assert not stale_screen_risk(sos_manifest_entry(MANIFEST).replace("singleTop", "standard"), "")


def test_onnewintent_uses_the_core_rule_and_starts_a_fresh_press() -> None:
    body = code(SOS)
    start = body.index("override fun onNewIntent(")
    chunk = body[start : start + 700]
    assert "SosPress.startsFresh(machine.state, kind, next)" in chunk
    assert "begin(next, newPressId())" in chunk


def test_core_has_the_new_press_rule_and_its_cases() -> None:
    machine = read(CORE / "SosMachine.kt")
    assert "object SosPress" in machine and "fun startsFresh(" in machine
    tests = read(
        ROOT / "android/core/src/test/kotlin/io/github/shark2558/jarvis/core/SosMachineTest.kt"
    )
    assert "SosPress.startsFresh" in tests and "never sends again" in tests


# ---- code M1: one press is at most one send, across a recreation ---------------------------
CHANGES = {
    "orientation", "screenSize", "screenLayout", "smallestScreenSize", "keyboardHidden",
    "keyboard", "navigation", "uiMode", "density", "fontScale", "locale", "layoutDirection",
    "colorMode",
}  # fmt: skip


def config_changes(entry: str) -> set[str]:
    m = re.search(r'android:configChanges="([^"]*)"', entry)
    return set(m.group(1).split("|")) if m else set()


def test_the_sos_screen_handles_every_change_that_would_recreate_it() -> None:
    assert CHANGES <= config_changes(sos_manifest_entry(MANIFEST))


def test_control_a_missing_uimode_is_caught() -> None:
    narrow = sos_manifest_entry(MANIFEST).replace("|uiMode", "")
    assert not CHANGES <= config_changes(narrow)


def test_the_screen_saves_and_restores_the_press_and_sends_through_the_ledger() -> None:
    body = code(SOS)
    assert "override fun onSaveInstanceState(" in body
    assert "SosMachine.restore(" in body and "machine.saved()" in body
    assert "PressLedger()" in body and "ledger" in body
    assert "setLastSosPress(" in body  # kept across a restart of the process
    machine = code(read(CORE / "SosMachine.kt"))
    assert "if (ledger.claim(pressId)) send(kind)" in machine


def test_control_a_send_without_the_claim_is_caught() -> None:
    machine = code(read(CORE / "SosMachine.kt")).replace(
        "if (ledger.claim(pressId)) send(kind)", "send(kind)"
    )
    assert "if (ledger.claim(pressId)) send(kind)" not in machine


def test_an_answer_of_an_older_press_is_ignored() -> None:
    assert "if (press != pressId) return" in code(SOS)


# ---- code M2: 112 and the text message are always on screen ---------------------------------
def inside_after(layout: str, view_id: str) -> bool:
    root = ElementTree.fromstring(layout)
    key = ANDROID_NS + "id"
    for node in root.iter():
        if node.get(key) == "@+id/sos_after":
            return any(n.get(key) == f"@+id/{view_id}" for n in node.iter())
    raise AssertionError("no sos_after")


LAYOUT = read(APP / "res" / "layout" / "activity_sos.xml")


def test_112_the_text_and_the_first_call_are_not_hidden_behind_the_after_block() -> None:
    for view in ("sos_call_112", "sos_text", "sos_call_first"):
        assert not inside_after(LAYOUT, view), view
    assert 'android:id="@+id/sos_call_112"' in LAYOUT


def test_control_a_button_moved_back_into_the_hidden_block_is_caught() -> None:
    moved = LAYOUT.replace(
        '<LinearLayout\n                android:id="@+id/sos_after"',
        '<LinearLayout\n                android:id="@+id/sos_after"',
    ).replace(
        '                <Button\n                    android:id="@+id/sos_safe"',
        '                <Button\n                    android:id="@+id/sos_call_112"\n'
        '                    android:layout_width="match_parent"\n'
        '                    android:layout_height="wrap_content" />\n'
        '                <Button\n                    android:id="@+id/sos_safe"',
    )
    assert inside_after(moved, "sos_call_112")


def test_a_refused_unlock_says_so_in_plain_words() -> None:
    body = code(SOS)
    assert "override fun onDismissCancelled()" in body and "override fun onDismissError()" in body
    assert body.count("R.string.sos_unlock_needed") >= 2


def test_a_test_hides_only_the_text_message_and_im_safe_is_real_only() -> None:
    body = code(SOS)
    assert "if (kind != SosKind.REAL) return" in body  # confirmSafe: a test never sends "safe"
    assert "after.visibility = if (kind == SosKind.REAL)" in body
    assert "R.id.sos_text).visibility = if (kind == SosKind.TEST) View.GONE" in body


def test_the_screen_stays_on_during_the_countdown_and_leaving_cancels() -> None:
    body = code(SOS)
    assert "FLAG_KEEP_SCREEN_ON" in body and "clearFlags" in body
    assert "if (!isChangingConfigurations)" in body and "machine.cancel(" in body


# ---- code M3, security L2/L3, code L3: the door's answers ----------------------------------
def test_the_door_answers_have_their_own_plain_sentences_in_core() -> None:
    replies = code(read(CORE / "Replies.kt"))
    for status in ("401", "403", "404", "413", "429"):
        assert f"status == {status}" in replies, status
    assert "status >= 500" in replies and "MAX_SKEW_SECONDS = 120L" in replies
    assert "clock" in read(CORE / "Replies.kt").lower()
    assert "This phone needs linking again, Sir." in read(CORE / "Replies.kt")


def test_the_client_reads_the_date_header_and_counts_refusals() -> None:
    client = code(read(SRC / "link" / "DoorClient.kt"))
    assert 'getHeaderFieldDate("Date"' in client and "Replies.skewSeconds(" in client
    assert "Replies.strikes(" in client and "setNeedsRelink(" in client


def test_workers_retry_only_what_waiting_can_cure_and_stop_when_unlinked() -> None:
    health = code(read(SRC / "health" / "HealthSyncWorker.kt"))
    folder = code(read(SRC / "inbox" / "FolderWorker.kt"))
    assert "HealthSync.Outcome.FAILED -> Result.retry()" in health
    assert "canSend()" in health and "canSend()" in folder
    assert "Replies.worthRetry(wait)" in folder
    assert (
        "catch (e: InterruptedException)" in health and "catch (e: InterruptedException)" in folder
    )
    sync = code(read(SRC / "health" / "HealthSync.kt"))
    assert "Replies.worthRetry(answer.status)" in sync


def test_the_folder_marks_a_file_only_on_success_or_a_refusal_for_good() -> None:
    sync = code(read(SRC / "inbox" / "FolderSync.kt"))
    assert "Inbox.fate(answer.status)" in sync
    assert "InboxFate.LATER" in sync and "break" in sync
    assert sync.count("keys = keys.adding(key)") == 3  # not-eligible, sent, refused for good
    assert "answer.status >= 500" not in sync


def test_the_phone_says_it_needs_linking_again_and_the_jobs_stop() -> None:
    setup = code(read(SRC / "link" / "SetupActivity.kt"))
    assert "R.string.setup_relink" in setup and "state.canSend()" in setup
    strings = read(APP / "res" / "values" / "strings.xml")
    assert "This phone needs linking again, Sir." in strings
    state = code(read(SRC / "link" / "AppState.kt"))
    assert "fun needsRelink()" in state and "fun canSend()" in state


def test_the_first_sync_keeps_its_30_days_until_something_is_sent() -> None:
    sync = code(read(SRC / "health" / "HealthSync.kt"))
    assert sync.count("setLastHealthSync(") == 1
    assert sync.index("setLastHealthSync(") > sync.index("answer.refusal")


def test_a_pasted_code_may_carry_any_white_space() -> None:
    assert "!it.isWhitespace()" in code(read(SRC / "link" / "SetupActivity.kt"))


# ---- security L6: the sealed contacts go when the server has none, or the link goes --------
def test_the_sealed_contacts_are_cleared_without_an_sos_part_and_on_forgetting() -> None:
    hello = code(read(SRC / "link" / "Hello.kt"))
    assert "ContactsVault.clear(context)" in hello and 'SosBook("", emptyList())' in hello
    state = code(read(SRC / "link" / "AppState.kt"))
    forget = state[state.index("fun forgetLink()") :][:300]
    assert "ContactsVault.clear(appContext)" in forget
    assert "fun clear(" in code(read(SRC / "sos" / "ContactsVault.kt"))


# ---- code L2: the comment on isPhone is true --------------------------------------------------
def test_the_day_builder_comment_does_not_claim_the_app_passes_isphone() -> None:
    text = read(CORE / "DayBuilder.kt")
    assert "The app passes `isPhone`" not in text
    assert "DayBuilder(zone)" in read(SRC / "health" / "HealthSync.kt")


# ---- code L6: OWNER-STEPS.md ------------------------------------------------------------------
def section_letters(text: str) -> list[str]:
    return re.findall(r"^## ([A-Z]) · ", text, flags=re.M)


def test_owner_steps_sections_run_a_b_c_without_a_gap() -> None:
    letters = section_letters(read(STEPS))
    assert letters == [chr(ord("A") + i) for i in range(len(letters))], letters


def test_control_a_gap_in_the_lettering_is_caught() -> None:
    letters = section_letters("## A · x\n## C · y\n")
    assert letters != ["A", "B"]


def test_owner_steps_answer_the_review() -> None:
    text = read(STEPS)
    assert "**A2** " in text or "step A2" in text  # App priority is A2, as the plan says
    assert re.search(r"A2\.? .*App priority|App priority.*A2", text, flags=re.S)
    assert "new laptop" in text and "new debug key" in text
    assert "Install unknown apps" in text
    assert "OnePlus" in text and "not checked" in text
    flat = " ".join(text.split())
    assert "Test SOS" in flat and "never opens the text message app" in flat
    assert "unverified" in text.lower()


# ---- the coordinator's press_id: the one optional field the SOS door accepts ----------------
def test_the_sos_body_adds_press_id_and_no_other_field() -> None:
    payloads = code(read(CORE / "Payloads.kt"))
    sos = payloads[payloads.index("fun sos(") :]
    assert 'fields.add("press_id" to pressId)' in sos
    assert sos.count("fields.add(") == 5  # v, kind, at, location, press_id
    assert "[A-Za-z0-9_-]{16,64}" in payloads
    assert "press" in code(SOS) and ", if (k == SosKind.SAFE) null else press)" in code(SOS)


def test_control_a_sixth_sos_field_is_caught() -> None:
    sos = code(read(CORE / "Payloads.kt"))
    sos = sos[sos.index("fun sos(") :] + ' fields.add("extra" to 1)'
    assert sos.count("fields.add(") != 5
