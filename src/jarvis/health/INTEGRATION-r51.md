# R5.1 Part C: systems check experience + offline ring (what I1 wires)

Plan: `docs/plans/r5-1-observations.md` D3, D4, D5, D6, D7, D8 (D10 for the panel). No model call is
added anywhere; no new Scheduler job, secret or paid call. Everything below is wiring only: the
behaviour is built and tested in `jarvis.health`, `jarvis.home.watchdog` and the console files.

## 1. D3: the laptop going quiet always reaches the owner (`api/home_wiring.py`)

```python
offline = OfflineJob(
    store,
    notifier,
    camera.alarm,
    clock=clock,
    offline_after_s=s.home_offline_after_s,
    tz=tz,
    alert_when=s.home_offline_alert,  # R5.1 D3: "always" (default) | "armed_only"
)
```

Behaviour (`home/watchdog.py` docstring): armed is unchanged (`home_offline`, urgent). Disarmed with
`always` sends ONE `home_offline_idle` per outage ("Your home laptop stopped answering at 21:10. The
camera and home devices are off until it's back, Sir."). Only an alert that Telegram or a browser
took counts as told. A HELD alert (quiet hours: `Delivery(action="hold")`) also counts as told, so
the watchdog does not add one more "laptop offline" to the held summary every 5 minutes. A drop
because the owner switched the kind off, or set it to feed only, also counts as told. Any other
drop, such as a storm gap or nobody reachable, is tried again on the next run. The "back online"
note is the existing `home_online` from the heartbeat handler. It goes out only when an outage
alert had gone out.

Arming during an outage that was already told as idle (review fix 9): the urgent `home_offline` goes
out once on the next run, so "camera alerts are off" is never lost behind the earlier idle alert.
Armed then disarmed sends nothing more. The kind told is remembered inside the `OfflineJob`
instance (the stored flag is only a boolean and `home/store.py` is not part C's). Known limit: an
instance that never saw the idle alert (a restart, another Cloud Run instance) treats the outage as
settled, so it does not repeat an alert that may already have gone out. If that matters, give
`HomeStore.mark_offline` a `kind` and read it back in `HomeStatus`.

## 2. D4: one shared systems-check job on the tick AND the 5-minute watchdog

The tick and the watchdog must share the SAME `HealthTickJob` instance: its per-owner 15-minute gate
lives on the instance, so the two runners never check one owner twice. The watchdog is built during
home wiring, which runs before `wire_r4` builds the health service. That is why `Watchdog.extend(job)`
exists: it adds the job later and refuses a name that is already in the list. In `api/r4_wiring.py`:

```python
def r4_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    ...
    if getattr(st, "health", None) is not None:
        from jarvis.health.tick import HealthTickJob

        job = getattr(st, "health_job", None)
        if job is None:  # built once: the tick and the watchdog share its per-owner gate
            job = st.health_job = HealthTickJob(st.health)
            if getattr(st, "home_watchdog", None) is not None:
                st.home_watchdog.extend(job)  # R5.1 D4: around the clock, every 5 minutes
        jobs.append(job)
```

(`_tick_jobs` in `api/app.py` may be called more than once. The `health_job` guard makes sure the
watchdog gets the job only once, because `extend` raises on a duplicate name.) Add `"health_job"` to
`R4_STATE` so it starts as None. Cadence: `CHECK_EVERY_S = 900`. The watchdog runs only for owners
with a linked home. Owners without one keep the morning tick and the on-demand check. The `home`
probe never sends `health_fault` / `health_degraded` / `health_recovered` (`changes.WATCHED_ELSEWHERE`).
It still appears in the report and the briefing, so there is no double ring with `home_offline*`.
The watchdog's `budget_s` stays 30 s per job. `HealthTickJob` keeps its own 40 s deadline under the
tick's 60 s cap.

## 3. D4: Telegram that is not set up is left out (`health_probes` in `api/r4_wiring.py`)

```python
    if (tg := getattr(st, "telegram", None)) is not None:  # no bot token -> no probe at all

        async def paired(uid: str) -> bool:  # a paired chat for THIS owner
            return await tg.store.get(uid) is not None

        probes.append(P.telegram_probe(tg.client, configured=paired))
```

Not paired: the probe answers None ("not set up", left out of the report). getMe answering HTTP 401
or 404: down, "the bot token was refused". Network trouble or a timeout: down, "Telegram could not
be reached". Anything else: down, "Telegram refused the check".

## 4. D5: the briefing reads Vitals (`wire_health` in `api/r4_wiring.py`)

```python
    return HealthService(
        health_probes(app, s, docs, mode),
        HealthStore(docs, prefix=s.firestore_prefix),
        notifier=_notifier(app),
        voice=getattr(app.state, "voice", None),
        vitals=getattr(app.state, "vitals", None),  # R5.1 D5 (built just before, in wire_r4)
    )
```

`VitalsService.board(uid)` matches `health.service.VitalsReader`. A board that fails or takes longer
than 5 s never fails the check: the briefing then says "Vitals can't be read just now." The briefing
reads Part B's `impact` / `fix` attributes on the items with `getattr`. It falls back to its own
fixed map when they are missing.

## 5. D7 / D5: `LiveHealth` gains the two new methods (`api/r4_wiring.py`)

`health_router` treats both as optional. Without `check_stream`, `POST /v1/health/run/stream`
answers 404 and the console falls back to `/v1/health/run`. Without `briefing`, the briefing has no
vitals. Add both:

```python
from collections.abc import AsyncIterator
from jarvis.health.briefing import Briefing


class LiveHealth:
    ...

    async def briefing(self, uid: str, report: HealthReport | None) -> Briefing:
        return await self._svc().briefing(uid, report)

    def check_stream(self, uid: str, *, force: bool = False) -> AsyncIterator[dict[str, Any]]:
        return self._svc().check_stream(uid, force=force)  # 503 before the service exists
```

## 6. D7 / D8: the routes (no change to `install_r4_routes`)

These are mounted by the same `health_router(LiveHealth(app), user=current_user,
dependencies=[Depends(require_auth)])` call:

- `POST /v1/health/run/stream` takes `{force?: bool}` and answers `application/x-ndjson`: a `plan`
  event, then one `result` event per system as it completes (`status: "skipped"` for a system that is
  not set up), then `done` (the `/run` shape plus `briefing`). If the check fails, the last event is
  `{"type":"error","detail":"The check did not complete."}`. Runs are coalesced per owner: a
  stream asked for while one is in flight attaches to it (the events so far, then the live ones),
  so a forced pop-up can never queue a second full check. A run takes at most 4 listeners; the
  next gets 429 `check_running` ("A check is already running, Sir. Wait a moment."). Every run has
  a 45 s total deadline (`CHECK_DEADLINE_S`): a probe still unfinished ends as down, "did not
  answer in time", and `done` still arrives. `LiveHealth.check_stream` must stay a plain method that
  returns the iterator (not an `async def`): `HealthService.check_stream` raises `CheckBusy`
  synchronously, and the route turns that into the 429.
- `POST /v1/health/remind` takes `{key, when: "1h"|"evening"|"tomorrow", session_id?}` and answers
  `{outcome: executed|awaiting_confirmation|refused, line}`. It reads `app.state.gateway`,
  `app.state.google` and `app.state.settings.user_timezone` live, so no wiring is needed. A key that
  is not one of the last check's concerns gets 422.
- run, run/stream, speak and remind share one per-owner budget of 10 per minute, inside the router.
  `require_auth` brings the cookie CSRF header rule (`X-Requested-With: JARVIS`) to every POST.

Scope for the reminder: there is no existing "console scope" in the code. The pop-up sends the
console's open conversation (`JarvisApprovals.session()`), and the route uses `<uid>:<session_id>`
only when the id is one of the owner's stored conversations (`app.state.store.get(id).user_id ==
uid`; the literal `console`, another owner's id, an unknown id, or no `app.state.store` all count
as no conversation), so a card raised by the owner's "Ask first" setting can be approved in
Approvals. Without a conversation the scope is `<uid>:console`. No card in that scope could ever be approved
(`Brain.approve` needs the session), so the route withdraws such a card at once
(`gate.cancel(id)`) and answers "Reminders ask first in your settings, Sir. Ask me in the chat and
I'll set it." The call runs inside `turn_budget()` and `context_trust(...)`. The text is JARVIS's
fixed label and consequence, for example "Fix Telegram: alerts and Telegram chat won't reach you".
Trust (review fix 2): owner-trusted (`untrusted=False`) only when every word is fixed in code: the
probe keys, and the automatic Vitals ids in `remind.VITALS_WORDS` (`brain_claude`, `brain_gemini`,
`google_link`, `telegram_bot`, `web_credits`, `github_token`, `home_link`, `ai_spend`, `quota_*`,
`allowance_*`). Any other `vitals.<id>` item (owner-typed, label is free text) runs with
`untrusted=True`, so the gateway asks for approval and the event is never stored as the owner's own
words. The same reminder (owner, key, time choice) inside 10 minutes answers "Already set, Sir."
with no second tool call (in-memory, per process; a refused attempt does not count).

## 7. `spoken` vs the briefing (decision)

- HTTP `/v1/health` and `/v1/health/run`: `spoken` stays the R4 one-liner ("Attention: Telegram is
  not answering."), for compatibility with older clients and because alerts use the same line. The
  full briefing is `briefing.spoken`. `briefing` also has `lines` (every sentence, uncapped),
  `concerns` (`{key, label, severity, impact, fix}`) and `spend` (the vitals sentence on its own).
- The `systems_check` tool: `spoken` is now the FULL briefing, so the voice, the AI and the no-AI
  router all read it as given. `headline` is the one-liner, and `concerns` is a list. The tool
  description says to read `spoken` aloud as given.

## 8. Console (`console.html`, `api/console.py`, `console.js`)

- `api/console.py` `APP_ASSETS`: add
  `"console-systems-modal.js": _JS,  # R5.1 C: the systems-check pop-up (ticks, briefing, reminder)`,
  `"console-systems-voice.js": _JS,  # R5.1 C: its phrases, speech and echo guard` and
  `"console-systems.css": "text/css",  # R5.1 C: Systems card + pop-up`. Also update the
  lists in `tests/test_console_assets.py` if they enumerate assets.
- `console.html`: add `<link rel="stylesheet" href="/static/console-systems.css">` after the last
  stylesheet link (after Part A's and B's new ones). Add
  `<script src="/static/console-systems-voice.js" defer></script>` and
  `<script src="/static/console-systems-modal.js" defer></script>` next to
  `console-systems.js`. The order doesn't matter: they look each other up when they are used
  (without the voice file the pop-up still works, silently, and `matches()` never matches).
- D10: remove `fixed-size` from `<section class="panel card fixed-size" id="p-integrations" ...>` so
  the Integrations panel (with the Systems card) can be resized both ways.
- The composer hook (typed "run a systems check" opens the pop-up with no AI call). In
  `console.js`, in the `$('form').addEventListener('submit', ...)` handler, add this right after
  `const t = input.value.trim(); if (!t || state.busy) return;`:

```js
    const SC = window.JarvisSystemsCheck; // R5.1 D6: typed or dictated "run a systems check" -> the pop-up, no AI call
    if (SC && SC.matches(t, { typed: true })) { // typed mode: the WHOLE message must be the phrase
      delete input.dataset.channel; input.value = ''; autosize(); syncSend();
      SC.open({ via: 'typed', opener: $('send') }); return;
    }
```

  `matches(t, {typed: true})` accepts only a message that is wholly "run a systems check", "run a
  system check", "run (a) system(s) check", "systems check", "system check", "system status",
  "systems status" or "run diagnostics", with an optional "jarvis," or "hey jarvis" in front and
  only ending punctuation (. ! ?) after. It does not accept "check my systems design doc", "system
  status of the order" or anything with extra words. Do NOT call `matches(t)` without the option on
  typed text: that is the voice matcher (see below).
- The voice command is already in `console-voice-commands.js` (`systems.check`, registered after
  the built-ins; not offered while JARVIS is speaking). Voice keeps the full-utterance matcher, but
  bare "system status" / "systems status" needs "Jarvis" in front (it is too common in talk). The
  command is also refused by `JarvisSystemsCheck.canHear()` while the pop-up speaks, for 2 s after
  any speech of its own ends, and for words that are mostly what it just said (the same
  `JarvisBarge.isEcho` the mic loop uses). The real speaker fires its `chunk` event for every
  line the pop-up says, which the mic loop already records as JARVIS's own words, so nothing more
  is wired. The closing line, "Closing this window, Sir. Whenever you'd like a fresh check, just
  ask and I'll update the status.", contains no trigger phrase. Optional: add "run a systems check" and
  "system status" to `voice/commands.py` `COMMAND_HINTS` as speech hints. `tests/test_r5_seams.py`
  ties the hints to the PHRASES table, so add them to the table as well, or leave them out.
- `scripts/ui_snapshots.py`: the card's "Run check" button now opens the pop-up. Before the
  Integrations panel shot, press Escape or click `#sysCheckClose`. Mock
  `**/v1/health/run/stream` with an NDJSON body (see `tests/browser/test_systems_check.py`
  `stream_body()`) and add pop-up shots (`#sysCheck`). The pop-up's top and foot are sticky. To
  check overlaps on its flowed layout, set `#sysCheck` `maxHeight = 'none'` first, as the browser
  test does.

## 9. Persona (p5.1, D12)

Suggested line: "Run a systems check opens the systems-check pop-up and I brief you on every system,
what is broken and what that breaks, your AI spend and anything expiring, then offer a reminder.
It works with the AI switched off."
