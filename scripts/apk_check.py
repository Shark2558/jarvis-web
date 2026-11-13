#!/usr/bin/env python3
# scripts/apk_check.py
"""R7 D22 (Part E): read the BUILT Android app and fail on anything it must not carry.

    python3 scripts/apk_check.py <app.apk | folder with one .apk> [--host jarvis.invalid]
                                  [--merged <Gradle's merged AndroidManifest.xml>]

It decodes the APK's binary AndroidManifest.xml itself (standard library only, so CI needs no
Android tool for it) and fails, listing EVERY finding at once, on:

- a permission that is not on ALLOWED_PERMISSIONS, any of FORBIDDEN_PERMISSIONS, or a missing one
  the app needs; a declared permission other than AndroidX core's own signature permission;
- a part reachable from outside the app that is not on REACHABLE, or that lacks the system
  permission REACHABLE names for it; one of the app's own reachable parts missing (Health
  Connect's two privacy-page entries among them). "Reachable" is fail-closed: any `exported`
  other than the literal false counts (a resource reference too), as does an intent filter with
  no `exported`. What a reachable part ACCEPTS is held too: each of the app's own parts has the
  exact intent filters (actions, categories, data) REACHABLE lists, and no reachable part,
  a library's included, takes a BROWSABLE category or any address data (an App Link);
- a package other than io.github.shark2558.jarvis; a debuggable build; backups on or no
  `dataExtractionRules`; cleartext traffic (the manifest's switch, or a network security config
  that permits it or trusts user certificates);
- a launch address whose host is not the placeholder; a host name in the app's code or resources
  that is not on the reviewed list (any host of a private hosting service always fails; in the
  resource files any dotted name ending in a public suffix counts, scheme or not; a URL with a
  user name in it always fails); a secret-shaped string (Slack, JWT and Stripe shapes among
  them); a keystore or local.properties packed inside the app.

`--merged` cross-checks the decoder: the merged manifest Gradle wrote must give the same model.
The lists were built from CI's first merged manifest and reviewed (docs/plans/r7-mobile.md D22;
docs/plans/r7-integration/INTEGRATION-E.md). Exit 0 when everything passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO
from xml.etree import ElementTree

PACKAGE = "io.github.shark2558.jarvis"
PLACEHOLDER = "jarvis.invalid"
ANDROID_NS = "http://schemas.android.com/apk/res/android"
TOOLS_NS = "http://schemas.android.com/tools"
DEFAULT_URL = "android.support.customtabs.trusted.DEFAULT_URL"
ICON_LAUNCHER = f"{PACKAGE}.shell.IconLauncherActivity"

ALLOWED_PERMISSIONS: dict[str, str] = {
    "android.permission.INTERNET": "the console and the phone's signed door",
    "android.permission.POST_NOTIFICATIONS": "alerts with the app closed (D10)",
    "android.permission.ACCESS_FINE_LOCATION": "the SOS location, while the app is in use (D19)",
    "android.permission.ACCESS_COARSE_LOCATION": "asked together with precise location (D19)",
    "android.permission.VIBRATE": "the SOS countdown vibrates (D19)",
    "android.permission.health.READ_STEPS": "the watch's and the phone's steps (D17)",
    "android.permission.health.READ_HEART_RATE": "heart rate lowest, average, highest (D17)",
    "android.permission.health.READ_SLEEP": "sleep sessions (D17, D18)",
    "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND": "the 6-hourly read (D17)",
    "android.permission.ACCESS_NETWORK_STATE": "WorkManager: run jobs only with a network",
    "android.permission.WAKE_LOCK": "WorkManager: keep the CPU awake for a short job",
    "android.permission.RECEIVE_BOOT_COMPLETED": "WorkManager: keep jobs after a restart",
    f"{PACKAGE}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION": "AndroidX core's own, app-only",
}
REQUIRED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "android.permission.INTERNET",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.health.READ_STEPS",
        "android.permission.health.READ_HEART_RATE",
        "android.permission.health.READ_SLEEP",
    }
)
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset(
    {
        "android.permission.READ_SMS",
        "android.permission.RECEIVE_SMS",
        "android.permission.SEND_SMS",
        "android.permission.RECEIVE_MMS",
        "android.permission.RECEIVE_WAP_PUSH",
        "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
        "android.permission.BIND_ACCESSIBILITY_SERVICE",
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_CONTACTS",
        "android.permission.WRITE_CONTACTS",
        "android.permission.GET_ACCOUNTS",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.MANAGE_EXTERNAL_STORAGE",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.QUERY_ALL_PACKAGES",
        "android.permission.REQUEST_INSTALL_PACKAGES",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
        "android.permission.READ_PHONE_STATE",
        "android.permission.READ_CALL_LOG",
        "android.permission.CALL_PHONE",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.USE_FULL_SCREEN_INTENT",
        "android.permission.health.READ_RESTING_HEART_RATE",
        "android.permission.health.READ_HEALTH_DATA_HISTORY",
    }
)
_DECLARED_OK = f"{PACKAGE}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
_SIGNATURE = frozenset({"signature", "2", "0x2", "0x00000002"})


@dataclass(frozen=True)
class Filter:
    """One intent filter: what it answers to. `data` holds each <data> element's attributes."""

    actions: frozenset[str]
    categories: frozenset[str] = frozenset()
    data: frozenset[tuple[tuple[str, str], ...]] = frozenset()

    def signature(self) -> str:
        return repr((sorted(self.actions), sorted(self.categories), sorted(self.data)))


def flt(
    actions: Iterable[str], categories: Iterable[str] = (), mimes: Iterable[str] = ()
) -> Filter:
    return Filter(
        frozenset(actions),
        frozenset(categories),
        frozenset((("mimeType", m),) for m in mimes),
    )


@dataclass(frozen=True)
class Reach:
    """A part other apps or the system may start, the permission that guards it, and (for the
    app's own parts) exactly the intent filters it may have; None leaves a library's own filters
    unpinned (the BROWSABLE and address-data rules still apply to them)."""

    permission: str | None
    ours: bool  # the app's own part: it must be there
    reason: str
    filters: frozenset[Filter] | None = None


_DEFAULT = "android.intent.category.DEFAULT"
_SHARE_MIMES = ("image/jpeg", "image/png", "image/webp", "application/pdf")


REACHABLE: dict[str, Reach] = {
    ICON_LAUNCHER: Reach(
        None,
        True,
        "the icon and the share entry; it ignores incoming addresses",
        frozenset(
            {
                flt(["android.intent.action.MAIN"], ["android.intent.category.LAUNCHER"]),
                flt(
                    ["android.intent.action.SEND"],
                    [_DEFAULT],
                    (*_SHARE_MIMES, "text/plain"),
                ),
                flt(["android.intent.action.SEND_MULTIPLE"], [_DEFAULT], _SHARE_MIMES),
            }
        ),
    ),
    f"{PACKAGE}.shell.JarvisDelegationService": Reach(
        None,
        True,
        "Chrome hands alerts to it; the library checks the caller's token (D10)",
        frozenset(
            {flt(["android.support.customtabs.trusted.TRUSTED_WEB_ACTIVITY_SERVICE"], [_DEFAULT])}
        ),
    ),
    f"{PACKAGE}.shell.TalkTileService": Reach(
        "android.permission.BIND_QUICK_SETTINGS_TILE",
        True,
        "the Talk tile (D9)",
        frozenset({flt(["android.service.quicksettings.action.QS_TILE"])}),
    ),
    f"{PACKAGE}.shell.SosTileService": Reach(
        "android.permission.BIND_QUICK_SETTINGS_TILE",
        True,
        "the SOS tile (D19)",
        frozenset({flt(["android.service.quicksettings.action.QS_TILE"])}),
    ),
    f"{PACKAGE}.health.PrivacyActivity": Reach(
        None,
        True,
        "Health Connect's privacy page, Android 13 and older (D17)",
        frozenset({flt(["androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE"])}),
    ),
    f"{PACKAGE}.health.ViewPermissionUsageActivity": Reach(
        "android.permission.START_VIEW_PERMISSION_USAGE",
        True,
        "Health Connect's privacy page, Android 14 and newer (D17)",
        frozenset(
            {
                flt(
                    ["android.intent.action.VIEW_PERMISSION_USAGE"],
                    ["android.intent.category.HEALTH_PERMISSIONS"],
                )
            }
        ),
    ),
    "androidx.work.impl.background.systemjob.SystemJobService": Reach(
        "android.permission.BIND_JOB_SERVICE", False, "WorkManager's job service"
    ),
    "androidx.work.impl.diagnostics.DiagnosticsReceiver": Reach(
        "android.permission.DUMP", False, "WorkManager's diagnostics"
    ),
    "androidx.profileinstaller.ProfileInstallReceiver": Reach(
        "android.permission.DUMP", False, "profileinstaller, through androidx.activity"
    ),
    "androidx.health.platform.client.impl.sdkservice.HealthDataSdkService": Reach(
        None, False, "Health Connect's own client service"
    ),
}

# Hosts written inside the app, each reviewed (CI's first report, run 43439904145): the placeholder,
# the app's own map link, XML namespaces, and the public pages the libraries' own texts link to.
# None can be a JARVIS address. CI prints every host it finds on every run; a new one fails the
# check until it is reviewed and added here with its reason.
REVIEWED_HOSTS: dict[str, str] = {
    PLACEHOLDER: "the address CI builds against (D23)",
    "maps.google.com": "the SOS text's map link (D19)",
    "schemas.android.com": "XML namespaces",
    "developer.android.com": "AndroidX error messages link Android's documentation",
    "issuetracker.google.com": "AndroidX error messages link Google's issue tracker",
    "github.com": "android-browser-helper's message links its README; a font names its makers",
    "youtrack.jetbrains.com": "the Kotlin standard library links its issue tracker",
    "www.apache.org": "the libraries' Apache-2.0 licence texts (META-INF)",
    "scripts.sil.org": "the fonts' SIL Open Font Licence link, inside the fonts and their licences",
    "example.com": "a sample address in a library's text (RFC 2606: never real)",
    "www.example.com": "a sample address in a library's text (RFC 2606: never real)",
}
ALLOWED_HOSTS: frozenset[str] = frozenset(REVIEWED_HOSTS)
# Any host of these services is a real address and always fails (the build book's own list).
PRIVATE_SUFFIXES = (
    ".run.app",
    ".appspot.com",
    ".firebaseapp.com",
    ".web.app",
    ".cloudfunctions.net",
    ".ts.net",
    ".onrender.com",
    ".vercel.app",
    ".workers.dev",
    ".pages.dev",
    ".trycloudflare.com",
    ".duckdns.org",
    ".ngrok-free.app",
    ".ngrok.io",
    ".fly.dev",
    ".railway.app",
    ".netlify.app",
    ".herokuapp.com",
)
# In the app's resource files any dotted name that ends in one of these public suffixes is read
# as a host name, with or without a scheme: it must be on the reviewed list.
PUBLIC_SUFFIXES = (
    "com", "org", "net", "io", "dev", "app", "co", "in", "me", "xyz", "info", "biz",
    "page", "site", "online", "cloud", "tech", "ai", "gov", "edu", "eu", "uk", "us",
)  # fmt: skip
_URL = re.compile(rb"(?i)\bhttps?://(?:[^\s/@\"'<>]*@)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)")
_USERINFO = re.compile(rb"(?i)\bhttps?://[^\s/@\"'<>]+@[a-z0-9-]+\.")
_BARE = re.compile(
    rb"(?i)(?<![A-Za-z0-9_.-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:"
    + b"|".join(s.encode() for s in PUBLIC_SUFFIXES)
    + rb"))(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"
)
_PRIVATE = re.compile(
    rb"(?i)\b(?:[a-z0-9-]+\.)+(?:"
    + b"|".join(re.escape(s[1:].encode()) for s in PRIVATE_SUFFIXES)
    + rb")\b"
)
SECRET_SHAPES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private key", re.compile(rb"-----BEGIN" + rb" (?:[A-Z0-9]+ )*PRIVATE KEY")),
    ("Google API key", re.compile(rb"AIza[0-9A-Za-z_-]{35}")),
    ("Google OAuth secret", re.compile(rb"GOCSPX-[A-Za-z0-9_-]{20,}")),
    ("model provider key", re.compile(rb"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(rb"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,}")),
    ("AWS key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("Slack token", re.compile(rb"xox[abprs]-[0-9A-Za-z-]{10,}")),
    (
        "JSON web token",
        re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    ("Stripe key", re.compile(rb"[sr]k_(?:live|test)_[0-9A-Za-z]{16,}")),
    (
        "Telegram bot token",
        re.compile(rb"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    ),
)
_SECRET_FILES = re.compile(r"(?i)(?:\.jks|\.keystore|\.p12|\.pfx|\.pem|(?:^|/)local\.properties)$")
_COMPONENTS = ("activity", "activity-alias", "service", "receiver", "provider")


class AxmlError(ValueError):
    """Bytes that are not Android's binary XML."""


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class Component:
    kind: str
    name: str
    exported: bool
    permission: str | None
    meta: tuple[tuple[str, str], ...]
    filters: tuple[Filter, ...] = ()


@dataclass(frozen=True)
class Manifest:
    package: str
    permissions: tuple[str, ...]
    declared: tuple[tuple[str, str], ...]
    components: tuple[Component, ...]
    app: tuple[tuple[str, str], ...]

    def app_attr(self, key: str) -> str | None:
        return dict(self.app).get(key)


# ---- Android's binary XML ---------------------------------------------------------------------
_NO_INDEX = 0xFFFFFFFF


def _u16(data: bytes, pos: int) -> int:
    return int(struct.unpack_from("<H", data, pos)[0])


def _len8(data: bytes, pos: int) -> tuple[int, int]:
    b = data[pos]
    if b & 0x80:
        return ((b & 0x7F) << 8) | data[pos + 1], pos + 2
    return b, pos + 1


def _len16(data: bytes, pos: int) -> tuple[int, int]:
    v = _u16(data, pos)
    if v & 0x8000:
        return ((v & 0x7FFF) << 16) | _u16(data, pos + 2), pos + 4
    return v, pos + 2


def _string_pool(data: bytes, pos: int) -> list[str]:
    _t, head, _size, count, _styles, flags, start, _ = struct.unpack_from("<HHIIIIII", data, pos)
    offsets = struct.unpack_from(f"<{count}I", data, pos + head)
    base, out = pos + start, []
    for off in offsets:
        p = base + off
        if flags & 0x100:  # UTF-8: the UTF-16 length, then the byte length
            _, p = _len8(data, p)
            n, p = _len8(data, p)
            out.append(data[p : p + n].decode("utf-8", errors="replace"))
        else:
            n, p = _len16(data, p)
            out.append(data[p : p + 2 * n].decode("utf-16-le", errors="replace"))
    return out


def _value(strings: list[str], raw: int, typ: int, data: int) -> str:
    if typ == 0x03 or (raw != _NO_INDEX and raw < len(strings)):
        index = raw if raw != _NO_INDEX else data
        return strings[index] if index < len(strings) else ""
    if typ == 0x12:
        return "true" if data else "false"
    if typ == 0x10:
        return str(data - (1 << 32) if data & 0x80000000 else data)
    if typ == 0x11:
        return f"0x{data:x}"
    if typ == 0x01:
        return f"@0x{data:08x}"
    return "" if typ == 0x00 else f"0x{data:x}"


def decode_axml(data: bytes) -> Node:
    """The element tree of a binary XML file. Attribute keys in the android namespace read
    'android:<name>'."""
    if len(data) < 8 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        raise AxmlError("not a binary XML file")
    head, size = struct.unpack_from("<HI", data, 2)
    end, pos = min(size, len(data)), head
    strings: list[str] = []
    prefixes: dict[str, str] = {}
    stack = [Node("#document")]
    try:
        while pos + 8 <= end:
            typ, chead, csize = struct.unpack_from("<HHI", data, pos)
            if csize < 8 or pos + csize > end:
                raise AxmlError("a broken chunk")
            if typ == 0x0001:
                strings = _string_pool(data, pos)
            elif typ == 0x0100:
                prefix, uri = struct.unpack_from("<II", data, pos + chead)
                prefixes[strings[uri]] = strings[prefix]
            elif typ == 0x0102:
                stack.append(_element(data, pos, chead, strings, prefixes, stack[-1]))
            elif typ == 0x0103 and len(stack) > 1:
                stack.pop()
            pos += csize
    except (struct.error, IndexError) as exc:
        raise AxmlError(f"a broken binary XML file: {exc}") from exc
    if not stack[0].children:
        raise AxmlError("no element")
    return stack[0].children[0]


def _element(
    data: bytes, pos: int, head: int, strings: list[str], prefixes: dict[str, str], parent: Node
) -> Node:
    ext = pos + head
    _ns, name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", data, ext)
    node = Node(strings[name])
    for i in range(count):
        a = ext + attr_start + i * attr_size
        ans, aname, raw, _sz, _res0, typ, adata = struct.unpack_from("<IIIHBBI", data, a)
        key = strings[aname]
        if ans != _NO_INDEX:
            uri = strings[ans]
            prefix = "android" if uri == ANDROID_NS else prefixes.get(uri, uri)
            key = f"{prefix}:{key}"
        node.attrs[key] = _value(strings, raw, typ, adata)
    parent.children.append(node)
    return node


def parse_text_manifest(text: str) -> Manifest:
    """A text manifest (Gradle's merged one) as the same model."""

    def convert(el: ElementTree.Element) -> Node:
        attrs = {}
        for key, value in el.attrib.items():
            if key.startswith("{"):
                uri, local = key[1:].split("}", 1)
                prefix = "android" if uri == ANDROID_NS else "tools" if uri == TOOLS_NS else uri
                key = f"{prefix}:{local}"
            attrs[key] = value
        return Node(el.tag, attrs, [convert(c) for c in el])

    return manifest_from_tree(convert(ElementTree.fromstring(text)))


def manifest_from_tree(root: Node) -> Manifest:
    if root.tag != "manifest":
        raise AxmlError("not a manifest")
    package = root.attrs.get("package", "")
    perms = tuple(
        c.attrs.get("android:name", "")
        for c in root.children
        if c.tag in ("uses-permission", "uses-permission-sdk-23")
    )
    declared = tuple(
        (c.attrs.get("android:name", ""), c.attrs.get("android:protectionLevel", ""))
        for c in root.children
        if c.tag == "permission"
    )
    app = next((c for c in root.children if c.tag == "application"), Node("application"))
    comps = tuple(_component(c, package) for c in app.children if c.tag in _COMPONENTS)
    return Manifest(package, perms, declared, comps, tuple(sorted(app.attrs.items())))


def _component(c: Node, package: str) -> Component:
    name = c.attrs.get("android:name", "")
    if name.startswith("."):
        name = package + name
    filters = [f for f in c.children if f.tag == "intent-filter"]
    exported_attr = c.attrs.get("android:exported")
    if exported_attr is None:
        exported = bool(filters) and c.tag != "provider"
    else:
        # fail closed: only the literal false is "not reachable" (a resource reference such as
        # "@bool/x" can be true on some phones)
        exported = exported_attr != "false"
    meta = tuple(
        (
            m.attrs.get("android:name", ""),
            m.attrs.get("android:value", m.attrs.get("android:resource", "")),
        )
        for m in c.children
        if m.tag == "meta-data"
    )
    return Component(
        c.tag,
        name,
        exported,
        c.attrs.get("android:permission") or None,
        meta,
        tuple(_filter(f) for f in filters),
    )


def _filter(node: Node) -> Filter:
    def names(tag: str) -> frozenset[str]:
        return frozenset(k.attrs.get("android:name", "") for k in node.children if k.tag == tag)

    data = frozenset(
        tuple(sorted((k.removeprefix("android:"), v) for k, v in d.attrs.items()))
        for d in node.children
        if d.tag == "data"
    )
    return Filter(names("action"), names("category"), data)


def summary(m: Manifest) -> tuple[object, ...]:
    """What the decoder and the merged manifest must agree on."""
    flags = tuple(
        m.app_attr(k)
        for k in ("android:debuggable", "android:usesCleartextTraffic", "android:allowBackup")
    )
    return (
        m.package,
        tuple(sorted(m.permissions)),
        tuple(sorted((c.kind, c.name, c.exported, c.permission or "") for c in m.components)),
        tuple(
            sorted((c.name, tuple(sorted(f.signature() for f in c.filters))) for c in m.components)
        ),
        flags,
        m.app_attr("android:dataExtractionRules") is not None,
    )


# ---- the rules --------------------------------------------------------------------------------
def check_manifest(m: Manifest, host: str = PLACEHOLDER) -> list[str]:
    out: list[str] = []
    if m.package != PACKAGE:
        out.append(f"the package is {m.package!r}, not {PACKAGE}")
    for perm in sorted(set(m.permissions)):
        if perm in FORBIDDEN_PERMISSIONS:
            out.append(f"a forbidden permission: {perm}")
        elif perm not in ALLOWED_PERMISSIONS:
            out.append(f"a permission not on the list: {perm}")
    for perm in sorted(REQUIRED_PERMISSIONS - set(m.permissions)):
        out.append(f"a needed permission is missing: {perm}")
    for name, level in m.declared:
        if name != _DECLARED_OK or level not in _SIGNATURE:
            out.append(f"a declared permission not on the list: {name} ({level})")
    out += _check_reachable(m)
    out += _check_app(m, host)
    return out


def _check_reachable(m: Manifest) -> list[str]:
    out = []
    present = {c.name for c in m.components if c.exported}
    for c in m.components:
        if not c.exported:
            continue
        rule = REACHABLE.get(c.name)
        if rule is None:
            out.append(f"reachable from outside but not on the list: {c.kind} {c.name}")
        elif rule.permission and c.permission != rule.permission:
            out.append(f"{c.name} must be guarded by {rule.permission} (has {c.permission})")
        out += _check_filters(c, rule)
    for name, rule in REACHABLE.items():
        if rule.ours and name not in present:
            out.append(f"one of the app's own reachable parts is missing: {name}")
    return out


def _check_filters(c: Component, rule: Reach | None) -> list[str]:
    """What a reachable part accepts: never an App Link, and (for ours) nothing but the list."""
    out = []
    for f in c.filters:
        if "android.intent.category.BROWSABLE" in f.categories:
            out.append(f"{c.name} has a BROWSABLE intent filter (a web link would open it)")
        for item in f.data:
            extra = sorted(k for k, _ in item if k != "mimeType")
            if extra:
                out.append(f"{c.name} has an intent filter with address data ({', '.join(extra)})")
    if rule is not None and rule.filters is not None and set(c.filters) != set(rule.filters):
        for f in sorted(set(c.filters) - set(rule.filters), key=Filter.signature):
            out.append(f"{c.name} has an intent filter that is not on the list: {f.signature()}")
        for f in sorted(set(rule.filters) - set(c.filters), key=Filter.signature):
            out.append(f"{c.name} lacks an intent filter on the list: {f.signature()}")
    return out


def _check_app(m: Manifest, host: str) -> list[str]:
    out = []
    if m.app_attr("android:debuggable") == "true":
        out.append("the build is debuggable")
    if m.app_attr("android:usesCleartextTraffic") == "true":
        out.append("cleartext (plain HTTP) traffic is switched on")
    if m.app_attr("android:allowBackup") != "false":
        out.append("allowBackup is not false")
    if m.app_attr("android:dataExtractionRules") is None:
        out.append("dataExtractionRules is missing")
    launcher = next((c for c in m.components if c.name == ICON_LAUNCHER), None)
    urls = dict(launcher.meta).get(DEFAULT_URL, "") if launcher else ""
    if not urls.startswith(f"https://{host}/"):
        out.append(f"the icon's DEFAULT_URL is {urls!r}, not https://{host}/…")
    return out


def _text_forms(data: bytes) -> Iterable[bytes]:
    yield data
    for start in (0, 1):  # UTF-16 strings (string pools of manifests and resources)
        yield data[start:].decode("utf-16-le", errors="ignore").encode("utf-8", errors="ignore")


def hosts_in(data: bytes, bare: bool = False) -> set[str]:
    """Host names written in `data`: from an http(s) address, of a private hosting service and
    (with `bare`) any dotted name that ends in a public suffix."""
    found: set[str] = set()
    for form in _text_forms(data):
        found |= {m.group(1).decode("ascii", "ignore").lower() for m in _URL.finditer(form)}
        found |= {m.group(0).decode("ascii", "ignore").lower() for m in _PRIVATE.finditer(form)}
        if bare:
            found |= {m.group(1).decode("ascii", "ignore").lower() for m in _BARE.finditer(form)}
    return found


def _is_resource_text(name: str) -> bool:
    return name.startswith("res/") and name.endswith(".xml")


def scan_entry(name: str, data: bytes, host: str = PLACEHOLDER) -> list[str]:
    out = []
    allowed = ALLOWED_HOSTS | {host}
    for form in _text_forms(data):
        if _USERINFO.search(form):
            out.append(f"a web address with a user name in it in {name}")
            break
    for h in sorted(hosts_in(data, bare=_is_resource_text(name))):
        private = h.endswith(PRIVATE_SUFFIXES) and h != host
        if private or h not in allowed:
            out.append(f"a host name in {name}: {h}")
    for kind, pattern in SECRET_SHAPES:
        for form in _text_forms(data):
            if pattern.search(form):
                out.append(f"a secret-shaped string ({kind}) in {name}")
                break
    return out


def _network_configs(z: zipfile.ZipFile) -> list[str]:
    out = []
    for name in z.namelist():
        if not (name.startswith("res/") and name.endswith(".xml")):
            continue
        try:
            root = decode_axml(z.read(name))
        except AxmlError:
            continue
        for node in _walk(root):
            if node.attrs.get("cleartextTrafficPermitted") == "true":
                out.append(f"cleartext traffic is permitted in {name}")
            if node.tag == "certificates" and "user" in node.attrs.get("src", ""):
                out.append(f"user certificates are trusted in {name}")
    return out


def _walk(node: Node) -> Iterable[Node]:
    yield node
    for c in node.children:
        yield from _walk(c)


def _read_manifest(z: zipfile.ZipFile) -> Manifest:
    return manifest_from_tree(decode_axml(z.read("AndroidManifest.xml")))


def check_apk(path: Path, host: str = PLACEHOLDER, merged: Path | None = None) -> list[str]:
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"not an APK: {path.name} ({exc})"]
    with z:
        if "AndroidManifest.xml" not in z.namelist():
            return ["the APK has no AndroidManifest.xml"]
        try:
            manifest = _read_manifest(z)
        except AxmlError as exc:
            return [f"the manifest cannot be read: {exc}"]
        out = check_manifest(manifest, host)
        out += _network_configs(z)
        for name in z.namelist():
            if _SECRET_FILES.search(name):
                out.append(f"a key or machine-local file inside the app: {name}")
            out += scan_entry(name, z.read(name), host)
    if merged is not None:
        other = parse_text_manifest(merged.read_text(encoding="utf-8"))
        if summary(other) != summary(manifest):
            out.append("the decoded manifest and Gradle's merged manifest disagree")
    return out


def report(path: Path, host: str = PLACEHOLDER, out: TextIO = sys.stdout) -> None:
    """What the app holds, for the reviewed lists (CI prints it on every run)."""
    with zipfile.ZipFile(path) as z:
        m = _read_manifest(z)
        hosts = sorted({h for name in z.namelist() for h in hosts_in(z.read(name))})
    print(f"package: {m.package}", file=out)
    for perm in sorted(set(m.permissions)):
        print(f"permission: {perm}", file=out)
    for c in sorted(m.components, key=lambda c: c.name):
        if c.exported:
            print(f"reachable: {c.kind} {c.name} (guard: {c.permission})", file=out)
    for h in hosts:
        print(f"host: {h}", file=out)


def _find_apk(target: Path) -> Path | None:
    if target.is_file():
        return target
    apks = sorted(target.glob("*.apk")) if target.is_dir() else []
    return apks[0] if len(apks) == 1 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="the APK, or the folder holding exactly one")
    parser.add_argument("--host", default=PLACEHOLDER, help="the address the app was built for")
    parser.add_argument("--merged", type=Path, help="Gradle's merged AndroidManifest.xml")
    args = parser.parse_args(argv)
    apk = _find_apk(args.target)
    if apk is None:
        print(f"apk_check: no single .apk at {args.target}")
        return 1
    problems = check_apk(apk, args.host, args.merged)
    try:
        report(apk, args.host)  # printed on every run: the reviewed lists are built from it
    except (OSError, zipfile.BadZipFile, KeyError, AxmlError) as exc:
        print(f"apk_check: no report ({exc})")
    for p in problems:
        print(f"apk_check: {p}")
    print(
        f"apk_check: {apk.name}: " + ("passed" if not problems else f"{len(problems)} problem(s)")
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
