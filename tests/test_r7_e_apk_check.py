# tests/test_r7_e_apk_check.py -- R7 D22 (Part E): scripts/apk_check.py reads the BUILT app in CI
# and fails on any permission or outside-reachable part that is not on its lists, any forbidden
# one, a debuggable `personal` build, plain HTTP, another package name, a real host name or a
# secret-shaped string. These tests build small made-up APKs: a binary XML writer below encodes
# a manifest the way aapt2 does (string pool, namespaces, typed attributes), so the checker's own
# decoder is tested on bytes, and CI cross-checks that decoder against Gradle's merged manifest.
from __future__ import annotations

import importlib.util
import io
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANDROID_NS = "http://schemas.android.com/apk/res/android"
PKG = "io.github.shark2558.jarvis"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("apk_check", ROOT / "scripts" / "apk_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apk_check"] = mod
    spec.loader.exec_module(mod)
    return mod


ac = _load()


# ---- a tiny binary XML writer (the format aapt2 writes into an APK) -------------------------
@dataclass
class El:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    kids: list[El] = field(default_factory=list)


def _pool(strings: list[str], utf8: bool) -> bytes:
    offsets, data = [], bytearray()
    for s in strings:
        offsets.append(len(data))
        if utf8:
            raw = s.encode("utf-8")
            for n in (len(s), len(raw)):
                data += bytes([n]) if n < 0x80 else bytes([0x80 | (n >> 8), n & 0xFF])
            data += raw + b"\x00"
        else:
            raw = s.encode("utf-16-le")
            n = len(raw) // 2
            data += (
                struct.pack("<H", n)
                if n < 0x8000
                else struct.pack("<HH", 0x8000 | (n >> 16), n & 0xFFFF)
            )
            data += raw + b"\x00\x00"
    while len(data) % 4:
        data += b"\x00"
    start = 28 + 4 * len(strings)
    head = struct.pack(
        "<HHIIIIII", 0x0001, 28, start + len(data), len(strings), 0, 0x100 if utf8 else 0, start, 0
    )
    return head + struct.pack(f"<{len(strings)}I", *offsets) + bytes(data)


def axml(root: El, utf8: bool = False) -> bytes:
    """Encode an element tree as binary XML. Attribute keys 'android:x' get the android
    namespace; 'true'/'false' become booleans, digits integers, '@...' references."""
    strings: list[str] = []

    def idx(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    refs: dict[str, int] = {}
    body = bytearray()
    none = 0xFFFFFFFF

    def typed(value: str) -> tuple[int, int, int]:  # raw, type, data
        if value in ("true", "false"):
            return none, 0x12, 0xFFFFFFFF if value == "true" else 0
        if value.isdigit():
            return none, 0x10, int(value)
        if value.startswith("@"):
            refs.setdefault(value, 0x7F010000 + len(refs))
            return none, 0x01, refs[value]
        i = idx(value)
        return i, 0x03, i

    def element(el: El) -> None:
        attrs = []
        for key, value in el.attrs.items():
            ns = idx(ANDROID_NS) if key.startswith("android:") else none
            name = idx(key.split(":", 1)[1] if key.startswith("android:") else key)
            raw, typ, data = typed(value)
            attrs.append(struct.pack("<IIIHBBI", ns, name, raw, 8, 0, typ, data))
        ext = struct.pack("<IIHHHHHH", none, idx(el.tag), 20, 20, len(attrs), 0, 0, 0)
        node = struct.pack("<HHIII", 0x0102, 16, 16 + len(ext) + 20 * len(attrs), 1, none)
        body.extend(node + ext + b"".join(attrs))
        for kid in el.kids:
            element(kid)
        body.extend(struct.pack("<HHIIIII", 0x0103, 16, 24, 1, none, none, idx(el.tag)))

    idx("android")
    idx(ANDROID_NS)
    start_ns = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, none, idx("android"), idx(ANDROID_NS))
    element(root)
    end_ns = struct.pack("<HHIIIII", 0x0101, 16, 24, 1, none, idx("android"), idx(ANDROID_NS))
    chunks = _pool(strings, utf8) + start_ns + bytes(body) + end_ns
    return struct.pack("<HHI", 0x0003, 8, 8 + len(chunks)) + chunks


# ---- the app as it should be built (our parts and the libraries' own entries) ---------------
def _filter(*actions: str, categories: tuple[str, ...] = ()) -> El:
    kids = [El("action", {"android:name": a}) for a in actions]
    kids += [El("category", {"android:name": c}) for c in categories]
    return El("intent-filter", kids=kids)


def good_tree(**app_attrs: str) -> El:
    perms = [
        "android.permission.INTERNET",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.VIBRATE",
        "android.permission.health.READ_STEPS",
        "android.permission.health.READ_HEART_RATE",
        "android.permission.health.READ_SLEEP",
        "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND",
        "android.permission.WAKE_LOCK",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        f"{PKG}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
    ]
    app = {
        "android:allowBackup": "false",
        "android:dataExtractionRules": "@xml/data_extraction_rules",
        "android:usesCleartextTraffic": "false",
        "android:networkSecurityConfig": "@xml/network_security_config",
        "android:label": "JARVIS",
        **app_attrs,
    }
    launcher = El(
        "activity",
        {"android:name": f"{PKG}.shell.IconLauncherActivity", "android:exported": "true"},
        [
            El(
                "meta-data",
                {
                    "android:name": "android.support.customtabs.trusted.DEFAULT_URL",
                    "android:value": "https://jarvis.invalid/?source=app",
                },
            ),
            _filter("android.intent.action.MAIN", categories=("android.intent.category.LAUNCHER",)),
            _filter("android.intent.action.SEND", categories=("android.intent.category.DEFAULT",)),
        ],
    )
    comps = [
        launcher,
        El(
            "activity",
            {"android:name": f"{PKG}.shell.ScreenLauncherActivity", "android:exported": "false"},
        ),
        El("activity", {"android:name": f"{PKG}.sos.SosActivity", "android:exported": "false"}),
        El(
            "activity",
            {"android:name": f"{PKG}.health.PrivacyActivity", "android:exported": "true"},
            [_filter("androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE")],
        ),
        El(
            "activity-alias",
            {
                "android:name": f"{PKG}.health.ViewPermissionUsageActivity",
                "android:exported": "true",
                "android:targetActivity": f"{PKG}.health.PrivacyActivity",
                "android:permission": "android.permission.START_VIEW_PERMISSION_USAGE",
            },
            [
                _filter(
                    "android.intent.action.VIEW_PERMISSION_USAGE",
                    categories=("android.intent.category.HEALTH_PERMISSIONS",),
                )
            ],
        ),
        El(
            "service",
            {"android:name": f"{PKG}.shell.JarvisDelegationService", "android:exported": "true"},
            [_filter("android.support.customtabs.trusted.TRUSTED_WEB_ACTIVITY_SERVICE")],
        ),
        *(
            El(
                "service",
                {
                    "android:name": f"{PKG}.shell.{tile}",
                    "android:exported": "true",
                    "android:permission": "android.permission.BIND_QUICK_SETTINGS_TILE",
                },
                [_filter("android.service.quicksettings.action.QS_TILE")],
            )
            for tile in ("TalkTileService", "SosTileService")
        ),
        El(
            "service",
            {
                "android:name": "androidx.work.impl.background.systemjob.SystemJobService",
                "android:exported": "true",
                "android:permission": "android.permission.BIND_JOB_SERVICE",
            },
        ),
        El(
            "receiver",
            {
                "android:name": "androidx.work.impl.diagnostics.DiagnosticsReceiver",
                "android:exported": "true",
                "android:permission": "android.permission.DUMP",
            },
            [_filter("androidx.work.diagnostics.REQUEST_DIAGNOSTICS")],
        ),
        El(
            "receiver",
            {
                "android:name": "androidx.work.impl.background.systemalarm.RescheduleReceiver",
                "android:exported": "false",
                "android:enabled": "false",
            },
            [_filter("android.intent.action.BOOT_COMPLETED")],
        ),
        El(
            "provider",
            {
                "android:name": "androidx.startup.InitializationProvider",
                "android:authorities": f"{PKG}.androidx-startup",
                "android:exported": "false",
            },
        ),
    ]
    kids = [El("uses-sdk", {"android:minSdkVersion": "28", "android:targetSdkVersion": "36"})]
    kids += [El("uses-permission", {"android:name": p}) for p in perms]
    kids.append(
        El(
            "permission",
            {
                "android:name": f"{PKG}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
                "android:protectionLevel": "signature",
            },
        )
    )
    kids.append(El("application", app, comps))
    return El("manifest", {"package": PKG, "android:versionCode": "1"}, kids)


NSC = El(
    "network-security-config",
    kids=[
        El(
            "base-config",
            {"cleartextTrafficPermitted": "false"},
            [El("trust-anchors", kids=[El("certificates", {"src": "system"})])],
        )
    ],
)
GOOD_DEX = (
    b"dex\n035\x00 https://jarvis.invalid/?source=app https://maps.google.com/?q= "
    b"http://schemas.android.com/apk/res/android io.github.shark2558.jarvis"
)


def make_apk(
    tmp: Path,
    tree: El | None = None,
    *,
    dex: bytes = GOOD_DEX,
    nsc: El | None = None,
    extra: dict[str, bytes] | None = None,
    utf8: bool = False,
) -> Path:
    path = tmp / "app-personal.apk"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", axml(tree or good_tree(), utf8=utf8))
        z.writestr("classes.dex", dex)
        z.writestr("res/xml/network_security_config.xml", axml(nsc or NSC, utf8=utf8))
        z.writestr("resources.arsc", b"\x02\x00\x0c\x00 jarvis.invalid")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def _text(el: El, depth: int = 0) -> str:
    def attr(k: str, v: str) -> str:
        return f' {k}="{v}"'

    ns = f' xmlns:android="{ANDROID_NS}"' if depth == 0 else ""
    head = f"<{el.tag}{ns}{''.join(attr(k, v) for k, v in el.attrs.items())}"
    if not el.kids:
        return head + "/>"
    return head + ">" + "".join(_text(k, depth + 1) for k in el.kids) + f"</{el.tag}>"


def _without(tree: El, name: str) -> El:
    app = next(k for k in tree.kids if k.tag == "application")
    app.kids = [c for c in app.kids if c.attrs.get("android:name") != name]
    return tree


def _app(tree: El) -> El:
    return next(k for k in tree.kids if k.tag == "application")


# ---- the decoder -----------------------------------------------------------------------------
@pytest.mark.parametrize("utf8", [False, True])
def test_the_decoder_reads_binary_xml_with_either_string_form(utf8: bool) -> None:
    root = ac.decode_axml(axml(good_tree(), utf8=utf8))
    assert root.tag == "manifest" and root.attrs["package"] == PKG
    app = next(c for c in root.children if c.tag == "application")
    assert app.attrs["android:allowBackup"] == "false"
    assert app.attrs["android:dataExtractionRules"].startswith("@0x7f")
    launcher = app.children[0]
    assert launcher.attrs["android:exported"] == "true"


def test_the_decoder_reads_long_and_non_ascii_strings() -> None:
    name = "Ünïcode " + "x" * 300
    for utf8 in (False, True):
        root = ac.decode_axml(
            axml(El("manifest", {"package": PKG, "android:label": name}), utf8=utf8)
        )
        assert root.attrs["android:label"] == name


def test_the_decoder_refuses_what_is_not_binary_xml() -> None:
    with pytest.raises(ac.AxmlError):
        ac.decode_axml(b"<manifest/>")
    with pytest.raises(ac.AxmlError):
        ac.decode_axml(struct.pack("<HHI", 0x0003, 8, 64) + struct.pack("<HHI", 0x0001, 28, 9999))


def test_the_binary_and_the_text_manifest_give_the_same_model() -> None:
    tree = good_tree()
    binary = ac.manifest_from_tree(ac.decode_axml(axml(tree)))
    text = ac.parse_text_manifest(_text(tree))
    assert ac.summary(binary) == ac.summary(text)


# ---- the good app passes --------------------------------------------------------------------
def test_a_good_app_passes(tmp_path: Path) -> None:
    assert ac.check_apk(make_apk(tmp_path), host="jarvis.invalid") == []


def test_the_command_line_finds_the_one_apk_and_exits_0(tmp_path: Path, capsys) -> None:
    make_apk(tmp_path)
    assert ac.main([str(tmp_path)]) == 0
    assert "passed" in capsys.readouterr().out


def test_the_command_line_fails_without_exactly_one_apk(tmp_path: Path) -> None:
    assert ac.main([str(tmp_path)]) == 1
    make_apk(tmp_path)
    (tmp_path / "second.apk").write_bytes((tmp_path / "app-personal.apk").read_bytes())
    assert ac.main([str(tmp_path)]) == 1


def test_the_merged_manifest_must_agree_with_the_built_one(tmp_path: Path) -> None:
    apk = make_apk(tmp_path)
    merged = tmp_path / "AndroidManifest.xml"
    merged.write_text(_text(good_tree()), encoding="utf-8")
    assert ac.check_apk(apk, host="jarvis.invalid", merged=merged) == []
    other = good_tree()
    _app(other).kids.append(
        El("activity", {"android:name": f"{PKG}.Extra", "android:exported": "false"})
    )
    merged.write_text(_text(other), encoding="utf-8")
    problems = ac.check_apk(apk, host="jarvis.invalid", merged=merged)
    assert any("disagree" in p for p in problems)


# ---- negative controls: each one must fail the check ----------------------------------------
def _problems(tmp: Path, tree: El | None = None, **kw) -> list[str]:
    return ac.check_apk(make_apk(tmp, tree, **kw), host="jarvis.invalid")


@pytest.mark.parametrize(
    "perm",
    [
        "android.permission.READ_SMS",
        "android.permission.RECEIVE_SMS",
        "android.permission.SEND_SMS",
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_CONTACTS",
        "android.permission.MANAGE_EXTERNAL_STORAGE",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.QUERY_ALL_PACKAGES",
        "android.permission.BIND_ACCESSIBILITY_SERVICE",
        "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.health.READ_RESTING_HEART_RATE",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
    ],
)
def test_control_a_forbidden_permission_fails(tmp_path: Path, perm: str) -> None:
    tree = good_tree()
    tree.kids.insert(1, El("uses-permission", {"android:name": perm}))
    assert any(perm in p for p in _problems(tmp_path, tree))


def test_control_an_unlisted_permission_fails(tmp_path: Path) -> None:
    tree = good_tree()
    tree.kids.insert(1, El("uses-permission-sdk-23", {"android:name": "com.example.SOMETHING"}))
    assert any("com.example.SOMETHING" in p for p in _problems(tmp_path, tree))


def test_control_a_missing_needed_permission_fails(tmp_path: Path) -> None:
    tree = good_tree()
    tree.kids = [
        k for k in tree.kids if k.attrs.get("android:name") != "android.permission.INTERNET"
    ]
    assert any("INTERNET" in p for p in _problems(tmp_path, tree))


def test_control_another_declared_permission_fails(tmp_path: Path) -> None:
    tree = good_tree()
    tree.kids.insert(
        1, El("permission", {"android:name": f"{PKG}.OPEN", "android:protectionLevel": "normal"})
    )
    assert any(f"{PKG}.OPEN" in p for p in _problems(tmp_path, tree))


def test_control_a_screen_marked_reachable_from_outside_fails(tmp_path: Path) -> None:
    tree = good_tree()
    for c in _app(tree).kids:
        if c.attrs.get("android:name") == f"{PKG}.shell.ScreenLauncherActivity":
            c.attrs["android:exported"] = "true"
    problems = _problems(tmp_path, tree)
    assert any("ScreenLauncherActivity" in p for p in problems)


def test_control_an_intent_filter_without_exported_counts_as_reachable(tmp_path: Path) -> None:
    tree = good_tree()
    _app(tree).kids.append(
        El("activity", {"android:name": f"{PKG}.Open"}, [_filter("android.intent.action.VIEW")])
    )
    assert any(f"{PKG}.Open" in p for p in _problems(tmp_path, tree))


def test_control_a_tile_without_its_permission_fails(tmp_path: Path) -> None:
    tree = good_tree()
    for c in _app(tree).kids:
        if c.attrs.get("android:name", "").endswith("TalkTileService"):
            del c.attrs["android:permission"]
    assert any("TalkTileService" in p for p in _problems(tmp_path, tree))


@pytest.mark.parametrize(
    "name", [f"{PKG}.health.PrivacyActivity", f"{PKG}.health.ViewPermissionUsageActivity"]
)
def test_control_a_missing_health_connect_privacy_entry_fails(tmp_path: Path, name: str) -> None:
    assert any(name in p for p in _problems(tmp_path, _without(good_tree(), name)))


def test_control_the_library_shortcut_trampoline_is_refused(tmp_path: Path) -> None:
    tree = good_tree()
    name = "com.google.androidbrowserhelper.trusted.ShortcutTrampolineActivity"
    _app(tree).kids.append(El("activity", {"android:name": name, "android:exported": "true"}))
    assert any(name in p for p in _problems(tmp_path, tree))


def test_control_a_debuggable_build_fails(tmp_path: Path) -> None:
    assert any(
        "debuggable" in p for p in _problems(tmp_path, good_tree(**{"android:debuggable": "true"}))
    )


def test_control_cleartext_traffic_fails(tmp_path: Path) -> None:
    tree = good_tree(**{"android:usesCleartextTraffic": "true"})
    assert any("cleartext" in p.lower() for p in _problems(tmp_path, tree))
    open_nsc = El(
        "network-security-config", kids=[El("base-config", {"cleartextTrafficPermitted": "true"})]
    )
    assert any("cleartext" in p.lower() for p in _problems(tmp_path, nsc=open_nsc))


def test_control_user_certificates_fail(tmp_path: Path) -> None:
    user = El(
        "network-security-config",
        kids=[
            El(
                "base-config",
                kids=[El("trust-anchors", kids=[El("certificates", {"src": "user"})])],
            )
        ],
    )
    assert any("user" in p for p in _problems(tmp_path, nsc=user))


def test_control_backups_on_or_no_extraction_rules_fail(tmp_path: Path) -> None:
    assert any(
        "allowBackup" in p
        for p in _problems(tmp_path, good_tree(**{"android:allowBackup": "true"}))
    )
    tree = good_tree()
    del _app(tree).attrs["android:dataExtractionRules"]
    assert any("dataExtractionRules" in p for p in _problems(tmp_path, tree))


def test_control_another_package_fails(tmp_path: Path) -> None:
    tree = good_tree()
    tree.attrs["package"] = "com.example.other"
    assert any("package" in p for p in _problems(tmp_path, tree))


def test_control_a_real_host_in_the_code_fails(tmp_path: Path) -> None:
    host = "jarvis-owner-1a2b3c." + "a.run" + ".app"
    for dex in (GOOD_DEX + b" https://" + host.encode(), GOOD_DEX + b" " + host.encode()):
        assert any(host in p for p in _problems(tmp_path, dex=dex))


def test_control_an_unknown_host_in_the_code_fails(tmp_path: Path) -> None:
    dex = GOOD_DEX + "https://telemetry.example.net/x".encode("utf-16-le")
    assert any("telemetry.example.net" in p for p in _problems(tmp_path, dex=dex))


def test_the_font_licences_may_name_their_own_hosts_and_nothing_else_may(tmp_path: Path) -> None:
    licence = b"Copyright (https://github.com/x) see http://scripts.sil.org/OFL"
    assert _problems(tmp_path, extra={"assets/fonts/OFL-orbitron.txt": licence}) == []
    problems = _problems(tmp_path, extra={"assets/notes.txt": licence})
    assert any("github.com" in p for p in problems)


def test_control_a_launch_address_with_another_host_fails(tmp_path: Path) -> None:
    tree = good_tree()
    launcher = _app(tree).kids[0]
    launcher.kids[0].attrs["android:value"] = "https://jarvis.example.com/?source=app"
    assert any("DEFAULT_URL" in p for p in _problems(tmp_path, tree))


def test_control_a_secret_shape_fails(tmp_path: Path) -> None:
    secrets = [
        "AI" + "za" + "S" * 35,
        "gh" + "p_" + "a1" * 18,
        "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "12345678" + ":" + "A" * 35,
        "-----BEGIN " + "EC PRIVATE KEY-----",
    ]
    for secret in secrets:
        problems = _problems(tmp_path, dex=GOOD_DEX + b" " + secret.encode())
        assert any("secret" in p for p in problems), secret


def test_control_a_keystore_inside_the_app_fails(tmp_path: Path) -> None:
    for name in ("assets/release.jks", "debug.keystore", "local.properties"):
        assert any(name in p for p in _problems(tmp_path, extra={name: b"x"}))


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    tree = good_tree(**{"android:debuggable": "true"})
    tree.kids.insert(1, El("uses-permission", {"android:name": "android.permission.READ_SMS"}))
    problems = _problems(tmp_path, tree, dex=GOOD_DEX + b" https://telemetry.example.net/")
    assert len(problems) >= 3


def test_the_lists_say_why_each_entry_is_allowed() -> None:
    assert all(reason.strip() for reason in ac.ALLOWED_PERMISSIONS.values())
    assert all(r.reason.strip() for r in ac.REACHABLE.values())
    assert not set(ac.ALLOWED_PERMISSIONS) & ac.FORBIDDEN_PERMISSIONS
    assert ac.PACKAGE == PKG and ac.PLACEHOLDER == "jarvis.invalid"


def test_the_checker_uses_only_the_standard_library() -> None:
    text = (ROOT / "scripts" / "apk_check.py").read_text(encoding="utf-8")
    imports = {
        line.split()[1].split(".")[0]
        for line in text.splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imports <= {
        "__future__",
        "argparse",
        "dataclasses",
        "io",
        "pathlib",
        "re",
        "struct",
        "sys",
        "xml",
        "zipfile",
        "collections",
        "typing",
    }, imports


def test_a_zip_that_is_not_an_apk_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "app-personal.apk"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("classes.dex", GOOD_DEX)
    assert any("AndroidManifest.xml" in p for p in ac.check_apk(path, host="jarvis.invalid"))
    path.write_bytes(b"not a zip")
    assert ac.check_apk(path, host="jarvis.invalid")


def test_the_report_lists_the_hosts_and_parts_it_found(tmp_path: Path) -> None:
    buf = io.StringIO()
    ac.report(make_apk(tmp_path), host="jarvis.invalid", out=buf)
    text = buf.getvalue()
    assert "IconLauncherActivity" in text and "maps.google.com" in text
