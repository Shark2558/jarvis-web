# evals/r11_1/photos.py
"""R11.1 eval, Part C (`photos`), on fakes (plan docs/plans/r11-1-observations.md "Tests and evals
per part", row C; decisions D13, D14, D15, D21-C).

O5  the deploy script switches the Photos Picker API on (a failure warns and carries on) and the
    Photos path names the service and the fix.
O6  2,000 picked photos import in steps of 10, never in one request; the import resumes after a
    restart and after "laptop off"; every photo has its metadata stripped; it stops cleanly when
    Google ends the Picker session; the progress line is the plan's.
O7  on the REAL signed channel and the REAL bridge app (a scripted engine stands in for the two
    models; test pictures are drawn in code, never a real person): the three routes answer ids
    only; an unknown face seen in 3 pictures becomes a group; naming a group runs the consent
    check once per person; a child needs a guardian's yes; without a yes nothing is enrolled and
    the bridge is never told; afterwards a new photo and a camera sighting are recognised with no
    further step; unnamed groups expire and a forget is done only when the laptop confirmed it;
    and the needle scan: no picture, crop or embedding in anything the laptop sends or the cloud
    keeps, logs, audits, tells the owner or shows the model.

Three negative controls, each of which must fail this part on its own:
  consent_check_skipped        `faces.consent.check` passes everything
  a_crop_added_to_the_reply    the bridge's photo and group replies carry a face crop
  import_done_in_one_request   one `collect` call reads the whole pick
"""

from __future__ import annotations

import base64
import json
import logging
import struct
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
from google_fakes import GOOGLE_NOW, GOOGLE_UID, FakeGoogle, google_tokens
from home_fakes import ROOT as KEY_ROOT
from home_fakes import UID
from photos_fakes import JPEG, FakeEdge, rig
from pydantic import SecretStr
from r11_1_fakes_c import (
    CROP_NEEDLE,
    Cloud,
    build_cloud,
    consent,
    holds,
    jpeg_bytes,
    leaks,
    picture,
)

from jarvis.facegroups.privacy import FaceGroupsPrivacy
from jarvis.facegroups.tools import face_group_tools
from jarvis.faces import consent as consent_rules
from jarvis.faces.directory import Directory
from jarvis.faces.service import PersonRejected
from jarvis.faces.store import FacesStore
from jarvis.homebridge.face_groups import FaceGroupsPlugin
from jarvis.integrations.google import (
    PHOTOS_OFF_MSG,
    GoogleConnector,
    GoogleServiceDisabled,
    service_off_message,
)
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.keyring import Keyring
from jarvis.photos.models import PHOTOS_SCOPE, ImportLimits
from jarvis.photos.picker import PickerClient
from jarvis.photos.service import PhotosService, PhotosState
from jarvis.privacy.ports import PrivacyRegistry
from jarvis.privacy.service import PrivacyService
from jarvis.tools.context import tool_context
from jarvis.tools.provenance import unwrap

PART = "photos"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
REPO = Path(__file__).resolve().parents[2]
API = "https://photospicker.googleapis.com/v1"
GPS = b"GPS-LAT-12.97-LON-77.59"
OWN_NEEDLE = b"OWN-FILE-NEEDLE-5d20c7"
ENROL = ("POST", "/bridge/v1/faces/enrol")
STATE = ("POST", "/bridge/v1/state")
PHOTOS = ("POST", "/bridge/v1/faces/photos")
GROUPS = ("GET", "/bridge/v1/faces/groups")
DAY = 86400


def want(out: list[str], ok: object, problem: str) -> None:
    if not ok:
        out.append(problem)


@asynccontextmanager
async def cloud(**env: str) -> AsyncIterator[Cloud]:
    with tempfile.TemporaryDirectory() as tmp:
        c = await build_cloud(Path(tmp), env=env or None)
        try:
            yield c
        finally:
            await c.home.aclose()


def replies(c: Cloud, call: tuple[str, str]) -> list[Any]:
    """What the laptop answered on one route, as it crossed the signed channel."""
    pairs = zip(c.home.down.calls, c.home.down.got, strict=True)
    return [json.loads(body) for seen, body in pairs if seen == call]


# ---- O5 -----------------------------------------------------------------------------------------


async def o5_the_deploy_script_switches_photos_on() -> list[str]:
    out: list[str] = []
    script = (REPO / "deploy" / "cloudrun.sh").read_text(encoding="utf-8")
    line = "gcloud services enable photospicker.googleapis.com --quiet"
    want(out, line in script, "deploy/cloudrun.sh does not enable photospicker.googleapis.com")
    after = script.split(line, 1)[-1][:160]
    want(out, after.lstrip(" \\\n").startswith("|| say"), "a failure there does not warn and go on")
    off = {"error": {"message": "vendor words", "details": [{"reason": "SERVICE_DISABLED"}]}}
    store = MemoryTokenStore()
    await store.put(GOOGLE_UID, google_tokens(scopes=[PHOTOS_SCOPE]))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=off)))
    picker = PickerClient(
        GoogleConnector(store, client_id="c", client_secret=SecretStr("s"), http=http)
    )
    try:
        await picker.create_session(GOOGLE_UID)
        out.append("a switched-off Picker API was not reported")
    except GoogleServiceDisabled as exc:
        want(out, str(exc) == PHOTOS_OFF_MSG, f"the Photos path says: {exc}")
    want(out, "Google Photos Picker" in PHOTOS_OFF_MSG, "the message does not name the service")
    want(out, "re-run deploy/cloudrun.sh" in PHOTOS_OFF_MSG, "the message does not name the fix")
    other = service_off_message("https://tasks.googleapis.com/tasks/v1/users/@me/lists")
    want(out, other != PHOTOS_OFF_MSG, "another Google service is blamed on Photos")
    return out


# ---- O6 -----------------------------------------------------------------------------------------


async def o6_two_thousand_photos_in_steps_of_ten() -> list[str]:
    out: list[str] = []
    r = rig(items=2000)
    await r.svc.begin(UID)
    want(out, r.picker.max_items == [2000], f"the pick allows {r.picker.max_items}, not 2,000")
    steps, most, status = 0, 0, "reading"
    while status == "reading" and steps < 500:
        before = len(r.edge.received)
        status = (await r.svc.collect(UID)).status
        steps += 1
        most = max(most, len(r.edge.received) - before)
    done = await r.svc.progress(UID)
    want(out, most == 10, f"one request read {most} photos (the step is 10)")
    want(out, steps == 200, f"2,000 photos took {steps} requests, not 200")
    want(out, (done.status, done.photos, done.total) == ("done", 2000, 2000), f"ended {done}")
    sent = [image.removeprefix(JPEG).decode() for image in r.edge.received]
    want(out, sent == [f"m{i}" for i in range(2000)], "not every photo exactly once, in order")
    want(out, "2,000 of 2,000 read" in done.line, f"the line says: {done.line}")
    small = rig(items=37)
    small.svc.limits = ImportLimits(max_picked=2000, batch=4)  # `photos_import_batch`
    await small.svc.begin(UID)
    await small.svc.collect(UID)
    want(out, len(small.edge.received) == 4, "the batch setting is not the step")
    return out


async def o6_resumes_after_a_restart() -> list[str]:
    out: list[str] = []
    r = rig(items=35)
    await r.svc.begin(UID)
    for _ in range(2):
        await r.svc.collect(UID)
    again = PhotosService(r.picker, r.edge, r.f.svc, r.contacts, PhotosState(r.f.docs))  # type: ignore[arg-type]
    statuses = [(await again.collect(UID)).status for _ in range(2)]
    want(out, statuses == ["reading", "done"], f"after the restart: {statuses}")
    sent = [image.removeprefix(JPEG).decode() for image in r.edge.received]
    want(out, sent == [f"m{i}" for i in range(35)], "a photo was sent twice or lost in the restart")
    return out


async def o6_resumes_after_laptop_off() -> list[str]:
    out: list[str] = []
    r = rig(items=25)
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    r.edge.online = False
    before = list(r.picker.events)
    res = await r.svc.collect(UID)
    want(out, res.status == "laptop_offline" and res.photos == 10, f"asleep: {res.status}")
    want(out, r.picker.events == before, "a photo was downloaded for a laptop that is asleep")
    want(out, res.line == "10 of 25 read · 0 faces found · paused: laptop not reachable", res.line)
    r.edge.online = True
    statuses = [(await r.svc.collect(UID)).status for _ in range(2)]
    want(out, statuses == ["reading", "done"], f"when it is back: {statuses}")
    want(out, len(r.edge.received) == 25 == len(set(r.edge.received)), "not each photo once")
    return out


def _with_exif(n: int) -> bytes:
    """A small valid JPEG with an EXIF segment that holds a GPS position, and its own number."""
    exif = b"Exif\x00\x00" + GPS
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    return jpeg_bytes(8, 8, app=app1, tail=f"<photo:{n}>".encode())


async def o6_metadata_is_stripped_from_every_photo() -> list[str]:
    """The real Picker client over a scripted Google: what reaches the laptop has no EXIF."""
    out: list[str] = []
    fake, store = FakeGoogle(), MemoryTokenStore()
    await store.put(GOOGLE_UID, google_tokens(scopes=[PHOTOS_SCOPE]))
    conn = GoogleConnector(
        store,
        client_id="c",
        client_secret=SecretStr("s"),
        http=fake.client(),
        now=lambda: GOOGLE_NOW,
    )
    items = [
        {
            "id": f"m{i}",
            "type": "PHOTO",
            "mediaFile": {
                "baseUrl": f"https://lh3.googleusercontent.com/pw/{i}",
                "mimeType": "image/jpeg",
                "filename": f"IMG_{i}.jpg",
            },
        }
        for i in range(23)
    ]
    session = {"id": "sess-eval_1", "pickerUri": "https://photos.google.com/picker/x"}
    session |= {"expireTime": "2999-01-01T00:00:00Z", "mediaItemsSet": True}
    fake.on("POST", f"{API}/sessions", httpx.Response(200, json=session))
    fake.on("GET", f"{API}/sessions/sess-eval_1", httpx.Response(200, json=session))
    fake.on("DELETE", f"{API}/sessions/sess-eval_1", httpx.Response(200, json={}))
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": items}))
    for i in range(23):
        url = f"https://lh3.googleusercontent.com/pw/{i}=w1024-h1024"
        picture_ = httpx.Response(
            200, content=_with_exif(i), headers={"content-type": "image/jpeg"}
        )
        fake.on("GET", url, picture_)
    r = rig()
    edge = FakeEdge()
    svc = PhotosService(PickerClient(conn), edge, r.f.svc, r.contacts, PhotosState(r.f.docs))  # type: ignore[arg-type]
    await svc.begin(GOOGLE_UID)
    statuses = [(await svc.collect(GOOGLE_UID)).status for _ in range(3)]
    want(out, statuses == ["reading", "reading", "done"], f"23 photos: {statuses}")
    want(out, len(edge.received) == 23, f"{len(edge.received)} of 23 photos reached the laptop")
    dirty = [i for i, image in enumerate(edge.received) if b"Exif" in image or GPS in image]
    want(out, not dirty, f"metadata reached the laptop in photos {dirty[:5]}")
    whole = all(i.startswith(b"\xff\xd8") and b"<photo:" in i for i in edge.received)
    want(out, whole, "a photo did not arrive as the same picture without its metadata")
    return out


async def o6_stops_cleanly_when_the_session_expires() -> list[str]:
    out: list[str] = []
    r = rig(items=30)
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    r.picker.gone = True  # Google ended the Picker session
    try:
        res = await r.svc.collect(UID)
    except Exception as exc:  # noqa: BLE001 - the case is "no error reaches the caller"
        return [f"an expired session raised {type(exc).__name__}"]
    want(out, (res.status, res.photos, res.total) == ("expired", 10, 30), f"expired: {res}")
    want(out, "pick again to continue" in res.line and "10 of 30 read" in res.line, res.line)
    want(out, (await r.svc.progress(UID)).status == "expired", "the panel forgets why it stopped")
    want(out, (await r.svc.collect(UID)).status == "no_session", "the next ask is not a new pick")
    want(out, len(r.edge.received) == 10, "photos were sent after the session ended")
    return out


# ---- O7 -----------------------------------------------------------------------------------------


async def o7_the_three_routes_answer_ids_only() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        gid = await c.group_of(1)
        await c.photos.edge.analyse(UID, [picture(1, 2, n=9, needle=True)])
        await c.groups.name(UID, gid, **consent())
        photos, groups, enrol = replies(c, PHOTOS), replies(c, GROUPS), replies(c, ENROL)
        want(out, photos and groups and enrol, "a route was never called")
        for reply in photos:
            want(out, set(reply) == {"faces"}, f"photos answers {sorted(reply)}")
            for face in reply.get("faces", []):
                want(out, set(face) == {"cluster", "person", "score"}, f"a face has {sorted(face)}")
        fields = {"groups", "more", "strays", "named", "engine", "folder", "read", "keep_days"}
        for reply in groups:
            want(out, set(reply) == fields, f"groups answers {sorted(reply)}")
            for g in reply.get("groups", []):
                want(out, set(g) == {"id", "n", "photos", "first", "last"}, f"a group: {sorted(g)}")
        for reply in enrol:
            want(out, set(reply) == {"pictures", "camera"}, f"enrol answers {sorted(reply)}")
        text = json.dumps([photos, groups, enrol])
        want(out, leaks(text) == [], f"a reply holds {leaks(text)}")
    return out


async def o7_three_pictures_make_a_group() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        for n in range(2):
            await c.at_home(1, n=n)
        view = await c.groups.view(UID)
        want(out, view.groups == () and view.strays == 1, "a face in 2 pictures is already a group")
        await c.at_home(1, n=1)  # the same picture again: counted once
        want(out, (await c.groups.view(UID)).groups == (), "the same picture was counted twice")
        await c.at_home(1, n=2)
        view = await c.groups.view(UID)
        got = [(g.photos, g.n) for g in view.groups]
        want(out, got == [(3, 1)] and view.strays == 0, f"after 3 pictures: {got}")
        await c.at_home(2, n=0)
        view = await c.groups.view(UID)
        want(out, len(view.groups) == 1 and view.strays == 1, "another person joined the group")
    return out


async def o7_naming_runs_the_consent_check_once_per_person() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        first = await c.group_of(1)
        second = await c.group_of(40, start=10)  # the same person from another angle
        asked: list[dict[str, Any]] = []
        real = consent_rules.check

        def counting(**kw: Any) -> None:
            asked.append(kw)
            real(**kw)

        consent_rules.check = counting
        try:
            named = await c.groups.name(UID, first, **consent())
            again = await c.groups.name_existing(UID, second, named.person.id)
        finally:
            consent_rules.check = real
        want(out, len(asked) == 1, f"the consent check ran {len(asked)} times for one person")
        people = (await c.home.faces.state(UID)).people
        want(out, len(people) == 1 and again.person.id == named.person.id, "two people were made")
        want(out, people[0].state == "enrolled", "the laptop's answer did not finish the naming")
        try:
            await c.groups.name_existing(UID, second, "fp_ffffffffffff")
            out.append("a made-up person id was accepted as someone with consent")
        except PersonRejected:
            pass
    return out


async def o7_a_child_needs_a_guardians_yes() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        gid = await c.group_of(1)
        try:
            await c.groups.name(UID, gid, **consent(name="Mini", child=True, given_by="self"))
            out.append("a child was named without a parent's or guardian's yes")
        except PersonRejected as exc:
            want(out, exc.code == "child_needs_guardian", f"refused as {exc.code}")
        want(out, (await c.home.faces.state(UID)).people == (), "a child was registered anyway")
        want(out, ENROL not in c.home.down.calls, "the bridge was told about the child")
        yes = consent(name="Mini", child=True, given_by="parent_guardian")
        done = await c.groups.name(UID, gid, **yes)
        want(out, done.at_home and done.person.child, "a guardian's yes did not name the child")
    return out


async def o7_without_a_yes_nothing_is_enrolled() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        gid = await c.group_of(1)
        before = len(c.home.down.calls)
        for bad in (consent(confirm=False), consent(confirm="yes"), consent(consent_version="x")):
            try:
                await c.groups.name(UID, gid, **bad)
                out.append(f"named without a yes: confirm={bad['confirm']!r}")
            except PersonRejected as exc:
                want(out, exc.code == "consent_missing", f"refused as {exc.code}")
        told = c.home.down.calls[before:]
        want(out, (await c.home.faces.state(UID)).people == (), "a person was registered")
        want(out, ENROL not in told and STATE not in told, "the bridge was told without a yes")
        want(out, c.home.lib.pictures == {}, "a crop reached the camera's library")
        placed = (await c.home.groups.look(picture(1, n=9)))[1]
        want(out, placed[0].person is None, "the laptop names the face without consent")
        want(out, c.home.audit.entries == [], "an enrolment was audited that never happened")
        # the laptop's own door: a name for someone whose consent it never heard of is refused
        try:
            await c.photos.edge.enrol(UID, gid, "fp_ffffffffffff")
            out.append("the bridge enrolled an id with no consent on record")
        except Exception as exc:  # noqa: BLE001 - EdgeRefused(no_consent)
            want(out, getattr(exc, "code", "") == "no_consent", f"the bridge said {exc!r}")
    return out


async def o7_afterwards_recognised_with_no_further_step() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        gid = await c.group_of(1)
        done = await c.groups.name(UID, gid, **consent())
        res = await c.import_all([picture(1, n=7), picture(2, n=7)])  # a NEW photo of them
        names = [p.name for p in res.recognised]
        want(out, res.status == "done" and names == ["Anjali"], f"a new photo: {names}")
        want(out, res.unknown == 1, "the stranger beside them was counted as known")
        crops = c.home.lib.pictures.get(done.person.id, [])
        want(out, len(crops) == 3, f"the camera's library holds {len(crops)} of their pictures")
        match = c.home.faces_plugin.library.match(done.person.id, 0.95, "person")
        want(out, match is not None, "a camera sighting of them is dropped by the consent filter")
        if match is not None:
            directory = Directory(FacesStore(c.home.docs, Keyring(KEY_ROOT)))
            who = await directory.resolve(UID, match.person, match.score)
            want(out, who is not None and who.name == "Anjali", "the camera does not name them")
        want(out, (await c.groups.view(UID)).groups == (), "the named group is still to name")
    return out


async def o7_unnamed_groups_expire_and_forget_waits_for_the_laptop() -> list[str]:
    out: list[str] = []
    async with cloud(FACE_GROUPS_KEEP_DAYS="30") as c:
        kept = await c.group_of(1)
        await c.groups.name(UID, kept, **consent())
        await c.group_of(2, start=10)
        await c.at_home(3)
        c.home.clock.t += 31 * DAY
        gone = await c.home.groups.expire()
        home = c.home.groups.groups_view()
        want(out, gone >= 2, f"after 31 days of a 30-day rule {gone} were forgotten")
        want(out, (home["groups"], home["strays"], home["named"]) == ([], 0, 1), f"left: {home}")
        fresh = await c.group_of(4, start=20)
        await c.at_home(5)
        row = FaceGroupsPrivacy(lambda: c.groups)
        registry = PrivacyRegistry()
        registry.register(row)
        seen = await row.describe(UID)
        want(out, (seen.count, seen.delete) == (2, "confirm"), f"the Privacy row: {seen.count}")
        c.home.online = False
        waiting = await c.groups.forget(UID, fresh)
        want(out, waiting.done is False, "a forget was reported done while the laptop was asleep")
        want(out, c.home.groups.groups_view()["groups"], "the laptop forgot without being asked")
        seen = await row.describe(UID)
        done = await PrivacyService(registry).delete(
            UID, "face_groups", rev=seen.rev, confirm=None, proof=None, fresh_left_s=None
        )
        asleep = (done.deleted, done.remaining)
        want(out, asleep == (0, 2), f"Privacy reported {asleep} while the laptop was asleep")
        want(out, "NOT done" in (await row.describe(UID)).note, "the row does not say it waits")
        c.home.online = True
        polled = await c.groups.poll(UID)
        want(out, polled["forgotten"] >= 1, f"the poll did not finish the forget: {polled}")
        home = c.home.groups.groups_view()
        want(out, (home["groups"], home["strays"]) == ([], 0), "the laptop still has them")
        want(out, (await row.describe(UID)).count == 0, "Privacy still counts forgotten groups")
    return out


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.getMessage()} {record.__dict__!r}")


@contextmanager
def all_logs() -> Iterator[_Logs]:
    """Every line the product logs (all its loggers are `jarvis.*`), at DEBUG, kept not printed."""
    log, handler = logging.getLogger("jarvis"), _Logs()
    was = (log.level, log.handlers, log.propagate)
    log.handlers, log.propagate = [handler], False
    log.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        log.setLevel(was[0])
        log.handlers, log.propagate = was[1], was[2]


async def _journey(c: Cloud) -> str:
    """Folder pictures, a 12-photo import, an alert, a name, a forget, a sleeping laptop, the
    poll and a heartbeat; returns what the two tools showed the model."""
    for person, count in ((1, 4), (2, 3), (3, 1)):
        for i in range(count):
            own = jpeg_bytes(64, 64, tail=f"<people:{person};n:{100 * person + i}>".encode())
            await c.home.groups.look(own + OWN_NEEDLE, own_file=True)
    await c.import_all([picture(1, 4, n=i, needle=True) for i in range(12)])
    await c.groups.poll(UID)
    shown = []
    with tool_context(f"{UID}:eval_photos"):
        for tool in face_group_tools(c.groups, lambda: c.photos):
            shown.append(json.dumps(unwrap(await tool.run({}))[0]))
    by_photos = {g.photos: g.id for g in (await c.groups.view(UID)).groups}
    await c.groups.name(UID, by_photos[16], **consent())
    await c.groups.forget(UID, by_photos[3])
    c.home.online = False
    await c.groups.forget_all(UID)
    c.home.online = True
    await c.groups.poll(UID)
    await c.home.beat()
    return "\n".join(shown)


async def needles_nothing_but_ids_reaches_the_cloud() -> list[str]:
    out: list[str] = []
    async with cloud() as c:
        with all_logs() as logs:
            try:
                model = await _journey(c)
            except Exception as exc:  # noqa: BLE001 - what crossed so far is searched all the same
                model = ""
                out.append(f"the journey stopped: {type(exc).__name__}")
        docs = c.home.docs
        sent_home = list(zip(c.home.down.calls, c.home.down.sent, strict=True))
        want(
            out, len([1 for call, _ in sent_home if call == PHOTOS]) == 12, "the import did not run"
        )
        want(out, len((await c.home.faces.state(UID)).people) == 1, "nobody was named")
        places = {
            "what the laptop sent": c.home.received_by_the_cloud(),
            "a stored document": repr(docs.log) + repr(docs._data),  # noqa: SLF001
            "a log line": "\n".join(logs.lines),
            "the audit": repr(c.home.audit.entries),
            "an alert": repr(c.home.notes.sent),
            "a tool result": model,
        }
        for where, text in places.items():
            want(out, text, f"nothing was captured for: {where}")
            want(out, leaks(text) == [], f"{where} holds {leaks(text)}")
            want(out, not holds(text, OWN_NEEDLE), f"{where} holds a file the laptop read itself")
        for call, body in sent_home:
            want(out, not holds(body, OWN_NEEDLE), f"{call} carries one of the laptop's own files")
            want(out, not holds(body, CROP_NEEDLE), f"{call} carries a crop")
            if call != PHOTOS:  # a picked photo travels to the laptop's reader, nowhere else
                want(out, leaks(body) == [], f"{call} carries {leaks(body)}")
        # the control inside the case: the needles are real, and they live on the laptop
        kept = [p for p in c.home.bridge.cfg.data_dir.rglob("*") if p.is_file()]
        raw = b"".join(p.read_bytes() for p in kept)
        want(
            out, holds(raw, CROP_NEEDLE), "the scripted engine cut no crop: the scan proves nothing"
        )
        want(out, leaks(base64.b64encode(b"x" + CROP_NEEDLE)) == ["crop"], "the scan misses base64")
    return out


CASES: dict[str, Case] = {
    "o5_deploy_script_switches_photos_on": o5_the_deploy_script_switches_photos_on,
    "o6_2000_photos_in_steps_of_10": o6_two_thousand_photos_in_steps_of_ten,
    "o6_resumes_after_a_restart": o6_resumes_after_a_restart,
    "o6_resumes_after_laptop_off": o6_resumes_after_laptop_off,
    "o6_metadata_stripped_from_every_photo": o6_metadata_is_stripped_from_every_photo,
    "o6_stops_cleanly_when_the_session_expires": o6_stops_cleanly_when_the_session_expires,
    "o7_the_three_routes_answer_ids_only": o7_the_three_routes_answer_ids_only,
    "o7_three_pictures_make_a_group": o7_three_pictures_make_a_group,
    "o7_consent_check_once_per_person": o7_naming_runs_the_consent_check_once_per_person,
    "o7_a_child_needs_a_guardians_yes": o7_a_child_needs_a_guardians_yes,
    "o7_without_a_yes_nothing_is_enrolled": o7_without_a_yes_nothing_is_enrolled,
    "o7_recognised_afterwards_with_no_further_step": o7_afterwards_recognised_with_no_further_step,
    "o7_groups_expire_and_forget_waits_for_the_laptop": (
        o7_unnamed_groups_expire_and_forget_waits_for_the_laptop
    ),
    "needles_nothing_but_ids_reaches_the_cloud": needles_nothing_but_ids_reaches_the_cloud,
}


async def _run() -> list[dict[str, Any]]:
    results = []
    quiet = logging.getLogger("jarvis")
    level = quiet.level
    quiet.setLevel(logging.CRITICAL)  # the pauses and refusals these cases provoke are expected
    try:
        for name, case in CASES.items():
            try:
                failures = await case()
            except Exception as exc:  # noqa: BLE001 - a crash is a failed case, with its reason
                failures = [f"{type(exc).__name__}: {exc}"[:300]]
            results.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    finally:
        quiet.setLevel(level)
    return results


async def cases() -> list[dict[str, Any]]:
    results = await _run()
    print(f"{PART}: {sum(1 for r in results if r['passed'])}/{len(results)} cases passed")
    return results


# ---- the negative controls ----------------------------------------------------------------------


@contextmanager
def consent_check_skipped() -> Iterator[None]:
    real = consent_rules.check
    consent_rules.check = lambda **_: None
    try:
        yield
    finally:
        consent_rules.check = real


@contextmanager
def a_crop_added_to_the_reply() -> Iterator[None]:
    crop = base64.b64encode(b"\xff\xd8\xff" + CROP_NEEDLE).decode()
    wire, view = FaceGroupsPlugin._wire, FaceGroupsPlugin.groups_view  # noqa: SLF001
    FaceGroupsPlugin._wire = lambda self, placed: {**wire(self, placed), "crop": crop}  # type: ignore[method-assign]  # noqa: SLF001
    FaceGroupsPlugin.groups_view = lambda self: {**view(self), "crop": crop}  # type: ignore[method-assign]
    try:
        yield
    finally:
        FaceGroupsPlugin._wire, FaceGroupsPlugin.groups_view = wire, view  # type: ignore[method-assign]  # noqa: SLF001


@contextmanager
def import_done_in_one_request() -> Iterator[None]:
    real = PhotosService.collect

    async def whole(self: PhotosService, uid: str, *, budget_s: float | None = None) -> Any:
        res = await real(self, uid, budget_s=budget_s)
        while res.status == "reading":
            res = await real(self, uid, budget_s=budget_s)
        return res

    PhotosService.collect = whole  # type: ignore[method-assign]
    try:
        yield
    finally:
        PhotosService.collect = real  # type: ignore[method-assign]


CONTROLS = {
    "consent_check_skipped": consent_check_skipped,
    "a_crop_added_to_the_reply": a_crop_added_to_the_reply,
    "import_done_in_one_request": import_done_in_one_request,
}


async def control() -> dict[str, Any]:
    """Each control alone must make this part fail; `failed_cases` says which cases caught it."""
    failed: dict[str, list[str]] = {}
    for name, switch in CONTROLS.items():
        with switch():
            got = await _run()
        failed[name] = [r["id"] for r in got if not r["passed"]]
    return {
        "name": " / ".join(CONTROLS),
        "suite_failed": all(failed.values()),
        "failed_cases": failed,
    }
