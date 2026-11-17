# tests/test_r131_d_door.py -- R13.1 Part D's proposal for I1 (INTEGRATION-D "Needs I1", 1):
# three lines for the door (console-r7-send.js, I0's file, which D never edits). The seam tests
# let ONLY the door name /v1/seeme/photo, /pictures and /garments, but the door has no call for
# See it on me's paid press, Keep, the deletes or the garment list, so until I1 applies the lines
# the console says "This arrives with the next JARVIS update" and sends nothing. The browser
# tests serve the door with them applied (`r131_fakes_d.patched_door`); this file holds it to:
#   - every pin other tests put on the door (its size, its exports, no fetch, no address, R7's
#     needles), so I1 can apply the diff as it is
#   - its behaviour in Node: each call goes to exactly its route through JarvisConsole.api, an id
#     that isn't a picture's (`tp_`) or a garment's (`tg_`) is refused before anything is sent,
#     and Keep sends a real boolean
# Once I1 has applied the lines, `patched_door()` returns the door unchanged and this still holds.
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from r131_fakes_d import DOOR, patched_door

DOOR_LIMIT = 165  # tests/test_r131_seams.py and tests/test_r13_seams.py
PIC, GAR = "tp_0123456789ab", "tg_0123456789ab"


def _code(js: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.S)


def test_the_proposed_lines_keep_every_pin_of_the_door() -> None:
    door = patched_door()
    assert len(door.splitlines()) <= DOOR_LIMIT
    code = _code(door)
    assert "wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto," in code
    assert "wardrobe, tag, thumb, drop," in code  # R13's pin
    assert "fetch(" not in code and "http" not in code and "XMLHttpRequest" not in code
    r7 = ("JarvisAttach", ".add(", "shrink", "cost", "Pictures sent from this device today")
    for needle in r7:
        assert needle in door, needle  # R7's pins
    for pin in (
        "jpegTo('/v1/seeme/photo', blob, (meta || {}).maxKb)",
        "readBack(/^tp_[0-9a-f]{12}$/, '/v1/seeme/pictures/')",
        "readBack(/^tg_[0-9a-f]{12}$/, '/v1/seeme/garments/')",
        "doc.size > opts.maxKb * 1024",
    ):  # fmt: skip
        assert pin in code, pin
    added = set(door.splitlines()) - set(DOOR.read_text(encoding="utf-8").splitlines())
    assert len(added) == 4  # three new lines and the export line that names them
    for path in re.findall(r"""['"`](/v1/[^'"`]*)""", _code("\n".join(added))):
        assert path == "/v1/seeme/", path  # only See it on me's own routes, through the console


HARNESS = """
const calls = [];
globalThis.window = {
  JarvisMobile: { part(name, obj) { globalThis.__door = obj; } },
  JarvisConsole: { api: (path, opts) => {
    calls.push([path, opts === undefined ? null : opts]);
    return Promise.resolve({});
  } },
};
await import('data:text/javascript;base64,' + Buffer.from(SOURCE).toString('base64'));
const d = globalThis.__door, out = [];
const tryIt = async (fn) => {
  try { await fn(); out.push('sent'); } catch (e) { out.push('refused'); }
};
for (const step of STEPS) await tryIt(() => d[step[0]](...step.slice(1)));
console.log(JSON.stringify({ calls, out, frozen: Object.isFrozen(d), names: Object.keys(d) }));
"""


def _door(steps: list[list[Any]]) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    src = HARNESS.replace("SOURCE", json.dumps(patched_door())).replace("STEPS", json.dumps(steps))
    got = subprocess.run(
        [node, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60,
        check=False,
    )  # fmt: skip
    assert got.returncode == 0, got.stderr
    out: dict[str, Any] = json.loads(got.stdout)
    return out


def test_each_new_call_goes_to_exactly_its_route() -> None:
    body = {"garment": GAR, "pieces": ["wi_000000000002"], "confirm_cost": True,
            "inr_shown": 8.9, "request_id": "tq_0123456789abcdef"}  # fmt: skip
    got = _door([
        ["make", body], ["keep", PIC, True], ["keep", PIC, "yes"], ["forget", "photo"],
        ["forget", PIC], ["forget", GAR], ["garments"],
    ])  # fmt: skip
    assert got["out"] == ["sent"] * 7
    assert got["calls"] == [
        ["/v1/seeme/pictures", {"body": body}],
        [f"/v1/seeme/pictures/{PIC}/keep", {"body": {"keep": True}}],
        [f"/v1/seeme/pictures/{PIC}/keep", {"body": {"keep": False}}],  # only a real true keeps
        ["/v1/seeme/photo", {"method": "DELETE"}],
        [f"/v1/seeme/pictures/{PIC}", {"method": "DELETE"}],
        [f"/v1/seeme/garments/{GAR}", {"method": "DELETE"}],
        ["/v1/seeme/garments", None],
    ]
    assert got["frozen"] is True
    assert got["names"][-6:] == ["make", "keep", "forget", "garments", "sentToday", "line"]


def test_an_id_that_isnt_a_pictures_or_a_garments_is_refused_before_anything_is_sent() -> None:
    got = _door([
        ["keep", GAR, True], ["keep", "wi_0123456789ab", True], ["forget", "wi_0123456789ab"],
        ["forget", PIC + "/../../wardrobe"], ["forget", "../photo"], ["forget", None],
        ["keep", "tp_0123456789AB", True], ["forget", "tp_0123"],
    ])  # fmt: skip
    assert got["out"] == ["refused"] * 8 and got["calls"] == []
