Version v11.0.1 · 11 Nov 2026, 20:46 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# R11 Part B · Home and outside: what I1 needs to know

Branch `r11-b` (from `r11-i0` @ `0e2aec7`). Items 2 (chores rota), 3 (home upkeep), 4 (weather from
Open-Meteo), 5 (disaster alerts from NDMA SACHET) and 6 (breach-notice watching) of
`docs/plans/r11-free-helpers.md`, built in Part B's own files only. No wiring file was edited.

## 1. What was built

| Item | Where | What it does |
|---|---|---|
| 2 Chores rota | `helpers/house/chores.py` | Daily, chosen weekdays or every N days, at his time; a rota of up to 6 adult labels whose turn moves once per occurrence on "done" (a second "done" in the same period changes nothing) and at each period's end. A chore added after its time today starts next period (never "late"). `chores_due` sends `chore_due` once (a leased claim before send, released on `SendResult.retry`); the rota name only in `named`. |
| 3 Home upkeep | `helpers/house/upkeep.py` | Every N days or months (month ends clamp), lead days; `maint_due` at 09:00 on the lead day and the due day, once each. The starter list (D11) is offered, never added. |
| 4 Weather | `helpers/house/weather.py`, `fetch.py` | Open-Meteo for his point rounded to 0.01° (his own, or the district centre JARVIS knows for Kerala); his district's name never leaves JARVIS. Hourly and daily fields D12 names; values bounded; one `weather_warning` per kind per day (rain in an hour, rain in a day, apparent temperature, gusts); only when due (60 min; 15 min after an outage), in weather's own slot of the run (never waits for SACHET); the summary for the brief kept sealed. |
| 5 Disaster alerts | `helpers/house/sachet.py`, `feed.py`, `night.py`, `cap.py`, `xmlsafe.py` | His state's SACHET RSS (Kerala, Karnataka; the national feed otherwise) every 10 min with `If-None-Match` (only a printable-ASCII ETag of ≤ 200 characters is kept; a 304 without one keeps the old); each digits-only guid queued once, its CAP 1.2 fetched from the fixed CAP URL (an item's own link is never followed). A CAP that refuses (non-200) backs off (5 min doubling to 1 h) and the queue goes on; it ages out after 5 refusals or a day. A host that doesn't answer is an outage (`cap_fail_since`) until a CAP reads. XML in two layers (`xmlsafe`): strict UTF-8 bytes (no NUL, no BOM but UTF-8's, no other declared encoding, no `<!DOCTYPE`/`<!ENTITY`), then stdlib expat with every DTD handler raising; size capped (256 KB CAP, 512 KB RSS), 5,000 elements. Actual + Public only; his district by area name (the whole `areaDesc`, up to 4 KB, never shown) and state, LGD code or polygon (over 2,000 points: rejected); D13's kinds (non-Met or Met Extreme `disaster_alert`, rings at night; Met Severe `weather_warning`, held at night; Met Moderate/Minor `weather_note`); leased claims per CAP identifier and, for `disaster_alert`, per content key (kind, event word, district, onset day); at night at most 3 urgent rings, then one held morning summary and at most one "more alerts, open the SACHET app" ring an hour; an Update rings again only when it got worse; IMD nowcasts of the same event and kind within 3 h told once; Cancel (with or without an info block) says "lifted"; a warning without `expires` lapses after 24 h. Text is a fixed template from a fixed event word, his own district and the expiry. SACHET's words are kept sealed for the panel only. |
| 6 Breach notices | `helpers/house/breach.py` | Daily `breach_watch`: when he switched it on, and his Email (`gmail_*`) and outdoor (`breach_*`) rows allow it (fail closed): a Gmail search restricted to the fixed senders (HIBP `noreply@haveibeenpwned.com`, Mozilla Monitor at the exact host `monitor.mozilla.org`; no subdomains), headers only (`format=metadata`), counted only when the first Authentication-Results is Gmail's own (authserv-id `mx.google.com`) and passes DKIM/DMARC alignment for the From domain (`packages.carriers.authenticated`) and the subject is a notice, not a sign-up mail (a filter only: never stored, logged or sent). One fixed `breach_notice` per service, claims per message, a kind-only audit line (`helpers` / `breach_watch` / `breach_notice`). It also sweeps Part B's claims after 30 days. |

Shared pieces: `models.py` (pydantic, frozen), `store.py` (`chores/{uid}`, `maintenance/{uid}`,
`house_told/{uid}_{key}` claims of `{uid, tag, at, sent}` only, with a 15-minute lease: one never
marked sent is taken again after it, a send that raises or is cancelled releases it; a claim kept
without `sent` counts as sent), `outside/{uid}` sealed with `alerts_place`,
AAD `outside/{uid}/v1`; no keyring: `OutsideOff`, nothing kept in clear), `guard.py` (his rows by
`Policy.decide`, fail closed; the audit line), `words.py` (every template), `service.py` (shared by
routes and tools), `tools.py`, `phrases.py`, `privacy.py`, `brief.py` (brief lines and the pending
source), `part.py`. Routes: `api/helpers_house.py`. Tab: `console-helpers-house.js`.

- **Tools** (families `chore_`, `maint_`, `weather_`, `disaster_`, `breach_`): R1 `chore_list`,
  `maint_list`, `maint_starters`, `weather_now`, `disaster_status` (SACHET's words fenced by
  `wrap_external`, not trusted output), `breach_status`; R2 `chore_add`, `chore_done`, `maint_add`,
  `maint_done` (card texts and fixed Activity words). Nothing R3; no tool sets his place.
- **Jobs**: clock `chores_due`, `maint_due`, `disaster_poll` (if `disaster_alerts_enabled`),
  `weather_poll` (if `weather_enabled`); daily `breach_watch`. Budgets 3, 3, 8 and 6 s. An
  in-process `fetch.OutsideClock` gives Part B at most 12 s of the shared 19 s per run, in two
  separate slots that take their turns: SACHET 7 s (its RSS and CAPs, each fetch with what is
  left of the slot, ≤ 8 s), then weather 5 s. A SACHET outage or backlog spends only SACHET's
  slot, so weather is fetched whenever it is due (code review H1).
- **Privacy**: `helpers_house` (confirm; chores, upkeep and their claims) and `helpers_place`
  (simple, encrypted by JARVIS; place, thresholds, breach watch, feed bookkeeping and the active
  warnings' words; delete also drops the weather / CAP / breach claims).
- **No-AI** (anchored, Part B's own words; "done" needs the word "chore" or "upkeep"): chores list,
  "<x> chore done", upkeep list, "mark the <x> upkeep done", weather, disaster / weather warnings,
  breach notices.
- **Brief**: "house" (today's chores without rota names; upkeep due soon, today or overdue) and
  "outside" (active SACHET warnings, gravest first; the weather line with Open-Meteo's CC BY 4.0
  attribution; SACHET's outage). **Pending**: overdue / due / soon upkeep and today's chores.
- **Tab**: chores (adults-only line), upkeep with starters, his place (official SACHET app, SMS and
  cell broadcast first; each feed's outage; SACHET's words labelled "From SACHET:"), breach watch.
  Existing components only (`.btn.bact`, `.minput`, `label.k`, `.vt-grid` / `.vt-field`, `.lrow`,
  `.lerr`, `.bsw`), `textContent` only, ASCII.

## 2. How to check it

```
/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r11_b_*.py        # 143 tests
PYTHONPATH=src /tmp/venv-12/bin/python evals/r11_helpers/run.py --mock --part house
JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_b_house.py
```

The eval part `house` is BUILT (11 cases); its control (`cap.DISTRICT_FILTER = False`) fails it
(`another-district-ignored`: the Kollam flood warning then rings for him). The fixture
`b_cap_other_district.xml` is a flood since the reviews: as a landslide it is now the same warning
as his own (the content key), so the control would ring nothing new.
Results at the head of `r11-b` are in §5.

## 3. Needs I1 (exact diffs; nothing here was edited by B)

1. **`tests/test_r11_wiring.py` pins every part as an I0 stub.** With B built, three I0 tests fail
   by design (every builder's part does this). Proposed, once all four parts are merged:

   ```diff
   @@ test_the_helpers_start_with_four_empty_parts_and_both_composites
   -        assert {p.ready for p in st.r11_parts.values()} == {"not built yet"}
   +        assert "setup failed" not in {p.ready for p in st.r11_parts.values()}
   +        assert st.r11_parts["house"].ready.startswith("Chores and upkeep on")
   -        assert isinstance(st.helpers_clock, Composite) and st.helpers_clock.job_names == ()
   -        assert st.helpers_daily.job_names == ("helpers_sweep",)
   +        assert isinstance(st.helpers_clock, Composite)
   +        assert {"chores_due", "maint_due", "disaster_poll", "weather_poll"} <= set(
   +            st.helpers_clock.job_names
   +        )
   +        assert "breach_watch" in st.helpers_daily.job_names
   +        assert st.helpers_daily.job_names[-1] == "helpers_sweep"
   @@ test_a_parts_phrase_answers_in_no_ai_mode_through_its_tool
   -        assert a.state.brain_mode.phrases == (phrase,)
   +        assert phrase in a.state.brain_mode.phrases
   @@ test_the_four_part_routers_are_stubs_under_their_own_prefix
   -        assert module.PREFIX == f"/v1/helpers/{part}" and module.router.routes == []
   +        assert module.PREFIX == f"/v1/helpers/{part}"
   +        assert all(r.path.startswith(module.PREFIX) for r in module.router.routes)
   ```
   (B's routes: 10 under `/v1/helpers/house`. The no-AI test still proves C's phrase is reached:
   no B phrase matches "don't remind me to stand up".)
2. **Guide card C60** (`docs/architecture/JARVIS-Architecture.md`): Part B is built. Proposed
   "What it does" addition: "Built (R11 B): the chores rota and home upkeep with reminders once at
   their time; weather from Open-Meteo for your rounded point; NDMA SACHET disaster and weather
   warnings for your district (urgent ones ring at night, IMD "Severe" waits for the morning);
   breach notices from your own Gmail (HIBP / Mozilla Monitor senders, DKIM/DMARC-aligned)." In
   "Data it keeps", drop PLANNED for `chores/{uid}`, `maintenance/{uid}`, `house_told/{uid}_{key}`
   (hashes only, 30 days) and `outside/{uid}` (sealed with `alerts_place`). "When it fails": "a feed
   that is down shows since when (Open-Meteo, SACHET); weather and alerts are off without the token
   key". No new module, collection, host or console file outside what C60 already lists.
3. **Helpers-owned form CSS** (code review L5; `console-helpers.css` is I0's). The tab borrows
   the Vitals form grid (`.vt-grid`, `.vt-field`), so it depends on `console-vitals.css` being
   loaded, misses its `.vt-form`-scoped rules (select padding, option colours, `.lrow` wrap,
   `.lerr` margin) and picks up its phone rule that makes a 5th field full-width. Proposed, in one
   I1 commit with the matching rename in Part B's JS:

   ```diff
   --- a/src/jarvis/api/static/console-helpers.css
   +++ b/src/jarvis/api/static/console-helpers.css
   @@ (after the .hp-note rules)
   +/* the parts' forms (R11 B, Home): labels above inputs, 3 columns, 2 on phones */
   +.hp-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:end;gap:10px 8px;margin-top:10px}
   +.hp-field{min-width:0}
   +.hp-field.wide{grid-column:1/-1}
   +.hp-field label{display:block;margin-bottom:6px;cursor:pointer}
   +.hp-form select.minput{padding:0 8px;cursor:pointer}
   +.hp-form select.minput option{background:var(--well);color:var(--ink)}
   +.hp-form .lerr{margin-top:8px}
   +.hp-form .lrow{flex-wrap:wrap;gap:8px;margin-top:12px}
    @media (max-width:899px){.hp-tab{font-size:12px;letter-spacing:.08em}}
   +@media (max-width:899px){.hp-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
   --- a/src/jarvis/api/static/console-helpers-house.js
   +++ b/src/jarvis/api/static/console-helpers-house.js
   -    const w = mk('div', 'vt-field' + (wide ? ' wide' : ''));
   +    const w = mk('div', 'hp-field' + (wide ? ' wide' : ''));
   -    const f = mk('form', '');
   +    const f = mk('form', 'hp-form');
   -    const grid = mk('div', 'vt-grid');
   +    const grid = mk('div', 'hp-grid');
   ```
   (and `.vt-grid / .vt-field` -> `.hp-grid / .hp-field` in the file's header comment). Only
   existing tokens; the 44 px phone height of `.minput` already comes from `console-memory.css`.
4. **No new dependency**: no defusedxml. Security review M1 showed the text check alone was not
   enough (BOM-less UTF-16 reached expat's own encoding detection); `xmlsafe` now refuses at the
   byte layer AND in the parser (every DTD handler raises), with the bundled expat (2.6.1 here).
5. **A job can't see what is left of the shared clock budget** (code review M3). `ticks.run_jobs`
   gives each job `min(budget_s, what is left)` under `asyncio.timeout`, but the job can't read
   that value, so Part B bounds itself (`fetch.SHARE_S` = 12 s of the 19 s, in two slots) and
   leases its claims so a cut run loses nothing. Proposed, so each part can stop starting work it
   can't finish (`ticks.py` is outside Part B):

   ```diff
   --- a/src/jarvis/ticks.py
   +++ b/src/jarvis/ticks.py
   @@
    import asyncio
   +import contextvars
    import math
   @@
    JobResult = Literal["ok", "failed"]
   +# The monotonic time the running job must finish by (its budget, or what is left of the tick's);
   +# None outside `_run_one`. Nested runs (a composite's own jobs) set and reset it in turn.
   +_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("tick_deadline", default=None)
   +
   +
   +def time_left() -> float | None:
   +    """Seconds the running tick job has left, or None when no tick job is running."""
   +    at = _DEADLINE.get()
   +    return None if at is None else at - time.monotonic()
   @@ async def _run_one(
        budget = min(budget, remaining_s)
   +    token = _DEADLINE.set(time.monotonic() + budget)
        try:
            async with asyncio.timeout(budget):
                counts = await job.run(owners)
        except TimeoutError:
            log.error("tick job timed out", extra={"job": name, "budget_s": budget})
            return "failed"
        except Exception as exc:  # noqa: BLE001 - a job never fails the tick
            log.error("tick job failed", extra={"job": name, "error": type(exc).__name__})
            return "failed"
   +    finally:
   +        _DEADLINE.reset(token)
   @@ __all__
   +    "time_left",
   ```
   Then Part B's follow-up (B's own file, after I1): in `OutsideClock.deadline`, take
   `min(<slot end>, self._clock() + left - 0.5)` when `ticks.time_left()` gives a `left`.
5. **Fixture names**: the plan's `sachet_rss.xml`, `cap_*.xml`, `open_meteo_*.json`,
   `breach_*.eml` are `tests/fixtures/r11/b_*` (BRIEF-COMMON's prefix rule); the Gmail ones are
   the Gmail API's JSON (`b_gmail_*.json`), which is what the reader parses.
6. **Needles (I1's `r11_needles`)**: SACHET's headline and instruction are kept ONLY inside the
   sealed `outside/{uid}` blob (for the panel) and in `disaster_status`'s fenced output; the scan
   must treat a sealed blob as opaque. Rota labels are his own words and do appear in
   `chores/{uid}` (plain, by the plan's data model).

## 4. Owner checks (after deploy)

1. **His place**: Helpers → Home → type the district as official warnings write it (e.g.
   "Ernakulam"), pick the state; Kerala districts get their centre automatically, elsewhere add
   the latitude and longitude (rounded to about 1 km). Optional LGD district code for an exact
   match. Weather and disaster alerts stay off until then (owner default 11).
2. **Night rule** (owner default 10): urgent SACHET warnings (non-Met, or Met Extreme) ring at
   night; IMD "Severe" is held for the morning. At most 3 different urgent warnings ring a night
   (23:00-06:30); more fold into one morning summary plus at most one "more alerts, open the
   SACHET app" ring an hour, and the same warning under new identifiers rings once. Confirm.
3. **Breach notices**: subscribe at haveibeenpwned.com/NotifyMe (and Mozilla Monitor if you like),
   then switch "Watch my Gmail" on. *Unverified until a real notice arrives*: HIBP's sender
   (`noreply@haveibeenpwned.com`, from HIBP's support page) and the subject words ("pwned",
   "breach"); Mozilla Monitor's sender host (`monitor.mozilla.org`, exact: no subdomain) is a
   guess. A wrong guess means no alert, never a false one; tell the builder if a notice was missed.
4. **SACHET feeds**: only `rss_kerala.xml`, `rss_karnataka.xml` and `rss_india.xml` were seen to
   exist (11 Nov 2026); other states read the national feed (all states' warnings, ~100 a day).
5. **Cloud Run egress** to `api.open-meteo.com` and `sachet.ndma.gov.in` (unverified from the
   build sandbox): after deploy, the Home tab should show "Open-Meteo: …, checked HH:MM" and
   "SACHET: warnings for <district>, checked HH:MM" within 10 minutes of setting the place.
6. **Kerala district centres** in `models.DISTRICT_CENTRES` are approximate (district
   headquarters, 0.01°); correct them if one looks off.

## 5. Results at the head of `r11-b` (11 Nov 2026, after the review fixes)

| Check | Result |
|---|---|
| Part B tests, 3.12 / 3.11 (`tests/test_r11_b_*.py`) | 143 passed / 143 passed |
| Coverage of `src/jarvis/helpers/house/` (coverage.py, Part B's tests) | 96 % (2,041 statements) |
| ruff check + format (src tests evals scripts) | clean |
| mypy src | the 9 pre-existing errors only (anthropic_provider, window, redis_store) |
| `evals/r11_helpers/run.py --mock --part house` | 11/11; control fails it (`another-district-ignored`) |
| The reviewers' probes (scratchpad `p/probe1-5.py`, `test_flood_probe.py`, `probe_b.py`, `test_probe_b.py`) | every unsafe XML refused (BOM-less UTF-16 too); a non-ASCII ETag is a local error, never stored; forged / subdomain senders refused; 60 mutated identifiers ring once (was 60); weather fetched through a SACHET outage (deferred 0 of 12 runs, was 12); a 404 CAP no longer blocks the queue (3 sent at once, was 0 in 6 runs); a double "done" moves the turn once; a late-added chore sends nothing; a 304 without ETag keeps it |
| Function / module size | every function ≤ 50 lines, every module ≤ 400 (largest `weather.py` 351) |
| Whole unit suite, browser tests | not re-run for this round (shared machine); the first round's results stand: 10,894 passed with the 3 I0 stub pins of §3.1, browser 155 passed |

## 6. The review findings (security and code reviews of `fe5ac8b`)

| Finding | Status |
|---|---|
| Sec M1 DTD past BOM-less UTF-16 | Fixed: `xmlsafe` two layers (bytes: strict UTF-8, no NUL, no other BOM, no other declared encoding, no DOCTYPE/ENTITY; parser: expat with every DTD handler raising). RSS too. |
| Sec M2 non-ASCII ETag | Fixed: only printable ASCII ≤ 200 kept; `BadRequest` (a local error) clears it and the next run reads without it, never "unreachable"; a refusal clears it too. Code L1 (304 without ETag keeps it): fixed. |
| Sec M3 night rings with mutating identifiers | Fixed: content key (kind, event word, district, onset day) for `disaster_alert`; at night 3 rings, then one held summary and one "more" ring an hour. Met kinds keep the 3-hour nowcast rule. |
| Sec L1 authserv-id, L2 sender subdomains, L3 polygon cut, L4 no `expires` | Fixed (`mx.google.com` first header; exact hosts; rejected over 2,000 points; lapses after 24 h, in the job and the brief). |
| Code H1 weather starved | Fixed: separate slots (`OutsideClock`); 12-tick outage test. |
| Code H2 poison CAP | Fixed: backoff, the queue goes on, ages out after 5 refusals or a day. |
| Code M1 double "done", M2 late-added chore, M4 `areaDesc` cut, M5 CAP outage | Fixed (M5 shown in the tab and the brief). |
| Code M3 claim left by a cut run | Fixed: 15-minute lease; a raised or cancelled send releases its claim; slots keep SACHET inside Part B's share. Reading the real remaining budget needs I1 (§3.5). |
| Code L2 Cancel without info, L4 place form clobbered, L6 hints, L7 brief outages, L8 card / 120 / `RANK`, L9 bad zone | Fixed. |
| Code L5 borrowed `.vt-grid` / `.vt-field` | Left for I1: §3.3 (I0's CSS file). |
| Code L10 upkeep sent only on the lead day and the due day | Left: as the plan says ("first run at or after due" within the day); an overdue item stays in the brief and in pending. |
| Code L11 missing tests | Added: 29 Feb, 304 without ETag, long `areaDesc`, the slot per run (`no_time`). Left: a queue over 200 (the slice bounds it; low value). |
| Sec M3 extra "drop a CAP whose `sent` is stale" | Left: the RSS item's own age (a day) and `expires` already bound it; a long-lived warning can be re-sent late with an old `sent`. |
| Sec L4 note: same-named district in another state on the national feed | Left by design (fail-open: a spurious urgent alert beats a missed one); naming his state avoids it. |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.0 | 11 Nov 2026, 18:55 IST | R11 | Part B built: items 2-6, routes, tab, eval, browser test; Needs I1 and owner checks | 🛠 Mark XIV |
| v11.0.1 | 11 Nov 2026, 20:46 IST | R11 | The review fixes (two-layer XML, safe ETags, night cap and content key, outside slots, CAP backoff, claim lease, chores M1/M2, LOWs); Needs I1 §3.3 CSS diff and §3.5 `ticks.time_left`; §6 the findings | 🛠 Mark XIV |
