# tests/test_r7_e_sources.py -- R7 D8, D9, D17, D19, D21, D22, D24 (Part E): rules of the native
# screens that a JVM test cannot see, read from the Kotlin sources: the exported launcher's
# getLaunchingUrl() ignores an incoming address; the tile opens JARVIS with
# startActivityAndCollapse(PendingIntent); the SOS and set-up screens apply the system bars'
# insets; no expedited work; precise and approximate location asked together; steps and heart
# rate only through Health Connect's aggregate. Each rule has a negative control.
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "android" / "app" / "src" / "main" / "java" / "io" / "github" / "shark2558" / "jarvis"
LAYOUT = ROOT / "android" / "app" / "src" / "main" / "res" / "layout"


def _src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _all_kotlin() -> dict[str, str]:
    return {str(p.relative_to(SRC)): p.read_text(encoding="utf-8") for p in SRC.rglob("*.kt")}


def _code(text: str) -> str:
    """The text without its comments (a comment may name a banned thing to say why it is out)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(?:^|\s)//\s.*$", "", line) for line in text.splitlines())


_NEXT = re.compile(r"\n\s*\n|\n\s*(?:override |private |fun |companion |\})")


def _body(text: str, signature: str) -> str:
    """The body of the function whose declaration starts with `signature` (an expression body
    up to the next declaration or blank line, or a block body up to its matching brace)."""
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


# ---- the launchers (D8) -----------------------------------------------------------------------
def launcher_problems(text: str) -> list[str]:
    out = []
    body = _body(text, "override fun getLaunchingUrl()")
    if "Launch.iconUrl(" not in body:
        out.append("the icon does not open Launch.iconUrl")
    for word in ("intent", "data", "super.", "getUrlForIntent", "extras"):
        if re.search(rf"\b{re.escape(word)}", body):
            out.append(f"getLaunchingUrl() reads {word!r}: it must ignore an incoming address")
    if _body(text, "override fun getUrlForIntent(").strip() != "null":
        out.append("getUrlForIntent() must answer null (no address is forwarded)")
    return out


def test_the_exported_launcher_ignores_any_incoming_address() -> None:
    assert launcher_problems(_src("shell/IconLauncherActivity.kt")) == []


def test_the_second_launcher_adds_only_an_allow_listed_word_from_its_own_action() -> None:
    text = _src("shell/ScreenLauncherActivity.kt")
    body = _body(text, "override fun getLaunchingUrl()")
    assert "Launch.screenUrl(" in body and "Launch.wordForAction(" in body
    assert "data" not in body and "extras" not in body
    assert _body(text, "override fun getUrlForIntent(").strip() == "null"


def test_both_launchers_open_the_console_only_once_linked() -> None:
    for rel in ("shell/IconLauncherActivity.kt", "shell/ScreenLauncherActivity.kt"):
        assert "LaunchGate.linkedOrSetUp(this)" in _body(
            _src(rel), "override fun shouldLaunchImmediately()"
        )


def test_no_webview_and_no_bridge_into_the_page() -> None:
    for name, text in _all_kotlin().items():
        for banned in (
            "WebView",
            "addJavascriptInterface",
            "CookieManager",
            "postMessage",
            '"Cookie"',
        ):
            assert banned not in _code(text), (name, banned)


@pytest.mark.parametrize(
    "body",
    [
        "Uri = intent?.data ?: Uri.parse(Launch.iconUrl(BuildConfig.JARVIS_HOST))",
        "Uri = super.getLaunchingUrl()",
        'Uri = Uri.parse(Launch.iconUrl(BuildConfig.JARVIS_HOST) + intent.getStringExtra("q"))',
    ],
)
def test_control_the_launcher_made_to_honour_an_incoming_address(body: str) -> None:
    text = _src("shell/IconLauncherActivity.kt")
    sig = "override fun getLaunchingUrl():"
    line = text[text.index(sig) :].split("\n", 1)[0]
    assert launcher_problems(text.replace(line, f"{sig} {body}"))


def test_control_the_launcher_forwarding_the_intents_address() -> None:
    text = _src("shell/IconLauncherActivity.kt")
    line = text[text.index("override fun getUrlForIntent(") :].split("\n", 1)[0]
    assert launcher_problems(
        text.replace(line, "override fun getUrlForIntent(intent: Intent?): Uri? = intent?.data")
    )


# ---- the tile (D9) ----------------------------------------------------------------------------
def tile_problems(text: str) -> list[str]:
    out = []
    if not re.search(r"startActivityAndCollapse\(\s*pending\s*\)", text):
        out.append("the tile does not use startActivityAndCollapse(PendingIntent)")
    if "PendingIntent.getActivity(" not in text or "PendingIntent.FLAG_IMMUTABLE" not in text:
        out.append("no immutable PendingIntent")
    if "UPSIDE_DOWN_CAKE" not in text:
        out.append("the PendingIntent form is not used from Android 14")
    return out


def test_the_tile_opens_jarvis_with_a_pending_intent() -> None:
    assert tile_problems(_src("shell/Tiles.kt")) == []
    for tile in ("shell/TalkTileService.kt", "shell/SosTileService.kt"):
        assert "Tiles.open(" in _src(tile)


def test_the_talk_tile_asks_to_unlock_first_and_never_touches_the_microphone() -> None:
    talk = _src("shell/TalkTileService.kt")
    assert "unlockAndRun" in talk and 'ScreenLauncherActivity.launchIntent(this, "talk")' in talk
    for name, text in _all_kotlin().items():
        for banned in ("AudioRecord", "MediaRecorder", "RECORD_AUDIO", "SpeechRecognizer"):
            assert banned not in text, (name, banned)


def test_control_the_tile_with_the_old_intent_form_only() -> None:
    text = _src("shell/Tiles.kt").replace(
        "startActivityAndCollapse(pending)", "startActivityAndCollapse(intent)"
    )
    assert tile_problems(text)


# ---- edge to edge (D19) -----------------------------------------------------------------------
def insets_problems(screen: str, helper: str) -> list[str]:
    out = []
    if "SystemBars.pad(" not in screen:
        out.append("the screen does not pad itself inside the system bars")
    if (
        "setOnApplyWindowInsetsListener" not in helper
        or "WindowInsetsCompat.Type.systemBars()" not in helper
    ):
        out.append("the helper does not apply the system bars' insets")
    if "displayCutout()" not in helper:
        out.append("the helper ignores the camera cut-out")
    return out


@pytest.mark.parametrize(
    "screen", ["sos/SosActivity.kt", "link/SetupActivity.kt", "health/PrivacyActivity.kt"]
)
def test_the_native_screens_apply_the_system_bars_insets(screen: str) -> None:
    assert insets_problems(_src(screen), _src("ui/SystemBars.kt")) == []


def test_the_sos_cancel_button_is_full_width_inside_the_padded_screen() -> None:
    layout = (LAYOUT / "activity_sos.xml").read_text(encoding="utf-8")
    cancel = layout[layout.index('android:id="@+id/sos_cancel"') :]
    cancel = cancel[: cancel.index("/>")]
    assert 'android:layout_width="match_parent"' in cancel
    assert "@dimen/sos_button_height" in cancel
    assert 'android:id="@+id/sos_root"' in layout
    assert "SystemBars.pad(this, findViewById(R.id.sos_root))" in _src("sos/SosActivity.kt")


def test_control_the_sos_screen_without_insets() -> None:
    screen = _src("sos/SosActivity.kt").replace("SystemBars.pad(", "SystemBars.ignore(")
    assert insets_problems(screen, _src("ui/SystemBars.kt"))


# ---- background work (D16, D17, D22) ----------------------------------------------------------
EXPEDITED = (
    "setExpedited",
    "OutOfQuotaPolicy",
    "setForeground",
    "startForeground",
    "ForegroundInfo",
)


def background_problems(sources: dict[str, str]) -> list[str]:
    return [f"{n}: {w}" for n, t in sources.items() for w in EXPEDITED if w in t]


def test_no_expedited_or_foreground_work() -> None:
    assert background_problems(_all_kotlin()) == []
    jobs = _src("shell/Background.kt")
    assert "PeriodicWorkRequest.Builder(HealthSyncWorker::class.java, 6, TimeUnit.HOURS)" in jobs
    assert "PeriodicWorkRequest.Builder(FolderWorker::class.java, 1, TimeUnit.HOURS)" in jobs


def test_control_expedited_work_added() -> None:
    sources = _all_kotlin()
    sources["shell/Background.kt"] += (
        "\n// .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)\n"
    )
    assert background_problems(sources)


# ---- location (D19) ---------------------------------------------------------------------------
def location_problems(text: str) -> list[str]:
    asks = re.findall(r"arrayOf\(([^)]*)\)", text)
    together = [a for a in asks if "ACCESS_FINE_LOCATION" in a and "ACCESS_COARSE_LOCATION" in a]
    alone = [a for a in asks if ("FINE" in a) != ("COARSE" in a)]
    out = []
    if not together:
        out.append("precise and approximate location are not asked for in one request")
    if alone:
        out.append("a location request asks for only one of the two")
    if "ACCESS_BACKGROUND_LOCATION" in text:
        out.append("background location is never asked for")
    return out


def test_precise_and_approximate_location_are_asked_together() -> None:
    assert location_problems(_src("link/SetupActivity.kt")) == []


def test_control_precise_location_asked_alone() -> None:
    text = _src("link/SetupActivity.kt").replace(", Manifest.permission.ACCESS_COARSE_LOCATION", "")
    assert location_problems(text)


# ---- Health Connect (D17) ---------------------------------------------------------------------
def health_problems(text: str) -> list[str]:
    out = []
    if not re.search(r"aggregate\(\s*AggregateRequest\(\s*setOf\(StepsRecord\.COUNT_TOTAL\)", text):
        out.append("steps do not come from Health Connect's aggregate")
    for metric in ("BPM_MIN", "BPM_AVG", "BPM_MAX"):
        if f"HeartRateRecord.{metric}" not in text:
            out.append(f"heart rate {metric} does not come from the aggregate")
    if re.search(r"ReadRecordsRequest\(\s*(?:StepsRecord|HeartRateRecord)::class", text):
        out.append("raw step or heart-rate records are read (they would be summed twice)")
    if re.search(r"readRecords\b[^\n]*(?:StepsRecord|HeartRateRecord)", text):
        out.append("raw step or heart-rate records are read")
    if "RestingHeartRateRecord" in text:
        out.append("resting heart rate is read (D17: not asked for)")
    return out


def test_steps_and_heart_rate_come_only_from_the_aggregate() -> None:
    assert health_problems(_src("health/HealthReader.kt")) == []


def test_control_the_dedupe_switched_off_raw_steps_summed() -> None:
    raw = (
        "\nfun rawSteps(c: HealthConnectClient, f: TimeRangeFilter) = await { "
        "c.readRecords(ReadRecordsRequest(StepsRecord::class, f)) }.records.sumOf { it.count }\n"
    )
    assert health_problems(_src("health/HealthReader.kt") + raw)


def test_the_reader_asks_for_three_kinds_and_the_background_read_only() -> None:
    perms = _src("health/HealthPermissions.kt")
    kinds = set(re.findall(r"getReadPermission\((\w+)::class\)", perms))
    assert kinds == {"StepsRecord", "HeartRateRecord", "SleepSessionRecord"}
    assert "READ_HEALTH_DATA_IN_BACKGROUND" in perms


# ---- the door, the set-up screen and SOS (D6, D19, D21) ---------------------------------------
STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def test_the_door_client_is_https_only_follows_no_redirect_and_adds_no_query() -> None:
    door = _src("link/DoorClient.kt")
    assert door.count('URL("https://$host$path")') == 1
    assert "instanceFollowRedirects = false" in door
    assert "Door.path(route)" in door and "Door.signingString(" in door
    literals = STRING.findall(door)
    assert literals and not [s for s in literals if "?" in s]  # no query string, ever (D6)


def test_the_set_up_screen_blocks_screenshots() -> None:
    assert "WindowManager.LayoutParams.FLAG_SECURE" in _src("link/SetupActivity.kt")


def test_sos_never_sends_a_text_itself_and_never_places_a_call() -> None:
    sos = _src("sos/SosActivity.kt")
    assert "Intent.ACTION_SENDTO" in sos and "Intent.ACTION_DIAL" in sos
    for name, text in _all_kotlin().items():
        for banned in (r"SmsManager", r"ACTION_CALL\b", r"sendTextMessage"):
            assert not re.search(banned, text), (name, banned)


BANNED_IN_LOGS = ("lat", "lon", "location", "fix", "number", "phone", "body", "contact", "label")


def log_problems(sources: dict[str, str]) -> list[str]:
    out = []
    for name, text in sources.items():
        for call in re.findall(r"Log\.[dviwe]\(([^\n]*)", text):
            for ref in re.findall(r"\$\{?([A-Za-z_][\w.]*)", call):
                if any(word in ref.lower() for word in BANNED_IN_LOGS):
                    out.append(f"{name}: a log line carries {ref}")
    return out


def test_logs_carry_kinds_and_counts_never_a_value() -> None:
    assert log_problems(_all_kotlin()) == []


def test_control_a_coordinate_written_to_the_log() -> None:
    sources = _all_kotlin()
    sources["sos/SosActivity.kt"] += '\nLog.d(TAG, "fix ${fix.latE6}")\n'
    assert log_problems(sources)


def test_the_countdown_goes_through_core_and_only_its_send_reaches_the_door() -> None:
    sos = _src("sos/SosActivity.kt")
    assert re.search(r"SosMachine\([^)]*\)\s*\{\s*\w+\s*->\s*sendSos\(", sos)
    assert "machine.cancel(" in sos
    assert sos.count('signed("sos"') == 1
    assert 'signed("sos"' in _body(sos, "private fun sendSos(")
