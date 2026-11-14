# tests/test_r7_e_manifest.py -- R7 D1, D8, D9, D17, D19, D22 (Part E): the app's own manifest and
# its XML resources, read as text in the Python suite (this workspace cannot build Android; CI's
# scripts/apk_check.py then reads the BUILT app). The app asks for little: only its listed
# permissions, only its listed parts reachable from outside, no App Links, no backups, no plain
# HTTP. Each rule has a negative control that must make it fail.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app"
MANIFEST = APP / "src" / "main" / "AndroidManifest.xml"
RES = APP / "src" / "main" / "res"
A = "{http://schemas.android.com/apk/res/android}"
T = "{http://schemas.android.com/tools}"
PKG = "io.github.shark2558.jarvis"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("apk_check", ROOT / "scripts" / "apk_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("apk_check", mod)
    spec.loader.exec_module(mod)
    return mod


ac = _checker()
OWN_PERMISSIONS = {
    "android.permission.INTERNET",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.VIBRATE",
    "android.permission.health.READ_STEPS",
    "android.permission.health.READ_HEART_RATE",
    "android.permission.health.READ_SLEEP",
    "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND",
}
COMPONENTS = ("activity", "activity-alias", "service", "receiver", "provider")


def _full(name: str) -> str:
    return PKG + name if name.startswith(".") else name


def _actions(el: ElementTree.Element) -> set[str]:
    return {a.get(A + "name", "") for f in el.iter("intent-filter") for a in f.iter("action")}


def _categories(el: ElementTree.Element) -> set[str]:
    return {c.get(A + "name", "") for f in el.iter("intent-filter") for c in f.iter("category")}


def manifest_problems(text: str) -> list[str]:  # noqa: C901 -- one list of rules, read in order
    out: list[str] = []
    root = ElementTree.fromstring(text)
    removed, asked = set(), set()
    for p in root.iter("uses-permission"):
        (removed if p.get(T + "node") == "remove" else asked).add(p.get(A + "name", ""))
    for perm in sorted(asked - OWN_PERMISSIONS):
        out.append(f"a permission the app must not ask for: {perm}")
    for perm in sorted(asked & ac.FORBIDDEN_PERMISSIONS):
        out.append(f"a forbidden permission: {perm}")
    if "android.permission.FOREGROUND_SERVICE" not in removed:
        out.append("WorkManager's FOREGROUND_SERVICE is not removed (D9, D22)")
    fine = "android.permission.ACCESS_FINE_LOCATION" in asked
    coarse = "android.permission.ACCESS_COARSE_LOCATION" in asked
    if fine != coarse or not fine:
        out.append("precise and approximate location are not declared together")
    if not any(
        q.get(A + "name") == "com.google.android.apps.healthdata" for q in root.iter("package")
    ):
        out.append("Health Connect's package is not in <queries>")
    app = root.find("application")
    if app is None:
        return out + ["no <application>"]
    for key, want in (
        ("allowBackup", "false"),
        ("usesCleartextTraffic", "false"),
        ("dataExtractionRules", "@xml/data_extraction_rules"),
        ("networkSecurityConfig", "@xml/network_security_config"),
        ("fullBackupContent", "@xml/backup_rules"),
    ):
        if app.get(A + key) != want:
            out.append(f"application {key} is not {want}")
    if app.get(A + "debuggable") is not None:
        out.append("the manifest sets debuggable")
    own = {n for n, r in ac.REACHABLE.items() if r.ours}
    exported = {}
    for el in app:
        if el.tag not in COMPONENTS or el.get(T + "node") == "remove":
            continue
        name = _full(el.get(A + "name", ""))
        flag = el.get(A + "exported")
        if flag is None:
            out.append(f"{name} does not say whether it is exported")
        if flag == "true" or (flag is None and el.find("intent-filter") is not None):
            exported[name] = el
    for name in sorted(set(exported) - own):
        out.append(f"reachable from outside but not on the list: {name}")
    for name in sorted(own - set(exported)):
        out.append(f"one of the app's reachable parts is missing: {name}")
    for name, el in exported.items():
        rule = ac.REACHABLE.get(name)
        if rule and rule.permission and el.get(A + "permission") != rule.permission:
            out.append(f"{name} must be guarded by {rule.permission}")
    launcher = exported.get(f"{PKG}.shell.IconLauncherActivity")
    if launcher is not None:
        if "android.intent.action.VIEW" in _actions(launcher):
            out.append("the icon accepts web links (no App Links, D4)")
        if "android.intent.category.BROWSABLE" in _categories(launcher):
            out.append("the icon is BROWSABLE (any app could open a JARVIS address through it)")
        if any(f.get(A + "autoVerify") for f in launcher.iter("intent-filter")):
            out.append("an App Links filter (autoVerify) is declared")
        if not {"android.intent.action.MAIN", "android.intent.action.SEND"} <= _actions(launcher):
            out.append("the icon lacks its launcher or share filter")
    removed_parts = {_full(e.get(A + "name", "")) for e in app if e.get(T + "node") == "remove"}
    for lib in ("ShortcutTrampolineActivity", "ColdShortcutActivity"):
        if f"com.google.androidbrowserhelper.trusted.{lib}" not in removed_parts:
            out.append(f"the library's {lib} is not removed (it opens any address it is sent)")
    for el in app.iter("meta-data"):
        value = el.get(A + "value", "")
        if value.startswith("https://") and not value.startswith("https://${jarvisHost}/"):
            out.append(f"an address that is not built from jarvis.host: {value}")
    return out


def _real() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_the_manifest_asks_for_little_and_exposes_only_its_listed_parts() -> None:
    assert manifest_problems(_real()) == []


def test_health_connect_finds_both_privacy_page_entries() -> None:
    root = ElementTree.fromstring(_real())
    app = root.find("application")
    assert app is not None
    rationale = [
        e for e in app if "androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" in _actions(e)
    ]
    assert len(rationale) == 1 and rationale[0].tag == "activity"
    alias = [e for e in app if e.tag == "activity-alias"]
    assert len(alias) == 1
    assert "android.intent.action.VIEW_PERMISSION_USAGE" in _actions(alias[0])
    assert "android.intent.category.HEALTH_PERMISSIONS" in _categories(alias[0])
    assert _full(alias[0].get(A + "targetActivity", "")) == _full(rationale[0].get(A + "name", ""))


def test_the_second_launcher_and_the_sos_screen_cannot_be_started_by_other_apps() -> None:
    app = ElementTree.fromstring(_real()).find("application")
    assert app is not None
    by_name = {_full(e.get(A + "name", "")): e for e in app if e.tag in COMPONENTS}
    for name in ("shell.ScreenLauncherActivity", "sos.SosActivity", "link.SetupActivity"):
        assert by_name[f"{PKG}.{name}"].get(A + "exported") == "false", name
    sos = by_name[f"{PKG}.sos.SosActivity"]
    assert sos.get(A + "showWhenLocked") == "true"  # a countdown on the lock screen (question 6)


def test_the_tiles_are_quick_settings_tiles_behind_the_system_permission() -> None:
    app = ElementTree.fromstring(_real()).find("application")
    assert app is not None
    tiles = [e for e in app if "android.service.quicksettings.action.QS_TILE" in _actions(e)]
    assert {_full(t.get(A + "name", "")).rsplit(".", 1)[1] for t in tiles} == {
        "TalkTileService",
        "SosTileService",
    }
    assert all(
        t.get(A + "permission") == "android.permission.BIND_QUICK_SETTINGS_TILE" for t in tiles
    )


def test_the_notification_service_answers_chrome() -> None:
    app = ElementTree.fromstring(_real()).find("application")
    assert app is not None
    svc = [
        e
        for e in app
        if "android.support.customtabs.trusted.TRUSTED_WEB_ACTIVITY_SERVICE" in _actions(e)
    ]
    assert len(svc) == 1
    metas = {m.get(A + "name"): m.get(A + "resource") for m in svc[0].iter("meta-data")}
    assert metas.get("android.support.customtabs.trusted.SMALL_ICON") == "@drawable/ic_notification"


def test_backups_and_device_transfer_exclude_everything() -> None:
    rules = ElementTree.parse(RES / "xml" / "data_extraction_rules.xml").getroot()
    for part in ("cloud-backup", "device-transfer"):
        section = rules.find(part)
        assert section is not None, part
        assert section.find("include") is None, part
        excluded = {e.get("domain") for e in section.iter("exclude") if e.get("path") == "."}
        assert {"root", "file", "database", "sharedpref", "external"} <= excluded, part


def test_android_9_to_11_backup_rules_exclude_everything_too() -> None:
    rules = ElementTree.parse(RES / "xml" / "backup_rules.xml").getroot()
    assert rules.tag == "full-backup-content" and rules.find("include") is None
    excluded = {e.get("domain") for e in rules.iter("exclude") if e.get("path") == "."}
    assert {"root", "file", "database", "sharedpref", "external"} <= excluded


def test_no_plain_http_and_system_certificates_only() -> None:
    nsc = ElementTree.parse(RES / "xml" / "network_security_config.xml").getroot()
    base = nsc.find("base-config")
    assert base is not None and base.get("cleartextTrafficPermitted") == "false"
    assert nsc.find("domain-config") is None
    assert [c.get("src") for c in nsc.iter("certificates")] == ["system"]


def test_the_shortcuts_reach_only_the_apps_own_screens_with_its_own_words() -> None:
    root = ElementTree.parse(RES / "xml" / "shortcuts.xml").getroot()
    targets = {}
    for sc in root.iter("shortcut"):
        intent = sc.find("intent")
        assert intent is not None
        assert intent.get(A + "targetPackage") == PKG
        targets[sc.get(A + "shortcutId")] = (
            intent.get(A + "targetClass"),
            intent.get(A + "action"),
        )
    assert targets == {
        "talk": (f"{PKG}.shell.ScreenLauncherActivity", f"{PKG}.action.TALK"),
        "look": (f"{PKG}.shell.ScreenLauncherActivity", f"{PKG}.action.LOOK"),
        "sos": (f"{PKG}.sos.SosActivity", f"{PKG}.action.SOS"),
        "setup": (f"{PKG}.link.SetupActivity", f"{PKG}.action.SETUP"),
    }


def test_every_string_the_screens_show_is_a_resource() -> None:
    for layout in (RES / "layout").glob("*.xml"):
        for el in ElementTree.parse(layout).getroot().iter():
            for key in ("text", "hint", "contentDescription"):
                value = el.get(A + key)
                assert value is None or value.startswith("@string/"), (layout.name, key, value)


# ---- negative controls ----------------------------------------------------------------------
def _with(old: str, new: str) -> str:
    text = _real()
    assert old in text, old
    return text.replace(old, new, 1)


@pytest.mark.parametrize(
    "perm",
    ["android.permission.READ_SMS", "android.permission.CAMERA", "android.permission.RECORD_AUDIO"],
)
def test_control_a_forbidden_permission_added(perm: str) -> None:
    text = _with("<application", f'<uses-permission android:name="{perm}" />\n    <application')
    assert any(perm in p for p in manifest_problems(text))


def test_control_a_screen_marked_reachable_from_outside() -> None:
    text = _real()
    start = text.index('android:name=".shell.ScreenLauncherActivity"')
    cut = text.index('android:exported="false"', start)
    text = text[:cut] + 'android:exported="true"' + text[cut + len('android:exported="false"') :]
    assert any("ScreenLauncherActivity" in p for p in manifest_problems(text))


def test_control_the_icon_made_to_accept_web_links() -> None:
    link = (
        '<intent-filter android:autoVerify="true">'
        '<action android:name="android.intent.action.VIEW" />'
        '<category android:name="android.intent.category.BROWSABLE" />'
        '<data android:scheme="https" android:host="${jarvisHost}" /></intent-filter>\n'
        "            <intent-filter>"
    )
    text = _with("<intent-filter>", link)
    problems = manifest_problems(text)
    assert any("web links" in p for p in problems) and any("BROWSABLE" in p for p in problems)


def test_control_backups_switched_on_or_rules_dropped() -> None:
    assert manifest_problems(_with('android:allowBackup="false"', 'android:allowBackup="true"'))
    text = _with('android:dataExtractionRules="@xml/data_extraction_rules"', "")
    assert any("dataExtractionRules" in p for p in manifest_problems(text))


def test_control_precise_location_without_approximate() -> None:
    text = _with('<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />', "")
    assert any("together" in p for p in manifest_problems(text))


def test_control_the_library_trampoline_left_in() -> None:
    text = _real()
    needle = 'android:name="com.google.androidbrowserhelper.trusted.ShortcutTrampolineActivity"'
    start = text.index(needle)
    cut = text.index('tools:node="remove"', start)
    text = text[:cut] + text[cut + len('tools:node="remove"') :]
    assert any("ShortcutTrampolineActivity" in p for p in manifest_problems(text))


def test_control_a_real_address_written_into_the_manifest() -> None:
    host = "jarvis-owner." + "example.org"
    text = _with("https://${jarvisHost}/?source=app", f"https://{host}/?source=app")
    assert any(host in p for p in manifest_problems(text))
