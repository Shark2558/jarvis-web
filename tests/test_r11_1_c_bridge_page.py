# tests/test_r11_1_c_bridge_page.py -- R11.1 O7 (plan D15): the laptop's own Faces page shows WHO
# a group is (its crops), which the cloud console never can. Behind the page's login like the rest:
# the groups with their pictures, "Forget this group", the watched folder's state and "read the
# folder again". Writes need the CSRF token; a crop is served only to a signed-in browser on this
# laptop and is never cached.
from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from r11_1_fakes_c import CROP_NEEDLE, A
from test_r11_1_c_bridge_groups import ENROL, Rig

from jarvis.homebridge.local_page import PORT, STATIC, create_local_app

CODE = "correct-horse-battery"
BASE = f"http://localhost:{PORT}"


async def page(tmp_path: Path, *, groups: bool = True, **env: str) -> tuple[AsyncClient, Rig]:
    rig = Rig(tmp_path, **env)
    provider = (lambda: rig.groups) if groups else (lambda: None)
    app = create_local_app(rig.faces.library, CODE, now=lambda: 1000.0, groups=provider)
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE), rig


async def signed_in(c: AsyncClient) -> dict[str, str]:
    r = await c.post("/faces/api/login", json={"code": CODE})
    assert r.status_code == 200
    return {"X-CSRF": r.json()["csrf"]}


async def test_the_groups_and_their_pictures_need_the_pages_login(tmp_path: Path) -> None:
    c, rig = await page(tmp_path)
    gid = await rig.seen(1)
    for path in ("/faces/api/groups", f"/faces/api/groups/{gid}/0"):
        r = await c.get(path)
        assert r.status_code == 401 and r.json()["error"] == "login"
    assert (await c.post("/faces/api/groups/forget", json={"group": gid})).status_code == 401


async def test_a_group_is_listed_with_its_number_and_shown_by_its_crops(tmp_path: Path) -> None:
    c, rig = await page(tmp_path, FACE_GROUPS_KEEP_DAYS="60")
    gid = await rig.seen(1)
    await rig.send(2)  # a stray: not listed
    await signed_in(c)
    body = (await c.get("/faces/api/groups")).json()
    assert body["available"] is True and body["keep_days"] == 60 and body["strays"] == 1
    (group,) = body["groups"]
    assert (group["id"], group["n"], group["photos"], group["crops"]) == (gid, 1, 3, 3)
    assert body["folder"] == "off" and body["engine"] == "ready"
    r = await c.get(f"/faces/api/groups/{gid}/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8\xff") and CROP_NEEDLE in r.content
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    for bad in (
        f"{gid}/3",
        f"{gid}/9",
        f"{gid}/-1",
        f"{gid}/x",
        "c_ffffffffffff/0",
        "..%2f..%2fx/0",
    ):
        assert (await c.get(f"/faces/api/groups/{bad}")).status_code in (404, 422), bad


async def test_forget_this_group_needs_the_csrf_token_and_removes_it(tmp_path: Path) -> None:
    c, rig = await page(tmp_path)
    one, two = await rig.seen(1), await rig.seen(2)
    csrf = await signed_in(c)
    r = await c.post("/faces/api/groups/forget", json={"group": one})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await c.post("/faces/api/groups/forget", json={"group": one}, headers=csrf)
    assert r.status_code == 200 and r.json() == {"forgotten": 1}
    assert [g["id"] for g in (await c.get("/faces/api/groups")).json()["groups"]] == [two]
    assert (await c.get(f"/faces/api/groups/{one}/0")).status_code == 404
    for bad in ({"group": "nope"}, {"group": 5}, {}, {"group": two, "extra": 1}):
        r = await c.post("/faces/api/groups/forget", json=bad, headers=csrf)
        assert r.status_code in (404, 422), bad
    other = {"Origin": "http://evil.example", **csrf}
    r = await c.post("/faces/api/groups/forget", json={"group": two}, headers=other)
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


async def test_a_named_group_is_not_forgotten_from_this_page(tmp_path: Path) -> None:
    c, rig = await page(tmp_path)
    gid = await rig.seen(1)
    await rig.consent(A)
    await rig.call(ENROL, {"cluster": gid, "person": A})
    csrf = await signed_in(c)
    r = await c.post("/faces/api/groups/forget", json={"group": gid}, headers=csrf)
    assert r.status_code == 200 and r.json() == {"forgotten": 0}  # it goes with the person
    assert rig.groups.store.pictures_of(A) == 3


async def test_read_the_folder_again_needs_the_token(tmp_path: Path) -> None:
    c, rig = await page(tmp_path)
    await rig.seen(1)
    rig.groups.store.mark_file("file-1", "pic-1")
    csrf = await signed_in(c)
    assert (await c.post("/faces/api/groups/rescan")).status_code == 403
    r = await c.post("/faces/api/groups/rescan", headers=csrf)
    assert r.status_code == 200 and rig.groups.store.file_seen("file-1") is False


async def test_without_the_groups_part_the_page_says_so(tmp_path: Path) -> None:
    c, _ = await page(tmp_path, groups=False)
    csrf = await signed_in(c)
    assert (await c.get("/faces/api/groups")).json() == {"available": False}
    assert (await c.get("/faces/api/groups/c_0123456789ab/0")).status_code == 404
    r = await c.post("/faces/api/groups/forget", json={"group": "c_0123456789ab"}, headers=csrf)
    assert r.status_code == 404


def test_the_page_stays_script_safe_and_says_where_naming_happens() -> None:
    html = (STATIC / "faces.html").read_text()
    js = (STATIC / "faces.js").read_text()
    assert "<script>" not in html and "style=" not in html and 'id="groups"' in html
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js
    assert "Unnamed groups" in html and "never changed" in html
    assert "/faces/api/groups" in js and js.isascii() and html.isascii()


async def test_a_view_never_reaches_the_signed_route(tmp_path: Path) -> None:
    """What the page adds for the owner's own eyes (how many crops, what is waiting) is not in
    the answer the cloud gets."""
    _, rig = await page(tmp_path)
    await rig.seen(1)
    signed: dict[str, Any] = await rig.call(("GET", "/bridge/v1/faces/groups"))
    assert "crops" not in signed["groups"][0] and "waiting" not in signed
    assert "crops" in rig.groups.page_view()["groups"][0]
