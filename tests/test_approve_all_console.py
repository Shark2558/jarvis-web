# tests/test_approve_all_console.py — the "Approve all (n)" button's static contract (slice 11 D6):
# served and loaded after the console, no HTML sinks, the console's own transport and reply path,
# only cards that can be undone AND that the server marks bulk_ok (review MEDIUM-1: never a draft
# to an untyped address or a memory write), of one conversation, and only when 2 or more wait.
# The batch sent is exactly the one shown: a change disables the button for a moment first.
# The approvals decision path itself lives in console-approvals.js (review housekeeping).
from __future__ import annotations

from httpx import AsyncClient
from test_console_assets import _sinks  # same directory (pytest prepend import)

from jarvis.api.console import APP_ASSETS

NAME = "console-approve-all.js"
DECISIONS = "console-approvals.js"


async def test_served_as_javascript_with_no_store(client: AsyncClient) -> None:
    for name in (NAME, DECISIONS):
        r = await client.get(f"/static/{name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(
            "application/javascript"
        )
        assert r.headers["cache-control"] == "no-store"
    assert DECISIONS in APP_ASSETS


async def test_never_parses_server_text_as_html_and_uses_the_consoles_transport(
    client: AsyncClient,
) -> None:
    js = (await client.get(f"/static/{NAME}")).text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js
    assert "'/v1/approvals/approve-all'" in js
    assert "h.decide(" in js  # one action at a time, the reply shown in its conversation
    assert "import " not in js and "http" not in js


async def test_only_bulk_ok_undoable_cards_of_one_conversation_and_at_least_two(
    client: AsyncClient,
) -> None:
    js = (await client.get(f"/static/{NAME}")).text
    assert "new Set(['reversible', 'read_only'])" in js  # unknown risk never counts
    assert "a.bulk_ok === true" in js  # the server's word: a missing flag is never bulk
    assert "const MIN = 2;" in js
    assert "Approve all (${n})" in js
    assert "session_id: sid, ids" in js
    assert "need you one by one" in js and "needs you one by one" in js


async def test_the_batch_sent_is_exactly_the_one_shown(client: AsyncClient) -> None:
    js = (await client.get(f"/static/{NAME}")).text
    assert "const SETTLE_MS = 1500;" in js
    assert "Object.freeze(next.ids.slice())" in js  # frozen when shown, sent as is
    assert "setTimeout(" in js and "btn.disabled = true" in js


async def test_loaded_after_the_console_above_the_cards(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert f'<script src="/static/{NAME}" defer></script>' in html
    assert f'<script src="/static/{DECISIONS}" defer></script>' in html
    order = [html.index(f'src="/static/{n}"') for n in (DECISIONS, "console.js", NAME)]
    assert order == sorted(order)  # the decision path first: console.js hands it its pieces
    css = (await client.get("/static/console-permissions.css")).text
    assert ".apall{" in css and ".apall[hidden]{display:none}" in css


async def test_the_console_hands_over_the_cards_and_the_decision_path(client: AsyncClient) -> None:
    js = (await client.get("/static/console.js")).text
    assert "cards: list" in js  # jarvis:approvals carries the cards it rendered
    assert "window.JarvisApprovals = Object.freeze({ session: () => state.sessionId, " in js
    assert "cards: () => lastCards, decide: decideWith })" in js
    assert "window.JarvisDecisions" in js and "function runDecision" not in js


async def test_the_decision_path_moved_out_of_the_console_unchanged(client: AsyncClient) -> None:
    js = (await client.get(f"/static/{DECISIONS}")).text
    assert _sinks(js) == [] and "fetch(" not in js and "http" not in js
    assert "async function decide(id, action, card, sid, tool, passkey)" in js
    assert "async function runDecision(target, call, noteText, failText)" in js
    assert "async function decideWith(sid, call, noteText, failText)" in js
    assert "window.JarvisDecisions = Object.freeze({ make })" in js
    # every console*.js is at most 800 lines: tests/test_console_integrations.py (review C5)
