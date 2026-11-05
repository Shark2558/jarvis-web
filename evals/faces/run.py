# evals/faces/run.py
"""R3 D13 eval -- Faces and consent: nobody is named without consent, enrolment needs a recorded
consent, deletes reach the laptop, children are never named off the console.

    python evals/faces/run.py --mock

38 cases over the real registry (in-memory Docs, real keyring), the directory, the service, the tool
through the gateway, the privacy source, the bridge's face library and retention (fake Frigate,
temp folders). No model call, no network.
Groups: unknown never named (11), consent (7), delete (9), channels (6), retention (5).
Negative controls (each must make the suite FAIL): resolve without the registry check; the bridge's
consent check off; the children's rule off.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from r1d_common import finish  # noqa: E402

import jarvis.faces.models as models_mod  # noqa: E402
import jarvis.faces.tools as tools_mod  # noqa: E402
from jarvis.core.channel import telegram_turn  # noqa: E402
from jarvis.core.guardrails import ConfirmationGate  # noqa: E402
from jarvis.faces.consent import ConsentRejected, check, renewal_due  # noqa: E402
from jarvis.faces.directory import Directory, alert_words  # noqa: E402
from jarvis.faces.ports import (  # noqa: E402
    FAMILY_CHILD,
    RECOGNISED_PERSON,
    UNKNOWN,
    UNKNOWN_PERSON,
)
from jarvis.faces.privacy import FacesPrivacy  # noqa: E402
from jarvis.faces.service import FacesService, PersonRejected  # noqa: E402
from jarvis.faces.store import FacesStore, FacesUnavailable  # noqa: E402
from jarvis.faces.tools import faces_tools  # noqa: E402
from jarvis.home.ports import Ack, FacesState, HomeOffline  # noqa: E402
from jarvis.homebridge.faces import FaceLibrary, FaceRefused  # noqa: E402
from jarvis.homebridge.retention import Retention  # noqa: E402
from jarvis.keyring import Keyring  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.logging import configure_logging  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.telegram.rules import HOME_PATTERNS  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.tools.gateway import Gateway  # noqa: E402
from jarvis.tools.policy import Policy  # noqa: E402
from jarvis.tools.registry import ToolRegistry  # noqa: E402

UID = "u_owner"
ROOT_KEY = bytes(range(1, 33))
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
GHOST = "fp_0123456789ab"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64
Case = Callable[[], Awaitable[list[str]]]
CASES: list[tuple[str, Case]] = []


def case(name: str) -> Callable[[Case], Case]:
    def deco(fn: Case) -> Case:
        CASES.append((name, fn))
        return fn

    return deco


def check_(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Home:
    def __init__(self, online: bool = True) -> None:
        self.online, self.calls = online, []  # type: ignore[var-annotated]

    async def call(
        self, uid: str, method: str, path: str, body: Any = None, *, query: Any = None
    ) -> dict[str, Any]:
        if not self.online:
            raise HomeOffline()
        self.calls.append(body)
        return {}


class Audit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append(self, **kw: Any) -> None:
        self.entries.append(kw)


class Rig:
    def __init__(self, online: bool = True) -> None:
        self.docs = MemoryDocs()
        self.store = FacesStore(self.docs, Keyring(ROOT_KEY))
        self.home, self.audit, self.clock = Home(online), Audit(), Clock()
        self.svc = FacesService(self.store, self.home, audit=self.audit, clock=self.clock)  # type: ignore[arg-type]
        self.directory = Directory(self.store)

    async def adult(self, name: str = "Anjali", *, enrolled: bool = True, vip: bool = False) -> Any:
        p = await self.svc.add(
            UID,
            name=name,
            relation="friend",
            child=False,
            vip=vip,
            given_by="self",
            consent_version="fc1",
            confirm=True,
        )
        if enrolled:
            await self.svc.apply_pictures(UID, {p.id: 5})
        return p

    async def child(self, name: str = "Mini", *, enrolled: bool = True) -> Any:
        p = await self.svc.add(
            UID,
            name=name,
            relation="family",
            child=True,
            vip=False,
            given_by="parent_guardian",
            consent_version="fc1",
            confirm=True,
        )
        if enrolled:
            await self.svc.apply_pictures(UID, {p.id: 4})
        return p

    def gateway(self) -> Gateway:
        reg = ToolRegistry()
        for t in faces_tools(self.svc):
            reg.register(t)
        return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=AuditLog())

    async def listed(self) -> str:
        res = await self.gateway().execute(
            ToolCall(id="c", name="faces_list", arguments={}), scope=f"{UID}:s"
        )
        return str(res.result)


def bridge(
    tmp: Path, *people: str, deleting: tuple[str, ...] = ()
) -> tuple[FaceLibrary, Any, list[Ack]]:
    class Lib:
        def __init__(self) -> None:
            self.pictures: dict[str, list[bytes]] = {}

        async def counts(self) -> dict[str, int]:
            return {k: len(v) for k, v in self.pictures.items()}

        async def register(self, name: str, image: bytes, content_type: str) -> None:
            self.pictures.setdefault(name, []).append(image)

        async def delete(self, name: str) -> None:
            self.pictures.pop(name, None)

        async def recent(self) -> list[str]:
            return []

        async def recent_image(self, file: str) -> bytes:
            return JPEG

        async def classify(self, name: str, file: str) -> None:
            return None

    acks: list[Ack] = []

    async def post(ack: Ack) -> bool:
        acks.append(ack)
        return True

    (tmp / "attempts").mkdir(exist_ok=True)
    lib = Lib()
    fl = FaceLibrary(lib, tmp, Retention(tmp / "attempts"), post_ack=post, now=lambda: 1000.0)
    fl.apply(FacesState(rev=1, people=people, deleting=deleting))
    return fl, lib, acks


# ---- unknown never named (11) --------------------------------------------------------------------


@case("no_sub_label_is_unknown")
async def _c1() -> list[str]:
    r = Rig()
    await r.adult()
    f: list[str] = []
    check_((await r.directory.resolve(UID, None, 0.99)) is UNKNOWN, "named with no sub-label", f)
    return f


@case("a_name_typed_in_frigate_is_unknown_in_cloud_and_bridge")
async def _c2() -> list[str]:
    r = Rig()
    await r.adult()
    f: list[str] = []
    check_(
        (await r.directory.resolve(UID, "Anjali", 0.99)) is UNKNOWN, "cloud named a typed name", f
    )
    with tempfile.TemporaryDirectory() as d:
        fl, _, _ = bridge(Path(d), "fp_3a9c12ab34cd")
        check_(fl.match("Anjali", 0.99) is None, "bridge forwarded a typed name", f)
    return f


@case("an_unregistered_fp_id_is_unknown")
async def _c3() -> list[str]:
    r = Rig()
    await r.adult()
    f: list[str] = []
    check_(
        (await r.directory.resolve(UID, GHOST, 0.99)) is UNKNOWN,
        "named an id not in the registry",
        f,
    )
    return f


@case("a_deleting_person_is_unknown")
async def _c4() -> list[str]:
    r = Rig(online=False)
    p = await r.adult()
    await r.svc.remove(UID, p.id)
    f: list[str] = []
    check_((await r.directory.resolve(UID, p.id, 0.99)) is UNKNOWN, "named a deleting person", f)
    return f


@case("consented_but_not_enrolled_is_unknown")
async def _c5() -> list[str]:
    r = Rig()
    p = await r.adult(enrolled=False)
    f: list[str] = []
    check_(
        (await r.directory.resolve(UID, p.id, 0.99)) is UNKNOWN,
        "named a person with no pictures",
        f,
    )
    return f


@case("score_0_89_is_unknown_and_0_9_is_named")
async def _c6() -> list[str]:
    r = Rig()
    p = await r.adult()
    f: list[str] = []
    check_((await r.directory.resolve(UID, p.id, 0.89)) is UNKNOWN, "named at 0.89", f)
    check_((await r.directory.resolve(UID, p.id, 0.9)).named, "not named at 0.9", f)
    return f


@case("a_malformed_id_is_unknown")
async def _c7() -> list[str]:
    r = Rig()
    await r.adult()
    f: list[str] = []
    for bad in ("fp_xyz", "FP_3A9C12AB34CD", "fp_3a9c12ab34cdee", "../x", ""):
        check_((await r.directory.resolve(UID, bad, 0.99)) is UNKNOWN, f"named {bad!r}", f)
    return f


@case("a_face_result_on_a_car_never_reaches_the_cloud")
async def _c8() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        fl, _, _ = bridge(Path(d), "fp_3a9c12ab34cd")
        check_(fl.match("fp_3a9c12ab34cd", 0.99, "car") is None, "matched a car", f)
        check_(fl.match("fp_3a9c12ab34cd", 0.99, "person") is not None, "missed a person", f)
    return f


@case("a_deleted_person_in_yesterdays_feed_reads_as_someone")
async def _c9() -> list[str]:
    r = Rig()
    p = await r.adult()
    f: list[str] = []

    async def feed_words() -> str:
        who = await r.directory.resolve(
            UID, p.id, 1.0
        )  # names are resolved when the feed is viewed
        return who.name or UNKNOWN_PERSON

    check_(await feed_words() == "Anjali", "not named while enrolled", f)
    await r.svc.remove(UID, p.id)
    await r.svc.ack(UID, p.id)
    check_(await feed_words() == UNKNOWN_PERSON, "a deleted person is still named in the feed", f)
    return f


@case("the_models_tool_output_has_no_name_for_deleting_or_deleted_people")
async def _c10() -> list[str]:
    r = Rig(online=False)
    a = await r.adult("Anjali")
    await r.adult("Ravi")
    f: list[str] = []
    await r.svc.remove(UID, a.id)
    out = await r.listed()
    check_("Anjali" not in out, "faces_list names a deleting person", f)
    check_("Ravi" in out, "faces_list lost a live person", f)
    return f


@case("an_unreadable_registry_names_nobody")
async def _c11() -> list[str]:
    r = Rig()
    p = await r.adult()
    r.docs._data["jarvis_faces/" + UID]["blob"] = "x"  # type: ignore[attr-defined]
    f: list[str] = []
    check_(
        (await r.directory.resolve(UID, p.id, 0.99)) is UNKNOWN,
        "named from an unreadable registry",
        f,
    )
    return f


# ---- consent (7) ---------------------------------------------------------------------------------


@case("no_statement_is_422_consent_missing")
async def _c12() -> list[str]:
    r = Rig()
    f: list[str] = []
    try:
        await r.svc.add(
            UID,
            name="A",
            relation="friend",
            child=False,
            vip=False,
            given_by="self",
            consent_version="fc1",
            confirm=False,
        )
        f.append("added without consent")
    except PersonRejected as exc:
        check_(exc.code == "consent_missing" and exc.status == 422, f"{exc.code}", f)
    check_((await r.store.load(UID)).people == (), "something was stored", f)
    return f


@case("a_child_without_a_guardian_is_422")
async def _c13() -> list[str]:
    r = Rig()
    f: list[str] = []
    try:
        await r.svc.add(
            UID,
            name="M",
            relation="family",
            child=True,
            vip=False,
            given_by="self",
            consent_version="fc1",
            confirm=True,
        )
        f.append("added a child on their own say-so")
    except PersonRejected as exc:
        check_(exc.code == "child_needs_guardian", exc.code, f)
    return f


@case("an_adult_cannot_be_added_on_a_guardians_say_so")
async def _c14() -> list[str]:
    f: list[str] = []
    try:
        check(child=False, given_by="parent_guardian", version="fc1", confirm=True)
        f.append("accepted")
    except ConsentRejected as exc:
        check_(exc.code == "consent_missing", exc.code, f)
    return f


@case("version_and_date_are_recorded")
async def _c15() -> list[str]:
    r = Rig()
    p = await r.adult()
    f: list[str] = []
    check_(
        p.consent_version == "fc1" and p.consent_at == NOW.isoformat(),
        f"{p.consent_version} {p.consent_at}",
        f,
    )
    return f


@case("the_bridge_refuses_enrolment_for_an_id_without_consent")
async def _c16() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        fl, lib, _ = bridge(Path(d), "fp_3a9c12ab34cd")
        try:
            await fl.enrol(GHOST, JPEG)
            f.append("enrolled an id without consent")
        except FaceRefused as exc:
            check_(exc.code == "no_consent", exc.code, f)
        check_(lib.pictures == {}, "a picture was stored", f)
    return f


@case("yearly_check_shows_after_365_days")
async def _c17() -> list[str]:
    r = Rig()
    p = await r.adult()
    f: list[str] = []
    check_(not renewal_due(p, NOW + timedelta(days=365)), "due on day 365", f)
    check_(renewal_due(p, NOW + timedelta(days=366)), "not due on day 366", f)
    return f


@case("nobody_is_enrolled_by_default")
async def _c18() -> list[str]:
    r = Rig()
    f: list[str] = []
    check_((await r.svc.view(UID)).people == (), "the registry did not start empty", f)
    part = await r.svc.state_part(UID)
    check_(part.faces is not None and part.faces.people == (), "the bridge was told of someone", f)
    return f


# ---- delete (9) ----------------------------------------------------------------------------------


@case("mapping_is_gone_at_once")
async def _c19() -> list[str]:
    r = Rig()
    p = await r.adult()
    await r.svc.remove(UID, p.id)
    f: list[str] = []
    check_((await r.directory.resolve(UID, p.id, 1.0)) is UNKNOWN, "still named after delete", f)
    return f


@case("the_bridge_is_told_ids_only")
async def _c20() -> list[str]:
    r = Rig()
    p = await r.adult()
    await r.svc.remove(UID, p.id)
    f: list[str] = []
    check_(r.home.calls[-1]["faces"]["deleting"] == [p.id], f"{r.home.calls[-1]}", f)
    check_("Anjali" not in str(r.home.calls), "a name went to the laptop", f)
    return f


@case("the_ack_removes_the_record_and_audits_a_count_only")
async def _c21() -> list[str]:
    r = Rig()
    p = await r.adult()
    await r.svc.remove(UID, p.id)
    await r.svc.handle(UID, Ack(type="ack", id="e1", at=1.0, what="face_deleted", person=p.id))
    f: list[str] = []
    check_((await r.store.load(UID)).people == (), "record still there", f)
    check_(
        r.audit.entries[-1]["args"] == {"count": 1} and "Anjali" not in str(r.audit.entries),
        "audit not count-only",
        f,
    )
    return f


@case("laptop_off_means_deleting_when_its_back")
async def _c22() -> list[str]:
    r = Rig(online=False)
    p = await r.adult()
    res = await r.svc.remove(UID, p.id)
    f: list[str] = []
    check_(res.pushed is False, "claimed the laptop was told", f)
    part = await r.svc.state_part(UID)
    check_(
        part.faces is not None and part.faces.deleting == (p.id,),
        "the next heartbeat would not carry it",
        f,
    )
    check_(
        (await r.store.load(UID)).people[0].state == "deleting", "record dropped before the ack", f
    )
    return f


@case("privacy_count_is_zero_after_delete_all")
async def _c23() -> list[str]:
    r = Rig(online=False)
    await r.adult("A")
    await r.child("B")
    priv = FacesPrivacy(r.svc)
    await priv.delete(UID)
    view = await priv.describe(UID)
    f: list[str] = []
    check_(view.count == 0 and view.delete == "none", f"{view.count} {view.delete}", f)
    return f


@case("privacy_rev_changes_with_the_data_so_a_stale_passkey_is_refused")
async def _c24() -> list[str]:
    r = Rig()
    priv = FacesPrivacy(r.svc)
    before = await priv.describe(UID)
    await r.adult()
    after = await priv.describe(UID)
    f: list[str] = []
    check_(before.rev != after.rev and after.delete == "passkey", "rev/passkey class wrong", f)
    return f


@case("a_stray_ack_never_deletes_a_live_person")
async def _c25() -> list[str]:
    r = Rig()
    p = await r.adult()
    await r.svc.handle(UID, Ack(type="ack", id="e1", at=1.0, what="face_deleted", person=p.id))
    f: list[str] = []
    check_(len((await r.store.load(UID)).people) == 1, "a live person was deleted by an ack", f)
    return f


@case("the_bridge_deletes_library_and_attempts_then_acks")
async def _c26() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        pid = "fp_3a9c12ab34cd"
        fl, lib, acks = bridge(Path(d), pid)
        await fl.enrol(pid, JPEG)
        crop = Path(d) / "attempts" / f"1-{pid}-0.9.webp"
        crop.write_bytes(b"x")
        fl.apply(FacesState(rev=2, deleting=(pid,)))
        await fl.finish_deletes()
        check_(lib.pictures == {} and not crop.exists(), "pictures or crops left at home", f)
        check_([a.person for a in acks] == [pid], "no ack", f)
        try:
            await fl.enrol(pid, JPEG)
            f.append("re-enrolled a deleted person")
        except FaceRefused:
            pass
    return f


@case("other_owners_are_untouched_by_a_delete")
async def _c27() -> list[str]:
    r = Rig()
    await r.adult()
    other = await r.svc.add(
        "u_other",
        name="Z",
        relation="other",
        child=False,
        vip=False,
        given_by="self",
        consent_version="fc1",
        confirm=True,
    )
    await FacesPrivacy(r.svc).delete(UID)
    f: list[str] = []
    check_(
        (await r.store.load("u_other")).people[0].id == other.id,
        "another owner's person changed",
        f,
    )
    return f


# ---- channels (6) --------------------------------------------------------------------------------


@case("a_childs_name_is_never_in_an_alert_whatever_the_switch")
async def _c28() -> list[str]:
    r = Rig()
    k = await r.child("Mini")
    who = await r.directory.resolve(UID, k.id, 0.99)
    f: list[str] = []
    for on in (True, False):
        text = alert_words(who, say_names=on)
        check_(text == FAMILY_CHILD and "Mini" not in text, f"{on}: {text}", f)
    return f


@case("names_in_alerts_off_says_a_person_recognised")
async def _c29() -> list[str]:
    r = Rig()
    p = await r.adult()
    who = await r.directory.resolve(UID, p.id, 0.99)
    f: list[str] = []
    check_(alert_words(who, say_names=False) == RECOGNISED_PERSON, "named with the switch off", f)
    check_(alert_words(who, say_names=True) == "Anjali", "did not name with the switch on", f)
    return f


@case("faces_list_is_in_the_telegram_home_group")
async def _c30() -> list[str]:
    import fnmatch

    f: list[str] = []
    check_(
        any(fnmatch.fnmatch("faces_list", p) for p in HOME_PATTERNS),
        "faces_list is not refused on Telegram by default",
        f,
    )
    return f


@case("on_telegram_a_child_is_never_named_by_the_tool_and_digits_are_masked")
async def _c31() -> list[str]:
    r = Rig()
    await r.child("Mini")
    await r.adult("Ravi 9876543210")
    with telegram_turn():
        out = await r.listed()
    f: list[str] = []
    check_("Mini" not in out and FAMILY_CHILD in out, "a child was named on Telegram", f)
    check_("9876543210" not in out, "digits were not masked", f)
    return f


@case("faces_list_says_nothing_about_who_was_seen")
async def _c32() -> list[str]:
    r = Rig()
    await r.adult()
    out = (await r.listed()).lower()
    f: list[str] = []
    for word in ("seen", "arrived", "last_seen", "embedding", "thumbnail"):
        check_(word not in out, f"faces_list says {word}", f)
    return f


@case("the_registry_holds_no_name_in_clear_in_firestore")
async def _c33() -> list[str]:
    r = Rig()
    await r.adult("Anjali Verma")
    await r.child("Mini")
    dump = str(r.docs._data).lower()  # type: ignore[attr-defined]
    f: list[str] = []
    for needle in ("anjali", "verma", "mini", "friend", "parent_guardian"):
        check_(needle not in dump, f"{needle} in Firestore in clear", f)
    return f


# ---- retention (5) -------------------------------------------------------------------------------


def _aged(path: Path, hours: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    t = 1_800_000_000.0 - hours * 3600
    os.utime(path, (t, t))
    return path


@case("unknown_attempts_older_than_72h_are_deleted")
async def _c34() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        old, new = _aged(Path(d) / "a" / "1.webp", 73), _aged(Path(d) / "a" / "2.webp", 71)
        Retention(Path(d) / "a", now=lambda: 1_800_000_000.0).sweep()
        check_(not old.exists() and new.exists(), "72 h rule wrong", f)
    return f


@case("doorstep_attempts_older_than_7_days_are_deleted")
async def _c35() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        old, new = (
            _aged(Path(d) / "d" / "1.jpg", 24 * 7 + 1),
            _aged(Path(d) / "d" / "2.jpg", 24 * 7 - 1),
        )
        Retention(None, Path(d) / "d", now=lambda: 1_800_000_000.0).sweep()
        check_(not old.exists() and new.exists(), "7 day rule wrong", f)
    return f


@case("retention_never_leaves_its_folder_or_follows_links")
async def _c36() -> list[str]:
    f: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        outside = _aged(Path(d) / "outside" / "x.webp", 500)
        root = Path(d) / "a"
        root.mkdir()
        (root / "l.webp").symlink_to(outside)
        (root / "dir").symlink_to(outside.parent)
        Retention(root, now=lambda: 1_800_000_000.0).sweep()
        check_(outside.exists(), "deleted through a link", f)
    return f


@case("recognised_attempts_follow_the_7_day_rule_and_deleted_people_go_at_once")
async def _c37() -> list[str]:
    f: list[str] = []
    pid = "fp_3a9c12ab34cd"
    with tempfile.TemporaryDirectory() as d:
        mine = _aged(Path(d) / "a" / f"1-{pid}-0.9.webp", 100)
        other = _aged(Path(d) / "a" / "2-fp_000000000001-0.9.webp", 100)
        r = Retention(Path(d) / "a", now=lambda: 1_800_000_000.0)
        r.sweep()
        check_(mine.exists() and other.exists(), "a recognised crop went before 7 days", f)
        r.delete_for(pid)
        check_(not mine.exists() and other.exists(), "delete_for wrong", f)
    return f


@case("a_registry_that_cannot_be_saved_changes_nothing")
async def _c38() -> list[str]:
    r = Rig()
    await r.adult()

    async def boom(_fn: Any) -> None:
        raise RuntimeError("down")

    r.docs.transaction = boom  # type: ignore[method-assign]
    f: list[str] = []
    try:
        await r.adult("Ravi")
        f.append("reported success")
    except FacesUnavailable:
        pass
    return f


async def run_all() -> list[dict[str, Any]]:
    out = []
    for name, fn in CASES:
        try:
            fails = await fn()
        except Exception as exc:  # noqa: BLE001 -- a crashing case is a failed case
            fails = [f"crashed: {type(exc).__name__}: {exc}"]
        out.append({"id": name, "passed": not fails, "failures": fails})
    return out


@contextmanager
def registry_check_off() -> Any:
    """resolve() without the registry check: any well-formed id with a score is named."""
    saved = models_mod.State.find

    def find(self: Any, person_id: str) -> Any:
        return saved(self, person_id) or (self.people[0] if self.people else None)

    models_mod.State.find = find  # type: ignore[method-assign]
    try:
        yield
    finally:
        models_mod.State.find = saved  # type: ignore[method-assign]


@contextmanager
def bridge_consent_off() -> Any:
    saved = FaceLibrary.consented
    FaceLibrary.consented = lambda self, person: isinstance(person, str)  # type: ignore[method-assign]
    try:
        yield
    finally:
        FaceLibrary.consented = saved  # type: ignore[method-assign]


@contextmanager
def children_rule_off() -> Any:
    saved_tool, saved_words = tools_mod._name, alert_words.__globals__["FAMILY_CHILD"]
    tools_mod._name = lambda name, child: name  # type: ignore[assignment]
    alert_words.__globals__["FAMILY_CHILD"] = "Mini"
    try:
        yield
    finally:
        tools_mod._name = saved_tool  # type: ignore[assignment]
        alert_words.__globals__["FAMILY_CHILD"] = saved_words


async def controls() -> dict[str, Any]:
    with registry_check_off():
        a = await run_all()
    with bridge_consent_off():
        b = await run_all()
    with children_rule_off():
        c = await run_all()
    failed = {
        "registry_check_off": [r["id"] for r in a if not r["passed"]],
        "bridge_consent_off": [r["id"] for r in b if not r["passed"]],
        "children_rule_off": [r["id"] for r in c if not r["passed"]],
    }
    return {"suite_failed": all(failed.values()), "failed_cases": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    configure_logging()
    results = asyncio.run(run_all())
    return finish(HERE, "faces", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
