# tests/test_permissions_console.py — the Permissions section's static contract (slice 10 D): served
# and loaded after the console, no HTML sinks, the console's transport only, native WebAuthn (no
# library, no CDN), plain-English errors, and the approval card hook in console.js.
from __future__ import annotations

import re

from httpx import AsyncClient
from test_console_assets import _sinks  # same directory (pytest prepend import)

REAUTH = "window.location.assign('/auth/login?reauth=1')"


async def test_permissions_script_never_parses_server_text_as_html(client: AsyncClient) -> None:
    r = await client.get("/static/console-permissions.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    js = r.text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js  # the console's api() only
    for path in (
        "'/v1/permissions'",
        "'/v1/passkeys/challenge'",
        "'/v1/passkeys/register/options'",
        "'/v1/passkeys/register'",
        "`/v1/passkeys/${encodeURIComponent(p.id)}/remove`",
        "'/v1/passkeys/reset'",
        "'/v1/passkeys/reset/cancel'",
    ):
        assert path in js, path
    # the browser's own WebAuthn, user verification required, no library or remote script
    assert "navigator.credentials[kind]({ publicKey })" in js
    assert "userVerification: 'required'" in js
    assert "import " not in js and "http" not in js.replace("https://", "")
    assert js.count(REAUTH) == 1  # the one navigation: the fixed re-auth path


async def test_permissions_script_speaks_plain_english_for_each_failure(
    client: AsyncClient,
) -> None:
    js = (await client.get("/static/console-permissions.js")).text
    for name in ("NotAllowedError", "AbortError", "SecurityError", "NotSupportedError"):
        assert f"'{name}'" in js
    for words in ("Cancelled.", "timed out", "not supported in this browser"):
        assert words in js
    # no sign-in shortcut: removing and switching off always carry a passkey check
    assert "{ body: { proof: await prove({ purpose: 'remove', credential_id: p.id }) } }" in js
    assert "proof: await prove({ purpose: 'disable' })" in js
    assert "Google didn\\'t ask you to sign in again" in js


async def test_permissions_section_is_collapsed_in_the_approvals_panel(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    panel = html[html.index('id="p-approvals"') : html.index('id="p-activity"')]
    assert 'id="permSet"' in panel and 'id="permSetBtn"' in panel
    assert re.search(r'id="permSetBtn"[^>]*aria-expanded="false"', panel)
    assert re.search(r'id="permSetBody"\s+hidden', panel)
    assert 'id="permSum"' in panel and 'id="pskBox"' in panel
    # a pending passkey reset is a banner at the top of the panel, above the cards
    assert re.search(r'id="permBanner"[^>]*role="alert"[^>]*hidden', panel)
    assert panel.index('id="permBanner"') < panel.index('id="approvals"')
    names = ("console-deck.js", "console.js", "console-permissions.js")
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    assert 'href="/static/console-permissions.css"' in html
    css = await client.get("/static/console-permissions.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


async def test_approval_cards_offer_approve_with_passkey(client: AsyncClient) -> None:
    js = (await client.get("/static/console.js")).text
    assert "a.passkey_required === true ? 'Approve with passkey' : 'Approve'" in js
    assert '<p class="perr" role="alert"></p>' in js
    decisions = (await client.get("/static/console-approvals.js")).text  # slice 11 review
    assert "body.passkey = await P.approve(id)" in decisions
    perm = (await client.get("/static/console-permissions.js")).text
    assert "window.JarvisPasskey = Object.freeze(" in perm
    assert "document.addEventListener('jarvis:ready'" in perm
