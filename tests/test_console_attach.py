# tests/test_console_attach.py — slice 10 E console: the paperclip, drag-and-drop and file chips are
# served from this server under the unchanged CSP, load after console.js, write text only through
# textContent, use the console's own transport, and the composer is wired for them.
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "createContextualFragment",
    "DOMParser",
    "setHTMLUnsafe",
    "eval(",
    "new Function",
)
URL_SINK = re.compile(
    r"\.(?:href|src|action|formAction)\s*=(?!=)|setAttribute\(\s*['\"`](?:on|href|src)"
)


async def test_attach_assets_are_served_with_no_store(client: AsyncClient) -> None:
    for name, kind in (("console-attach.js", "javascript"), ("console-attach.css", "css")):
        r = await client.get(f"/static/{name}")
        assert r.status_code == 200 and kind in r.headers["content-type"]
        assert r.headers["cache-control"] == "no-store"


async def test_attach_script_and_styles_load_after_the_console(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert '<script src="/static/console-attach.js" defer></script>' in html
    assert html.index('src="/static/console.js"') < html.index('src="/static/console-attach.js"')
    assert '<link rel="stylesheet" href="/static/console-attach.css">' in html


async def test_composer_has_the_paperclip_input_chips_and_error_line(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="attachBtn" type="button" aria-label="Attach files"' in html
    assert (
        'type="file" id="attachInput" accept=".pdf,.docx,.txt,.md,.markdown,.csv" multiple hidden'
        in html
    )
    assert 'id="attachChips" role="list"' in html and 'id="attachErr" role="alert" hidden' in html
    form = html[html.index('id="form"') : html.index("</form>")]
    assert form.index('id="attachBtn"') < form.index('id="input"')


def test_attach_script_writes_text_only_and_uses_the_console_transport() -> None:
    js = (STATIC / "console-attach.js").read_text(encoding="utf-8")
    assert [s for s in SINKS if s in js] == [] and not URL_SINK.search(js)
    assert "textContent" in js and "fetch(" not in js  # JarvisChat.raw / JarvisConsole.api only
    assert "chat.raw('/v1/attachments'" in js and "'X-Jarvis-Filename': encodeURIComponent(" in js
    assert "/v1/attachments/${encodeURIComponent(id)}`, { method: 'DELETE' }" in js
    # R11.1 D11: 10 files a message (it was 3), 10 MB each, 40 MB together, 4 pictures
    assert "let MAX_FILES = 10, MAX_BYTES = 10 * MB, TOTAL_BYTES = 40 * MB, MAX_PICTURES = 4;" in js
    assert "const MB = 1024 * 1024;" in js
    for lit in re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]  # rupees only, never dollars


def test_console_sends_ready_files_and_keeps_them_on_a_refusal() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    assert "body.attachments = files.map(f => f.id)" in js
    assert "e.code !== 'input_rejected' && e.status !== 402" in js
    assert "Attach().show(row, t.attachments)" in js  # restored transcripts show their files
    assert "document.addEventListener('jarvis:attach'" in js
