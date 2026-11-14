# tests/test_r3_wiring.py -- R3 I1: the app wires the home link, the camera, faces and the one alert
# policy (api/home_wiring.py), each OFF with plain words without the token key; one webhook
# dispatches every kind to the parts that take it; the alarm, faces and alerts meet end to end;
# the R3 tools are registered (never offered offline); the watchdog's jobs are unique; the privacy
# dashboard lists the R3 categories with Faces last; the bridge gets its environment and finds C's
# face library; the VIP list has its own keyring purpose; Telegram can carry the opted-in photo.
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.routing import iter_route_contexts
from pydantic import SecretStr
from r3_app import HOME_ID, UID, H, R3App, detection, heartbeat, r3_app, r3_settings

from jarvis.alerts import AlertResult
from jarvis.api import auth as auth_mod
from jarvis.home.heartbeat import HeartbeatHandler
from jarvis.home.ports import FacesState
from jarvis.home.webhook import HomeWebhook
from jarvis.homebridge.app import create_bridge
from jarvis.homebridge.config import BridgeConfig
from jarvis.homebridge.registry import PLUGINS
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.llm.fallback import OFFLINE_TOOLS
from jarvis.notify.models import NotifySettings, QuietHours, Vip
from jarvis.notify.sink import PolicyAlerts
from jarvis.notify.store import NotifyStore
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.client import TelegramClient

R3_TOOLS = {
    "home_status",
    "home_devices",
    "home_control",
    "home_arm",
    "home_disarm",
    "camera_history",
    "faces_list",
}
JPEG = b"\xff\xd8\xff\xe0" + b"SNAPSHOT-NEEDLE-7c1f" + b"\x00" * 64 + b"\xff\xd9"
CHILD = "Mira Needlechild"


async def _cameras(w: R3App) -> None:
    r = await w.client.put(
        "/v1/home/cameras",
        json={"cameras": {"gate": {"label": "Gate", "alarm_zones": ["gate"]}}},
        headers=H,
    )
    assert r.status_code == 200, r.text


async def _armed(w: R3App) -> None:
    await _cameras(w)
    r = await w.client.post("/v1/home/arm", json={"mode": "away"}, headers=H)
    assert r.status_code == 200, r.text
    rev = (await w.state.camera.alarm.record(UID)).rev
    ack = {"type": "ack", "id": f"arm:{rev}:abc", "at": w.clock[0], "what": "state", "rev": rev}
    assert (await w.event(ack)).status_code == 200
    view = (await w.client.get("/v1/home/alarm", headers=H)).json()
    assert view["armed"] is True and view["confirmed"] is True, view


# ---- off without the token key ---------------------------------------------------------------


async def test_without_the_token_key_home_faces_and_alert_settings_are_off() -> None:
    async with r3_app(r3_settings(token_key=None), link=False) as w:
        st = w.state
        assert st.home_store is None and st.camera is None and st.faces is None
        assert st.notify is None and st.push is None
        assert not isinstance(st.alerts, PolicyAlerts)  # R1's Telegram alerts, as before
        assert (await w.client.post("/home/webhook", content=b"{}")).status_code == 404
        home = (await w.client.get("/v1/home", headers=H)).json()
        assert home["available"] is False and "encryption key" in home["reason"]
        assert (await w.client.get("/v1/faces", headers=H)).json()["available"] is False
        assert not R3_TOOLS & {t.name for t in st.gateway.registry.specs()}


async def test_home_switched_off_keeps_the_alert_policy() -> None:
    async with r3_app(r3_settings(home_enabled=False), link=False) as w:
        assert w.state.home_store is None and w.state.camera is None
        assert isinstance(w.state.alerts, PolicyAlerts)


# ---- on: services, routes, tools, jobs, privacy -------------------------------------------------


async def test_everything_is_wired_with_the_token_key() -> None:
    async with r3_app() as w:
        st = w.state
        for name in ("home_store", "home_link", "home_webhook", "home_watchdog", "home_devices"):
            assert getattr(st, name) is not None, name
        assert st.camera is not None and st.faces is not None and st.notify is not None
        assert st.push is not None  # VAPID from the token key + the public address
        assert isinstance(st.alerts, PolicyAlerts)
        assert st.brief._home is not None  # noqa: SLF001 - Home overnight in the brief
        names = {t.name for t in st.gateway.registry.specs()}
        assert R3_TOOLS <= names
        assert not R3_TOOLS & set(OFFLINE_TOOLS)  # offline mode never offers an R3 tool
        paths = {str(rc.path) for rc in iter_route_contexts(w.app.routes)}
        for path in (
            "/home/link",
            "/home/webhook",
            "/internal/home/watchdog",
            "/v1/home",
            "/v1/home/alarm",
            "/v1/home/arm",
            "/v1/home/disarm",
            "/v1/faces",
            "/v1/notify/settings",
            "/v1/push/key",
        ):
            assert path in paths, path


async def test_the_watchdog_runs_every_job_once_with_unique_names() -> None:
    async with r3_app() as w:
        out = await w.state.home_watchdog.run()
        jobs = out["jobs"]
        assert {
            "home_offline",
            "home_claims_sweep",
            "home_link_sweep",
            "home_arm_pending",
            "home_feed_sweep",
            "notify_held",
            "notify_summaries",
            "notify_rate_sweep",
        } <= set(jobs)
        assert all(v == "ok" for v in jobs.values()), jobs


async def test_privacy_lists_the_r3_categories_with_faces_last() -> None:
    async with r3_app() as w:
        r = await w.client.get("/v1/privacy", headers=H)
        assert r.status_code == 200, r.text
        ids = [c["id"] for c in r.json()["categories"]]
        assert ids[-6:] == ["home", "home_feed", "camera_home", "notify", "webpush", "faces"]
        assert ids.count("faces") == 1


async def test_the_home_routes_have_their_own_body_caps() -> None:
    async with r3_app() as w:
        big = await w.client.post("/home/webhook", content=b"x" * (128 * 1024 + 1))
        assert big.status_code == 413
        link = await w.client.post("/home/link", content=b"x" * 5000)
        assert link.status_code == 413


# ---- the one webhook: dispatch, alarm, faces, alerts ------------------------------------------


async def test_a_heartbeat_answers_with_every_part_of_the_state() -> None:
    async with r3_app() as w:
        r = await w.event(heartbeat())
        assert r.status_code == 200, r.text
        state = json.loads(r.content)["state"]
        assert {"arm", "settings", "devices", "faces"} <= set(state)
        assert (await w.client.get("/v1/home", headers=H)).json()["state"] == "online"


async def test_a_kind_no_handler_takes_is_refused_and_never_claimed() -> None:
    async with r3_app() as w:
        st = w.state
        st.home_webhook = HomeWebhook(
            st.home_store, [HeartbeatHandler(st.home_store, None)], [], clock=lambda: w.clock[0]
        )
        ev = detection()
        assert (await w.event(ev)).status_code == 422
        assert await st.home_store.claim(UID, ev["id"]) is True  # the id was never taken


async def test_disarmed_detection_is_dropped_and_counted_with_no_alert() -> None:
    async with r3_app() as w:
        await _cameras(w)
        assert (await w.event(detection())).status_code == 200
        assert w.sent_texts() == []
        assert (await w.client.get("/v1/home", headers=H)).json()["dropped_disarmed"] == 1


async def test_armed_detection_rings_telegram_once_through_the_policy() -> None:
    async with r3_app() as w:
        await _armed(w)
        ev = detection()
        assert (await w.event(ev)).status_code == 200
        assert (await w.event(ev)).status_code == 200  # a bridge retry is a no-op
        texts = [t for t in w.sent_texts() if "Burglar alert" in t]
        assert len(texts) == 1 and "someone JARVIS didn't recognise" in texts[0]
        feed = (await w.client.get("/v1/home/feed?day=today", headers=H)).json()["items"]
        assert feed and feed[0]["decision"] == "ring"


async def test_a_recognised_child_still_rings_and_is_never_named_off_the_console() -> None:
    async with r3_app() as w:
        r = await w.client.post(
            "/v1/faces",
            json={
                "name": CHILD,
                "relation": "family",
                "child": True,
                "vip": True,
                "given_by": "parent_guardian",
                "consent_version": "fc1",
                "confirm": True,
            },
            headers=H,
        )
        assert r.status_code == 201, r.text
        pid = r.json()["person"]["id"]
        assert (await w.event(heartbeat(faces={pid: 5}))).status_code == 200
        await _armed(w)
        ev = detection(face={"person": pid, "score": 0.97})
        assert (await w.event(ev)).status_code == 200
        texts = [t for t in w.sent_texts() if "Burglar alert" in t]
        assert len(texts) == 1 and "a child from your family" in texts[0]
        assert not any(CHILD in t for t in w.sent_texts())
        assert not any(CHILD in json.dumps(d) for d in w.docs._data.values())  # noqa: SLF001


async def test_a_face_lookup_that_fails_never_costs_the_burglar_alert() -> None:
    async with r3_app() as w:
        await _armed(w)

        async def broken(*_: Any) -> Any:
            raise RuntimeError("registry down")

        w.state.camera.events._faces.resolve = broken  # noqa: SLF001
        ev = detection(face={"person": "fp_0123456789ab", "score": 0.99})
        assert (await w.event(ev)).status_code == 200
        assert len([t for t in w.sent_texts() if "Burglar alert" in t]) == 1


async def test_without_the_opt_in_a_snapshot_never_leaves() -> None:
    async with r3_app() as w:
        await _armed(w)
        snap = base64.b64encode(JPEG).decode()
        assert (await w.event(detection(snapshot=snap))).status_code == 200
        assert w.photos() == [] and len(w.sent_texts()) == 1  # the alert, without the photo
        assert not any("SNAPSHOT-NEEDLE" in t for t in w.sent_texts())


async def test_the_opted_in_snapshot_goes_only_to_telegrams_photo() -> None:
    async with r3_app() as w:
        await _armed(w)
        snap = base64.b64encode(JPEG).decode()
        r = await w.client.put(
            "/v1/notify/settings", json={"snapshot": {"on": True, "confirm": True}}, headers=H
        )
        assert r.status_code == 200, r.text
        assert (await w.event(detection(snapshot=snap))).status_code == 200
        photos = w.photos()
        assert len(photos) == 1 and b"SNAPSHOT-NEEDLE-7c1f" in photos[0]
        assert b'name="protect_content"\r\n\r\ntrue' in photos[0]
        for d in w.docs._data.values():  # noqa: SLF001
            assert "SNAPSHOT-NEEDLE" not in json.dumps(d) and snap not in json.dumps(d)


async def test_r1_alerts_go_through_the_policy_and_wait_out_quiet_hours() -> None:
    async with r3_app() as w:
        store: NotifyStore = w.state.notify_store
        await store.update(
            UID,
            lambda s: s.model_copy(
                update={"quiet": QuietHours(on=True, start="00:00", end="23:59")}
            ),
        )
        got = await w.state.alerts.send(UID, "A card is waiting.", kind="approval_waiting")
        assert isinstance(got, AlertResult) and got.sent is False and "quiet hours" in got.reason
        assert w.sent_texts() == []
        assert [i["kind"] for i in await store.held_list(UID)] == ["approval_waiting"]


async def test_unlink_wipes_the_camera_state_and_the_arm_rev_never_goes_back() -> None:
    async with r3_app() as w:
        await _cameras(w)
        rev = (await w.state.camera.alarm.record(UID)).rev
        r = await w.client.delete("/v1/home/link?confirm=1", headers=H)  # disarmed: simple
        assert r.status_code == 200 and r.json()["unlinked"] is True
        after = await w.state.camera.alarm.record(UID)
        assert after.armed is False and after.rev > rev
        assert (await w.state.camera.config.get(UID)).cameras == {}


# ---- integrated review S4: unlinking while armed is a disarm ------------------------------------

OWNER_EMAIL = "akash@example.com"


def _google() -> Any:
    from jarvis.config import AuthMode

    return r3_settings(
        auth_mode=AuthMode.GOOGLE,
        google_client_id="cid.apps.googleusercontent.com",
        google_client_secret=SecretStr("gsecret"),
        owner_emails=[OWNER_EMAIL],
        session_secret=SecretStr("x" * 32),
        api_token=SecretStr("cli-token"),
        public_base_url="http://test",
    )


async def _sign_in(w: R3App, *, fresh: bool) -> str:
    """A Google session in this browser; `fresh`: the owner just signed in again (5 minutes)."""
    from jarvis.api.identity import user_id_for_email

    async def fake(request: Any) -> dict[str, Any]:
        return {
            "userinfo": {
                "email": OWNER_EMAIL,
                "email_verified": True,
                "sub": OWNER_EMAIL,
                "auth_time": int(auth_mod._now()),
            }
        }

    w.app.state.oauth.google.authorize_access_token = fake
    assert (await w.client.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)
    if fresh:
        await w.client.get("/auth/login?reauth=1", follow_redirects=False)
        assert (await w.client.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)
    uid = user_id_for_email(OWNER_EMAIL)
    await w.state.home_store.link(uid, HOME_ID, "https://laptop.tail1234.ts.net:8443", b"s" * 32)
    return uid


async def _arm_signed_in(w: R3App, uid: str) -> None:
    await _cameras(w)
    assert (await w.client.post("/v1/home/arm", json={}, headers=H)).status_code == 200
    assert (await w.state.camera.alarm.record(uid)).armed is True


async def test_unlink_while_armed_needs_disarm_proof() -> None:
    async with r3_app() as w:
        await _armed(w)
        r = await w.client.delete("/v1/home/link?confirm=1", headers=H)  # a bearer caller
        assert r.status_code == 403 and r.json()["error"] == "console_only", r.text
        assert (await w.state.camera.alarm.record(UID)).armed is True
        assert await w.state.home_store.status(UID) is not None  # still linked
    async with r3_app(_google(), link=False) as w:
        uid = await _sign_in(w, fresh=False)
        await _arm_signed_in(w, uid)
        r = await w.client.delete("/v1/home/link?confirm=1", headers=H)
        assert r.status_code == 403 and r.json()["error"] == "reauth_required", r.text
        assert (await w.state.camera.alarm.record(uid)).armed is True
        assert await w.state.home_store.status(uid) is not None


async def test_unlink_while_armed_with_a_fresh_sign_in_disarms_audited_then_unlinks() -> None:
    async with r3_app(_google(), link=False) as w:
        uid = await _sign_in(w, fresh=True)
        await _arm_signed_in(w, uid)
        r = await w.client.delete("/v1/home/link?confirm=1", headers=H)
        assert r.status_code == 200 and r.json()["unlinked"] is True, r.text
        assert (await w.state.camera.alarm.record(uid)).armed is False
        assert await w.state.home_store.status(uid) is None
        tools = [e.tool for e in w.state.gateway.audit._entries]  # noqa: SLF001
        assert "home_disarm" in tools and tools.index("home_disarm") < tools.index("home_unlink")


async def test_privacy_delete_of_the_home_link_while_armed_needs_disarm_proof() -> None:
    async with r3_app(_google(), link=False) as w:
        uid = await _sign_in(w, fresh=False)
        await _arm_signed_in(w, uid)
        cats = {
            c["id"]: c for c in (await w.client.get("/v1/privacy", headers=H)).json()["categories"]
        }
        r = await w.client.post(
            "/v1/privacy/home/delete", json={"rev": cats["home"]["rev"]}, headers=H
        )
        assert r.status_code == 403 and r.json()["error"] == "reauth_required", r.text
        assert (await w.state.camera.alarm.record(uid)).armed is True
        assert await w.state.home_store.status(uid) is not None
        await w.client.get("/auth/login?reauth=1", follow_redirects=False)
        assert (await w.client.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)
        r = await w.client.post(
            "/v1/privacy/home/delete", json={"rev": cats["home"]["rev"]}, headers=H
        )
        assert r.status_code == 200, r.text
        assert (await w.state.camera.alarm.record(uid)).armed is False
        assert await w.state.home_store.status(uid) is None


async def test_the_home_privacy_source_never_unlinks_an_armed_home_on_its_own() -> None:
    from jarvis.camera.ports import AlarmRefused

    async with r3_app() as w:
        await _armed(w)
        home = next(s for s in _privacy_sources(w) if s.id == "home")
        with pytest.raises(AlarmRefused):
            await home.delete(UID)
        assert (await w.state.camera.alarm.record(UID)).armed is True
        assert await w.state.home_store.status(UID) is not None


def _privacy_sources(w: R3App) -> list[Any]:
    from jarvis.api.home_wiring import home_privacy_sources

    return home_privacy_sources(w.app)


async def test_home_disarm_through_the_gateway_never_disarms() -> None:
    from jarvis.llm.base import ToolCall
    from jarvis.tools.gateway import GatewayOutcome

    async with r3_app() as w:
        await _armed(w)
        out = await w.state.gateway.execute(
            ToolCall(id="t1", name="home_disarm", arguments={}), scope=f"{UID}:s"
        )
        assert out.outcome is GatewayOutcome.EXECUTED and "Home panel" in out.result["message"]
        assert (await w.state.camera.alarm.record(UID)).armed is True


async def test_permission_rows_say_link_your_laptop_first_until_it_is_linked() -> None:
    from jarvis.permissions.availability import LINK_HOME, NO_KEY, notes

    async with r3_app(link=False) as w:
        rows = await notes(w.state, UID)
        for gid in ("home_read", "home_control", "home_arm", "home_secure", "camera"):
            assert rows[gid].available is False and rows[gid].note == LINK_HOME, gid
        await w.state.home_store.link(
            UID, HOME_ID, "https://laptop.tail1234.ts.net:8443", b"s" * 32
        )
        assert (await notes(w.state, UID))["home_arm"].available is True
    async with r3_app(r3_settings(token_key=None), link=False) as w:
        assert (await notes(w.state, UID))["camera"].note == NO_KEY


# ---- the bridge: its environment, its plugins, the face library ---------------------------------


class _Sink:
    async def post_event(self, event: Any) -> bool:
        return True


def test_the_bridge_builds_every_plugin_with_its_environment(tmp_path: Path) -> None:
    cfg = BridgeConfig(jarvis_url="https://jarvis.example.run.app", data_dir=tmp_path)
    env = {"MQTT_USER": "bridge", "MQTT_PASSWORD": "pw-1234567890", "FACES_ATTEMPTS_DIR": "/x"}
    bridge = create_bridge(cfg, PLUGINS, env=env)
    names = [p.name for p in bridge.plugins]
    assert names == ["core", "camera", "faces", "facegroups"]  # R11.1 C: the face groups
    camera = bridge.plugins[1]
    assert camera._ctx.env["MQTT_USER"] == "bridge"  # noqa: SLF001
    assert camera._ctx.peers["faces"] is bridge.plugins[2]  # noqa: SLF001


def test_the_camera_asks_cs_face_library_and_a_deleting_person_never_matches(
    tmp_path: Path,
) -> None:
    cfg = BridgeConfig(jarvis_url="https://jarvis.example.run.app", data_dir=tmp_path)
    bridge = create_bridge(cfg, PLUGINS, env={"MQTT_USER": "b", "MQTT_PASSWORD": "p"})
    camera, faces = bridge.plugins[1], bridge.plugins[2]
    a, b = "fp_aaaaaaaaaaaa", "fp_bbbbbbbbbbbb"
    faces.library.apply(FacesState(rev=2, people=(a, b), deleting=()))
    assert camera.face([a, 0.95]) is not None
    assert camera.face([a, 0.95], "car") is None  # a car's "face" never matches
    faces.library.apply(FacesState(rev=3, people=(a,), deleting=(b,)))
    faces.library.apply(FacesState(rev=2, people=(a, b), deleting=()))  # a late, older push
    assert camera.face([b, 0.99]) is None  # still being deleted at home
    assert camera.face(["Anjali", 0.99]) is None  # a name typed in Frigate's UI


# ---- the VIP list's own key; Telegram's photo ----------------------------------------------------


async def test_the_vip_list_is_sealed_under_its_own_keyring_purpose() -> None:
    docs, ring = MemoryDocs(), Keyring(bytes(range(1, 33)))
    store = NotifyStore(docs, ring, prefix="t_")
    vip = Vip(id="v_00000001", kind="phone", ref="+91 98765 43210")
    await store.update(UID, lambda s: s.model_copy(update={"vip": (vip,)}))
    doc = await docs.get(f"t_notify/{UID}")
    assert doc is not None and "98765" not in json.dumps(doc)
    plain = ring.cipher("notify").decrypt(doc["vip_blob"], aad=f"notify_vip/{UID}/v1")
    assert b"98765" in plain
    with pytest.raises(VaultError):
        ring.cipher("faces").decrypt(doc["vip_blob"], aad=f"notify_vip/{UID}/v1")
    assert (await store.get(UID)).vip[0].ref == "+91 98765 43210"
    assert isinstance(await store.get("nobody"), NotifySettings)


async def test_telegram_send_photo_is_one_protected_multipart_upload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = TelegramClient(
        SecretStr("1:tok"), http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await client.send_photo(CHAT, JPEG, "Burglar alert at Gate")
    (req,) = seen
    assert req.url.path.endswith("/sendPhoto")
    body = req.content
    assert JPEG in body and b"Burglar alert at Gate" in body
    assert b'name="protect_content"\r\n\r\ntrue' in body and b'name="chat_id"\r\n\r\n42' in body


CHAT = 42
_ = HOME_ID


# ---- integrated review S3 / S1: an armed alert is never lost ------------------------------------


def _telegram_failing_first(w: R3App, failures: int) -> list[int]:
    left = [failures]

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        w.telegram.append(request)
        if request.url.path.endswith("/sendMessage") and left[0] > 0:
            left[0] -= 1
            return httpx.Response(500, json={"ok": False, "description": "down"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    w.state.telegram.client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: SLF001
    return left


async def test_armed_detection_with_telegram_500_answers_503_then_delivers_on_retry() -> None:
    async with r3_app() as w:
        await _armed(w)
        _telegram_failing_first(w, 1)
        ev = detection(id="det:fail-1")
        assert (await w.event(ev)).status_code == 503  # nobody had it: the bridge retries
        assert (await w.event(ev)).status_code == 200  # never swallowed as a storm
        delivered = [
            json.loads(r.content)["text"]
            for r in w.telegram
            if r.url.path.endswith("/sendMessage") and b"Burglar alert" in r.content
        ]
        assert len(delivered) == 2  # the failed try and the retry that rang
        assert (await w.event(ev)).status_code == 200  # a third copy is a no-op
        assert sum(1 for r in w.telegram if b"Burglar alert" in r.content) == 2


async def test_a_bridge_whose_mqtt_library_is_missing_makes_an_armed_home_alert(
    tmp_path: Path,
) -> None:
    """C1/S1 end to end: the camera plugin can't connect (no MQTT library in the image) -> its
    heartbeat part says mqtt false -> the cloud, armed, alerts that camera alerts can't arrive."""
    from contextlib import AbstractAsyncContextManager

    from jarvis.homebridge.camera import CameraPlugin
    from jarvis.homebridge.plugins import BridgeContext, FatalTaskError

    def connect() -> AbstractAsyncContextManager[Any]:
        raise ModuleNotFoundError("No module named 'aiomqtt'")

    class Frigate:
        async def stats(self) -> tuple[bool, dict[str, bool]]:
            return True, {"gate": True}

        async def has_doorstep_model(self) -> bool:
            return False

    ctx = BridgeContext(env={}, data_dir=tmp_path, events=_Sink())
    plugin = CameraPlugin(ctx, frigate=Frigate(), connect=connect)  # type: ignore[arg-type]
    with pytest.raises(FatalTaskError):
        await plugin.mqtt.run()
    parts = (await plugin.heartbeat_part()).model_dump(mode="json", exclude_none=True)
    assert parts["mqtt"] is False
    async with r3_app() as w:
        await _armed(w)
        assert (await w.event(heartbeat(**parts))).status_code == 200
        texts = [t for t in w.sent_texts() if "camera's events" in t]
        assert len(texts) == 1
        assert (await w.client.get("/v1/home", headers=H)).json()["state"] == "degraded"


# ---- integrated review H3: held alerts and storm summaries go out with Home off ------------------


async def test_with_home_off_the_tick_runs_the_alert_jobs() -> None:
    async with r3_app(r3_settings(home_enabled=False), link=False) as w:
        names = [j.name for j in w.state.tick_jobs]
        assert {"notify_held", "notify_summaries", "notify_rate_sweep"} <= set(names)
        assert len(names) == len(set(names))
    async with r3_app() as w:  # Home on: the 5-minute watchdog runs them, the tick does not
        names = [j.name for j in w.state.tick_jobs]
        assert not {"notify_held", "notify_summaries", "notify_rate_sweep"} & set(names)


async def test_with_home_off_a_held_vault_reminder_is_delivered_after_quiet_hours() -> None:
    from jarvis.ticks import run_jobs

    async with r3_app(r3_settings(home_enabled=False), link=False) as w:
        await w.state.telegram.store.set_settings(UID, alerts={"vault_expiry": True})
        store: NotifyStore = w.state.notify_store
        await store.update(
            UID,
            lambda s: s.model_copy(
                update={"quiet": QuietHours(on=True, start="00:00", end="23:59")}
            ),
        )
        got = await w.state.alerts.send(UID, "A document expires soon.", kind="vault_expiry")
        assert got.queued is True and w.sent_texts() == []
        await store.update(UID, lambda s: s.model_copy(update={"quiet": QuietHours(on=False)}))
        out = await run_jobs(w.state.tick_jobs, [UID])
        assert out["notify_held"] == "ok", out
        assert any("While you were resting" in t for t in w.sent_texts()), w.sent_texts()


# ---- integrated review M9: an optional part that fails never takes the app down ------------------


async def test_a_home_part_that_fails_to_build_leaves_the_app_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.api.home_wiring as hw

    class Broken:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("firestore client exploded")

    monkeypatch.setattr(hw, "HomeStore", Broken)
    async with r3_app(link=False) as w:
        assert w.state.home_store is None and w.state.camera is None
        chat = await w.client.post("/v1/chat", json={"message": "Hello"}, headers=H)
        assert chat.status_code == 200, chat.text
        assert (await w.client.get("/v1/home", headers=H)).json()["available"] is False
        names = {j.name for j in w.state.tick_jobs}  # the alert jobs still run (the tick)
        assert "notify_held" in names


async def test_browser_push_that_fails_to_build_leaves_alerts_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.api.home_wiring as hw

    def broken(*a: Any, **k: Any) -> Any:
        raise ValueError("bad VAPID key")

    monkeypatch.setattr(hw, "build_push", broken)
    async with r3_app() as w:
        assert w.state.push is None and isinstance(w.state.alerts, PolicyAlerts)
        assert w.state.home_store is not None


async def test_the_watchdog_answers_503_when_a_job_failed() -> None:
    from jarvis.api.scheduler_auth import require_scheduler

    async with r3_app() as w:
        w.app.dependency_overrides[require_scheduler] = lambda: None
        try:
            ok = await w.client.post("/internal/home/watchdog")
            assert ok.status_code == 200, ok.text

            async def boom(owners: Any) -> dict[str, int]:
                raise RuntimeError("x")

            w.state.home_watchdog._offline.run = boom  # noqa: SLF001
            bad = await w.client.post("/internal/home/watchdog")
            assert bad.status_code == 503 and bad.json()["jobs"]["home_offline"] == "failed"
        finally:
            w.app.dependency_overrides.clear()
