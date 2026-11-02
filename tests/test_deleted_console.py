# tests/test_deleted_console.py — the Recently deleted section and Undo chip's static contract
# (slice 11 D1): served like the other console assets, loaded after the console, no HTML sinks,
# the console's transport only, and the one-line hook in console.js.
from __future__ import annotations

from httpx import AsyncClient
from test_console_assets import _sinks  # same directory (pytest prepend import)


async def test_deleted_script_never_parses_server_text_as_html(client: AsyncClient) -> None:
    r = await client.get("/static/console-deleted.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert r.headers["cache-control"] == "no-store"
    js = r.text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js  # the console's api() only
    assert "'/v1/deleted'" in js
    assert "`/v1/deleted/${encodeURIComponent(id)}/restore`, { method: 'POST' }" in js
    assert "import " not in js and "http" not in js.replace("http://www.w3.org/2000/svg", "")
    assert "window.JarvisDeleted = Object.freeze(" in js
    assert "document.addEventListener('jarvis:ready', ready)" in js
    assert "JC.ready()" in js  # arrives late: asks the console whether it is signed in


async def test_deleted_section_sits_in_the_approvals_panel_above_permissions(
    client: AsyncClient,
) -> None:
    js = (await client.get("/static/console-deleted.js")).text
    assert "document.querySelector('#p-approvals .pbody')" in js
    assert "panel.insertBefore(section, perm)" in js
    assert "btn.setAttribute('aria-expanded', 'false')" in js and "body.hidden = true" in js
    html = (await client.get("/")).text
    names = ("console-deck.js", "console.js", "console-permissions.js", "console-deleted.js")
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    assert '<link rel="stylesheet" href="/static/console-deleted.css">' in html
    css = await client.get("/static/console-deleted.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert "Anything that sends, pays or can't be undone waits for your approval." in html


async def test_replies_get_undo_chips_through_one_hook(client: AsyncClient) -> None:
    js = (await client.get("/static/console.js")).text
    hook = "if (window.JarvisDeleted) window.JarvisDeleted.chips(row, r.undo);"
    assert js.count(hook) == 1 and js.count("JarvisDeleted") == 2  # that one line only
    deleted = (await client.get("/static/console-deleted.js")).text
    assert "function chips(rowEl, undo)" in deleted
    assert "ID.test(r.undo_id)" in deleted  # anything but a real undo id is dropped
