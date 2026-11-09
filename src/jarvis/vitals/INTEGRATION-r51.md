# Vitals tracks itself (R5.1 Part B) -- integration

Plan: `docs/plans/r5-1-observations.md` D1, D2, D11. Nothing in a shared wiring file was edited; every
step below is for the integrator (I1). No model call, no new paid call, no new secret, no new
Scheduler job anywhere in this part.

## 1. Wire JARVIS's own keys and connections into the board (`api/r4_wiring.py`)

`VitalsService` takes a new keyword `own: OwnSources | None`. Each field is optional: a source that is
None is simply not read (a configured key without its reader shows as "Unknown"; a thing that is not
set up at all is left off the board). The Protocols live in `jarvis/vitals/own.py`; the real classes
below fit them (`tests/test_r51b_vitals_seams.py` wires exactly these).

`OwnSources` needs `app.state.health` and `app.state.github`, which `wire_r4` builds AFTER Vitals
today, so build Vitals after them. Replace in `wire_r4`:

```python
    st.vitals = _part("Vitals", lambda: wire_vitals(app, s, docs))
    st.health = _part("The systems check", lambda: wire_health(app, s, docs, mode))
    st.github = _part("GitHub", lambda: wire_github(s, docs))
```

with

```python
    st.health = _part("The systems check", lambda: wire_health(app, s, docs, mode))
    st.github = _part("GitHub", lambda: wire_github(s, docs))
    st.vitals = _part("Vitals", lambda: wire_vitals(app, s, docs))
```

and in `wire_vitals` pass the sources:

```python
from jarvis.vitals.own import OwnSources


def vitals_sources(app: FastAPI) -> OwnSources:
    """R5.1 D2: what Vitals reads to track JARVIS's own keys and connections (all free)."""
    st = app.state
    brains = st.brains
    have = {b.id for b in brains.list()}

    def health_of(brain_id: str):  # the router's own record of its last call: no model call
        return brains.router_for(brain_id).health if brain_id in have else None

    web = getattr(st, "web", None)
    usage = web.provider if web is not None and hasattr(web.provider, "usage") else None
    return OwnSources(
        claude=health_of("anthropic"),
        gemini=health_of("gemini"),
        google=getattr(st, "google", None),  # GoogleConnector.status(uid)
        health=getattr(st, "health", None),  # HealthService.last(uid): the LAST stored report
        web=usage,  # TavilyProvider.usage(): the vendor's free usage report
        github=getattr(st, "github", None),  # GithubClient.status / .token_meta
        home=getattr(st, "home_store", None),  # HomeStore.status(uid)
        default_brain=brains.default.id,  # the brain the systems check's probe watches
    )


def wire_vitals(app: FastAPI, s: Settings, docs: Docs) -> VitalsService | None:
    ...
    return VitalsService(
        VitalsStore(docs, prefix=s.firestore_prefix),
        s,
        billing=app.state.billing,
        ledger=media.ledger if media is not None else None,
        allowances=voice_allowances(s),
        own=vitals_sources(app),
    )
```

What each item reads and when it shows:

| id | label | shown when | status from |
|---|---|---|---|
| `brain_claude` | Claude (paid AI) key | `Settings.anthropic_api_key` is set | `router.health()` state: refused = red; busy / odd / unreachable = amber; else ok |
| `brain_gemini` | Gemini (free AI) key | `Settings.gemini_api_key` is set | same; busy = "has reached its free limit for now" |
| `google_link` | Google sign-in | connected, or needs reconnecting | `GoogleConnector.status`: needs_reconnect = red |
| `telegram_bot` | Telegram bot | `Settings.telegram_bot_token` is set, and the last systems check included `telegram` (left out of it = not set up, D4) | that result (ok / degraded / down); no check stored yet, or one older than 2 hours = Unknown "run a systems check" |
| `web_credits` | Web search allowance | a web provider with `usage()` is wired | the vendor's free usage report, cached 10 min per process; exhausted = red; resets next month |
| `github_token` | GitHub token | connected, or needs reconnecting | the token's expiry and hourly limit from GitHub's own headers (below); a 401 from GitHub = red "the token was refused" (fix: "Paste a new token in Connectors"); an expiry header that can't be read = Unknown "its expiry date couldn't be read" |
| `home_link` | Home laptop link | a home is linked | heartbeat age vs `home_offline_after_s`: offline or never reported = red; degraded = amber |

Every item has fixed `impact` / `fix` words (`jarvis/vitals/words.py`), as do `ai_spend`, the voice
allowances and the Google SKU quotas. `google_link`, `telegram_bot`, `home_link` and the DEFAULT brain's
key never ring from Vitals (`Own.quiet_ids()`): the systems check and the home watchdog already ring
for them. The health check's brain probe reads only the default brain, so the OTHER brain's key
(e.g. Gemini refused while Claude is default) DOES ring from Vitals. Tell Vitals which brain is the
default with `OwnSources(default_brain=brains.default.id)` ("anthropic" or "gemini"); left None, both
brains ring (a double ring is better than a lost one).
`github_token` (expiry, hourly limit) and `web_credits` ring like any other item (amber at 80 %, red
at the limit / expiry). Each source has a 3 s deadline; a failing or slow one makes only its own item
"Unknown" (its error text never reaches the board).

**Out of credit (Anthropic):** the router can NOT tell it apart today. Anthropic's "credit balance is
too low" answer is an HTTP 400 `invalid_request_error`; `AnthropicProvider._translate` maps it to a
plain `LLMError`, and `ModelRouter._note_failure` records `"odd"`. So the Claude key shows amber
"answered oddly", never a specific "out of credit". Telling it apart needs a change in `jarvis.llm`
(a typed error, e.g. `LLMOutOfCredit`, and a `BrainState` such as `"no_credit"`); out of scope here,
not invented.

## 2. The GitHub token's facts (`integrations/github.py`, `integrations/github_meta.py`)

`GithubClient` now records, as clear fields beside the sealed token in
`{prefix}connectors_github/{uid}` (`meta`: `seen_at, expires_at, rate_limit, rate_used, rate_reset`),
what GitHub's response headers say: `GitHub-Authentication-Token-Expiration` (absent = the token
doesn't expire) and `x-ratelimit-limit / -used / -reset`. Written on connect, then on later reads when
the expiry changed or at most every 10 minutes (a transaction: a deleted record is never brought back).
No secret is in them; the token stays sealed and is never logged. `GithubClient(store, http=..., clock=time.time)`
-- the new `clock` keyword has a default, so `wire_github` needs no change. Tokens connected before
R5.1 show "Unknown -- JARVIS sees its limits the next time it reads GitHub" until the next GitHub tool call.

## 3. The console (`console.html`, `api/console.py`) -- D1, audit #14

- Link the stylesheet after the existing ones (after `console-alerts.css`, and after any Part A/C
  stylesheets):
  `<link rel="stylesheet" href="/static/console-vitals.css">`
- Serve it: add to `APP_ASSETS` in `src/jarvis/api/console.py`:
  `"console-vitals.css": "text/css",  # R5.1 B: the Vitals board (groups, chips, the add form)`
  (`tests/test_console_assets.py` checks every APP_ASSETS entry is served; add it to any CSS list there.)
- Move `<div id="vitals-board"></div>` up so it sits DIRECTLY AFTER the `#spend` section (before the
  `<div class="list">` of `.kv` rows), with its comment. Today it is two screens down.
- D10: remove `fixed-size` from `<section class="panel card fixed-size" id="p-vitals" ...>` so the panel
  can be resized both ways (the board reflows; nothing in it needs a fixed size). Optionally give the
  Vitals panel the Integrations default width (340) in `console-deck.js`.
- The board's script stays `console-vitals.js` (already linked).

The board no longer shows its own "AI spend" line or bar (the "This month" block above shows them);
the `ai_spend` item appears only when it is amber or red, pointing at "This month".

## 4. API shape (additive; nothing removed)

`GET /v1/vitals` and the `vitals_show` tool now also carry, per item, `impact`, `fix` (strings, may be
empty) and `group` (`keys | allowances | bills`), and at the top level `manual_unavailable` (bool) and
`manual_note` (a fixed line when true). The in-Python `ProviderView` has `.impact`, `.fix`, `.group`
(Part C's briefing reads `item.impact` / `item.fix` with getattr). `vitals_show` also returns
`spoken`: the board in fixed words (what No-AI mode reads out; at most 700 characters). New ids
(`brain_claude`, `brain_gemini`, `google_link`, `telegram_bot`, `web_credits`, `github_token`,
`home_link`) are reserved: a manual record can't take them (an old one that did is hidden from the board).

## 5. Deploy

`deploy/cloudrun.sh` (lines ~426-434, "R4 A (W15)") still creates the composite index
`jarvis_vitals_providers (user_id ASC, label ASC)`. It is no longer needed: the board never waits for
it. Keeping it is harmless (one unused index); removing those lines is the integrator's call
(`tests/test_deploy_config.py` does not mention it). Not edited here.

## 6. Persona (optional, D12)

"JARVIS keeps its own Vitals: every key and connection it uses is tracked automatically (Claude,
Gemini, Google, Telegram, web search credits, GitHub, the home laptop); the owner never types a key's
details. For things JARVIS can't see (an insurance renewal), use 'Track something JARVIS can't see'."


## 7. R5.1 B review fixes (what changed after review)

- **Create-only add:** `PUT /v1/vitals/keys` with `"create": true` answers 409 "That name is taken." when the id
  exists (a transaction in `VitalsStore.put(create=True)`); the panel sends it for a NEW item, reloads and
  retries once with the next suffix. Edit keeps the plain upsert. The `vitals_set_key` tool is unchanged (upsert).
- **GitHub token facts** (`integrations/github_meta.py`): `meta` gains `rejected_at` (a 401; cleared by the next
  200 or a reconnect) and `expiry_unreadable` (header present but not readable, or before 1970 / after 2100).
  An absent header still means "doesn't expire". Integers are ASCII digits only (<= 13 chars); an odd header
  drops only its own field. A failed meta write backs off 10 minutes; a per-owner generation drops facts from a
  read begun before a connect / disconnect.
- **Old manual records under a now-reserved id** are shown as manual with " (old)" appended to the label, can be
  stopped (their shared alert-status record is left alone), count toward the 50 cap visibly, and never alert.
- **`GET /v1/vitals`** is rate limited per owner (30 / minute, `app.state.vitals_limiter`, created on first use,
  so no wiring is needed) and the computed board is cached per owner for 15 s (`VitalsService.board_cached`,
  also used by the `vitals_show` tool; a save or stop drops the owner's cached board). Alerts always compute fresh.
- **Guard:** the id derived from the label is checked on its own (dashes read as word breaks) and glued to the
  note and unit, never to the label. Real key shapes in any field are still refused.
- **Label rename:** "Web search credits" is now "Web search allowance" (so the spoken line reads "is at 85%").

## 8. Scope of the process-wide items (D2 note)

`brain_claude`, `brain_gemini`, `web_credits` and `telegram_bot` describe the DEPLOYMENT (its keys, its Tavily plan,
its bot), not one owner, so every signed-in owner sees the same state. That is correct because a JARVIS
deployment is single-owner (access is gated by `owner_emails`). If a multi-owner deployment is ever added, gate
these four items on an operator flag first.
