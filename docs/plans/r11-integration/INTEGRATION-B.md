Version v11.0.0 · 11 Nov 2026, 18:55 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# R11 Part B · Home and outside: what I1 needs to know

Branch `r11-b` (from `r11-i0` @ `0e2aec7`). Items 2 (chores rota), 3 (home upkeep), 4 (weather from
Open-Meteo), 5 (disaster alerts from NDMA SACHET) and 6 (breach-notice watching) of
`docs/plans/r11-free-helpers.md`, built in Part B's own files only. No wiring file was edited.

## 1. What was built

| Item | Where | What it does |
|---|---|---|
| 2 Chores rota | `helpers/house/chores.py` | Daily, chosen weekdays or every N days, at his time; a rota of up to 6 adult labels whose turn moves on "done" and at each period's end. `chores_due` sends `chore_due` once (claim before send, released on `SendResult.retry`); the rota name only in `named`. |
| 3 Home upkeep | `helpers/house/upkeep.py` | Every N days or months (month ends clamp), lead days; `maint_due` at 09:00 on the lead day and the due day, once each. The starter list (D11) is offered, never added. |
| 4 Weather | `helpers/house/weather.py`, `fetch.py` | Open-Meteo for his point rounded to 0.01° (his own, or the district centre JARVIS knows for Kerala); his district's name never leaves JARVIS. Hourly and daily fields D12 names; values bounded; one `weather_warning` per kind per day (rain in an hour, rain in a day, apparent temperature, gusts); only when due (60 min; 15 min after an outage); the summary for the brief kept sealed. |
| 5 Disaster alerts | `helpers/house/sachet.py`, `cap.py` | His state's SACHET RSS (Kerala, Karnataka; the national feed otherwise) every 10 min with `If-None-Match`; each digits-only guid queued once, its CAP 1.2 fetched once from the fixed CAP URL (an item's own link is never followed). XML: stdlib ElementTree only after refusing a DOCTYPE or ENTITY, anything not UTF-8 and anything over the cap (256 KB CAP, 512 KB RSS). Actual + Public only; his district by area name and state, LGD code or polygon; D13's kinds (non-Met or Met Extreme `disaster_alert`, rings at night; Met Severe `weather_warning`, held at night; Met Moderate/Minor `weather_note`); claim per CAP identifier; an Update rings again only when it got worse; IMD nowcasts of the same event and kind within 3 h told once; Cancel says "lifted". Text is a fixed template from a fixed event word, his own district and the expiry. SACHET's words are kept sealed for the panel only. |
| 6 Breach notices | `helpers/house/breach.py` | Daily `breach_watch`: when he switched it on, and his Email (`gmail_*`) and outdoor (`breach_*`) rows allow it (fail closed): a Gmail search restricted to the fixed senders (HIBP `haveibeenpwned.com`, Mozilla Monitor `monitor.mozilla.org`), headers only (`format=metadata`), counted only when the From domain passes Gmail's own DKIM/DMARC alignment (`packages.carriers.authenticated`) and the subject is a notice, not a sign-up mail (a filter only: never stored, logged or sent). One fixed `breach_notice` per service, claims per message, a kind-only audit line (`helpers` / `breach_watch` / `breach_notice`). It also sweeps Part B's claims after 30 days. |

Shared pieces: `models.py` (pydantic, frozen), `store.py` (`chores/{uid}`, `maintenance/{uid}`,
`house_told/{uid}_{key}` claims of `{uid, tag, at}` only, `outside/{uid}` sealed with `alerts_place`,
AAD `outside/{uid}/v1`; no keyring: `OutsideOff`, nothing kept in clear), `guard.py` (his rows by
`Policy.decide`, fail closed; the audit line), `words.py` (every template), `service.py` (shared by
routes and tools), `tools.py`, `phrases.py`, `privacy.py`, `brief.py` (brief lines and the pending
source), `part.py`. Routes: `api/helpers_house.py`. Tab: `console-helpers-house.js`.

- **Tools** (families `chore_`, `maint_`, `weather_`, `disaster_`, `breach_`): R1 `chore_list`,
  `maint_list`, `maint_starters`, `weather_now`, `disaster_status` (SACHET's words fenced by
  `wrap_external`, not trusted output), `breach_status`; R2 `chore_add`, `chore_done`, `maint_add`,
  `maint_done` (card texts and fixed Activity words). Nothing R3; no tool sets his place.
- **Jobs**: clock `chores_due`, `maint_due`, `disaster_poll` (if `disaster_alerts_enabled`),
  `weather_poll` (if `weather_enabled`); daily `breach_watch`. Budgets 3, 3, 10 (soft deadline 9 s,
  each fetch ≤ 8 s), 9 s. An in-process `OutsideSlot` makes weather wait a run whenever SACHET
  fetched anything, so Part B uses one outside fetch window of the shared 20 s per run.
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
/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r11_b_*.py        # 102 tests
PYTHONPATH=src /tmp/venv-12/bin/python evals/r11_helpers/run.py --mock --part house
JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_b_house.py
```

The eval part `house` is BUILT (11 cases); its control (`cap.DISTRICT_FILTER = False`) fails it
(`another-district-ignored` and the two refused-CAP cases, whose other-district alert then rings).
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
3. **Optional CSS** (`console-helpers.css`, I0's): the tab borrows the Vitals form grid
   (`.vt-grid`, `.vt-field`). If I1 prefers helpers-owned names, add
   `.hp-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:end;gap:10px 8px;margin-top:10px}`
   `.hp-field{min-width:0}.hp-field.wide{grid-column:1/-1}` and
   `@media (max-width:899px){.hp-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}`, then rename
   the two classes in `console-helpers-house.js` (3 places). No visual change.
4. **No new dependency**: no defusedxml. The DOCTYPE / ENTITY / encoding / size refusals plus the
   bundled expat (2.6.1 here, ≥ 2.4.1 per D13) are enough; the security review should confirm.
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
   night; IMD "Severe" is held for the morning. Confirm this is what you want.
3. **Breach notices**: subscribe at haveibeenpwned.com/NotifyMe (and Mozilla Monitor if you like),
   then switch "Watch my Gmail" on. *Unverified until a real notice arrives*: HIBP's sender
   (`noreply@haveibeenpwned.com`, from HIBP's support page) and the subject words ("pwned",
   "breach"); Mozilla Monitor's sender domain (`monitor.mozilla.org`) is a guess. A wrong guess
   means no alert, never a false one; tell the builder if a notice was missed.
4. **SACHET feeds**: only `rss_kerala.xml`, `rss_karnataka.xml` and `rss_india.xml` were seen to
   exist (11 Nov 2026); other states read the national feed (all states' warnings, ~100 a day).
5. **Cloud Run egress** to `api.open-meteo.com` and `sachet.ndma.gov.in` (unverified from the
   build sandbox): after deploy, the Home tab should show "Open-Meteo: …, checked HH:MM" and
   "SACHET: warnings for <district>, checked HH:MM" within 10 minutes of setting the place.
6. **Kerala district centres** in `models.DISTRICT_CENTRES` are approximate (district
   headquarters, 0.01°); correct them if one looks off.

## 5. Results at the head of `r11-b` (11 Nov 2026)

| Check | Result |
|---|---|
| Part B tests, 3.12 / 3.11 (`tests/test_r11_b_*.py`) | 102 passed / 102 passed |
| Whole unit suite (3.12) | 10,894 passed, 107 skipped, **3 failed**: exactly the three I0 stub pins of §3.1 |
| Coverage of `src/jarvis/helpers/house/` (coverage.py, Part B's tests) | 95 % (1,714 statements) |
| ruff check + format (src tests evals scripts) | clean |
| mypy src | the 9 pre-existing errors only (anthropic_provider, window, redis_store) |
| `evals/r11_helpers/run.py --mock` | 22/22 (gate + house); control fails it (house: `district_filter_off`) |
| `evals/run_all_mock.py` | every suite passes and every control fails it (R11 not gated there until I1) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK, OK |
| Browser (`-k "helpers or dock or ui_audit or r11_b"`) | 155 passed (incl. `test_r11_b_house.py`: Night and Day, 1440x900 and 390x844, no JS error or CSP violation) |
| Function / module size | every function ≤ 50 lines, every module ≤ 400 (largest `sachet.py` 394) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.0 | 11 Nov 2026, 18:55 IST | R11 | Part B built: items 2-6, routes, tab, eval, browser test; Needs I1 and owner checks | 🛠 Mark XIV |
