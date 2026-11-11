Version v11.0.1 · 11 Nov 2026, 23:30 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# INTEGRATION-C — R11 Part C: Nudges (items 8, 9, 11, 12 and the focus nudge of 10)

Branch `r11-c` (from `r11-i0` @ 0e2aec7). Plan: `docs/plans/r11-free-helpers.md` D1, D3–D6, D9, D12,
D16–D21; contract: `docs/plans/r11-integration/BRIEF-COMMON.md`. No wiring file, no I0 core file and no
other part's file was edited.

## What was built

| Item | What it does | Where |
|---|---|---|
| 8 Stand-up | "Time to stand up and move for a few minutes, Sir." every N minutes after his window opens (default every 60, 09:30–18:30, Mon–Sat, OFF): 10:30 … 17:30, eight a day, inside the default cap of 8. The **meeting variant** (owner decision 1, OFF): "Your stand-up starts in 10 minutes, Sir." from a calendar event whose title holds his word ("stand-up", "standup" and "stand up" all match); the title is matched in code, never sent. It has its own switch: it works with the move nudge off; "stop … for good" switches both off. | `helpers/nudges/standup.py` |
| 9 Water | "Time for a glass of water, Sir." every 90 min, same window (11:00, 12:30, 14:00, 15:30, 17:00). His log (glasses, stand-ups) is sealed (`wellbeing`); no keyring → the log says it is off, the reminders still work. | `hydrate.py`, `store.py` |
| 11 Missed activity | An event only he wrote (`provenance.is_owner_authored_event`) whose title holds one of his activity words (default walk, gym, yoga, run): 15 min after it ends, with no check-in, JARVIS asks **once**: "Your walk at 17:00 has no check-in yet, Sir. Did it happen? Say 'walk done', 'missed my walk' or 'moved my walk'." Check-ins and the ask are sealed, kept by a fingerprint of the event id, never its title. Off without a keyring. | `activity.py` |
| 12 Free time | Plain code (D1): the gap until his next event (any event; never past the window), an idea from **his** list that fits it, not done in the last 3 days, not outdoor when rain is likely; the day picks among those that qualify. At his times (default 18:00, OFF). No gap / nothing fits / calendar not linked → nothing sent. | `freetime.py`, `ideas.py` |
| 10 Focus nudge | At his times (default 10:00, 15:00, OFF): "Top priority now, Sir: {label}." — the top `PendingItem` from `ctx.pending_all()` (Part A's sources), ranked by D9 in code (overdue → today → urgency → his pin → due). Nothing pending → nothing sent. | `focus.py` |

Shared: `models.py` (settings; each nudge OFF until switched on), `schedule.py` (slots: first run at or
after due, never early; a slot more than 30 min old is skipped as stale), `service.py` (`deliver`),
`calendar.py` (his calendar and the rain port), `jobs.py`, `tools.py` + `ideas.py` (13 tools),
`words.py`, `phrases.py`, `privacy.py`, `brief.py`, `part.py`; routes `api/helpers_nudges.py`; tab
`console-helpers-nudges.js`; eval `evals/r11_helpers/nudges.py` (`BUILT = True`).

### How a nudge goes out (D3, D4)

`NudgeService.deliver`: **claim** the nudge's key for the day in a transaction
(`nudges/{uid}_told`, `{day: [key]}`, last 3 days, keys like `nudge_hydrate@2026-11-10T05:30Z` or a
fingerprint — no words) → compose → `ctx.sender.send(uid, nudge_*, text, due=...)` (the gate: caps,
snooze, stop; the policy drops it at night) → **release** the claim when `SendResult.retry` (no channel
took it), when the sender raised, or when the text couldn't be made yet (calendar didn't answer). Every
other outcome (rang, silent, held, dropped, stopped, snoozed, capped) keeps the claim: never twice.

### Jobs, tools, phrases, data

- **Jobs** (5-minute clock): `nudges` (stand-up + meeting variant, water, focus, free time) and
  `activity_check` (item 11; also sweeps sealed days past 30 once a local day). Both run for
  `ctx.owners`, read his settings once a run, read his calendar only when a nudge that needs it is on
  (cached 30 min per owner, a failure remembered 10 min), each read ≤ 8 s, after his `calendar_read`
  row allows it (unreadable rules → no read) and with one audit line (agent `helpers`, tool
  `calendar_list_events`, outcome only). A pending source that fails at focus time is not "nothing
  pending": with nothing back, the focus claim is released and the next run retries (inside the
  slot's 30 minutes). A failed sweep is logged by class name, the asks still go, and its claim is
  released so the next run sweeps again.
- **Tools** (all `agent="nudges"`, fixed `activity_words`): `nudge_status` R1, `nudge_set` R2 (a card
  when the round read outside content), `nudge_snooze` / `nudge_stop` / `nudge_resume` R2 (I0's
  `GateStore`, the same documents the tab's taps change; stop = for today, `for_good` = switched off;
  snooze kind `last` = the nudge that reached him in the last 30 minutes, none → "Which nudge should I
  snooze?"; a stop says what it stopped, that his reminders are not affected, and the phrase that
  brings it back), `nudge_water_log`, `nudge_standup_log`, `nudge_activity_checkin` R2 (the word must
  be one of his activity words, or answer an ask still open today), `freetime_suggest` R1, `freetime_list` R1, `freetime_add` R2 (a card when tainted),
  `freetime_remove` R2, `freetime_done` R2.
- **No-AI phrases** (D18; anchored, whole message): every one of the 13 tools is reachable
  (`tests/test_r11_c_phrases.py` pins it). "don't remind me to stand up" → `nudge_stop`, never
  `reminder_add`; "remind me to drink water every 45 minutes" → `nudge_set`; a one-off "remind me to
  drink water at 5 pm" still reaches the reminders. Telegram replies ("stop water") reach the same rules
  (owner decision 7: no buttons). A check-in ("walk done", "missed my gym") fires only for one of his
  activity words or a word JARVIS asked about in the last 12 hours; "homework done", "the report is
  done" and "I missed my flight" fall through to the other routers. A bare "snooze" snoozes only the
  nudge sent last (above); "stop my reminders" / "no reminders" still stop every nudge for today.
- **Data**: `nudges/{uid}` (settings, ≤ 50 ideas; plain, his own words), `nudges/{uid}_told` (claims;
  no new collection), `wellbeing/{uid}_{date}` (sealed, AAD `wellbeing/{uid}/v1`, the date inside the
  seal checked on read, 30 days). No count and no word he typed reaches a log line
  (`test_no_log_line_carries_a_count_or_his_words`).
- **Privacy row** `helpers_wellbeing` (section Helpers, passkey delete): lists the sealed days and his
  settings, exports the log opened plus his settings and ideas (never a calendar title or a blob),
  deletes all of it and the claims (every nudge back to OFF).
- **Counts and the model (by design)**: on a console turn with the AI on, `nudge_status`,
  `nudge_water_log` and `nudge_standup_log` hand today's water and stand-up counts back to the model as
  tool output. That is his own data, in a turn he started, through his own provider, so it stays as
  designed; only a Telegram turn keeps the counts out (owner check 8).
- **Brief**: "Nudges today: drink water every 90 min, your top priority." and "Yesterday: 4 glasses of
  water, 0 stand-ups." (sealed log, only when something was logged).
- **Routes** `/v1/helpers/nudges`: `GET` (view, incl. the gate's snoozes/stops), `PUT /{name}`,
  `POST /water`, `POST /stood`, `POST /ideas`, `POST /ideas/{id}/done`, `DELETE /ideas/{id}`;
  owner-only, `no-store`, I0's per-owner limiter; 404 `helpers_off`, 409 `sealed_off`, 422 `invalid`,
  503 `unavailable`. Snooze/stop/resume taps use I0's `/v1/helpers/gate/...`.
- **Tab**: switches, Snooze (1 h) / Stop (today) / Resume per nudge and for all, when each comes, today's
  water and stand-ups (+1), the free-time list (add, done, remove) and the settings. Shell builders and
  existing classes only (`.btn.bact`, `.bsw`, `.minput` in `.pskadd`, `.sfine`), `textContent`, ASCII.

## How to check it

```
/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r11_c_*.py           # 199 passed
/tmp/venv-12/bin/python evals/r11_helpers/run.py --mock --part nudges           # 7/7, control fails it
JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_c_nudges.py
```

- The 14-day simulation (`tests/test_r11_c_sim.py`, eval case `fourteen-days-on-time`): 4,032 runs with
  up to 40 s jitter, a restart after every run that sent (175), 202 nudges, each in the first run at or
  after due, none early, twice or missed; per-kind, daily and hourly caps held (his cap of 3 that day:
  2 capped); snooze by phrase and by tap, stop by phrase ("don't remind me to stand up" sets no
  reminder); the missed walk asked once on each of 7 days; the free-time pick fits the 90-minute gap,
  is never outdoor on a rainy day and skips the idea he did in the last 3 days; D21's line: nudges
  within the limits on 14 of 14 days.
- Control: claims off (`NudgeStore.claim` always yes, `release` a no-op) → fails
  `fourteen-days-on-time` ("sent twice"), `missed-activity-asked-once`, `night-drops-a-nudge`,
  `retry-is-released`.
- Coverage of `helpers/nudges/` + `api/helpers_nudges.py`: 98 % (coverage 7.6.10 from a scratch dir;
  no shared venv was changed).

### Results on this branch (head of `r11-c`)

| Check | Result |
|---|---|
| Part C tests `tests/test_r11_c_*.py` (3.12; 3.11 the same), after the review fixes | 199 passed |
| Whole unit suite (3.12, under the shared lock; at 37b773c, not re-run for the review fixes) | 10,968 passed, 107 skipped, 3 failed: exactly the three I0 stub assumptions of "Needs I1" 1 |
| Targeted re-run after the last Part C fixes (console assets, arch coverage, permissions, Telegram guard, every R11 test) | 1,075 passed, the same 3 failed |
| ruff check / ruff format --check (src tests evals scripts) | clean |
| mypy src | the 9 pre-existing errors only |
| `evals/r11_helpers/run.py --mock` | 18/18; control `caps_off + claims_off` fails the suite (nudges: 4 cases). After the review fixes `--part nudges`: 7/7, its control fails it |
| `evals/run_all_mock.py` (R11 not in it until I1) | ALL MOCK EVALS: PASS |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK; all 25 documents versioned |
| Browser subset `-k "helpers or dock or ui_audit"` (incl. `test_r11_c_nudges.py`) | 156 passed |
| Coverage of `helpers/nudges/` + `api/helpers_nudges.py` | 98 % |

## Needs I1

1. **Three I0 tests assume every part is a stub** and fail once any part is built
   (`tests/test_r11_wiring.py`). Proposed diff:

   ```diff
   @@ test_the_helpers_start_with_four_empty_parts_and_both_composites
   -        assert {p.ready for p in st.r11_parts.values()} == {"not built yet"}
   +        assert r11.SETUP_FAILED not in {p.ready for p in st.r11_parts.values()}
            assert st.helpers_sender is not None and st.helpers_off is None
   -        assert isinstance(st.helpers_clock, Composite) and st.helpers_clock.job_names == ()
   +        assert isinstance(st.helpers_clock, Composite)
   +        assert set(st.helpers_clock.job_names) <= {j for js in CLOCK_JOBS.values() for j in js}
   @@ test_a_failing_part_is_left_empty_and_the_others_run
   -    builders = {**r11.BUILDERS, "today": today, "house": house}
   +    stubs = {p: (lambda ctx, p=p: HelperPart(name=p)) for p in PARTS}  # the parts not under test
   +    builders = {**stubs, "today": today, "house": house}
   @@ test_the_four_part_routers_are_stubs_under_their_own_prefix
   -        assert module.PREFIX == f"/v1/helpers/{part}" and module.router.routes == []
   +        assert module.PREFIX == f"/v1/helpers/{part}"
   +        assert all(r.path.startswith(module.PREFIX) for r in module.router.routes)
   ```
   (imports: `from jarvis.helpers.kinds import CLOCK_JOBS, PARTS`.) The test's name may become
   `test_the_four_part_routers_live_under_their_own_prefix`. Checked on a temporary copy of the file
   on this branch: 12 passed (the copy was removed, the I0 file is untouched). Parts A, B and D trip
   the same three assertions once built, so the one diff serves all four.

2. **Rain for the free-time pick (D12)**: Part C reads a rain hint late through `ctx.rain` (a callable
   returning an object with `async rain_likely(uid, start, end) -> bool | None`); until I1 joins Part
   B's weather it is unknown and no rain rule applies. Proposed diff:

   ```diff
   # src/jarvis/helpers/ports.py, class HelperContext
        brain_mode: BrainMode | None = None
   +    # I1: Part B's rain hint for Part C's free-time pick, read late (None / returns None: unknown)
   +    rain: Callable[[], Any] | None = None
   # src/jarvis/api/r11_wiring.py, _context(...)
   +    def rain() -> Any:
   +        parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
   +        house = parts.get("house")
   +        return house.services.get("rain") if house is not None else None
   +
        return HelperContext(
            ...
            brain_mode=getattr(st, "brain_mode", None),
   +        rain=rain,
        )
   ```
   and Part B exposes `services={"rain": <its weather service>}` with `rain_likely` (rain ≥ its
   threshold in his place between `start` and `end`; None when his place isn't set or the forecast is
   stale). Part C needs nothing else: `part._rain_from` already reads `ctx.rain`.

3. **Focus ranking**: `focus.rank` is D9's order in code (Part A owns D9). If Part A exposes its ranker,
   I1 may point `focus.plans` at it; the order must stay overdue → today → urgency → pin → due.

4. **Persona p11.0** (D22, I1's): `HELPERS_RULE` should also say "for 'don't remind me to …' about a
   nudge, use nudge_stop, never a reminder" so the AI-on path matches the No-AI phrase.

5. **Telegram's read-tool guard** (`tests/test_telegram_tool_guard.py`) builds its gateway without
   the R11 parts, so it never classifies their reads. With `r11=` added there, Part C's three reads
   are safe to answer on Telegram: add `"nudge_status", "freetime_list", "freetime_suggest"` to its
   safe list. On a Telegram turn (`core.channel.on_telegram()`) Part C's tools already keep the sealed
   log's counts out of the reply ("Logged 2 glasses of water, Sir."; the status points to the tab),
   because a bot chat is a cloud chat (`test_on_telegram_the_log_counts_never_leave_the_console`).

6. **Guide / C60**: no new collection (the claims doc lives in `nudges`); the card's module list may add
   Part C's modules (`helpers/nudges/{calendar,service,schedule,jobs,words,ideas}.py`) if it lists files.

## Owner checks (live, after I1)

1. Helpers → Nudges: switch on Stand up and Drink water; on a weekday a nudge arrives on Telegram at
   10:30 / 11:00 (within 5 minutes), none at night or on Sunday.
2. Reply "stop water" in Telegram (AI off and on) → no more water today; "snooze stand-up for 30
   minutes" → none for 30 minutes; the tab shows "Snoozed until …"; Resume brings it back.
3. Say "don't remind me to stand up" → the stand-up nudge stops for today and no reminder is created.
4. With JARVIS's token key set: "had a glass of water" → the tab's water count rises; Privacy → Helpers
   → "Water, stand-ups, activities and free time" lists, exports and deletes (passkey).
5. Put "Evening walk" in your own calendar, don't check in → one question about 15 minutes after it
   ends; "walk done" before then → no question.
6. Add three free-time ideas, switch on Ideas for free time → at 18:00 one that fits before your next
   event (never an outdoor one when rain is likely, once I1 joins the weather).
7. Owner decision 1: if "stand-up" meant your meeting, switch on "Also 10 minutes before my stand-up
   meeting" and set the word your meeting's title contains.
8. With the AI on, ask in the console "how much water have I had today?": the answer (and so the
   model, through your own provider) has today's counts. Accept that, or say so; on Telegram the
   reply only points to the tab.
9. With the AI off: "homework done" and "I missed my flight" are not taken as check-ins; "walk done"
   is. Right after a nudge, "snooze" snoozes only that one; with none in the last 30 minutes JARVIS
   asks which.

## Known limits

- Without the 5-minute clock (deploy step 8) nudges come only 04:00–11:30 on the morning tick, and a
  slot more than 30 minutes old is skipped (a stale nudge is noise), so most daytime nudges are lost
  then; the Helpers panel already says the clock is stopped.
- A planned activity is matched by his words in the event title; an event someone else created (an
  invite) is never treated as his plan.
- The No-AI check-in phrases know his activity words from memory (the router is synchronous): from
  the last read or change of his settings, which every clock run makes. Right after a restart they
  use the default words (walk, gym, yoga, run) until the first run; with several owners, every
  owner's words (the tool still checks his own).
- Nudge texts go out in English, fixed; the free-time and focus nudges carry his own words (an idea, a
  pending label), never outside text.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.1 | 11 Nov 2026, 23:30 IST | R11 | Part C built: the nudges, tools, phrases, privacy row, brief, routes, tab, eval; Needs I1 and owner checks | 🛠 Mark XIV |
