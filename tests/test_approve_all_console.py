# tests/test_approve_all_console.py — the "Approve all (n)" button's static contract (slice 11 D6):
# served and loaded after the console, no HTML sinks, the console's own transport and reply path,
# only cards that can be undone, of one conversation, and only when 2 or more wait.
from __future__ import annotations

from httpx import AsyncClient
from test_console_assets import _sinks  # same directory (pytest prepend import)

NAME = "console-approve-all.js"


async def test_served_as_javascript_with_no_store(client: AsyncClient) -> None:
    r = await client.get(f"/static/{NAME}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert r.headers["cache-control"] == "no-store"


async def test_never_parses_server_text_as_html_and_uses_the_consoles_transport(
    client: AsyncClient,
) -> None:
    js = (await client.get(f"/static/{NAME}")).text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js
    assert "'/v1/approvals/approve-all'" in js
    assert "h.decide(" in js  # one action at a time, the reply shown in its conversation
    assert "import " not in js and "http" not in js


async def test_only_undoable_cards_of_one_conversation_and_at_least_two(
    client: AsyncClient,
) -> None:
    js = (await client.get(f"/static/{NAME}")).text
    assert "new Set(['reversible', 'read_only'])" in js  # unknown risk never counts
    assert "const MIN = 2;" in js
    assert "Approve all (${n})" in js
    assert "session_id: sid, ids" in js


async def test_loaded_after_the_console_above_the_cards(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert f'<script src="/static/{NAME}" defer></script>' in html
    assert html.index('src="/static/console.js"') < html.index(f'src="/static/{NAME}"')
    css = (await client.get("/static/console-permissions.css")).text
    assert ".apall{" in css and ".apall[hidden]{display:none}" in css


async def test_the_console_hands_over_the_cards_and_the_decision_path(client: AsyncClient) -> None:
    js = (await client.get("/static/console.js")).text
    assert "cards: list" in js  # jarvis:approvals carries the cards it rendered
    assert "window.JarvisApprovals = Object.freeze({ session: () => state.sessionId, " in js
    assert "cards: () => lastCards, decide: decideWith })" in js
