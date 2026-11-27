# tests/test_r18_d_android.py -- R18 builder D: the phone app's calls part, read from its sources in
# the Python suite (this workspace cannot build Android; CI's android workflow builds the app and
# runs core's JVM tests against tests/fixtures/r18). The rules a JVM test cannot see: every new
# part is the app's own; the caller's number is read only with READ_CALL_LOG and that permission
# says why; a dial goes only through TelecomManager.placeCall after core's checks; JARVIS ends or
# moves only its own call; the Calls launcher opens one fixed address; the doorbell is handled
# before anything else in the notification service; the version moved on. Each rule has a
# negative control that must make it fail.
from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app" / "src" / "main"
SRC = APP / "java" / "io" / "github" / "shark2558" / "jarvis"
CALLS = SRC / "calls"
MANIFEST = APP / "AndroidManifest.xml"
STRINGS = APP / "res" / "values" / "strings.xml"
A = "{http://schemas.android.com/apk/res/android}"
PKG = "io.github.shark2558.jarvis"
NEW_PARTS = {
    ".calls.CallsSetupActivity",
    ".calls.CallTapActivity",
    ".calls.CallsLauncherActivity",
    ".calls.CallDecisionReceiver",
    ".calls.CallStateReceiver",
}
CALL_PERMISSIONS = {
    "android.permission.CALL_PHONE",
    "android.permission.ANSWER_PHONE_CALLS",
    "android.permission.READ_PHONE_STATE",
    "android.permission.READ_CALL_LOG",
}


def _src(name: str) -> str:
    return (CALLS / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The text without its comments."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(?:^|\s)//\s.*$", "", line) for line in text.splitlines())


_NEXT = re.compile(r"\n\s*\n|\n\s*(?:override |private |fun |companion |\})")


def _body(text: str, signature: str) -> str:
    """The body of the function whose declaration starts with `signature` (as R7's source tests:
    an expression body up to the next declaration, or a block body up to its matching brace)."""
    start = text.index(signature)
    rest = text[start + len(signature) :]
    eq, brace = rest.find("="), rest.find("{")
    if eq != -1 and (brace == -1 or eq < brace):
        return _NEXT.split(rest[eq + 1 :], maxsplit=1)[0]
    depth, i = 0, brace
    while True:
        depth += {"{": 1, "}": -1}.get(rest[i], 0)
        if depth == 0:
            return rest[brace + 1 : i]
        i += 1


# ---- the manifest ------------------------------------------------------------------------------
def manifest_problems(text: str) -> list[str]:
    out = []
    root = ElementTree.fromstring(text)
    asked = {p.get(A + "name", "") for p in root.iter("uses-permission")}
    for perm in sorted(CALL_PERMISSIONS - asked):
        out.append(f"a call permission is missing: {perm}")
    for perm in (
        "android.permission.READ_CONTACTS",
        "android.permission.FOREGROUND_SERVICE_PHONE_CALL",
    ):
        if perm in asked:
            out.append(f"calls must not ask for {perm}")
    feature = [
        f for f in root.iter("uses-feature") if f.get(A + "name") == "android.hardware.telephony"
    ]
    if not feature or feature[0].get(A + "required") != "false":
        out.append("telephony must be optional (a phone without it still installs JARVIS)")
    app = root.find("application")
    assert app is not None
    parts = {el.get(A + "name", ""): el for el in app}
    for name in sorted(NEW_PARTS):
        el = parts.get(name)
        if el is None:
            out.append(f"missing: {name}")
        elif el.get(A + "exported") != "false":
            out.append(f"{name} must not be reachable from other apps")
    state = parts.get(".calls.CallStateReceiver")
    if state is not None:
        actions = {a.get(A + "name", "") for a in state.iter("action")}
        if actions != {"android.intent.action.PHONE_STATE"}:
            out.append(f"the call-state receiver hears only PHONE_STATE, not {sorted(actions)}")
    launcher = parts.get(".calls.CallsLauncherActivity")
    if launcher is not None:
        urls = [m.get(A + "value") for m in launcher.iter("meta-data")]
        if "https://${jarvisHost}/?source=app&open=calls" not in urls:
            out.append("the Calls launcher does not open the Calls panel")
    return out


def test_the_manifest_adds_the_call_permissions_and_only_the_apps_own_parts() -> None:
    assert manifest_problems(MANIFEST.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "change",
    [
        (
            'android:name=".calls.CallStateReceiver"\n            android:exported="false"',
            'android:name=".calls.CallStateReceiver"\n            android:exported="true"',
        ),
        ('<uses-permission android:name="android.permission.ANSWER_PHONE_CALLS" />', ""),
        ('android:required="false" />', 'android:required="true" />'),
    ],
)
def test_control_a_reachable_receiver_a_missing_permission_or_required_telephony(
    change: tuple[str, str],
) -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert change[0] in text
    assert manifest_problems(text.replace(change[0], change[1]))


# ---- the caller's number -----------------------------------------------------------------------
def number_problems(access: str, receiver: str) -> list[str]:
    out = []
    for words in ("EXTRA_INCOMING_NUMBER", "Android 9", "Android 16", "CallScreeningService"):
        if words not in access:
            out.append(f"CallsAccess.kt does not explain READ_CALL_LOG ({words})")
    code = _code(receiver)
    line = next((ln for ln in code.splitlines() if "EXTRA_INCOMING_NUMBER" in ln), "")
    if "CallsAccess.granted(app, CallsAccess.NUMBER)" not in line:
        out.append("the number is read without checking READ_CALL_LOG on the same line")
    if "CallLog" in _code(access + receiver):
        out.append("JARVIS never reads the call log itself")
    return out


def test_the_number_is_read_only_with_the_call_log_permission_which_says_why() -> None:
    assert number_problems(_src("CallsAccess.kt"), _src("CallStateReceiver.kt")) == []


def test_control_a_number_read_without_the_check() -> None:
    receiver = _src("CallStateReceiver.kt").replace(
        "if (CallsAccess.granted(app, CallsAccess.NUMBER)) intent.getStringExtra",
        "intent.getStringExtra",
    )
    receiver = receiver.replace(
        "TelephonyManager.EXTRA_INCOMING_NUMBER) else null",
        "TelephonyManager.EXTRA_INCOMING_NUMBER)",
    )
    assert number_problems(_src("CallsAccess.kt"), receiver)


# ---- placing, ending and moving calls ----------------------------------------------------------
def action_problems(actions: str, tap: str) -> list[str]:
    out = []
    code = _code(actions)
    if code.count("telecom.placeCall(") != 1:
        out.append("a dial goes through TelecomManager.placeCall, once")
    act_on = _body(code, "fun actOn(")
    if "CallCommands.check(" not in act_on or "store.markActed(" not in act_on:
        out.append("actOn does not check each command and mark it acted on")
    end = _body(code, "private fun end(")
    if "machine.callId != cmd.callId" not in end or "not_jarvis_call" not in end:
        out.append("end() can end a call JARVIS did not place or answer")
    route = _body(code, "private fun route(")
    if "machine.callId != cmd.callId" not in route:
        out.append("route() can move the sound of his own call")
    if "CallCommands.check(" not in _code(tap):
        out.append("the tapped notification does not check the signed command again")
    if "whenUnlocked { approve(cmd) }" not in tap:
        out.append("approving a card does not need the phone unlocked")
    return out


def test_dials_are_checked_placed_once_and_only_jarvis_calls_are_ended_or_moved() -> None:
    assert action_problems(_src("CallActions.kt"), _src("CallTapActivity.kt")) == []


@pytest.mark.parametrize(
    "file,needle,replacement",
    [
        (
            "CallActions.kt",
            'if (machine.callId != cmd.callId) return result(cmd, false, "not_jarvis_call")',
            "",
        ),
        ("CallTapActivity.kt", "whenUnlocked { approve(cmd) }", "approve(cmd)"),
        (
            "CallTapActivity.kt",
            "CallCommands.check(key, body, sig",
            "CallCommands.read(body).let { ",
        ),
    ],
)
def test_control_his_call_ended_an_approval_on_the_lock_screen_or_no_second_check(
    file: str, needle: str, replacement: str
) -> None:
    sources = {
        "CallActions.kt": _src("CallActions.kt"),
        "CallTapActivity.kt": _src("CallTapActivity.kt"),
    }
    assert needle in sources[file]
    sources[file] = sources[file].replace(needle, replacement)
    assert action_problems(sources["CallActions.kt"], sources["CallTapActivity.kt"])


def test_no_call_screen_of_its_own_no_audio_capture_and_no_foreground_service() -> None:
    for path in CALLS.rglob("*.kt"):
        code = _code(path.read_text(encoding="utf-8"))
        for banned in (
            "InCallService",
            "ConnectionService",
            "startForeground",
            "AudioRecord",
            "setExpedited",
        ):
            assert banned not in code, (path.name, banned)


# ---- the launcher, the doorbell, the first run, the version ------------------------------------
def test_the_calls_launcher_opens_one_fixed_address_and_reads_no_intent() -> None:
    text = _src("CallsLauncherActivity.kt")
    body = _body(text, "override fun getLaunchingUrl()")
    assert "CallLaunch.panelUrl(BuildConfig.JARVIS_HOST)" in body
    assert "intent" not in body and "extras" not in body
    assert _body(text, "override fun getUrlForIntent(").strip() == "null"


def test_the_doorbell_is_handled_first_and_shows_nothing_of_its_own() -> None:
    text = (SRC / "shell" / "JarvisDelegationService.kt").read_text(encoding="utf-8")
    body = _code(_body(text, "override fun onNotifyNotificationWithChannel("))
    bell = body.index("CallsWake.isDoorbell(platformTag)")
    assert bell < body.index("areNotificationsEnabled()")
    branch = body[bell : body.index("}", bell)]
    assert "CallsLink.pullSoon(this)" in branch and "return true" in branch
    assert "manager.notify" not in branch
    assert 'KIND = "call_command"' in _src("CallsWake.kt")


def test_the_calls_screen_comes_once_after_linking_and_pads_itself() -> None:
    gate = (SRC / "shell" / "LaunchGate.kt").read_text(encoding="utf-8")
    assert "state.asked(CallsSetupActivity.ASKED)" in gate
    setup = _src("CallsSetupActivity.kt")
    assert "SystemBars.pad(this, root)" in setup and "AppState(this).setAsked(ASKED)" in setup
    assert "askCore.launch(CallsAccess.CORE)" in setup
    assert "askNumber.launch(CallsAccess.NUMBER)" in setup  # asked apart, on its own tap


def test_the_words_say_what_jarvis_will_and_will_not_do() -> None:
    root = ElementTree.parse(STRINGS).getroot()
    words = {s.get("name"): (s.text or "") for s in root.iter("string")}
    assert words["calls_tap_title"] == "Tap to let JARVIS call %1$s"
    assert "Read your call log or your contacts" in words["calls_setup_never_list"]
    assert "without your tap" in words["calls_setup_never_list"]
    for name in ("calls_approve", "calls_decline", "channel_calls", "calls_locked_title"):
        assert words.get(name), name


def test_the_app_version_moved_on_with_r18() -> None:
    props = (ROOT / "android" / "version.properties").read_text(encoding="utf-8")
    code = re.search(r"^versionCode=(\d+)$", props, re.M)
    name = re.search(r"^versionName=(.+)$", props, re.M)
    assert code and int(code.group(1)) == 2
    assert name and name.group(1) == "18.0.0"
    assert re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", name.group(1))  # the door's shape
