# tests/test_homebridge_local_page.py -- R3 D13: the laptop Faces page. 127.0.0.1 only, Host and
# Origin checks, login code (constant time, lockout), HttpOnly SameSite=Strict cookie, CSRF on
# writes, uploads only for consented ids, its own CSP, nothing cached.
from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from test_homebridge_faces import JPEG, A, B, FakeLib, consent, rig

from jarvis.homebridge import local_page
from jarvis.homebridge.local_page import PORT, create_local_app, login_code

CODE = "correct-horse-battery"
BASE = f"http://localhost:{PORT}"


async def client(tmp_path: Path, now: Any = lambda: 1000.0) -> tuple[AsyncClient, FakeLib, Any]:
    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    app = create_local_app(fl, CODE, now=now)
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE), lib, fl


async def signed_in(c: AsyncClient) -> dict[str, str]:
    r = await c.post("/faces/api/login", json={"code": CODE})
    assert r.status_code == 200
    return {"X-CSRF": r.json()["csrf"]}


def test_it_binds_to_loopback_only() -> None:
    assert local_page.HOST == "127.0.0.1" and local_page.PORT == 8098


async def test_assets_are_served_with_the_pages_own_csp(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    for path, kind in (
        ("/faces", "text/html"),
        ("/faces/faces.js", "javascript"),
        ("/faces/faces.css", "text/css"),
    ):
        r = await c.get(path)
        assert r.status_code == 200 and kind in r.headers["content-type"]
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"
    assert (await c.get("/faces/other.js")).status_code == 404
    assert (await c.get("/faces/..%2f..%2fetc")).status_code in (404, 422)
    html = (await c.get("/faces")).text
    assert (
        "<script>" not in html
        and "style=" not in html
        and "http" not in html.replace("http://localhost", "")
    )


async def test_a_foreign_host_is_refused_dns_rebinding(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    r = await c.get("/faces", headers={"Host": "evil.example:8098"})
    assert r.status_code == 403
    r2 = await c.get("/faces", headers={"Host": "localhost:9999"})
    assert r2.status_code == 403
    assert (await c.get("/faces", headers={"Host": f"127.0.0.1:{PORT}"})).status_code == 200


async def test_a_post_from_another_origin_is_refused(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    r = await c.post(
        "/faces/api/login", json={"code": CODE}, headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    ok = await c.post("/faces/api/login", json={"code": CODE}, headers={"Origin": BASE})
    assert ok.status_code == 200


async def test_nothing_without_a_session(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    for method, path in (
        ("GET", "/faces/api/people"),
        ("POST", "/faces/api/enrol?person=" + A),
        ("GET", "/faces/api/recent/a.webp"),
    ):
        assert (await c.request(method, path)).status_code == 401


async def test_wrong_code_then_lockout_then_it_opens_again(tmp_path: Path) -> None:
    clock = [1000.0]
    c, _, _ = await client(tmp_path, now=lambda: clock[0])
    for _ in range(5):
        r = await c.post("/faces/api/login", json={"code": "nope"})
        assert r.status_code == 401
    locked = await c.post("/faces/api/login", json={"code": CODE})
    assert locked.status_code == 429
    clock[0] += 61
    assert (await c.post("/faces/api/login", json={"code": CODE})).status_code == 200


async def test_the_cookie_is_httponly_strict_and_scoped(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    r = await c.post("/faces/api/login", json={"code": CODE})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/faces" in cookie
    assert "max-age=43200" in cookie
    assert CODE not in r.text


async def test_writes_need_the_csrf_token(tmp_path: Path) -> None:
    c, lib, _ = await client(tmp_path)
    await signed_in(c)
    r = await c.post(f"/faces/api/enrol?person={A}", content=JPEG)
    assert r.status_code == 403 and r.json()["error"] == "csrf" and lib.pictures == {}
    bad = await c.post(f"/faces/api/enrol?person={A}", content=JPEG, headers={"X-CSRF": "x"})
    assert bad.status_code == 403


async def test_people_are_listed_by_code_with_counts_and_no_names(tmp_path: Path) -> None:
    c, lib, _ = await client(tmp_path)
    csrf = await signed_in(c)
    lib.pictures[A] = [JPEG] * 2
    got = (await c.get("/faces/api/people")).json()
    assert got["people"] == [{"id": A, "pictures": 2}] and got["recent"] == ["a.webp"]
    assert got["csrf"] == csrf["X-CSRF"]


async def test_upload_for_a_consented_id_only(tmp_path: Path) -> None:
    c, lib, _ = await client(tmp_path)
    h = await signed_in(c)
    ok = await c.post(f"/faces/api/enrol?person={A}", content=JPEG, headers=h)
    assert ok.status_code == 200 and ok.json() == {"pictures": 1}
    no = await c.post(f"/faces/api/enrol?person={B}", content=JPEG, headers=h)
    assert no.status_code == 422 and no.json()["error"] == "no_consent"
    bad = await c.post(f"/faces/api/enrol?person={A}", content=b"GIF89a", headers=h)
    assert bad.json()["error"] == "bad_image"
    big = await c.post(
        f"/faces/api/enrol?person={A}", content=JPEG + b"x" * (5 * 1024 * 1024), headers=h
    )
    assert big.status_code == 413
    assert list(lib.pictures) == [A] and len(lib.pictures[A]) == 1


async def test_recent_visitors_can_be_picked(tmp_path: Path) -> None:
    c, lib, _ = await client(tmp_path)
    h = await signed_in(c)
    img = await c.get("/faces/api/recent/a.webp")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert (await c.get("/faces/api/recent/..%2fx")).status_code in (404, 422)
    ok = await c.post("/faces/api/classify", json={"person": A, "file": "a.webp"}, headers=h)
    assert ok.status_code == 200 and lib.classified == [(A, "a.webp")]
    no = await c.post("/faces/api/classify", json={"person": B, "file": "a.webp"}, headers=h)
    assert no.status_code == 422


async def test_frigate_down_is_plain_words(tmp_path: Path) -> None:
    c, lib, _ = await client(tmp_path)
    await signed_in(c)
    lib.down = True
    r = await c.get("/faces/api/people")
    assert r.status_code == 503 and "10.0.0.5" not in r.text


async def test_logout_ends_the_session(tmp_path: Path) -> None:
    c, _, _ = await client(tmp_path)
    h = await signed_in(c)
    assert (await c.post("/faces/api/logout", headers=h)).status_code == 200
    assert (await c.get("/faces/api/people")).status_code == 401


async def test_sessions_expire_after_twelve_hours(tmp_path: Path) -> None:
    clock = [1000.0]
    c, _, _ = await client(tmp_path, now=lambda: clock[0])
    await signed_in(c)
    clock[0] += 12 * 3600 + 1
    assert (await c.get("/faces/api/people")).status_code == 401


def test_login_code_comes_from_the_environment_or_a_private_file(tmp_path: Path) -> None:
    assert login_code({"FACES_CODE": "my-own-code-123"}, tmp_path) == "my-own-code-123"
    made = login_code({"FACES_CODE": "short"}, tmp_path)
    assert len(made) >= 8 and made != "short"
    assert login_code({}, tmp_path) == made  # stable across restarts
    assert (tmp_path / "faces_code.txt").stat().st_mode & 0o777 == 0o600


def test_the_page_script_never_uses_inline_markup() -> None:
    js = (Path(local_page.__file__).parent / "static" / "faces.js").read_text()
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js
