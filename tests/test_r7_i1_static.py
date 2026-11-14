# tests/test_r7_i1_static.py -- R7 I1 (INTEGRATION-A "Needs I1" 5): the Android app and the web
# manifest say the same things. The app's own share target (android/app/build.gradle.kts) posts the
# same form to the same route as the manifest's (`/app/share/in`, `title`/`text`/`url`/`files`, the
# same picture and PDF types); the app's launch addresses are the manifest's (`/?source=app` and
# `&do=talk|look|sos`, words from one allow-list); the delegated notification keeps its actions
# (A's "Talk", `/?do=talk`). The app's SOS shortcut opens the app's own SOS screen (D19), which
# needs the same hold as the console's sheet that `do=sos` opens.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
APP = ANDROID / "app" / "src" / "main"
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
WORDS = ("talk", "look", "sos")


def _manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((STATIC / "manifest.webmanifest").read_text("utf-8"))
    return data


def _app_share_target() -> dict[str, Any]:
    """The JSON the app's build writes into its string resource, with the host filled in."""
    gradle = (ANDROID / "app" / "build.gradle.kts").read_text("utf-8")
    body = gradle[gradle.index("fun shareTarget(host: String): String =") :]
    body = body[: body.index("\n\n")]
    parts = re.findall(r'"""(.*?)"""', body, flags=re.S)
    text = "".join(parts).replace('\\"', '"').replace("$host", "jarvis.invalid")
    data: dict[str, Any] = json.loads(text)
    return data


def test_the_apps_share_target_is_the_manifests() -> None:
    web, app = _manifest()["share_target"], _app_share_target()
    assert (
        app["action"]
        == "https://jarvis.invalid" + web["action"]
        == ("https://jarvis.invalid/app/share/in")
    )
    for key in ("method", "enctype"):
        assert app[key] == web[key], key
    for key in ("title", "text", "url"):
        assert app["params"][key] == web["params"][key] == key
    (web_files,), (app_files,) = web["params"]["files"], app["params"]["files"]
    assert app_files["name"] == web_files["name"] == "files"
    web_types = [t for t in web_files["accept"] if "/" in t]
    assert app_files["accept"] == web_types  # the manifest adds file endings for Chrome only
    assert set(web_types) == {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def test_the_apps_launch_addresses_are_the_manifests() -> None:
    m = _manifest()
    assert m["start_url"] == "/?source=app"
    assert [s["url"] for s in m["shortcuts"]] == [f"/?source=app&do={w}" for w in WORDS]
    rules = (ANDROID / "core" / "src" / "main" / "kotlin").rglob("Rules.kt")
    code = next(iter(rules)).read_text("utf-8")
    assert 'fun iconUrl(host: String): String = "https://${checkedHost(host)}/?source=app"' in code
    assert '"${iconUrl(host)}&do=$word"' in code
    assert 'val WORDS: List<String> = listOf("talk", "look", "sos", "shared")' in code


def test_the_apps_shortcuts_add_only_allow_listed_words_or_open_its_sos_screen() -> None:
    xml = (APP / "res" / "xml" / "shortcuts.xml").read_text("utf-8")
    pairs = re.findall(
        r'android:action="io\.github\.shark2558\.jarvis\.action\.([A-Z]+)"\s+'
        r'android:targetClass="io\.github\.shark2558\.jarvis\.([a-z.]+\.[A-Za-z]+)"',
        xml,
    )
    assert pairs == [
        ("TALK", "shell.ScreenLauncherActivity"),  # -> /?source=app&do=talk
        ("LOOK", "shell.ScreenLauncherActivity"),  # -> /?source=app&do=look
        ("SOS", "sos.SosActivity"),  # the app's own SOS screen: the same hold, D19
        ("SETUP", "link.SetupActivity"),
    ]


def test_the_delegated_notification_keeps_its_actions_and_its_tag_picks_the_channel() -> None:
    code = (
        (APP / "java" / "io" / "github" / "shark2558" / "jarvis" / "shell")
        .joinpath("JarvisDelegationService.kt")
        .read_text("utf-8")
    )
    assert "Notification.Builder.recoverBuilder(this, notification)" in code  # actions kept
    assert "setActions(" not in code and "clearActions" not in code
    assert "Channels.forTag(platformTag)" in code
    sw = (STATIC / "console-sw.js").read_text("utf-8")
    assert (
        "const TALK = '/?do=talk';" in sw and "actions: [{ action: 'talk', title: 'Talk' }]" in sw
    )
