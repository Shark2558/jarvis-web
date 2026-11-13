# tests/test_r7_e_gradle.py -- R7 D23, D24 (Part E): the Android project's Gradle files and what
# the repository may hold. Exact versions, Apache-2.0 libraries only, built-in Kotlin in `app`,
# `core` with the standard library alone, the `personal` build type, and the JARVIS address only
# in the git-ignored local.properties (CI builds against the placeholder `jarvis.invalid`). No
# key, keystore or host name is ever written under android/.
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
TOML = ANDROID / "gradle" / "libs.versions.toml"
APP_GRADLE = ANDROID / "app" / "build.gradle.kts"
CORE_GRADLE = ANDROID / "core" / "build.gradle.kts"
PKG = "io.github.shark2558.jarvis"
# Every library the app may use (D1 "Modules": all Apache-2.0), by Maven group and name.
LIBRARIES = {
    "com.google.androidbrowserhelper:androidbrowserhelper",
    "androidx.browser:browser",
    "androidx.core:core",
    "androidx.work:work-runtime",
    "androidx.health.connect:connect-client",
}
TEXT_SUFFIXES = (".kt", ".kts", ".xml", ".toml", ".properties", ".pro", ".json", ".md", ".txt")
# Hosts that may be written in android/: the placeholder, the SOS text's map link, XML
# namespaces, the Gradle wrapper's download address and the page I0's wrapper note cites, and
# example.com names in tests (RFC 2606: never a real address).
ALLOWED_HOSTS = {
    "jarvis.invalid",
    "maps.google.com",
    "schemas.android.com",
    "services.gradle.org",
    "developer.android.com",
}
URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://([a-z0-9-]+(?:\.[a-z0-9-]+)+)")
BARE = re.compile(
    r"(?i)(?<![\w.$])((?:[a-z0-9-]+\.)+(?:com|net|org|app|dev|io|in|co|cloud|me|xyz|site|online|"
    r"tech|ai|run\.app|appspot\.com|web\.app|ts\.net))(?![\w.])"
)
SECRET_SHAPES = (
    re.compile(r"-----BEGIN" + r" (?:[A-Z0-9]+ )*PRIVATE KEY"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}"),
    re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)storePassword|keyPassword"),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tracked_android_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "android"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


# The fonts' licence texts (SIL OFL 1.1, copied verbatim with the fonts from static/fonts) name
# the licence's page and the fonts' makers, and only there.
LICENCE_HOSTS = {
    "scripts.sil.org",
    "github.com",
    "indiantypefoundry.com",
    "carrois.com",
    "www.carrois.com",
}
LICENCE_FILE = re.compile(r"(?:^|/)assets/fonts/OFL-[a-z-]+\.txt$")


def host_problems(name: str, text: str) -> list[str]:
    found = {m.group(1).lower() for m in URL.finditer(text)}
    found |= {m.group(1).lower() for m in BARE.finditer(text) if not m.group(1).startswith(PKG)}
    reserved = {h for h in found if h == "example.com" or h.endswith(".example.com")}
    allowed = ALLOWED_HOSTS | (LICENCE_HOSTS if LICENCE_FILE.search(name) else set())
    return [f"{name}: a host name {h}" for h in sorted(found - allowed - reserved)]


def secret_problems(name: str, text: str) -> list[str]:
    return [f"{name}: a secret shape" for p in SECRET_SHAPES if p.search(text)]


# ---- the project's shape --------------------------------------------------------------------
def test_the_project_has_core_and_app() -> None:
    settings = _text(ANDROID / "settings.gradle.kts")
    assert re.search(r'include\(\s*":core"\s*,\s*":app"\s*\)', settings)
    assert (ANDROID / "core" / "build.gradle.kts").is_file()
    assert APP_GRADLE.is_file()


def test_every_version_is_exact_and_every_library_is_on_the_list() -> None:
    toml = _text(TOML)
    versions = dict(re.findall(r'^([a-z0-9-]+) = "([^"]+)"$', toml.split("[libraries]")[0], re.M))
    for name, version in versions.items():
        assert re.fullmatch(r"\d+(?:\.\d+)+", version), (name, version)  # no +, range or alpha
    modules = set(re.findall(r'module = "([^"]+)"', toml))
    assert modules == LIBRARIES
    assert versions["androidbrowserhelper"] == "2.7.4"
    assert versions["health-connect"].startswith("1.1.")
    assert "kotlinx-serialization" not in toml and "compose" not in toml.lower()


def test_the_app_uses_built_in_kotlin_and_the_planned_sdks() -> None:
    gradle = _text(APP_GRADLE)
    plugins = re.search(r"plugins \{(.*?)\}", gradle, re.S)
    assert plugins and plugins.group(1).split() == ["alias(libs.plugins.android.application)"]
    for banned in ("org.jetbrains.kotlin.android", "kotlin-android", "kotlinOptions", "compose"):
        assert banned not in gradle, banned
    assert re.search(r"^\s*compileSdk = 36$", gradle, re.M)
    assert re.search(r"^\s*targetSdk = 36$", gradle, re.M)
    assert re.search(r"^\s*minSdk = 28$", gradle, re.M)
    assert f'namespace = "{PKG}"' in gradle and f'applicationId = "{PKG}"' in gradle


def test_the_personal_build_is_not_debuggable_and_signed_with_the_laptops_debug_key() -> None:
    gradle = _text(APP_GRADLE)
    block = gradle[gradle.index('create("personal")') :]
    block = block[: block.index("\n        }")]
    assert "isDebuggable = false" in block
    assert 'signingConfig = signingConfigs.getByName("debug")' in block
    assert "storeFile" not in gradle and "storePassword" not in gradle


def test_the_address_comes_only_from_local_properties_or_the_command_line() -> None:
    gradle = _text(APP_GRADLE)
    assert 'rootProject.file("local.properties")' in gradle
    assert 'findProperty("jarvis.host")' in gradle and 'getProperty("jarvis.host")' in gradle
    assert '"jarvis.invalid"' in gradle  # the placeholder when no address is given
    assert "prePersonalBuild" in gradle and "GradleException" in gradle  # personal stops plainly
    assert "android/local.properties" in _text(ROOT / ".gitignore")


def test_dependencies_are_the_listed_libraries_by_the_catalogue_only() -> None:
    gradle = _text(APP_GRADLE)
    deps = gradle[gradle.index("dependencies {") :]
    lines = [ln.strip() for ln in deps.splitlines()[1:] if ln.strip() and ln.strip() != "}"]
    for ln in lines:
        assert re.fullmatch(r'implementation\((?:project\(":core"\)|libs\.[a-z.]+)\)', ln), ln


def test_core_has_no_library_but_the_standard_library() -> None:
    gradle = _text(CORE_GRADLE)
    assert "alias(libs.plugins.kotlin.jvm)" in gradle
    assert "implementation(" not in gradle and "testImplementation(" not in gradle
    assert "jvmTests" in gradle and "phone_vectors.json" in gradle
    for src in (ANDROID / "core" / "src").rglob("*.kt"):
        for line in _text(src).splitlines():
            if line.startswith("import "):
                assert re.match(r"import (java|kotlin)\.", line), (src.name, line)


# ---- what the repository may hold under android/ --------------------------------------------
def test_no_key_keystore_or_machine_file_is_in_the_repository() -> None:
    for path in _tracked_android_files():
        name = path.name.lower()
        assert not name.endswith((".jks", ".keystore", ".p12", ".pem", ".apk", ".aab")), path
        assert name != "local.properties", path


def test_no_host_name_or_secret_shape_in_any_android_file() -> None:
    problems = []
    for path in _tracked_android_files():
        if path.suffix in TEXT_SUFFIXES and path.is_file():
            rel = str(path.relative_to(ROOT))
            text = _text(path)
            problems += host_problems(rel, text) + secret_problems(rel, text)
    assert problems == []


# ---- negative controls ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "snippet",
    [
        'const val HOST = "jarvis-owner-2f3e.a.' + 'run.app"',
        'val base = "https://my-jarvis.' + 'onrender.com/"',
        "<!-- served from jarvis." + "myhome.in -->",
    ],
)
def test_control_a_host_name_written_into_a_source_file(snippet: str) -> None:
    src = ANDROID / "core" / "src" / "main" / "kotlin" / "io" / "github" / "shark2558" / "jarvis"
    text = _text(src / "core" / "Rules.kt") + "\n" + snippet + "\n"
    assert host_problems("Rules.kt", text)


def test_control_a_secret_written_into_a_source_file() -> None:
    assert secret_problems("x.kt", 'val k = "' + "AI" + "za" + "Q" * 35 + '"')
    assert secret_problems("build.gradle.kts", "storePassword = " + '"hunter2"')


def test_the_package_names_and_the_placeholder_are_not_host_names() -> None:
    text = (
        'import io.github.shark2558.jarvis.core.Door\nval h = "jarvis.invalid"\nimport java.io.File'
    )
    assert host_problems("x.kt", text) == []
