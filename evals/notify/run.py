# evals/notify/run.py
"""R3 D eval -- one alert policy and browser notifications (plan docs/plans/r3-home-camera.md
"Evals -> notify (D, >= 46)").

    python evals/notify/run.py --mock

No network, no model. The real policy, storm control, store, notifier, Telegram adapter and Web
Push service run over an in-memory Docs port, a fake Telegram Bot API and a fake push service.

  rules   (22)  each rule in order; quiet hours across midnight; VIP rings in quiet hours;
                emergency words in English, Hindi, Malayalam and Odia; "firewall" does not ring;
                info is silent; ring_for=urgent; kinds off are dropped; burglar alerts have no
                switch; an approval at 00:30 through the sink is held
  storm   (8)   50 detections in 2 minutes -> <= 2 rings and one summary; the 10-in-10-minutes cap;
                package and greeting gaps; the urgent bucket survives ten approvals; an unreadable
                urgent counter still sends; an unreadable normal counter does not
  push    (14)  RFC 8291 Appendix A byte for byte; VAPID verifies with aud = the endpoint's origin
                and exp <= 12 h; the endpoint rule (http, IP literal, port 8443, a look-alike host,
                a private address, a redirect); 410 removes; payload <= 1 KB, no picture; keys
                checked; 5 devices; nothing readable in storage
  channels (6)  zero model calls; a failing push never blocks Telegram (and the other way round);
                audit without content; the photo only with the opt-in; a child is never named
  Negative controls (each must make the suite FAIL): quiet hours off; VIP check off; storm cap
  off; endpoint allow-list off; urgent bucket merged with the normal one; hazards capped.
  Review fixes: a hazard rings after a burglar flood and ignores every cap; flapping alerts make
  one push; vault_expiry is off everywhere; held alerts survive a failed send.
Gate (hard): every case passes; every negative control fails the suite.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import json
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tests"))

from notify_fakes import MIDNIGHT, NOON, build  # noqa: E402
from r1d_common import finish  # noqa: E402
from telegram_fakes import UID  # noqa: E402
from webpush_fakes import Browser, PushWorld  # noqa: E402

from jarvis.logging import configure_logging  # noqa: E402
from jarvis.notify import policy as policy_mod  # noqa: E402
from jarvis.notify import telegram_out  # noqa: E402
from jarvis.notify.models import NotifySettings, QuietHours, Snapshot, Vip  # noqa: E402
from jarvis.notify.policy import decide  # noqa: E402
from jarvis.notify.ports import Signal  # noqa: E402
from jarvis.notify.sink import PolicyAlerts  # noqa: E402
from jarvis.notify.storm import Storm  # noqa: E402
from jarvis.webpush import endpoints  # noqa: E402
from jarvis.webpush.ece import encrypt  # noqa: E402

Case = Callable[[], Awaitable[list[str]]]
CASES: list[tuple[str, str, Case]] = []


def case(group: str, cid: str) -> Callable[[Case], Case]:
    def reg(fn: Case) -> Case:
        CASES.append((group, cid, fn))
        return fn

    return reg


def sig(kind: str, **kw: Any) -> Signal:
    return Signal(source="home", kind=kind, **kw)


def want(got: Any, expected: Any, what: str) -> list[str]:
    return [] if got == expected else [f"{what}: got {got!r}, wanted {expected!r}"]


def act(kind: str, now: datetime = NOON, settings: NotifySettings | None = None, **kw: Any) -> str:
    d = decide(sig(kind, **kw), settings or NotifySettings(), now)
    return f"{d.action}/{d.reason}"


# ---- rules -----------------------------------------------------------------------------------
RULES: list[tuple[str, str, str, dict[str, Any]]] = [
    ("test_rings_at_night", "test", "ring/test", {"now": MIDNIGHT}),
    ("hazard_rings_at_night", "home_hazard", "ring/emergency", {"now": MIDNIGHT}),
    ("intruder_rings_at_night", "home_intruder", "ring/intruder", {"now": MIDNIGHT}),
    (
        "emergency_english",
        "approval_waiting",
        "ring/emergency",
        {"now": MIDNIGHT, "text": "fire in the kitchen"},
    ),
    (
        "emergency_hindi",
        "approval_waiting",
        "ring/emergency",
        {"now": MIDNIGHT, "text": "\u0906\u0917 \u0932\u0917\u0940"},
    ),
    (
        "emergency_malayalam",
        "approval_waiting",
        "ring/emergency",
        {"now": MIDNIGHT, "text": "\u0d24\u0d40 \u0d2a\u0d3f\u0d1f\u0d3f\u0d1a\u0d4d\u0d1a\u0d41"},
    ),
    (
        "emergency_odia",
        "approval_waiting",
        "ring/emergency",
        {"now": MIDNIGHT, "text": "\u0b1a\u0b4b\u0b30"},
    ),
    (
        "emergency_latin_bachao",
        "approval_waiting",
        "ring/emergency",
        {"now": MIDNIGHT, "text": "bachao bachao"},
    ),
    (
        "word_boundary_firewall",
        "approval_waiting",
        "hold/quiet_hours",
        {"now": MIDNIGHT, "text": "my firewall"},
    ),
    ("important_held_at_night", "home_package", "hold/quiet_hours", {"now": MIDNIGHT}),
    ("info_feed_only_at_night", "home_online", "drop/feed_only", {"now": MIDNIGHT}),
    ("info_silent_by_day", "home_online", "silent/info", {}),
    ("important_silent_when_only_urgent", "home_package", "silent/only_urgent_rings", {}),
    ("r1_kind_held_at_night", "approval_waiting", "hold/quiet_hours", {"now": MIDNIGHT}),
    ("greeting_feed_only_by_default", "home_greeting", "drop/feed_only", {}),
    (
        "quiet_starts_at_2300",
        "home_package",
        "hold/quiet_hours",
        {"now": datetime(2027, 1, 15, 17, 30, tzinfo=UTC)},
    ),
    (
        "quiet_ends_at_0630",
        "home_package",
        "silent/only_urgent_rings",
        {"now": datetime(2027, 1, 15, 1, 0, tzinfo=UTC)},
    ),
]


def _rule_case(cid: str, kind: str, expected: str, kw: dict[str, Any]) -> Case:
    async def run() -> list[str]:
        return want(act(kind, **kw), expected, cid)

    return run


for _cid, _kind, _exp, _kw in RULES:
    CASES.append(("rules", _cid, _rule_case(_cid, _kind, _exp, _kw)))


@case("rules", "vip_face_rings_at_night")
async def _() -> list[str]:
    s = NotifySettings(kinds={"home_greeting": "on"})
    return want(act("home_greeting", MIDNIGHT, s, vip=True), "ring/vip", "vip")


@case("rules", "listed_vip_rings_at_night")
async def _() -> list[str]:
    s = NotifySettings(vip=(Vip(id="v_0123abcd", kind="phone", ref="+911234567890"),))
    return want(act("approval_waiting", MIDNIGHT, s, person_ref="+911234567890"), "ring/vip", "vip")


@case("rules", "kind_off_drops_and_burglar_has_no_switch")
async def _() -> list[str]:
    off = NotifySettings(kinds={"home_package": "off"})
    forced = NotifySettings.model_construct(
        kinds={"home_intruder": "off"},
        quiet=QuietHours(),
        tz="Asia/Kolkata",
        vip=(),
        ring_for="urgent",
    )
    return want(act("home_package", settings=off), "drop/switched_off", "off") + want(
        decide(sig("home_intruder"), forced, NOON).action, "ring", "intruder"
    )


@case("rules", "ring_for_important_rings")
async def _() -> list[str]:
    return want(
        act("home_package", settings=NotifySettings(ring_for="important")),
        "ring/important",
        "ring_for",
    )


@case("rules", "approval_at_0030_is_held_through_the_sink")
async def _() -> list[str]:
    w = await build(MIDNIGHT)
    res = await PolicyAlerts(w.service).send(UID, "Something is waiting.", kind="approval_waiting")
    return want((res.sent, w.tg.bot.calls), (False, []), "held, nothing sent")


# ---- storm -----------------------------------------------------------------------------------
@case("storm", "fifty_detections_in_two_minutes")
async def _() -> list[str]:
    w = await build()
    rings = 0
    for _ in range(50):
        d = await w.service.notify(UID, sig("home_intruder", camera="gate"), "Someone at the Gate.")
        rings += d.action == "ring" and d.telegram
        w.clock.advance(seconds=2.4)
    w.clock.advance(minutes=11)
    await w.service.flush_summaries()
    summaries = [t for t in w.tg.bot.texts if "more alerts" in t]
    return want(rings <= 2, True, f"rings {rings}") + want(len(summaries), 1, "summaries")


@case("storm", "ten_urgent_rings_in_ten_minutes_then_dropped")
async def _() -> list[str]:
    s, out = Storm(), 0
    from jarvis.notify.ports import Decision

    d = Decision(action="ring", reason="x", urgency="urgent")
    for i in range(25):
        cam = f"c{i}"
        out += s.admit(UID, sig("home_intruder", camera=cam), d, NOON + timedelta(seconds=i)).admit
    return want(out, 10, "admitted")


@case("storm", "package_gap")
async def _() -> list[str]:
    s = Storm()
    from jarvis.notify.ports import Decision

    d = Decision(action="silent", reason="x", urgency="important")
    got = [
        s.admit(UID, sig("home_package"), d, NOON + timedelta(minutes=m)).admit for m in (0, 5, 10)
    ]
    return want(got, [True, False, True], "package")


@case("storm", "greeting_gap_per_person")
async def _() -> list[str]:
    s = Storm()
    from jarvis.notify.ports import Decision

    d = Decision(action="silent", reason="x", urgency="info")
    a, b = "fp_aaaaaaaaaaaa", "fp_bbbbbbbbbbbb"
    got = [
        s.admit(UID, sig("home_greeting", person_ref=p), d, NOON + timedelta(minutes=m)).admit
        for p, m in ((a, 0), (b, 1), (a, 20), (a, 31))
    ]
    return want(got, [True, True, False, True], "greeting")


@case("storm", "urgent_bucket_survives_ten_approvals")
async def _() -> list[str]:
    w = await build(with_push=False)
    for _ in range(12):
        await w.alerts.send(UID, "w", kind="approval_waiting")
    res = await w.alerts.send(UID, "Someone.", kind="home_intruder")
    return want(res.sent, True, "burglar after approvals")


@case("storm", "urgent_counter_unreadable_still_sends")
async def _() -> list[str]:
    w = await build(with_push=False)

    async def boom(*a: Any, **k: Any) -> bool:
        raise RuntimeError("down")

    w.alerts._notify.take_urgent = boom  # type: ignore[method-assign]
    return want((await w.alerts.send(UID, "x", kind="home_intruder")).sent, True, "urgent")


@case("storm", "normal_counter_unreadable_does_not_send")
async def _() -> list[str]:
    w = await build(with_push=False)

    async def boom(*a: Any, **k: Any) -> bool:
        raise RuntimeError("down")

    w.tg.store.count_alert = boom  # type: ignore[method-assign]
    return want((await w.alerts.send(UID, "x", kind="approval_waiting")).sent, False, "normal")


@case("storm", "urgent_has_its_own_hourly_cap")
async def _() -> list[str]:
    w = await build(with_push=False)
    sent = [(await w.alerts.send(UID, "x", kind="home_intruder")).sent for _ in range(35)]
    return want(sent.count(True), telegram_out.URGENT_PER_HOUR, "urgent sent")


@case("storm", "hazard_rings_after_a_burglar_flood")
async def _() -> list[str]:
    w = await build()
    for i in range(30):
        await w.service.notify(UID, sig("home_intruder", camera=f"c{i}"), "Someone.")
        w.clock.advance(seconds=100)
    d = await w.service.notify(UID, sig("home_hazard", camera="kitchen"), "Smoke alarm at home.")
    return want((d.action, d.telegram, d.push), ("ring", True, 1), "hazard")


@case("storm", "hazard_ignores_every_cap")
async def _() -> list[str]:
    w = await build()
    for _ in range(telegram_out.URGENT_PER_HOUR):
        await w.store.take_urgent(UID, NOON, per_hour=30, per_day=100)
    for _ in range(20):
        await w.store.take_push(UID, NOON, per_hour=20)
    burglar = await w.alerts.send(UID, "x", kind="home_intruder")
    d = await w.service.notify(UID, sig("home_hazard", camera="garage"), "Gas leak at home.")
    return want((burglar.sent, d.telegram, d.push), (False, True, 1), "burglar / hazard")


@case("channels", "flapping_offline_makes_one_push")
async def _() -> list[str]:
    w = await build()
    for _ in range(40):
        await w.service.notify(UID, sig("home_offline"), "Laptop off.")
        w.clock.advance(seconds=1)
    return want(len(w.push.requests) <= 1, True, f"pushes {len(w.push.requests)}")


@case("channels", "vault_expiry_off_by_default_everywhere")
async def _() -> list[str]:
    w = await build()
    d = await w.service.notify(UID, sig("vault_expiry"), "A document is due.")
    return want((d.action, d.telegram, d.push), ("drop", False, 0), "vault_expiry")


@case("channels", "held_alerts_survive_a_failed_send")
async def _() -> list[str]:
    w = await build(MIDNIGHT, with_push=False)
    await w.service.notify(UID, sig("home_package"), "Pkg.")
    w.clock.now = NOON
    w.tg.bot.raise_transport = True
    sent = await w.service.flush_held(UID)
    return want((sent, len(await w.store.held_list(UID))), (False, 1), "held after failure")


# ---- push ------------------------------------------------------------------------------------
def b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@case("push", "rfc8291_appendix_a")
async def _() -> list[str]:
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.derive_private_key(
        int.from_bytes(b64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1()
    )
    got = encrypt(
        b"When I grow up, I want to be a watermelon",
        b64(
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
        ),
        b64("BTBZMqHH6r4Tts7J_aSIgg"),
        salt=b64("DGv6ra1nlYgDCS1FRnbzlw"),
        sender_private=key,
    )
    exp = (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmY"
        "WAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexS"
        "gSxsj_Qulcy4a-fN"
    )
    return want(got == b64(exp), True, "body matches")


@case("push", "vapid_jwt_verifies")
async def _() -> list[str]:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from joserfc import jwt
    from joserfc.jwk import ECKey

    w = PushWorld()
    from webpush_fakes import NOW

    token = w.vapid.token("https://fcm.googleapis.com/fcm/send/x", NOW)
    pem = w.vapid._private.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    claims = jwt.decode(token, ECKey.import_key(pem)).claims
    exp_ok = 0 < claims["exp"] - int(NOW.timestamp()) <= 12 * 3600
    return want(claims["aud"], "https://fcm.googleapis.com", "aud") + want(
        exp_ok, True, "exp <= 12 h"
    )


async def _endpoint_refused(url: str) -> list[str]:
    from webpush_fakes import resolver

    try:
        await endpoints.check(url, resolver=resolver)
    except endpoints.BadEndpoint:
        return []
    return [f"accepted {url}"]


for _id, _url in (
    ("endpoint_http", "http://fcm.googleapis.com/fcm/send/x"),
    ("endpoint_ip_literal", "https://127.0.0.1/fcm/send/x"),
    ("endpoint_port_8443", "https://fcm.googleapis.com:8443/fcm/send/x"),
    ("endpoint_lookalike_host", "https://fcm.googleapis.com.evil.example/x"),
    ("endpoint_metadata_ip", "https://169.254.169.254/latest"),
):

    def _mk(u: str) -> Case:
        async def run() -> list[str]:
            return await _endpoint_refused(u)

        return run

    CASES.append(("push", _id, _mk(_url)))


@case("push", "endpoint_private_resolution")
async def _() -> list[str]:
    async def inward(host: str) -> list[str]:
        return ["10.1.2.3"]

    try:
        await endpoints.check("https://fcm.googleapis.com/fcm/send/x", resolver=inward)
    except endpoints.BadEndpoint:
        return []
    return ["accepted a private resolution"]


@case("push", "redirect_not_followed")
async def _() -> list[str]:
    import httpx

    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    seen: list[str] = []

    def red(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    w.service._http = httpx.AsyncClient(transport=httpx.MockTransport(red), follow_redirects=False)
    await w.service.send(UID, kind="test", text="t")
    return want(len(seen), 1, "requests")


@case("push", "gone_device_removed")
async def _() -> list[str]:
    w = PushWorld(410)
    await w.service.subscribe(UID, **Browser().sub())
    await w.service.send(UID, kind="test", text="t")
    return want(await w.store.list(UID), [], "devices left")


@case("push", "payload_small_and_pictureless")
async def _() -> list[str]:
    from jarvis.webpush.service import payload_for

    raw = payload_for("home_intruder", "x" * 4000)
    return want(len(raw) <= 1024, True, "size") + want(
        sorted(json.loads(raw)), ["kind", "text", "url"], "fields"
    )


@case("push", "bad_keys_refused")
async def _() -> list[str]:
    from jarvis.webpush.service import BadSubscription

    w, out = PushWorld(), []
    for patch in (
        {"p256dh": "AAAA"},
        {"auth": "AAAA"},
        {"p256dh": b64_str(b"\x04" + b"\x01" * 64)},
    ):
        try:
            await w.service.subscribe(UID, **{**Browser().sub(), **patch})
            out.append(f"accepted {sorted(patch)}")
        except BadSubscription:
            pass
    return out


def b64_str(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@case("push", "five_devices_cap")
async def _() -> list[str]:
    from jarvis.webpush.store import PushFull

    w = PushWorld()
    for i in range(5):
        await w.service.subscribe(UID, **Browser(f"https://fcm.googleapis.com/fcm/send/{i}").sub())
    try:
        await w.service.subscribe(UID, **Browser("https://fcm.googleapis.com/fcm/send/z").sub())
    except PushFull:
        return []
    return ["a sixth device was accepted"]


@case("push", "subscriptions_unreadable_in_storage")
async def _() -> list[str]:
    w, br = PushWorld(), Browser()
    await w.service.subscribe(UID, **br.sub("Needle phone"))
    blob = json.dumps(w.docs._data)
    return want(
        [n for n in (br.p256dh, "fcm.googleapis.com", "Needle") if n in blob], [], "needles"
    )


@case("push", "owner_bound")
async def _() -> list[str]:
    w = PushWorld()
    dev = await w.service.subscribe(UID, **Browser().sub())
    return want(
        (await w.service.remove("other", dev.id), await w.store.list("other")),
        (False, []),
        "other owner",
    )


@case("push", "vapid_key_stable")
async def _() -> list[str]:
    return want(PushWorld().vapid.public_key == PushWorld().vapid.public_key, True, "stable")


@case("push", "audit_counts_only")
async def _() -> list[str]:
    w = PushWorld()
    await w.service.subscribe(UID, **Browser().sub())
    await w.service.send(UID, kind="home_intruder", text="SECRETWORD at the gate")
    return want(
        "SECRETWORD" in repr(w.audit.args) + repr(w.audit._entries), False, "content in audit"
    )


# ---- channels --------------------------------------------------------------------------------
@case("channels", "zero_model_calls")
async def _() -> list[str]:
    bad: list[str] = []
    for pkg in ("notify", "webpush"):
        for path in (ROOT / "src" / "jarvis" / pkg).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                )
                bad += [
                    f"{path.name} imports {m}"
                    for m in mods
                    if m.startswith(("jarvis.llm", "anthropic", "openai"))
                ]
    return bad


@case("channels", "failing_push_never_blocks_telegram")
async def _() -> list[str]:
    w = await build()

    async def boom(*a: Any, **k: Any) -> int:
        raise RuntimeError("down")

    w.push.service.send = boom  # type: ignore[method-assign]
    d = await w.service.notify(UID, sig("home_intruder", camera="gate"), "Someone.")
    return want((d.telegram, d.push), (True, 0), "telegram/push")


@case("channels", "failing_telegram_never_blocks_push")
async def _() -> list[str]:
    w = await build()
    w.tg.bot.raise_transport = True
    d = await w.service.notify(UID, sig("home_intruder", camera="gate"), "Someone.")
    return want((d.telegram, d.push), (False, 1), "telegram/push")


@case("channels", "delivery_audit_has_no_content")
async def _() -> list[str]:
    w = await build()
    await w.service.notify(UID, sig("home_intruder", camera="gate"), "SECRETWORD at the gate")
    blob = repr(w.tg.audit._entries) + repr(w.push.audit.args)
    return want("SECRETWORD" in blob, False, "content in audit")


@case("channels", "photo_only_with_opt_in_and_never_in_push_or_storage")
async def _() -> list[str]:
    w, jpg = await build(), b"\xff\xd8NEEDLEJPEG"
    off = await w.service.notify(UID, sig("home_intruder", camera="gate"), "Someone.", photo=jpg)
    await w.store.update(
        UID, lambda s: s.model_copy(update={"snapshot": Snapshot(on=True, at="t")})
    )
    w.clock.advance(minutes=2)
    on = await w.service.notify(UID, sig("home_intruder", camera="gate"), "Someone.", photo=jpg)
    leaked = any(b"NEEDLEJPEG" in r.content for r in w.push.requests) or "NEEDLEJPEG" in json.dumps(
        w.docs._data, default=str
    )
    return want(
        (off.photo_sent, on.photo_sent, len(w.photos), leaked), (False, True, 1, False), "photo"
    )


@case("channels", "child_never_named")
async def _() -> list[str]:
    w = await build()
    await w.store.update(UID, lambda s: s.model_copy(update={"names_in_alerts": True}))
    s = sig("home_intruder", camera="gate", person_ref="fp_aaaaaaaaaaaa", child=True)
    await w.service.notify(UID, s, "A child from your family.", named_message="Kidname is here.")
    seen = " ".join(w.tg.bot.texts) + " ".join(r.content.decode("latin-1") for r in w.push.requests)
    return want("Kidname" in seen, False, "child name")


@case("channels", "names_off_by_default")
async def _() -> list[str]:
    w = await build()
    await w.service.notify(
        UID,
        sig("home_intruder", camera="gate", person_ref="fp_aaaaaaaaaaaa"),
        "A person JARVIS recognised.",
        named_message="Anjali is here.",
    )
    return want(w.tg.bot.texts, ["A person JARVIS recognised."], "texts")


# ---- harness ---------------------------------------------------------------------------------
async def run_all() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group, cid, fn in CASES:
        try:
            failures = await fn()
        except Exception as exc:  # noqa: BLE001 - a crash is a failure
            failures = [f"raised {type(exc).__name__}: {exc}"]
        out.append(
            {"id": f"{group}:{cid}", "group": group, "passed": not failures, "failures": failures}
        )
    return out


@contextmanager
def patched(obj: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _merged_bucket() -> Any:
    """Negative control: urgent kinds use the normal bucket (R1's counter)."""
    real = telegram_out.TelegramHomeAlerts._allowed

    async def merged(self: Any, uid: str, kind: str) -> bool:
        return await real(self, uid, "approval_waiting")

    return merged


async def controls() -> dict[str, Any]:
    ran: dict[str, bool] = {}
    plans: dict[str, tuple[Any, str, Any]] = {
        "quiet_hours_off": (policy_mod, "in_quiet", lambda *a, **k: False),
        "vip_check_off": (policy_mod, "_is_vip", lambda *a, **k: False),
        "storm_cap_off": (
            Storm,
            "admit",
            lambda self, *a, **k: __import__("jarvis.notify.storm", fromlist=["Verdict"]).Verdict(
                True
            ),
        ),
        "endpoint_allow_list_off": (endpoints, "ENFORCE", False),
        "hazard_capped": (telegram_out, "NO_CAP_KINDS", frozenset()),
        "urgent_bucket_merged": (telegram_out.TelegramHomeAlerts, "_allowed", _merged_bucket()),
    }
    for name, (obj, attr, val) in plans.items():
        with patched(obj, attr, val):
            ran[name] = any(not r["passed"] for r in await run_all())
    return {"suite_failed": all(ran.values()), "controls": ran}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    configure_logging()
    results = asyncio.run(run_all())
    return finish(HERE, "notify", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
