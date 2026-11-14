# src/jarvis/mobile/ports.py
"""The plug-in contract of R7 (docs/plans/r7-mobile.md "The I0 seams" 8, 20).

Four server parts are built in parallel (Part E, the Android app, has no server part). Each owns
a module whose `build(ctx: MobileContext) -> MobilePart` gets what it may use and hands back what
the app wires for it; no part edits a wiring file.

| Part     | Deliverables         | Module                 | Routes under                         |
|----------|----------------------|------------------------|--------------------------------------|
| `shell`  | A: 1, 3 (web side)   | `jarvis.api.app_shell` | `/app`, `/manifest.webmanifest`      |
| `vision` | B: 2, 8              | `jarvis.vision.part`   | `/v1/vision`                         |
| `phone`  | C: 1, 4 (server)     | `jarvis.phone.part`    | `/v1/phone`, `/phone`, asset links   |
| `body`   | D: 5, 6, 7           | `jarvis.watch.part`    | `/v1/watch`, `/v1/sos`               |

- `MobilePart`: R11.1's part fields (`FixPart`): its tools (registered through the gateway; names
  inside its `TOOL_FAMILIES`), its jobs for the helpers' 5-minute clock (`clock_jobs`: the
  `watch_stale` check) and the morning tick (`daily_jobs`: the 400-day and 90-day sweeps), its
  privacy rows (`PrivacySource`s), the services its own routes read from
  `app.state.r7_parts[<part>].services`, and one plain status word (`ready`). Named services the
  wiring reads: `phrases` (No-AI routers), `brief` (a brief contributor), `door` ({door route:
  `PhoneHandler`}, only the routes `DOOR_OWNER` gives the part), `app_lock` (phone only: an async
  `(scope) -> bool` that says a cookie session is locked) and `sos_hook` (body only: the code
  behind the Telegram hook, `jarvis.sos.hook.SosHook`).
- `MobileContext`: as `FixContext`: the settings, the document store, the audit chain, a LATE
  `state(name)` read of `app.state.<name>` (None when absent) and the app's one notifier.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Literal, get_args

if TYPE_CHECKING:
    from jarvis.config import Settings
    from jarvis.notify.ports import Notifier
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.base import Tool

PartName = Literal["shell", "vision", "phone", "body"]
PARTS: tuple[PartName, ...] = get_args(PartName)
NOT_BUILT = "not built yet"
PACKAGE = "io.github.shark2558.jarvis"  # the one app the server accepts (D5; owner question 15)

# The tool names a part may register (fnmatch patterns). `sos_status` is the brain's ONLY SOS
# tool (a read): no tool sends an SOS (D19). The shell and the phone give the brain nothing.
TOOL_FAMILIES: Mapping[PartName, tuple[str, ...]] = {
    "shell": (),
    "vision": ("vision_*",),
    "phone": (),
    "body": ("watch_*", "sleep_*", "sos_status"),
}
ROUTE_PREFIX: Mapping[PartName, tuple[str, ...]] = {
    "shell": ("/app", "/manifest.webmanifest"),
    "vision": ("/v1/vision",),
    "phone": ("/v1/phone", "/phone", "/.well-known/assetlinks.json", "/v1/session"),
    "body": ("/v1/watch", "/v1/sos"),
}
STATUS_ROUTE: Mapping[PartName, str] = {
    "shell": "/app/status",
    "vision": "/v1/vision",
    "phone": "/v1/phone",
    "body": "/v1/watch",
}
# Firestore collections (all `{prefix}<name>/...`); the guide's cards C62-C65 list every one.
COLLECTIONS: Mapping[PartName, tuple[str, ...]] = {
    "shell": (),
    "vision": ("vision_results",),
    "phone": ("phone_link", "phone_devices"),
    "body": ("watch_days", "watch_state", "sos", "sos_join", "sos_log"),
}

# ---- the phone's door (D6): four signed routes, each owned by one part ---------------------
DOOR_PREFIX = "/phone/v1/"
DoorRoute = Literal["hello", "health", "inbox", "sos"]
DOOR_ROUTES: tuple[DoorRoute, ...] = get_args(DoorRoute)
DOOR_OWNER: Mapping[str, PartName] = {
    "hello": "phone",
    "health": "body",
    "inbox": "phone",
    "sos": "body",
}
_KB = 1024
DOOR_CAPS: Mapping[str, int] = {  # the body cap of each route, checked before any parsing
    "hello": 16 * _KB,
    "health": 256 * _KB,  # 35 days of daily sums at most
    "inbox": 10 * _KB * _KB + 64 * _KB,  # one file of at most 10 MB and its first line
    "sos": 16 * _KB,
}
# The four launch words (D8): a launch address opens a screen and never acts.
LAUNCH_WORDS: tuple[str, ...] = ("talk", "look", "sos", "shared")


@dataclass(frozen=True)
class PhoneRequest:
    """A door request that passed every check of D6 (route, no query, cap, header, device,
    time, nonce, signature, rate): what a handler gets. `body` is exactly the signed bytes."""

    route: str
    device_id: str
    uid: str
    body: bytes
    at: float


@dataclass(frozen=True)
class PhoneReply:
    status: int
    body: Mapping[str, Any]


PhoneHandler = Callable[[PhoneRequest], Awaitable[PhoneReply]]

# ---- the app lock (D21): what is never locked ----------------------------------------------
NEVER_LOCKED_EXACT: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/console/config"),
        ("POST", "/v1/passkeys/challenge"),
        ("POST", "/v1/session/unlock"),
        ("GET", "/manifest.webmanifest"),
        ("GET", "/.well-known/assetlinks.json"),
    }
)
NEVER_LOCKED_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/auth/",
    "/app/share/",
    "/v1/sos/",
    DOOR_PREFIX,  # cookie-less anyway: the lock only ever reads a cookie session
)
_NEVER_LOCKED_ROOTS = frozenset({"/v1/sos"})


def never_locked(method: str, path: str) -> bool:
    """D21's list: these answer while the app is locked (sign-in, the page itself, the unlock
    ceremony, the public files, the share tray and every SOS route)."""
    if (method.upper(), path) in NEVER_LOCKED_EXACT or path in _NEVER_LOCKED_ROOTS:
        return True
    return path.startswith(NEVER_LOCKED_PREFIXES)


def tool_allowed(part: PartName, tool: str) -> bool:
    return any(fnmatchcase(tool, pattern) for pattern in TOOL_FAMILIES[part])


@dataclass(frozen=True)
class MobilePart:
    name: PartName
    tools: tuple[Tool, ...] = ()
    clock_jobs: tuple[TickJob, ...] = ()
    daily_jobs: tuple[TickJob, ...] = ()
    privacy: tuple[PrivacySource, ...] = ()
    services: Mapping[str, Any] = field(default_factory=dict)
    ready: str = NOT_BUILT


@dataclass(frozen=True)
class MobileContext:
    s: Settings
    docs: Docs | None
    audit: AuditTrail | None
    state: Callable[[str], Any]
    notifier: Callable[[], Notifier] | None = None

    @property
    def prefix(self) -> str:
        return self.s.firestore_prefix


__all__ = [
    "COLLECTIONS",
    "DOOR_CAPS",
    "DOOR_OWNER",
    "DOOR_PREFIX",
    "DOOR_ROUTES",
    "LAUNCH_WORDS",
    "NEVER_LOCKED_EXACT",
    "NEVER_LOCKED_PREFIXES",
    "NOT_BUILT",
    "PACKAGE",
    "PARTS",
    "ROUTE_PREFIX",
    "STATUS_ROUTE",
    "TOOL_FAMILIES",
    "DoorRoute",
    "MobileContext",
    "MobilePart",
    "PartName",
    "PhoneHandler",
    "PhoneReply",
    "PhoneRequest",
    "never_locked",
    "tool_allowed",
]
