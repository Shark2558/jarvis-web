# tests/test_r3_seams.py
"""R3 I0 seams: the shared hooks the four R3 workstreams build on (docs/plans/r3-home-camera.md).

The R3 alert kinds and the sink's silent / photo keywords, the notify ports (Signal, Decision,
Delivery, the policy and notifier protocols, DirectNotifier), the home wire (signing, events,
bridge state, the caller and handler ports), the faces port, the bridge plugin seam, the keyring
purposes, the five permission rows and the home_disarm passkey purpose, one scheduler audience per
route, the console CSP's worker-src, the R3 settings, the bridge extra and the Telegram home group.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import inspect
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from telegram_fakes import UID as TG_UID
from telegram_fakes import Clock as TgClock
from telegram_fakes import build_world
from test_permissions_service import UID, Rig
from test_scheduler_auth import KEY as OIDC_KEY
from test_scheduler_auth import SA, FakeJWKS, token
from test_scheduler_auth import Clock as OidcClock

from jarvis.alerts import HOME_ALERT_KINDS, AlertKind, AlertResult, AlertSink, NoAlerts
from jarvis.api.console import CONSOLE_CSP
from jarvis.api.scheduler_auth import (
    SCHEDULER_PATHS,
    TICK_PATH,
    WATCHDOG_PATH,
    GoogleOIDCVerifier,
    SchedulerUnauthorized,
    require_scheduler,
)
from jarvis.config import Settings
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.faces.ports import (
    FAMILY_CHILD,
    RECOGNISED_PERSON,
    RECOGNITION_THRESHOLD,
    UNKNOWN,
    UNKNOWN_PERSON,
    FaceDirectory,
    NoFaces,
    Resolved,
    is_person_id,
)
from jarvis.home import signing
from jarvis.home.ports import (
    BRIDGE_ROUTES,
    HOME_NOT_LINKED,
    HOME_OFFLINE,
    LABELS,
    MAX_EVENT_BYTES,
    MAX_SNAPSHOT_BYTES,
    MAX_WEBHOOK_BYTES,
    ArmReader,
    ArmView,
    BridgeState,
    Detection,
    EventRejected,
    HomeCaller,
    HomeEventHandler,
    HomeOffline,
    HomeRefused,
    HomeUnavailable,
    StateSource,
    parse_event,
    route_allowed,
)
from jarvis.home.signing import (
    HEADER,
    NonceCache,
    SignatureError,
    derive_keys,
    new_seed,
    parse,
    sign,
    sign_response,
    verify,
    verify_response,
)
from jarvis.homebridge.plugins import BridgeContext, BridgePlugin, BridgeRoute, check_routes
from jarvis.homebridge.registry import PLUGINS
from jarvis.integrations.vault import VaultError
from jarvis.keyring import PURPOSES, SECRET_PURPOSES, Keyring
from jarvis.notify.ports import (
    DEFAULT_URGENCY,
    Action,
    Decision,
    Delivery,
    DirectNotifier,
    Notifier,
    NotifyPolicy,
    Signal,
)
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired
from jarvis.permissions.groups import (
    GROUPS,
    PermissionRejected,
    get_group,
    group_ids,
    groups_for,
    validate_choices,
)
from jarvis.permissions.models import TARGETED_PURPOSES, PermissionsPatch, Purpose
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.models import TelegramLink
from jarvis.telegram.rules import HOME_PATTERNS, HOME_REFUSAL, ChannelRules
from jarvis.telegram.store import TelegramStore
from jarvis.tools.policy import Effect

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
KEY = bytes(range(1, 33))
SEED = bytes(range(100, 132))
NOW = 1_800_000_000.0
HOME = "h_0a1b2c3d"
NONCE = "A" * 22
PERSON = "fp_0123456789ab"
BODY = b'{"type":"heartbeat"}'


# ---- alerts ----------------------------------------------------------------------------------

NEW_KINDS = (
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    "home_offline_idle",  # R5.1 D3
)


def test_r3_alert_kinds_join_the_older_ones() -> None:
    kinds = get_args(AlertKind)
    assert HOME_ALERT_KINDS == NEW_KINDS and set(NEW_KINDS) <= set(kinds)
    for older in ("approval_waiting", "offline_on", "offline_off", "brief_ready", "vault_expiry"):
        assert older in kinds
    # R4 added vitals_warn/vitals_critical/health_fault/health_recovered/health_degraded (14 -> 19)
    # R5.1 added home_offline_idle (19 -> 20)
    # R6 added book_sealed/book_seal_failed/book_session_closed (20 -> 23)
    # R11 added the thirteen helper kinds (23 -> 36; tests/test_r11_seams.py) and R11.1 two more
    # (36 -> 38; tests/test_r11_1_seams.py)
    assert "test" in kinds and len(kinds) == len(set(kinds)) == 38


async def test_the_sink_takes_silent_and_photo_keywords() -> None:
    sig = inspect.signature(AlertSink.send)
    for name, default in (("kind", inspect.Parameter.empty), ("silent", False), ("photo", None)):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters[name].default is default
    off = NoAlerts("Telegram isn't set up")
    assert isinstance(off, AlertSink)
    got = await off.send("u", "x", kind="home_intruder", silent=True, photo=b"\xff\xd8\xff")
    assert got == AlertResult(False, "Telegram isn't set up")


async def test_telegram_alerts_accept_the_keywords_and_send_no_photo_yet() -> None:
    w = build_world()
    await w.pair()
    res = await w.service.alerts.send(
        TG_UID, "Test.", kind="test", silent=True, photo=b"\xff\xd8\xffJPEG"
    )
    assert res.sent is True
    assert not [m for m, _ in w.bot.calls if "photo" in m.lower()]


# ---- notify ports ----------------------------------------------------------------------------


def test_every_alert_kind_has_a_default_urgency() -> None:
    assert set(DEFAULT_URGENCY) == set(get_args(AlertKind))
    urgent = {k for k, v in DEFAULT_URGENCY.items() if v == "urgent"}
    # integrated review H5: a laptop that stopped answering or an alarm that can't work rings.
    # (R4 made a red vitals line / health fault urgent; R5.1 D13 moved them to important.)
    assert urgent == {
        "home_intruder",
        "home_hazard",
        "home_summary",
        "home_offline",
        "home_arm_failed",
        # R5.1 D13: vitals_critical / health_fault are now "important" daytime rings (see
        # tests/test_r51_int_notify.py), no longer urgent.
        "disaster_alert",  # R11 D5: a disaster warning near him rings at night (owner's rule)
    }
    for kind in ("home_package", "approval_waiting"):
        assert DEFAULT_URGENCY[kind] == "important"
    assert DEFAULT_URGENCY["vault_expiry"] == "important"
    for kind in ("home_greeting", "home_online", "offline_on", "offline_off", "brief_ready"):
        assert DEFAULT_URGENCY[kind] == "info"
    with pytest.raises(TypeError):
        DEFAULT_URGENCY["test"] = "info"  # type: ignore[index]


def test_a_signal_is_strict_and_frozen() -> None:
    s = Signal(source="home", kind="home_intruder", camera="gate", person_ref=PERSON, vip=True)
    assert (s.child, s.text) == (False, None)
    for bad in (
        {"source": "home", "kind": "nope"},
        {"source": "email", "kind": "test"},
        {"source": "home", "kind": "test", "camera": "gate/../x"},
        {"source": "home", "kind": "test", "camera": "Gate"},
        {"source": "home", "kind": "test", "extra": 1},
        {"source": "home", "kind": "test", "text": "x" * 4001},
        {"source": "home", "kind": "test", "person_ref": ""},
        {"source": "home", "kind": "test", "vip": "yes"},
    ):
        with pytest.raises(ValidationError):
            Signal(**bad)
    with pytest.raises(ValidationError):
        s.kind = "test"  # type: ignore[misc]


def test_decision_and_delivery_shapes() -> None:
    d = Decision(action="drop", reason="feed_only", urgency="info")
    assert d.action == "drop"
    for bad in (
        {"action": "maybe", "reason": "x", "urgency": "info"},
        {"action": "ring", "reason": "Has Spaces", "urgency": "urgent"},
        {"action": "ring", "reason": "x", "urgency": "loud"},
    ):
        with pytest.raises(ValidationError):
            Decision(**bad)
    words = {a: Delivery(action=a, reason="x").feed_decision for a in get_args(Action)}
    assert words == {"ring": "ring", "silent": "silent", "hold": "held", "drop": "dropped"}
    with pytest.raises(ValidationError):
        Delivery(action="ring", reason="x", push=6)


class _Sink:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, str, str, bool, bytes | None]] = []

    async def send(
        self, uid: str, text: str, *, kind: Any, silent: bool = False, photo: bytes | None = None
    ) -> AlertResult:
        self.sent.append((uid, text, kind, silent, photo))
        return AlertResult(self.ok, "" if self.ok else "down")


async def test_direct_notifier_rings_through_the_sink_without_names_or_photos() -> None:
    sink = _Sink()
    n = DirectNotifier(sink)
    assert isinstance(n, Notifier)
    sig = Signal(source="home", kind="home_intruder", camera="gate", person_ref=PERSON)
    got = await n.notify(
        "u",
        sig,
        "Someone is at the Gate, 23:10.",
        named_message="Anjali is at the Gate, 23:10.",
        photo=b"\xff\xd8\xff",
    )
    assert got == Delivery(action="ring", reason="direct", telegram=True)
    assert sink.sent == [("u", "Someone is at the Gate, 23:10.", "home_intruder", False, None)]
    info = await n.notify("u", Signal(source="home", kind="home_online"), "Your laptop is back.")
    assert info.action == "silent" and sink.sent[-1][3] is True
    down = await DirectNotifier(_Sink(ok=False)).notify("u", sig, "x")
    assert down.telegram is False and down.photo_sent is False


def test_a_policy_satisfies_the_protocol() -> None:
    class Rings:
        def decide(self, signal: Signal, settings: Any, now: datetime) -> Decision:
            return Decision(action="ring", reason="test", urgency="urgent")

    assert isinstance(Rings(), NotifyPolicy)
    sig = Signal(source="nudge", kind="test")
    assert Rings().decide(sig, None, datetime.now(UTC)).action == "ring"


# ---- home signing ----------------------------------------------------------------------------


def _hkdf(seed: bytes, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(seed)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_keys_are_hkdf_of_the_seed_one_per_direction() -> None:
    keys = derive_keys(SEED)
    assert keys.up == _hkdf(SEED, b"jarvis/home/up/v1")
    assert keys.down == _hkdf(SEED, b"jarvis/home/down/v1")
    assert keys.up != keys.down and keys.key("up") == keys.up and keys.key("down") == keys.down
    with pytest.raises(ValueError):
        keys.key("Up")  # type: ignore[arg-type]
    for secret in (SEED, keys.up, keys.down):
        assert secret.hex() not in repr(keys) and _b64(secret) not in repr(keys)
    for bad in (b"", b"x" * 31, b"x" * 33):
        with pytest.raises(ValueError):
            derive_keys(bad)
    assert len(new_seed()) == 32 and new_seed() != new_seed()


def test_the_signed_string_is_the_plans() -> None:
    keys = derive_keys(SEED)
    header = sign(
        keys, "up", home_id=HOME, method="POST", target="/home/webhook", body=BODY, now=NOW,
        nonce=NONCE,
    )  # fmt: skip
    msg = (
        "jarvis-home-v1\nup\n" + HOME + "\n" + str(int(NOW)) + "\n" + NONCE
        + "\nPOST\n/home/webhook\n" + hashlib.sha256(BODY).hexdigest()
    )  # fmt: skip
    mac = _b64(hmac.new(keys.up, msg.encode(), hashlib.sha256).digest())
    assert header == f"v1;h={HOME};t={int(NOW)};n={NONCE};s={mac}"
    assert HEADER == "X-Jarvis-Home"
    signed = parse(header)
    assert (signed.home_id, signed.t, signed.nonce) == (HOME, int(NOW), NONCE)


def _sign(**over: Any) -> str:
    kw: dict[str, Any] = {
        "home_id": HOME, "method": "POST", "target": "/home/webhook", "body": BODY, "now": NOW,
    }  # fmt: skip
    keys = over.pop("keys", derive_keys(SEED))
    direction = over.pop("direction", "up")
    return sign(keys, direction, **{**kw, **over})


def _verify(header: str, *, nonces: NonceCache | None = None, **over: Any) -> None:
    kw: dict[str, Any] = {"method": "POST", "target": "/home/webhook", "body": BODY, "now": NOW}
    keys = over.pop("keys", derive_keys(SEED))
    direction = over.pop("direction", "up")
    verify(parse(header), keys, direction, nonces=nonces or NonceCache(), **{**kw, **over})


def test_a_good_signature_verifies_once() -> None:
    nonces = NonceCache()
    header = _sign()
    _verify(header, nonces=nonces)
    with pytest.raises(SignatureError) as err:
        _verify(header, nonces=nonces)
    assert err.value.check == "nonce"
    _verify(_sign(now=NOW + 60), now=NOW)  # 60 s of skew either way is fine
    _verify(_sign(now=NOW - 60), now=NOW)


@pytest.mark.parametrize(
    ("signed_with", "verified_with", "check"),
    [
        ({"keys": derive_keys(bytes(range(32)))}, {}, "mac"),  # another home's key
        ({"direction": "down"}, {}, "mac"),  # the down-key used upward
        ({}, {"keys": derive_keys(SEED), "direction": "down"}, "mac"),  # reflected downward
        ({"body": b'{"type":"ack"}'}, {}, "mac"),  # a signature over another body
        ({"target": "/home/link"}, {}, "mac"),  # another path
        ({"method": "GET"}, {}, "mac"),  # another method
        ({"now": NOW - 61}, {}, "time"),  # 61 s old
        ({"now": NOW + 61}, {}, "time"),  # 61 s ahead
    ],
)
def test_every_forgery_fails_its_own_check(
    signed_with: dict[str, Any], verified_with: dict[str, Any], check: str
) -> None:
    with pytest.raises(SignatureError) as err:
        _verify(_sign(**signed_with), **verified_with)
    assert err.value.check == check
    assert "h_" not in str(err.value) and NONCE not in str(err.value)


def test_the_home_id_is_inside_the_mac() -> None:
    moved = _sign().replace(f"h={HOME}", "h=h_ffffffff")  # same keys, another home's header
    with pytest.raises(SignatureError) as err:
        _verify(moved)
    assert err.value.check == "mac"


def test_the_header_shape_is_checked_before_anything() -> None:
    good = _sign(nonce=NONCE)
    for bad in (
        None,
        "",
        good.replace("v1;", "v2;"),
        good + "x",
        good.replace("h=h_", "h=x_"),
        good.replace(f"n={NONCE}", "n=short"),
        good.replace(";t=", ";t=-"),
        f"v1;h={HOME};t=1;n={NONCE};s=" + "a" * 43 + "\n",
        "a" * 500,
    ):
        with pytest.raises(SignatureError) as err:
            parse(bad)
        assert err.value.check == "shape"


def test_targets_with_spaces_or_control_characters_are_refused() -> None:
    for target in ("/home/webhook\nPOST", "home/webhook", "/home web", ""):
        with pytest.raises(ValueError):
            _sign(target=target)
        with pytest.raises(SignatureError):
            _verify(_sign(), target=target)


def test_the_mac_compare_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(signing.hmac, "compare_digest", spy)
    _verify(_sign())
    assert calls


def test_a_bad_signature_never_burns_the_nonce() -> None:
    nonces = NonceCache()
    good = _sign(nonce=NONCE)
    bad = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    with pytest.raises(SignatureError):
        _verify(bad, nonces=nonces)
    _verify(good, nonces=nonces)


def test_the_nonce_cache_expires_and_fails_closed_when_full() -> None:
    c = NonceCache(ttl_s=300, max_entries=2)
    c.remember(HOME, "a" * 22, NOW)
    c.remember(HOME, "b" * 22, NOW)
    assert c.seen(HOME, "a" * 22, NOW + 299) and not c.seen(HOME, "a" * 22, NOW + 301)
    assert not c.seen("h_ffffffff", "a" * 22, NOW)  # per home
    with pytest.raises(SignatureError) as err:
        c.remember(HOME, "c" * 22, NOW + 1)
    assert err.value.check == "nonce"
    c.remember(HOME, "c" * 22, NOW + 301)  # the old ones expired and were pruned


def _response(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "home_id": HOME, "request_nonce": "R" * 22, "status": 200, "method": "POST",
        "target": "/home/webhook", "body": b"{}", "now": NOW,
    }  # fmt: skip
    return {**base, **over}


def test_responses_are_bound_to_their_request() -> None:
    keys = derive_keys(SEED)
    header = sign_response(keys, "down", **_response())
    verify_response(header, keys, "down", **_response())
    for over in (
        {"request_nonce": "S" * 22},
        {"status": 401},
        {"body": b'{"x":1}'},
        {"target": "/bridge/v1/health"},
        {"method": "GET"},
        {"home_id": "h_ffffffff"},
        {"now": NOW + 61},
    ):
        with pytest.raises(SignatureError):
            verify_response(header, keys, "down", **_response(**over))
    with pytest.raises(SignatureError):  # the direction is part of it
        verify_response(header, keys, "up", **_response())
    req = sign(
        keys, "down", home_id=HOME, method="POST", target="/home/webhook", body=b"{}", now=NOW,
        nonce="R" * 22,
    )  # fmt: skip
    with pytest.raises(SignatureError):  # a request signature is never a response signature
        verify_response(req, keys, "down", **_response())


# ---- home events and the bridge state ----------------------------------------------------------

HEARTBEAT = {
    "type": "heartbeat",
    "id": "hb-1",
    "at": NOW,
    "bridge_version": "0.3.0",
    "state_rev": 4,
    "parts": {
        "ha": True,
        "frigate": True,
        "cameras": [{"id": "gate", "online": True}],
        "doorstep_model": False,
        "faces": {PERSON: 6},
    },
}
DETECTION = {
    "type": "detection",
    "id": "1800000000.123456-abc123",
    "camera": "gate",
    "zones": ["gate"],
    "label": "person",
    "start": NOW,
    "end": None,
    "score": 0.87,
    "face": {"person": PERSON, "score": 0.93},
}
FACE_SEEN = {
    "type": "face_seen",
    "id": "1800000000.123456-abc123:face",
    "event": "1800000000.123456-abc123",
    "camera": "gate",
    "zones": ["gate"],
    "at": NOW,
    "face": {"person": PERSON, "score": 0.95},
}
PACKAGE = {
    "type": "package",
    "id": "pkg-1",
    "camera": "gate",
    "zone": "doorstep",
    "state": "package",
    "at": NOW,
    "delivered": True,
}
HAZARD = {
    "type": "hazard",
    "id": "hz-1",
    "entity": "binary_sensor.kitchen_smoke",
    "device_class": "smoke",
    "state": "on",
    "at": NOW,
}
ACK = {"type": "ack", "id": "ack-1", "at": NOW, "what": "state", "rev": 4, "person": None}
EVENTS = (HEARTBEAT, DETECTION, FACE_SEEN, PACKAGE, HAZARD, ACK)


def _raw(event: dict[str, Any], **over: Any) -> bytes:
    return json.dumps({**event, **over}).encode()


@pytest.mark.parametrize("event", EVENTS, ids=[e["type"] for e in EVENTS])
def test_each_event_type_parses(event: dict[str, Any]) -> None:
    got = parse_event(_raw(event))
    assert got.type == event["type"] and got.id == event["id"]


@pytest.mark.parametrize(
    ("event", "over"),
    [
        (DETECTION, {"extra": 1}),
        (DETECTION, {"label": "package"}),
        (DETECTION, {"label": "gun"}),
        (DETECTION, {"camera": "gate/1"}),
        (DETECTION, {"camera": "Gate"}),
        (DETECTION, {"zones": ["gate"] * 9}),
        (DETECTION, {"score": 1.5}),
        (DETECTION, {"score": "0.9"}),
        (DETECTION, {"start": -1}),
        (DETECTION, {"face": {"person": "anjali", "score": 0.95}}),
        (DETECTION, {"face": {"person": PERSON, "score": 0.95, "name": "Anjali"}}),
        (DETECTION, {"type": "intruder"}),
        (DETECTION, {"id": "a/b"}),
        (HEARTBEAT, {"bridge_version": "1.0"}),
        (HEARTBEAT, {"state_rev": "4"}),
        (HEARTBEAT, {"parts": {"ha": "yes"}}),
        (HEARTBEAT, {"parts": {"faces": {"anjali": 3}}}),
        (HAZARD, {"device_class": "door"}),
        (HAZARD, {"entity": "binary_sensor.Kitchen"}),
        (PACKAGE, {"state": "maybe"}),
        (ACK, {"what": "everything"}),
    ],
)
def test_the_vocabulary_is_strict(event: dict[str, Any], over: dict[str, Any]) -> None:
    with pytest.raises(EventRejected) as err:
        parse_event(_raw(event, **over))
    assert err.value.code == "invalid" and str(err.value) == "invalid"


def _jpeg(size: int) -> str:
    return base64.b64encode(b"\xff\xd8\xff" + b"\x00" * (size - 3)).decode()


def test_sizes_and_the_one_snapshot_path() -> None:
    assert (MAX_EVENT_BYTES, MAX_WEBHOOK_BYTES, MAX_SNAPSHOT_BYTES) == (16_384, 131_072, 81_920)
    padded = b" " * MAX_EVENT_BYTES + _raw(DETECTION)
    with pytest.raises(EventRejected) as err:
        parse_event(padded)  # past 16 KB without a snapshot
    assert err.value.code == "too_large"
    with pytest.raises(EventRejected):
        parse_event(b" " * MAX_WEBHOOK_BYTES + _raw(HEARTBEAT))
    snap = parse_event(_raw(DETECTION, snapshot=_jpeg(60_000)))
    assert isinstance(snap, Detection) and snap.snapshot_bytes() == base64.b64decode(_jpeg(60_000))
    assert isinstance(parse_event(_raw(DETECTION)), Detection)
    plain = parse_event(_raw(DETECTION))
    assert isinstance(plain, Detection) and plain.snapshot_bytes() is None
    for bad in (
        {"snapshot": _jpeg(1000), "label": "car"},  # only with a person
        {"snapshot": base64.b64encode(b"\x89PNG" + b"\x00" * 100).decode()},  # JPEG only
        {"snapshot": _jpeg(MAX_SNAPSHOT_BYTES + 1)},
        {"snapshot": "not base64!"},
    ):
        with pytest.raises(EventRejected):
            parse_event(_raw(DETECTION, **bad))


def test_the_bridge_state_round_trips_and_merges() -> None:
    arm = BridgeState.model_validate({"arm": {"armed": True, "mode": "night", "rev": 3}})
    faces = BridgeState.model_validate({"faces": {"rev": 2, "people": [PERSON], "deleting": []}})
    settings = BridgeState.model_validate(
        {
            "settings": {
                "rev": 1,
                "cameras": {"gate": {"alarm_zones": ["gate"], "package_zone": "doorstep"}},
            }
        }
    )
    devices = BridgeState.model_validate(
        {"devices": {"rev": 1, "exposed": [{"entity_id": "light.porch", "tier": "everyday"}]}}
    )
    both = arm.merged(faces).merged(settings).merged(devices)
    assert both.arm == arm.arm and both.faces == faces.faces and both.devices == devices.devices
    assert both.settings is not None and both.settings.snapshot is False  # D12: off by default
    assert both.settings.greetings is False and both.settings.packages is False
    assert both.settings.retention_days == 7 and both.settings.heartbeat_s == 120
    again = BridgeState.model_validate_json(both.model_dump_json())
    assert again == both
    for bad in (
        {"arm": {"armed": "yes", "rev": 1}},
        {"arm": {"armed": True, "mode": "holiday", "rev": 1}},
        {"faces": {"rev": 1, "people": ["Anjali"]}},
        {"devices": {"rev": 1, "exposed": [{"entity_id": "script.x", "tier": "admin"}]}},
        {"settings": {"rev": 1, "retention_days": 31}},
        {"settings": {"rev": 1, "heartbeat_s": 30}},
        {"other": {}},
    ):
        with pytest.raises(ValidationError):
            BridgeState.model_validate(bad)


def test_bridge_routes_are_the_fixed_list() -> None:
    assert BRIDGE_ROUTES == frozenset(
        {
            ("GET", "/bridge/v1/health"),
            ("POST", "/bridge/v1/state"),
            ("GET", "/bridge/v1/devices"),
            ("POST", "/bridge/v1/devices/action"),
            ("GET", "/bridge/v1/events"),
            ("GET", "/bridge/v1/packages"),
            ("GET", "/bridge/v1/faces/summary"),
            # R4 C (D-C3): picked photos and consented enrolment; the kit serves them later
            ("POST", "/bridge/v1/faces/photos"),
            ("POST", "/bridge/v1/faces/enrol"),
            # R11.1 C (D15, D21-C): the unnamed groups, and forgetting them
            ("GET", "/bridge/v1/faces/groups"),
            ("POST", "/bridge/v1/faces/groups/forget"),
        }
    )
    assert route_allowed("GET", "/bridge/v1/health")
    assert not route_allowed("POST", "/bridge/v1/health")
    assert not route_allowed("GET", "/api/states")
    assert LABELS == ("person", "car", "motorcycle", "bicycle", "dog", "cat")


def test_home_errors_carry_plain_words_and_a_code() -> None:
    off = HomeOffline()
    assert isinstance(off, HomeUnavailable) and str(off) == HOME_OFFLINE and off.code == "offline"
    assert "laptop is off, asleep or offline" in HOME_OFFLINE
    refused = HomeRefused("not_linked", HOME_NOT_LINKED)
    assert refused.code == "not_linked" and "Integrations" in str(refused)
    assert HOME_OFFLINE.isascii() and HOME_NOT_LINKED.isascii()


def test_the_cloud_ports_are_protocols() -> None:
    class Handler:
        handles = frozenset({"detection", "ack"})

        async def handle(self, uid: str, event: Any) -> None:
            return None

    class Caller:
        async def call(
            self, uid: str, method: Any, path: str, body: Any = None, *, query: Any = None
        ) -> dict[str, Any]:
            raise HomeOffline()

    class Arms:
        async def view(self, uid: str) -> ArmView:
            return ArmView(armed=True, mode="away", rev=2, confirmed=False, pending_since=NOW)

    class Parts:
        async def state_part(self, uid: str) -> BridgeState:
            return BridgeState()

    assert isinstance(Handler(), HomeEventHandler) and isinstance(Caller(), HomeCaller)
    assert isinstance(Arms(), ArmReader) and isinstance(Parts(), StateSource)


# ---- faces port ------------------------------------------------------------------------------


async def test_no_faces_names_nobody() -> None:
    d = NoFaces()
    assert isinstance(d, FaceDirectory)
    for person, score in ((PERSON, 0.99), (None, None), ("Anjali", 1.0)):
        assert await d.resolve("u", person, score) == UNKNOWN
    assert UNKNOWN == Resolved() and not UNKNOWN.named


def test_only_a_named_person_can_be_vip_or_a_child() -> None:
    r = Resolved(name="Anjali", person=PERSON, vip=True, child=False)
    assert r.named and r.vip
    for bad in (
        {"vip": True},
        {"child": True},
        {"person": PERSON},
        {"name": "Anjali"},
        {"name": "Anjali", "person": "anjali"},
        {"name": "", "person": PERSON},
    ):
        with pytest.raises(ValueError):
            Resolved(**bad)


def test_the_shared_words_and_threshold() -> None:
    assert UNKNOWN_PERSON == "someone JARVIS didn't recognise"
    assert RECOGNISED_PERSON == "a person JARVIS recognised"
    assert FAMILY_CHILD == "a child from your family"
    assert RECOGNITION_THRESHOLD == 0.9
    assert is_person_id(PERSON) and not is_person_id("fp_0123") and not is_person_id(None)
    assert not is_person_id("FP_0123456789AB") and not is_person_id(PERSON + "\n")


# ---- the bridge plugin seam --------------------------------------------------------------------


async def _ok(query: Any, body: Any) -> dict[str, Any]:
    return {}


def test_a_bridge_route_must_be_one_of_the_fixed_routes() -> None:
    BridgeRoute("GET", "/bridge/v1/events", _ok)
    for method, path in (("GET", "/bridge/v1/admin"), ("POST", "/bridge/v1/events"), ("GET", "")):
        with pytest.raises(ValueError):
            BridgeRoute(method, path, _ok)  # type: ignore[arg-type]


class _Plugin:
    def __init__(self, name: str, routes: tuple[BridgeRoute, ...] = ()) -> None:
        self.name = name
        self._routes = routes

    def routes(self) -> tuple[BridgeRoute, ...]:
        return self._routes

    def tasks(self) -> tuple[Any, ...]:
        return ()

    async def heartbeat_part(self) -> Any:
        from jarvis.home.ports import HeartbeatParts

        return HeartbeatParts()

    async def apply_state(self, state: BridgeState) -> None:
        return None


def test_the_registry_lists_the_camera_and_faces_plugins_and_plugins_satisfy_the_port() -> None:
    # I1: the core plugin is built by the bridge itself; the registry adds B's and C's (and, since
    # R11.1 C, the face groups' plugin, whose factory is also called `create_plugin`)
    assert [f.__name__ for f in PLUGINS] == ["camera_plugin", "create_plugin", "create_plugin"]
    assert [f.__module__ for f in PLUGINS] == [
        "jarvis.homebridge.camera",
        "jarvis.homebridge.faces",
        "jarvis.homebridge.face_groups",
    ]
    assert isinstance(_Plugin("camera"), BridgePlugin)
    ctx = BridgeContext(env={}, data_dir=ROOT, events=None)  # type: ignore[arg-type]
    assert ctx.now() > 0


def test_check_routes_refuses_one_route_served_twice() -> None:
    events = BridgeRoute("GET", "/bridge/v1/events", _ok)
    check_routes([_Plugin("a", (events,)), _Plugin("b")])
    with pytest.raises(ValueError):
        check_routes([_Plugin("a", (events,)), _Plugin("b", (events,))])
    with pytest.raises(ValueError):
        check_routes([_Plugin("a"), _Plugin("a")])


KIT_MODULES = (
    "home/__init__.py",
    "home/ports.py",
    "home/signing.py",
    "homebridge/__init__.py",
    "homebridge/plugins.py",
    "homebridge/registry.py",
)
KIT_OK = {"pydantic", "cryptography", "jarvis"}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_the_kit_modules_import_only_what_the_bridge_image_has() -> None:
    """D4: the home kit zips `home/{ports,signing}.py` with `homebridge/`: nothing in them may
    pull in the cloud app (Firestore, the brain, settings)."""
    for name in KIT_MODULES:
        for mod in _imports(SRC / name):
            top = mod.split(".")[0]
            assert top in sys.stdlib_module_names or top in KIT_OK, (name, mod)
            if top == "jarvis":
                assert mod in {"jarvis.home.ports", "jarvis.home.signing"} or mod.startswith(
                    "jarvis.homebridge."
                ), (name, mod)


# ---- keyring ---------------------------------------------------------------------------------

R2_PURPOSES = {"vault", "vault_index", "notes", "belongings", "tickets"}


def _purpose_key(info: str, length: int = 32) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=b"jarvis-keyring-v1", info=info.encode()
    ).derive(KEY)


def test_r3_cipher_purposes_are_pinned() -> None:
    assert set(PURPOSES) == R2_PURPOSES | {
        "home",
        "home_feed",
        "faces",
        "webpush",
        "notify",
        "connectors",  # R4 D9: the owner's own GitHub token
        "book_index",  # R6 D6: the sealed build-book index
        "book_session",  # R6 D9: book sessions (a cipher and a MAC domain)
        # R11: the helpers' sealed data (tests/test_r11_seams.py)
        "bills",
        "spend",
        "wellbeing",
        "alerts_place",
        "kitchen",
    }
    ring = Keyring(KEY)
    for purpose in ("home", "home_feed", "faces", "webpush"):
        from jarvis.integrations.vault import TokenCipher

        blob = TokenCipher(_purpose_key(f"jarvis/{purpose}/v1")).encrypt(b"x", aad="a")
        assert ring.cipher(purpose).decrypt(blob, aad="a") == b"x"


def test_the_vapid_secret_is_raw_hkdf_kept_apart_from_the_ciphers() -> None:
    assert SECRET_PURPOSES == ("webpush_vapid",)
    ring = Keyring(KEY)
    assert ring.secret("webpush_vapid") == _purpose_key("jarvis/secret/webpush_vapid/v1")
    long = ring.secret("webpush_vapid", length=48)
    assert long == _purpose_key("jarvis/secret/webpush_vapid/v1", 48)
    assert ring.secret("webpush_vapid") != _purpose_key("jarvis/webpush_vapid/v1")
    with pytest.raises(VaultError):
        ring.cipher("webpush_vapid")
    with pytest.raises(VaultError):
        ring.mac("webpush_vapid", b"x")
    for purpose in ("home", "vault", "nope"):
        with pytest.raises(VaultError):
            ring.secret(purpose)
    for length in (15, 65):
        with pytest.raises(VaultError):
            ring.secret("webpush_vapid", length=length)


# ---- permission rows and the home_disarm purpose -----------------------------------------------

ROWS = {
    "home_read": ("Home", "See your home's status and devices", R1),
    "home_control": ("Home", "Switch lights, fans and other everyday devices", R2),
    "home_arm": ("Home", "Arm the burglar alert", R2),
    "home_secure": ("Home", "Disarm, and control locks, gates, alarms and heaters", R3),
    "camera": ("Camera", "Search camera history and say who it recognised", R1),
}


def test_five_rows_sit_after_things_and_before_maps() -> None:
    ids = [g.id for g in GROUPS]
    # R4 added 5 rows (vitals, vitals_change, systems, people, connectors); R11 added 6 (D16);
    # R11.1 added 2 (plans, pictures)
    assert len(ids) == 46
    at = ids.index("belongings")
    assert ids[at + 1 : at + 6] == list(ROWS)  # the five R3 rows still sit right after Things
    # R4's rows sit after the R3 block; Maps and YouTube stay last
    assert ids.index("maps") > at + 5 and ids[-1] == "youtube"


@pytest.mark.parametrize("gid", list(ROWS))
def test_row_texts_risks_and_choices(gid: str) -> None:
    section, label, risk = ROWS[gid]
    g = get_group(gid)
    assert g is not None and (g.section, g.label, g.risk) == (section, label, risk)
    assert g.irreversible is (gid == "home_secure")
    assert len(g.choices) == (2 if g.irreversible else 3)
    assert g.hint and "$" not in g.hint and "\u20b9" not in g.hint


def test_rows_catch_exactly_their_tools() -> None:
    def rows(tool: str, risk: ActionRisk) -> set[str]:
        return {g.id for g in groups_for(tool, risk)}

    assert rows("home_status", R1) == rows("home_devices", R1) == {"home_read"}
    assert rows("home_control", R2) == {"home_control"}
    assert rows("home_control", R3) == {"home_secure"}  # a lock, gate, alarm or heater
    assert rows("home_arm", R2) == {"home_arm"}
    assert rows("home_disarm", R3) == {"home_secure"}
    assert rows("camera_history", R1) == rows("faces_list", R1) == {"camera"}
    for older in ("memory_search", "belongings_where", "maps_search", "web_search"):
        assert not rows(older, R1) & set(ROWS)
        assert not rows(older, R2) & set(ROWS)


def test_home_secure_never_offers_allow_and_a_patch_can_name_every_row() -> None:
    with pytest.raises(PermissionRejected):
        validate_choices({"home_secure": "allow"})
    assert validate_choices({"home_secure": "deny", "camera": "ask"})["camera"] is Effect.ASK
    every = {gid: "ask" for gid in group_ids()}
    assert PermissionsPatch(groups=every).groups == every
    PermissionsPatch(groups={f"g{i}": "ask" for i in range(48)})
    with pytest.raises(ValidationError):
        PermissionsPatch(groups={f"g{i}": "ask" for i in range(49)})


def test_home_disarm_is_a_targeted_purpose() -> None:
    assert "home_disarm" in get_args(Purpose) and "home_disarm" in TARGETED_PURPOSES


async def _with_passkey() -> Rig:
    rig = Rig()
    await rig.register()
    assert await rig.svc.passkey_required(UID)
    return rig


async def test_a_disarm_proof_is_bound_to_the_home_and_its_rev() -> None:
    rig = await _with_passkey()
    target = f"{HOME}:7"
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_purpose(UID, "home_disarm", target, None)
    proof = await rig.proof("home_disarm", target=target)
    with pytest.raises(PasskeyRejected):  # made for rev 7, used for rev 8
        await rig.svc.check_purpose(UID, "home_disarm", f"{HOME}:8", proof)
    proof = await rig.proof("home_disarm", target=target)
    with pytest.raises(PasskeyRejected):  # a disarm proof is no privacy delete
        await rig.svc.check_purpose(UID, "privacy_delete", target, proof)
    proof = await rig.proof("privacy_delete", target=target)
    with pytest.raises(PasskeyRejected):  # and a privacy delete proof disarms nothing
        await rig.svc.check_purpose(UID, "home_disarm", target, proof)
    proof = await rig.proof("home_disarm", target=target)
    note = await rig.svc.check_purpose(UID, "home_disarm", target, proof)
    assert note is not None and note.startswith("passkey ")
    with pytest.raises(PasskeyRejected):  # single use
        await rig.svc.check_purpose(UID, "home_disarm", target, proof)


async def test_a_disarm_target_must_name_a_home_and_a_rev() -> None:
    rig = Rig()  # no passkeys in force: the target is still checked first
    for bad in ("", None, "memory:3", HOME, f"{HOME}:x", f"{HOME}:7:8", "h_0A1B2C3D:7"):
        with pytest.raises(PermissionRejected):
            await rig.svc.check_purpose(UID, "home_disarm", bad, None)
    assert await rig.svc.check_purpose(UID, "home_disarm", f"{HOME}:7", None) is None


def test_the_console_passkey_helper_knows_home_disarm() -> None:
    js = (STATIC / "console-permissions.js").read_text()
    allowed = js.split("prove: (purpose, target)")[1][:400]
    for purpose in ("vault_unlock", "privacy_delete", "privacy_export", "home_disarm"):
        assert f"'{purpose}'" in allowed


# ---- scheduler: one audience per route ---------------------------------------------------------

WATCH_AUD = "http://test" + WATCHDOG_PATH


def _verifier(**kw: Any) -> GoogleOIDCVerifier:
    return GoogleOIDCVerifier(email=SA, http=FakeJWKS(OIDC_KEY).client(), now=OidcClock(), **kw)


async def test_each_scheduler_route_has_its_own_exact_audience() -> None:
    assert WATCHDOG_PATH == "/internal/home/watchdog"
    assert SCHEDULER_PATHS == frozenset({TICK_PATH, WATCHDOG_PATH})
    v = _verifier(base_url="http://test/")
    assert await v.verify(token()) is True  # the tick, as before
    assert await v.verify(token(), path=TICK_PATH) is True
    assert await v.verify(token(aud=WATCH_AUD), path=WATCHDOG_PATH) is True
    assert await v.verify(token(aud=WATCH_AUD), path=TICK_PATH) is False
    assert await v.verify(token(), path=WATCHDOG_PATH) is False
    other = "http://test/internal/other"
    assert await v.verify(token(aud=other), path="/internal/other") is False


async def test_a_tick_only_verifier_refuses_the_watchdog() -> None:
    v = _verifier(audience="http://test" + TICK_PATH)
    assert await v.verify(token()) is True
    assert await v.verify(token(aud=WATCH_AUD), path=WATCHDOG_PATH) is False
    with pytest.raises(ValueError):
        _verifier()


async def test_require_scheduler_checks_the_route_being_called() -> None:
    app = FastAPI()
    app.state.scheduler_verifier = _verifier(base_url="http://test")

    @app.exception_handler(SchedulerUnauthorized)
    async def _bare(request: Request, exc: SchedulerUnauthorized) -> Response:
        return Response(status_code=401)

    @app.post(WATCHDOG_PATH, dependencies=[Depends(require_scheduler)])
    async def _watch() -> dict[str, bool]:
        return {"ok": True}

    @app.post(TICK_PATH, dependencies=[Depends(require_scheduler)])
    async def _tick() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        watch = {"Authorization": f"Bearer {token(aud=WATCH_AUD)}"}
        tick = {"Authorization": f"Bearer {token()}"}
        assert (await c.post(WATCHDOG_PATH, headers=watch)).status_code == 200
        assert (await c.post(TICK_PATH, headers=watch)).status_code == 401
        assert (await c.post(WATCHDOG_PATH, headers=tick)).status_code == 401
        assert (await c.post(TICK_PATH, headers=tick)).status_code == 200


def test_the_app_builds_one_verifier_for_both_routes() -> None:
    src = (SRC / "api" / "app.py").read_text()
    assert "GoogleOIDCVerifier(\n        base_url=s.public_base_url" in src


# ---- console CSP -----------------------------------------------------------------------------


def test_the_csp_gains_exactly_worker_src_self() -> None:
    assert CONSOLE_CSP.endswith("; worker-src 'self'") and CONSOLE_CSP.count("worker-src") == 1
    assert "blob:" not in CONSOLE_CSP and "child-src" not in CONSOLE_CSP
    src = (SRC / "api" / "console.py").read_text()
    assert "service worker" in src and "/static/push/" in src


# ---- settings --------------------------------------------------------------------------------


def test_r3_settings_defaults_and_bounds() -> None:
    s = Settings(_env_file=None)
    assert (s.home_enabled, s.faces_enabled, s.webpush_enabled) == (True, True, True)
    assert (s.home_heartbeat_s, s.home_offline_after_s) == (120, 360)  # R5.1 D3 (was 720)
    assert (s.home_feed_days, s.home_webhook_per_min) == (7, 60)
    roomy = {"home_offline_after_s": 3600}  # two beats of the slowest heartbeat fit
    for field, good, bad in (
        ("home_heartbeat_s", (60, 600), (59, 601)),
        ("home_offline_after_s", (300, 3600), (299, 3601)),
        ("home_feed_days", (1, 30), (0, 31)),
        ("home_webhook_per_min", (10, 600), (9, 601)),
    ):
        extra = roomy if field == "home_heartbeat_s" else {}
        for v in good:
            assert getattr(Settings(_env_file=None, **{**extra, field: v}), field) == v
        for v in bad:
            with pytest.raises(ValidationError):
                Settings(_env_file=None, **{**extra, field: v})


def test_the_offline_window_covers_two_heartbeats() -> None:
    ok = Settings(_env_file=None, home_heartbeat_s=300, home_offline_after_s=600)
    assert ok.home_offline_after_s == 600
    with pytest.raises(ValidationError):
        Settings(_env_file=None, home_heartbeat_s=300, home_offline_after_s=599)


# ---- the bridge extra ------------------------------------------------------------------------


def test_the_bridge_extra_is_optional_and_the_cloud_image_unchanged() -> None:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # integrated review C1: pinned like the bridge image's hash-locked requirements
    assert cfg["project"]["optional-dependencies"]["homebridge"] == [
        "aiomqtt==2.5.1",
        "paho-mqtt==2.1.0",
    ]
    assert not any(d.startswith(("aiomqtt", "paho")) for d in cfg["project"]["dependencies"])
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert "aiomqtt" not in lock and "paho-mqtt" not in lock


# ---- Telegram: the home group ----------------------------------------------------------------


class _Links:
    rules_token = "tok"

    def __init__(self, link: TelegramLink | None) -> None:
        self.link = link

    async def get(self, uid: str) -> TelegramLink | None:
        return self.link


def _link(**kw: Any) -> TelegramLink:
    return TelegramLink(tg_user_id=1, chat_id=2, paired_at="2026-11-05T00:00:00+00:00", **kw)


async def _denied(link: TelegramLink | None, names: list[str], *, on: bool = True) -> set[str]:
    rules = ChannelRules(None, _Links(link))  # type: ignore[arg-type]
    if on:
        with telegram_turn():
            got = await rules.rules_for(TG_UID)
    else:
        got = await rules.rules_for(TG_UID)
    return {n for n in names if any(r.effect is Effect.DENY and r.matches(n, {}, R1) for r in got)}


HOME_READS = ["home_devices", "camera_history", "faces_list"]


async def test_the_home_group_needs_its_own_switch_on_telegram() -> None:
    # R11.1 I1: the photo import's faces-found / people-recognised counts joined the home group
    assert HOME_PATTERNS == ("home_devices", "camera_*", "faces_*", "photos_import_*")
    assert "Telegram" in HOME_REFUSAL and HOME_REFUSAL.isascii()
    assert await _denied(None, HOME_READS) == set(HOME_READS)
    for kw in (
        {"allow_private_reads": True},
        {"allow_personal_reads": True},
        {"allow_private_reads": True, "allow_personal_reads": True},
    ):
        assert await _denied(_link(**kw), HOME_READS) == set(HOME_READS)
    assert await _denied(_link(allow_home_reads=True), HOME_READS) == set()
    opened = await _denied(_link(allow_home_reads=True), ["vault_list", "gmail_read"])
    assert opened == {"vault_list", "gmail_read"}  # it opens only its own group
    assert await _denied(None, HOME_READS, on=False) == set()  # only on a Telegram turn


async def test_status_and_arming_stay_open_on_telegram() -> None:
    assert await _denied(None, ["home_status", "home_arm", "home_control"]) == set()


async def test_the_home_switch_is_stored_off_by_default() -> None:
    assert _link().allow_home_reads is False
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=TgClock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    got = await store.get(UID)
    assert got is not None and got.allow_home_reads is False
    await store.set_settings(UID, allow_home_reads=True)
    got = await store.get(UID)
    assert got is not None and got.allow_home_reads is True
    assert (got.allow_private_reads, got.allow_personal_reads) == (False, False)


# ---- files -----------------------------------------------------------------------------------

NEW_FILES = (
    "notify/__init__.py",
    "notify/ports.py",
    "faces/__init__.py",
    "faces/ports.py",
    *KIT_MODULES,
)


def test_new_seam_files_are_ascii() -> None:
    for name in NEW_FILES:
        assert (SRC / name).read_text().isascii(), name
