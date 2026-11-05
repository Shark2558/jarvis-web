# evals/r3_needles/run.py
"""R3 I1 eval -- the cross-cutting needle scan (plan docs/plans/r3-home-camera.md "Evals ->
r3_needles"). Nothing R3 handles may leak through a side door.

    python evals/r3_needles/run.py --mock

Each flow runs in the WHOLE app as `create_app` wires it (tests/r3_app.py: the token key, a paired
Telegram owner whose Bot API calls are recorded, a linked home whose laptop is asleep, events signed
with the home's up key like the bridge signs them). Seeded needles: the link seed, a snapshot JPEG
with a marker, a child's name and an adult's name (the adult is the positive control: with "Say
names in alerts" on, the scan must SEE that name in Telegram, so it can see).

After every flow: every Firestore document, every log record and every audit entry are scanned for
the seed (base64 and hex), the snapshot marker (raw and base64) and both names; every Telegram text
and caption for the snapshot and the child's name.

Asserted: the seed and the snapshot never reach a document, log or audit entry; the snapshot reaches
Telegram only as `sendPhoto` and only after the opt-in; the child's name never reaches Telegram, the
brief's Home overnight section, a document, a log or an audit entry; names are sealed in Firestore;
a Telegram turn with the third switch off never sees faces. Not here (each has its own suite): the
Home Assistant token stays on the laptop (home_link s01-s04: cloud documents, logs, audit, model
requests); a training brain is offered no tools at all (Brain._tools_on; faces c04).

Integrated review S7 adds flows for what the owner types or a browser sends: a VIP phone number,
a browser's push subscription (endpoint and keys, with a burglar alert pushed to it), the
owner's camera label (seen on Telegram as the positive control) and a detection carrying a face
id (the id never in a log line or audit entry). Each is scanned like the rest.

Negative controls (each must make the suite FAIL): a "debug" log line of every webhook body; a log
line of the VIP references and of a new push endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
import httpx  # noqa: E402
from r1d_common import finish  # noqa: E402
from r3_app import SEED, UID, H, R3App, detection, heartbeat, r3_app  # noqa: E402
from webpush_fakes import Browser  # noqa: E402

import jarvis.home.webhook as webhook_mod  # noqa: E402
from jarvis.brief.home_overnight import HomeOvernightBrief  # noqa: E402
from jarvis.core.channel import telegram_turn  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.notify.store import NotifyStore  # noqa: E402
from jarvis.tools.gateway import GatewayOutcome  # noqa: E402
from jarvis.webpush.store import PushStore  # noqa: E402

CHILD = "Mira Needlechild"
ADULT = "Anjali Needleadult"
MARK = b"SNAPSHOT-NEEDLE-5e2a"
JPEG = b"\xff\xd8\xff\xe0" + MARK + b"\x00" * 64 + b"\xff\xd9"
SNAP = base64.b64encode(JPEG).decode()
SEED_B64 = base64.urlsafe_b64encode(SEED).decode().rstrip("=")
SEED_STD = base64.b64encode(SEED).decode()
VIP_REF = "+91 98765 13579"
PUSH_ENDPOINT = "https://fcm.googleapis.com/fcm/send/needle-endpoint-5c3d"
LABEL = "Needlegate Porch"
SECRET_NEEDLES = (SEED_B64, SEED_STD, SEED.hex(), MARK.decode(), SNAP[:40])
NAME_NEEDLES = (CHILD, ADULT)
# S7: what the owner typed or a browser sent (the push auth secret is a fixed fake's)
TYPED_NEEDLES = ("9876513579", "98765 13579", "needle-endpoint-5c3d", Browser().auth, LABEL)
LOG_AUDIT_ONLY: list[str] = []  # needles a flow adds that may sit sealed in a document


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        extra = {k: v for k, v in record.__dict__.items() if k not in _STD}
        self.lines.append(f"{record.getMessage()} {json.dumps(extra, default=str)}")


_STD = set(logging.LogRecord("x", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


@contextmanager
def captured() -> Any:
    cap = Capture()
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        yield cap
    finally:
        root.removeHandler(cap)


def scan(w: R3App, cap: Capture, needles: tuple[str, ...]) -> list[str]:
    """Where any needle was found: documents, log records, audit entries."""
    found: list[str] = []
    docs = json.dumps(w.docs._data, default=str)  # noqa: SLF001
    audit = json.dumps(
        [e.model_dump(mode="json") for e in w.state.gateway.audit._entries],  # noqa: SLF001
        default=str,
    )
    logs = "\n".join(cap.lines)
    for n in needles:
        for where, text in (("document", docs), ("log", logs), ("audit", audit)):
            if n in text:
                found.append(f"{n[:12]}... in a {where}")
    for n in LOG_AUDIT_ONLY:
        for where, text in (("log", logs), ("audit", audit)):
            if n in text:
                found.append(f"{n[:12]}... in a {where}")
    return found


async def _add(w: R3App, name: str, *, child: bool) -> str:
    r = await w.client.post(
        "/v1/faces",
        json={
            "name": name,
            "relation": "family",
            "child": child,
            "vip": True,
            "given_by": "parent_guardian" if child else "self",
            "consent_version": "fc1",
            "confirm": True,
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["person"]["id"])


async def _arm(w: R3App) -> None:
    r = await w.client.put(
        "/v1/home/cameras",
        json={"cameras": {"gate": {"label": "Gate", "alarm_zones": ["gate"]}}},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert (
        await w.client.post("/v1/home/arm", json={"mode": "away"}, headers=H)
    ).status_code == 200
    rev = (await w.state.camera.alarm.record(UID)).rev
    ack = {"type": "ack", "id": f"arm:{rev}:abc", "at": 1.0, "what": "state", "rev": rev}
    assert (await w.event(ack)).status_code == 200


async def _snapshot_on(w: R3App) -> None:
    body = {"snapshot": {"on": True, "confirm": True}}
    assert (await w.client.put("/v1/notify/settings", json=body, headers=H)).status_code == 200


async def _names_on(w: R3App) -> None:
    body = {"names_in_alerts": True}
    assert (await w.client.put("/v1/notify/settings", json=body, headers=H)).status_code == 200


def _texts(w: R3App) -> str:
    return "\n".join(w.sent_texts())


# ---- the flows ---------------------------------------------------------------------------------

Flow = Callable[[R3App], Awaitable[list[str]]]


async def f01_link_and_heartbeat(w: R3App) -> list[str]:
    f: list[str] = []
    if (await w.event(heartbeat())).status_code != 200:
        f.append("heartbeat refused")
    view = (await w.client.get("/v1/home", headers=H)).json()
    if view.get("state") != "online":
        f.append(f"not online: {view.get('state')}")
    return f


async def f02_child_added_and_enrolled(w: R3App) -> list[str]:
    pid = await _add(w, CHILD, child=True)
    await w.event(heartbeat(faces={pid: 6}))
    people = (await w.client.get("/v1/faces", headers=H)).json()["people"]
    return [] if people and people[0]["state"] == "enrolled" else [f"not enrolled: {people}"]


async def f03_armed_child_alert_never_names(w: R3App) -> list[str]:
    pid = await _add(w, CHILD, child=True)
    await w.event(heartbeat(faces={pid: 6}))
    await _names_on(w)  # even with names on, a child is never named
    await _arm(w)
    await w.event(detection(face={"person": pid, "score": 0.97}))
    t = _texts(w)
    f = [] if "a child from your family" in t else ["the alert did not go out as a child"]
    return f + ([f"child named on Telegram: {t[:80]}"] if CHILD in t else [])


async def f04_adult_named_only_with_the_switch(w: R3App) -> list[str]:
    """Positive control: the scan can see a name on Telegram when the owner allowed it."""
    pid = await _add(w, ADULT, child=False)
    await w.event(heartbeat(faces={pid: 6}))
    await _arm(w)
    await w.event(detection(face={"person": pid, "score": 0.97}))
    f = [] if ADULT not in _texts(w) else ["adult named with names off"]
    await _names_on(w)
    await w.event(detection(face={"person": pid, "score": 0.97}, camera="gate", zones=["gate"]))
    return f


async def f05_names_on_adult_seen(w: R3App) -> list[str]:
    pid = await _add(w, ADULT, child=False)
    await w.event(heartbeat(faces={pid: 6}))
    await _names_on(w)
    await _arm(w)
    await w.event(detection(face={"person": pid, "score": 0.97}))
    return [] if ADULT in _texts(w) else ["the scan could not see an allowed name"]


async def f06_snapshot_without_opt_in(w: R3App) -> list[str]:
    await _arm(w)
    await w.event(detection(snapshot=SNAP))
    f = [] if not w.photos() else ["a photo left without the opt-in"]
    return f + (["snapshot marker in a Telegram text"] if MARK.decode() in _texts(w) else [])


async def f07_snapshot_with_opt_in(w: R3App) -> list[str]:
    await _snapshot_on(w)
    await _arm(w)
    await w.event(detection(snapshot=SNAP))
    photos = w.photos()
    f = [] if len(photos) == 1 and MARK in photos[0] else [f"photos: {len(photos)}"]
    texts = [
        json.loads(r.content)["text"] for r in w.telegram if r.url.path.endswith("/sendMessage")
    ]
    return f + (["marker in a message"] if any(MARK.decode() in t for t in texts) else [])


async def f08_disarmed_greeting_feed_and_brief(w: R3App) -> list[str]:
    pid = await _add(w, CHILD, child=True)
    await w.event(heartbeat(faces={pid: 6}))
    await w.client.put(
        "/v1/home/cameras",
        json={"cameras": {"gate": {"label": "Gate", "alarm_zones": ["gate"]}}, "greetings": True},
        headers=H,
    )
    face = {"person": pid, "score": 0.96}
    ev = {"type": "face_seen", "id": "face:ev1", "event": "ev1", "camera": "gate"}
    await w.event({**ev, "zones": ["gate"], "at": 1.0e9 + 10, "face": face})
    section = await w.state.camera_brief.section(UID, ZoneInfo("Asia/Kolkata"), date.today())
    f = [] if CHILD not in _texts(w) else ["child named in a greeting alert"]
    if section is not None and CHILD in json.dumps(section.model_dump(mode="json")):
        f.append("child named in the brief's Home overnight")
    return f


async def f09_telegram_turn_faces_refused(w: R3App) -> list[str]:
    await _add(w, CHILD, child=True)
    with telegram_turn():
        out = await w.state.gateway.execute(
            ToolCall(id="t1", name="faces_list", arguments={}), scope=f"{UID}:tg"
        )
    f = [] if out.outcome is GatewayOutcome.DENIED else [f"faces_list ran: {out.outcome}"]
    return f + ([] if CHILD not in json.dumps(out.result, default=str) else ["name in result"])


async def f10_privacy_export_and_delete(w: R3App) -> list[str]:
    pid = await _add(w, CHILD, child=True)
    await w.event(heartbeat(faces={pid: 6}))
    r = await w.client.get("/v1/privacy", headers=H)
    cats = {c["id"]: c for c in r.json()["categories"]}
    f = [] if cats.get("faces", {}).get("count") == 1 else [f"faces count {cats.get('faces')}"]
    unlinked = await w.client.delete("/v1/home/link?confirm=1", headers=H)
    return f + ([] if unlinked.status_code == 200 else ["unlink failed"])


async def f11_offline_alert_while_armed(w: R3App) -> list[str]:
    await w.event(heartbeat())
    await _arm(w)
    store = w.state.home_store
    store._seen.clear()  # noqa: SLF001 - as if this instance never heard from the laptop
    doc_path = f"jarvis_home/{UID}"
    doc = dict(w.docs._data[doc_path])  # noqa: SLF001
    doc["last_seen_at"] = 1.0
    w.docs._data[doc_path] = doc  # noqa: SLF001
    await w.state.home_watchdog.run()
    return [] if "stopped answering" in _texts(w) else ["no offline alert"]


async def f12_vip_reference_stays_sealed(w: R3App) -> list[str]:
    r = await w.client.post("/v1/notify/vip", json={"kind": "phone", "ref": VIP_REF}, headers=H)
    f = [] if r.status_code == 201 else [f"VIP not added: {r.status_code}"]
    listed = (await w.client.get("/v1/notify/vip", headers=H)).text
    settings = (await w.client.get("/v1/notify/settings", headers=H)).text
    if "9876513579" in listed.replace(" ", "") or "98765" in listed + settings:
        f.append("the number came back from the server")
    return f


async def _public(host: str) -> list[str]:
    return ["142.250.1.1"]


async def f13_push_subscription_stays_sealed(w: R3App) -> list[str]:
    pushed: list[str] = []

    async def no_network(request: httpx.Request) -> httpx.Response:
        pushed.append(request.url.host)
        return httpx.Response(201)

    push = w.state.push
    push._resolver = _public  # noqa: SLF001 - no DNS in the eval
    push._http = httpx.AsyncClient(transport=httpx.MockTransport(no_network))  # noqa: SLF001
    br = Browser(PUSH_ENDPOINT)
    body = {
        "name": "Chrome",
        "endpoint": br.endpoint,
        "keys": {"p256dh": br.p256dh, "auth": br.auth},
    }
    r = await w.client.post("/v1/push/subscribe", json=body, headers=H)
    f = [] if r.status_code == 201 else [f"not subscribed: {r.status_code} {r.text[:80]}"]
    await _arm(w)
    await w.event(detection())  # the burglar alert is pushed to that browser too
    if pushed != ["fcm.googleapis.com"]:
        f.append(f"the alert was not pushed to the browser: {pushed}")
    devices = (await w.client.get("/v1/push/devices", headers=H)).text
    if "needle-endpoint" in devices or br.auth in devices:
        f.append("the device list returned the endpoint or its key")
    return f


async def f14_camera_label_only_where_the_owner_reads_it(w: R3App) -> list[str]:
    """Positive control: the owner's own label is in his alert, so the scan can see it."""
    cams = {"cameras": {"gate": {"label": LABEL, "alarm_zones": ["gate"]}}}
    assert (await w.client.put("/v1/home/cameras", json=cams, headers=H)).status_code == 200
    assert (await w.client.post("/v1/home/arm", json={}, headers=H)).status_code == 200
    rev = (await w.state.camera.alarm.record(UID)).rev
    await w.event({"type": "ack", "id": f"arm:{rev}:abc", "at": 1.0, "what": "state", "rev": rev})
    await w.event(detection())
    return [] if LABEL in _texts(w) else ["the owner's label did not reach his alert"]


async def f15_detection_with_a_face_id(w: R3App) -> list[str]:
    pid = await _add(w, ADULT, child=False)
    LOG_AUDIT_ONLY.append(pid)
    await w.event(heartbeat(faces={pid: 6}))
    await _arm(w)
    await w.event(detection(face={"person": pid, "score": 0.97}))
    t = _texts(w)
    f = [] if "Burglar alert" in t else ["no alert for a recognised face"]
    return f + ([f"face id on Telegram: {t[:60]}"] if pid in t else [])


FLOWS: tuple[tuple[str, Flow], ...] = (
    ("n01_link_and_heartbeat", f01_link_and_heartbeat),
    ("n02_child_added_and_enrolled", f02_child_added_and_enrolled),
    ("n03_armed_child_alert_never_names", f03_armed_child_alert_never_names),
    ("n04_adult_unnamed_with_names_off", f04_adult_named_only_with_the_switch),
    ("n05_positive_control_allowed_name_is_seen", f05_names_on_adult_seen),
    ("n06_snapshot_without_opt_in", f06_snapshot_without_opt_in),
    ("n07_snapshot_with_opt_in_only_as_a_photo", f07_snapshot_with_opt_in),
    ("n08_greeting_and_brief_never_name_a_child", f08_disarmed_greeting_feed_and_brief),
    ("n09_telegram_turn_faces_refused", f09_telegram_turn_faces_refused),
    ("n10_privacy_and_unlink", f10_privacy_export_and_delete),
    ("n11_offline_alert_while_armed", f11_offline_alert_while_armed),
    ("n12_vip_reference_stays_sealed", f12_vip_reference_stays_sealed),
    ("n13_push_subscription_stays_sealed", f13_push_subscription_stays_sealed),
    ("n14_camera_label_only_in_the_owners_alert", f14_camera_label_only_where_the_owner_reads_it),
    ("n15_detection_with_a_face_id", f15_detection_with_a_face_id),
)


async def one(case: str, flow: Flow) -> dict[str, Any]:
    failures: list[str] = []
    LOG_AUDIT_ONLY.clear()
    try:
        async with r3_app() as w:
            # after create_app: its logging set-up replaces the root handlers
            with captured() as cap:
                # a canary through a jarvis logger proves the scan can see the app's log lines
                logging.getLogger("jarvis.home.webhook").info("r3 needles canary")
                w.state.camera_brief = HomeOvernightBrief(
                    w.state.camera.feed, w.state.camera.config
                )
                failures += await flow(w)
                failures += scan(w, cap, SECRET_NEEDLES + NAME_NEEDLES + TYPED_NEEDLES)
                if not any("r3 needles canary" in line for line in cap.lines):
                    failures.append("the log capture saw nothing: the scan would be blind")
            if CHILD in _texts(w):
                failures.append("child's name on Telegram")
    except Exception as exc:  # noqa: BLE001 - a crash is a failed case, with its type
        failures.append(f"crashed: {type(exc).__name__}: {exc}")
    return {"id": case, "passed": not failures, "failures": failures}


async def run_all() -> list[dict[str, Any]]:
    return [await one(case, flow) for case, flow in FLOWS]


# ---- the negative control ---------------------------------------------------------------------


async def controls() -> dict[str, Any]:
    """A debug line logging every webhook body must make the suite fail."""
    original = webhook_mod.read_capped

    async def leaky(request: Any, cap: int) -> bytes | None:
        body = await original(request, cap)
        webhook_mod.log.info("webhook body", extra={"body": (body or b"").decode("latin-1")})
        return body

    webhook_mod.read_capped = leaky  # type: ignore[assignment]
    try:
        results = await run_all()
    finally:
        webhook_mod.read_capped = original  # type: ignore[assignment]
    failed = [r["id"] for r in results if not r["passed"]]
    typed = await _typed_control()
    return {
        "name": "debug_log_webhook_bodies",
        "suite_failed": bool(failed) and bool(typed),
        "failed_cases": {"debug_log_webhook_bodies": failed, "debug_log_vip_and_push": typed},
    }


async def _typed_control() -> list[str]:
    """S7: a log line of the VIP references and of a new push endpoint must fail the suite."""
    update, add = NotifyStore.update, PushStore.add
    leak = logging.getLogger("jarvis.notify.store")

    async def leaky_update(self: NotifyStore, uid: str, fn: Any) -> Any:
        new = await update(self, uid, fn)
        leak.info("notify settings saved", extra={"vip": [v.ref for v in new.vip]})
        return new

    async def leaky_add(self: PushStore, uid: str, name: str, endpoint: str, *a: Any) -> Any:
        leak.info("push device added", extra={"endpoint": endpoint})
        return await add(self, uid, name, endpoint, *a)

    NotifyStore.update = leaky_update  # type: ignore[method-assign]
    PushStore.add = leaky_add  # type: ignore[method-assign]
    try:
        results = await run_all()
    finally:
        NotifyStore.update, PushStore.add = update, add  # type: ignore[method-assign]
    return [r["id"] for r in results if not r["passed"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    results = asyncio.run(run_all())
    return finish(HERE, "r3_needles", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
