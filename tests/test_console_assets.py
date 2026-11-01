# tests/test_console_assets.py — self-hosted console assets: fonts (allow-listed) and the fx script
from __future__ import annotations

import pytest
from httpx import AsyncClient

ALLOWED_FONTS = (
    "orbitron-latin-600-normal.woff2",
    "orbitron-latin-700-normal.woff2",
    "rajdhani-latin-500-normal.woff2",
    "rajdhani-latin-600-normal.woff2",
    "rajdhani-latin-700-normal.woff2",
)


@pytest.mark.parametrize("name", ALLOWED_FONTS)
async def test_serves_each_allow_listed_font_as_woff2_with_long_cache(
    client: AsyncClient, name: str
) -> None:
    r = await client.get(f"/static/fonts/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content[:4] == b"wOF2"  # real woff2 payload, not an HTML error page


@pytest.mark.parametrize(
    "path",
    [
        "/static/fonts/evil.woff2",  # unknown name
        "/static/fonts/orbitron-latin-400-normal.woff2",  # real family, not shipped
        "/static/fonts/OFL-orbitron.txt",  # exists on disk but is not a served font
        "/static/fonts/ORBITRON-LATIN-700-NORMAL.WOFF2",  # no case folding
        "/static/fonts/console.html",
        "/static/fonts/..%2Fconsole.html",  # encoded traversal
        "/static/fonts/%2e%2e%2f%2e%2e%2fconsole.py",
        "/static/fonts/..%5Cconsole.py",  # backslash traversal
        "/static/fonts/",
    ],
)
async def test_rejects_unknown_font_names_and_traversal(client: AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 404
    assert r.content[:4] != b"wOF2"
    assert b"<html" not in r.content.lower()


async def test_console_page_loads_fx_script_and_keeps_strict_csp(client: AsyncClient) -> None:
    r = await client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self';" in csp and "font-src 'self'" in csp
    assert 'src="/static/console-fx.js"' in r.text
    assert "fonts.googleapis.com" not in r.text and "https://" not in r.text.split("<body")[0]
    fx = await client.get("/static/console-fx.js")
    assert fx.status_code == 200 and "javascript" in fx.headers["content-type"]
    assert fx.headers["cache-control"] == "no-store"


async def test_console_page_declares_self_hosted_font_faces(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    for name in ALLOWED_FONTS:
        assert f"/static/fonts/{name}" in html
