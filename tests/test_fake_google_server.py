# tests/test_fake_google_server.py — slice 11 fix: the eval fake Google
# (evals/slice6/fake_google.py) behaves like Calendar where undo depends on it: a deleted event
# reads as cancelled (or 410) and
# leaves lists, inserts are checked (times, ids), a duplicate id is 409.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_PATH = Path(__file__).resolve().parents[1] / "evals" / "slice6" / "fake_google.py"
_spec = importlib.util.spec_from_file_location("fake_google_server", _PATH)
assert _spec is not None and _spec.loader is not None
_mod = sys.modules.get("fake_google_server") or importlib.util.module_from_spec(_spec)
if "fake_google_server" not in sys.modules:
    sys.modules["fake_google_server"] = _mod
    _spec.loader.exec_module(_mod)
FakeGoogleServer = _mod.FakeGoogleServer

EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SLOT = {
    "start": {"dateTime": "2027-01-15T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
    "end": {"dateTime": "2027-01-15T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
}
WINDOW = {"timeMin": "2027-01-15T00:00:00+05:30", "timeMax": "2027-01-16T00:00:00+05:30"}
ZULU = "2027-01-15T10:30:00Z"


def _server(**kw: Any) -> Any:
    s = FakeGoogleServer(time_zone="Asia/Kolkata", events={}, **kw)
    s.plant_event(id="dentist0001", summary="Dentist", **SLOT)
    return s


async def test_a_deleted_event_reads_as_cancelled_and_leaves_the_list() -> None:
    s = _server()
    async with s.client() as c:
        assert (await c.delete(f"{EVENTS}/dentist0001")).status_code == 204
        got = await c.get(f"{EVENTS}/dentist0001")
        assert got.status_code == 200 and got.json()["status"] == "cancelled"
        assert (await c.get(EVENTS, params=WINDOW)).json()["items"] == []
        assert (await c.delete(f"{EVENTS}/dentist0001")).status_code == 410
    assert not s.live("dentist0001")


async def test_a_deleted_event_can_read_as_410() -> None:
    s = _server(deleted_status=410)
    async with s.client() as c:
        await c.delete(f"{EVENTS}/dentist0001")
        assert (await c.get(f"{EVENTS}/dentist0001")).status_code == 410


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"summary": "x"}, 400),  # no times
        ({"summary": "x", "start": {"dateTime": "2027-01-15T16:00:00"}, "end": SLOT["end"]}, 400),
        ({**SLOT, "id": "Bad_ID!"}, 400),
        ({**SLOT, "id": "abc"}, 400),  # too short
        ({**SLOT, "id": "dentist0001"}, 409),  # exists already
        ({**SLOT, "recurrence": ["RRULE:FREQ=DAILY"], "start": {"dateTime": ZULU}},
         400),  # a repeating event needs a time zone
        ({"start": SLOT["end"], "end": SLOT["start"]}, 400),  # ends before it starts
        ({"start": {"date": "2027-01-15"}, "end": {"date": "2027-01-16"}}, 200),
        ({**SLOT, "id": "jarvis0123456789abcdef0123"}, 200),
    ],
)  # fmt: skip
async def test_insert_bodies_are_checked_like_google(body: dict[str, Any], status: int) -> None:
    s = _server()
    async with s.client() as c:
        r = await c.post(EVENTS, json=body)
    assert r.status_code == status, r.text
    if status == 200:
        made = r.json()
        assert made["status"] == "confirmed" and made["organizer"]["self"] is True
        assert _mod._CLIENT_ID.fullmatch(made["id"])


async def test_made_ids_are_valid_event_ids() -> None:
    s = _server()
    async with s.client() as c:
        r = await c.post(EVENTS, json={"summary": "x", **SLOT})
    assert isinstance(r, httpx.Response) and _mod._CLIENT_ID.fullmatch(r.json()["id"])
