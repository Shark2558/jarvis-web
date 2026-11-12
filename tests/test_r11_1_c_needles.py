# tests/test_r11_1_c_needles.py -- R11.1 O7's line that must hold everywhere (plan D15): no
# picture, crop or embedding ever leaves the laptop or appears in a cloud request, log or document;
# the cloud sees ids and counts only. One whole journey runs on the real signed channel and the
# real bridge; every crop the (scripted) engine cuts carries CROP_NEEDLE, every picked photo
# PICTURE_NEEDLE and every file the laptop reads itself OWN_NEEDLE; then everything the cloud
# received, sent, stored, logged, audited, told the owner or showed the model is searched.
#
# The one place a picked photo's bytes exist in the cloud is memory, in transit from Google to the
# owner's own laptop (R4's design, unchanged): the test pins that this is the ONLY request that
# carries one, and that a file the laptop read itself appears nowhere at all.
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from home_fakes import UID
from r11_1_fakes_c import (
    CROP_NEEDLE,
    PICTURE_NEEDLE,
    Cloud,
    build_cloud,
    consent,
    holds,
    jpeg_bytes,
    leaks,
    picture,
    vec,
)

from jarvis.facegroups.privacy import FaceGroupsPrivacy, PhotoImportPrivacy
from jarvis.facegroups.tools import face_group_tools
from jarvis.photos.edge import EdgeBadReply
from jarvis.tools.context import tool_context
from jarvis.tools.provenance import unwrap

OWN_NEEDLE = b"OWN-FILE-NEEDLE-5d20c7"
PHOTOS = ("POST", "/bridge/v1/faces/photos")


def own(person: int, n: int) -> bytes:
    """A picture in the laptop's watched folder: it never passes through the cloud."""
    return jpeg_bytes(64, 64, tail=f"<people:{person};n:{n}>".encode() + OWN_NEEDLE)


@dataclass
class Seen:
    """Everything on the cloud's side of the line after the journey, as text."""

    cloud: Cloud
    from_laptop: bytes  # the laptop's answers and its webhook posts (heartbeats, acks)
    to_laptop: list[tuple[tuple[str, str], bytes]]  # every request the cloud sent, by route
    documents: str  # every document version ever written, and what is stored now
    logs: str
    audit: str
    told: str  # alert texts
    model: str  # what the two tools hand the model
    privacy: str  # the two rows and their exports


def _logs(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.getMessage()} {r.__dict__!r}" for r in caplog.records) + caplog.text


async def _tools(c: Cloud) -> str:
    out = []
    with tool_context(f"{UID}:needles"):
        for tool in face_group_tools(c.groups, lambda: c.photos):
            out.append(json.dumps(unwrap(await tool.run({}))[0]))
    return "\n".join(out)


async def _privacy(c: Cloud) -> str:
    out = []
    for row in (FaceGroupsPrivacy(lambda: c.groups), PhotoImportPrivacy(lambda: c.photos)):
        out.append((await row.describe(UID)).model_dump_json())
        out.append(json.dumps(await row.export(UID)))
    return "\n".join(out)


async def journey(tmp: Path, caplog: pytest.LogCaptureFixture) -> Seen:
    caplog.set_level(logging.DEBUG)
    c = await build_cloud(tmp)
    for person, count in ((1, 4), (2, 3), (3, 1)):  # the watched folder: two groups and a stray
        for i in range(count):
            await c.home.groups.look(own(person, 100 * person + i), own_file=True)
    # picked in Google Photos: person 1 again, and a stranger (4) often enough to be a group
    await c.import_all([picture(1, 4, n=i, needle=True) for i in range(12)])
    assert (await c.groups.poll(UID))["told"] == 3  # the alert: a count
    model, rows = await _tools(c), await _privacy(c)
    by_n = {g.photos: g.id for g in (await c.groups.view(UID)).groups}
    await c.groups.name(UID, by_n[16], **consent())  # person 1: 4 own files + 12 picked
    await c.import_all([picture(1, n=50, needle=True)])  # now recognised, with no further step
    await c.groups.forget(UID, by_n[3])  # person 2's group: the laptop confirms
    c.home.online = False  # asleep: a name and a forget wait in the cloud
    await c.groups.name(
        UID, by_n[12], **consent(name="Mini", child=True, given_by="parent_guardian")
    )
    await c.groups.forget_all(UID)
    await c.groups.view(UID)
    c.home.online = True
    await c.groups.poll(UID)
    await c.home.beat()  # the laptop's heartbeat: counts
    model += await _tools(c)
    rows += await _privacy(c)
    docs = c.home.docs
    return Seen(
        c,
        c.home.received_by_the_cloud(),
        list(zip(c.home.down.calls, c.home.down.sent, strict=True)),
        repr(docs.log) + repr(docs._data),  # noqa: SLF001 - the fake's own record of every write
        _logs(caplog),
        repr(c.home.audit.entries),
        repr(c.home.notes.sent),
        model,
        rows,
    )


async def test_the_journey_really_happened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Without this the search below could pass on an empty journey."""
    seen = await journey(tmp_path, caplog)
    c = seen.cloud
    people = {p.name: p for p in (await c.home.faces.state(UID)).people}
    assert set(people) == {"Anjali", "Mini"} and people["Mini"].child is True
    assert all(p.state == "enrolled" for p in people.values())  # both reached the laptop
    home = c.home.groups.groups_view()
    assert (home["groups"], home["strays"], home["named"]) == ([], 0, 2)  # forgotten there too
    assert len([1 for call, _ in seen.to_laptop if call == PHOTOS]) == 13
    assert {e["tool"] for e in c.home.audit.entries} >= {"faces_group_name", "faces_group_forget"}
    assert "3 new groups of faces to name" in seen.told
    assert seen.from_laptop.count(b'"cluster"') >= 13 and b'"groups"' in seen.from_laptop
    assert '"to_name": 3' in seen.model and "photo_imports" in seen.privacy
    await c.home.aclose()


async def test_nothing_the_laptop_sends_holds_a_picture_a_crop_or_an_embedding(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    seen = await journey(tmp_path, caplog)
    assert leaks(seen.from_laptop) == []
    assert not holds(seen.from_laptop, OWN_NEEDLE)
    await seen.cloud.home.aclose()


async def test_nothing_the_cloud_keeps_says_or_shows_holds_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    seen = await journey(tmp_path, caplog)
    for name in ("documents", "logs", "audit", "told", "model", "privacy"):
        text = getattr(seen, name)
        assert text, name
        assert leaks(text) == [], name
        assert not holds(text, OWN_NEEDLE), name
    await seen.cloud.home.aclose()


async def test_a_picked_photo_travels_only_to_the_laptops_reader_and_own_files_never(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    seen = await journey(tmp_path, caplog)
    carrying = {call for call, body in seen.to_laptop if holds(body, PICTURE_NEEDLE)}
    assert carrying == {PHOTOS}  # in transit from Google to the owner's laptop, nowhere else
    for call, body in seen.to_laptop:
        assert not holds(body, OWN_NEEDLE) and not holds(body, CROP_NEEDLE), call
        assert leaks(body) == ([] if call != PHOTOS else ["picture"]), call
    # the enrol and state requests carry ids only: a group, a person id; never a name or a face
    enrol = [body for call, body in seen.to_laptop if call[1].endswith("/faces/enrol")]
    assert enrol and all(set(json.loads(b)) == {"cluster", "person"} for b in enrol)
    assert all(b"Anjali" not in body and b"Mini" not in body for _, body in seen.to_laptop)
    await seen.cloud.home.aclose()


async def test_the_needles_are_real_they_live_on_the_laptop(tmp_path: Path) -> None:
    """The control: the same search does find them where they are allowed to be."""
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    assert CROP_NEEDLE in c.home.groups.crop(gid, 0)  # the laptop's own page shows the face
    raw = b"".join(p.read_bytes() for p in (tmp_path / "data").rglob("*") if p.is_file())
    assert CROP_NEEDLE in raw  # and its own store keeps it: there, and only there
    assert leaks(CROP_NEEDLE) == ["crop"] and leaks(b"x" + PICTURE_NEEDLE) == ["picture"]
    for lead in (b"", b"1", b"12"):  # base64, at each byte alignment
        assert leaks(base64.b64encode(lead + CROP_NEEDLE + b"tail")) == ["crop"]
        assert leaks(base64.b64encode(lead + PICTURE_NEEDLE + b"tail")) == ["picture"]
    assert leaks(json.dumps({"embedding": list(vec(7))})) == ["embedding"]
    assert leaks(json.dumps({"n": 3, "photos": 12, "first": "2026-11-12T00:00:00+00:00"})) == []
    await c.home.aclose()


@pytest.mark.parametrize(
    "extra",
    [{"crop": base64.b64encode(CROP_NEEDLE).decode()}, {"embedding": list(vec(3))}],
    ids=["a crop", "an embedding"],
)
async def test_a_reply_with_anything_more_than_ids_is_refused_whole(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, extra: dict[str, object]
) -> None:
    """Should a broken or tampered kit ever answer with a face, the cloud keeps none of it."""
    caplog.set_level(logging.DEBUG)
    c = await build_cloud(tmp_path)
    plugin = c.home.groups
    groups_view, wire = plugin.groups_view, plugin._wire  # noqa: SLF001
    plugin.groups_view = lambda: {**groups_view(), **extra}
    plugin._wire = lambda placed: {**wire(placed), **extra}  # noqa: SLF001
    await c.at_home(1)
    with pytest.raises(EdgeBadReply):
        await c.photos.edge.groups(UID)
    view = await c.groups.view(UID)
    assert view.laptop == "offline" and view.groups == ()  # treated as no answer at all
    res = await c.import_all([picture(1, n=1, needle=True)])
    assert res.status == "edge_error" and res.faces_found == 0  # the photo's answer is dropped too
    assert leaks(c.home.received_by_the_cloud()) != []  # the rig did send it: the control
    kept = repr(c.home.docs.log) + _logs(caplog) + repr(c.home.audit.entries)
    assert leaks(kept) == []
    await c.home.aclose()
