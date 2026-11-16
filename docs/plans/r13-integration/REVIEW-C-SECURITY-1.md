Version v13.0.1 · 15 Nov 2026, 21:41 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context security review, Part C)

# R13 Part C (Styling): security review 1

Fresh context: the reviewer did not write this code. Branch `r13-c` @ `54f95f4` in a detached, read-only
worktree; diff `r13-i0..r13-c` (34 files, +6,112). The review followed `.claude/agents/security-reviewer.md`,
`CLAUDE.md`, `.claude/rules/ecc/`, the plan `docs/plans/r13-wardrobe.md` v13.0.2 (Part C, D10, D12–D15,
D18, D19), `PLAN-REVIEW-1.md`, `BRIEF-COMMON.md`, `I0-NOTES.md` and `INTEGRATION-C.md`.

**Verdict: WARNING. No CRITICAL, 1 HIGH, 4 MEDIUM, 8 LOW.** The core privacy design holds:
- every tool goes through the gateway on the `outfits` row;
- every calendar read is governed ("Allow" only, kind-only audit);
- titles are never stored, logged or sent;
- the weather fetch is pinned with no SSRF;
- documents are sealed with per-collection and per-uid AAD;
- uid always comes from the session or the tool context;
- alerts never name a private piece.

Fix H1 and M1–M4 (or have the Workshop accept them in writing) before I1 merges Part C.

Five probes reproduced the findings. They are scratch scripts outside the repo, run against the branch's own
fakes: `/tmp/rv-c-scratch/probe.py`, `/tmp/rv-c-scratch/race.py`, `/tmp/rv-c-scratch/keychange.py`. They
cover:
- the lock bypass;
- the error echo into the audit;
- the invite flood;
- the lost update;
- the key change.

No suite was run. Only these probes ran, behind `flock /tmp/heavy.lock`.

## HIGH

### H1. Strangers' calendar invites flood `outfit_ready`, fill the 60-plan cap, and plans he removes come back

**Where:**
- `src/jarvis/wardrobe/styling/calendar.py:53` (`MAX_EVENTS = 50`) and `:256-262` (every unseen event becomes a plan until 60);
- `src/jarvis/wardrobe/styling/jobs.py:102-121` (one important `outfit_ready` per plan, no per-evening cap; the R13 kinds are in no storm table);
- `src/jarvis/wardrobe/styling/plans.py:152-157` (`put` refuses past 60);
- `src/jarvis/wardrobe/styling/actions.py:72-74` (release drops the plan, and the next read re-creates it).

**Scenario (reproduced):** Google adds invitations to his calendar by default, so anyone who knows his
address can put events there. The probe used 50 invites for tomorrow on the calendar he picked:
1. One clock read made **50 plans**.
2. At 20:00 he got **50 `outfit_ready` alerts** (important: they ring in the day and are held at night).
3. His own `outfit_plan(save)` was then refused: "You have 60 plans: remove an old one first."
4. A calendar plan he released came back at the next hourly read with a new id.

The plans stay until 14 days after their day (`pruned`), so manual planning stays blocked for about two
weeks. Every plan also costs engine runs and two Firestore reads in each `GET /v1/outfits` and each repick.
That multiplies against the ₹0 free-tier budget.

No data leaks: titles stay in memory, and the outside party controls only whether events exist and when.

**Fix:**
1. **Cap calendar plans** in `sync`. Calendar plans must never take the slots kept for his own plans:
   ```python
   MAX_CAL_PLANS = 20  # calendar-made plans; the other 40 slots stay his
   made = sum(1 for p in doc.plans if not p.manual)
   if plan is None and e.k not in doc.dismissed and made < MAX_CAL_PLANS and len(doc.plans) < MAX_PLANS:
   ```
2. **Remember what he dismissed.**
   - Add `dismissed: tuple[EventKey, ...] = Field(default=(), max_length=200)` to `StylingDoc`.
   - On `outfit_plan(action="release")` of a calendar plan, record its `event` key there:
     `d.drop(plan.id).model_copy(update={"dismissed": (*d.dismissed, plan.event)[-200:]})`.
   - `sync` skips those keys.
   - Prune a key once its day is past.
3. **One evening alert, not N.** Claim `ready_<day>` once, and send one fixed sentence with a count, e.g.
   "Tomorrow's outfits for 3 events are ready in Helpers, Wardrobe." Alternatively, send at most 3 alerts and
   then one "and N more". This changes D19's text, so it needs the Workshop's OK.
4. Drop cancelled calendar drafts once their day has passed, rather than keeping them 14 days.
5. Optional, for the owner to decide: skip events he declined by requesting `attendees(self,responseStatus)`.
   That returns only his own response, never a guest, but it differs from D13's "attendees never fetched".
6. Tests:
   - 50 invites → at most 20 plans;
   - one alert at 20:00;
   - his manual save still works;
   - a released calendar plan is not re-created.

## MEDIUM

### M1. Lost updates: four writers save a stale snapshot over his concurrent change (a released plan comes back, `worn` is undone)

**Where:**
- `src/jarvis/wardrobe/styling/jobs.py:64-100` with `_calendar_onto` `:133-140` (every non-manual plan of the snapshot is `put` over the current doc);
- `src/jarvis/wardrobe/styling/refresh.py:86-96` with `_onto` `:149-153`;
- `src/jarvis/wardrobe/styling/actions.py:65-79` with `_merge` `:82-88`;
- `src/jarvis/wardrobe/styling/tools.py:195-215` (`prefs` and `_code` write values computed from the snapshot).

`SealedDoc.change` is transactional, but each closure ignores the current document for the plans it touches.

**Scenario (reproduced in `race.py`):** while the clock's Google read was in flight (up to
`OUTSIDE_TIMEOUT_S`):
1. He released plan 1 and started wearing plan 2 (`worn=True`).
2. After the tick, **plan 1 was back with its old id and plan 2 had `worn=False`**.

The same race exists between:
- the refresh observer (a piece to the basket marks `needs`) and an owner action (lock, reserve) on the same plan;
- two `outfit_prefs` changes from the panel and from chat.

With `worn` undone, the refresh again judges changes to that plan's pieces as "left". That can send an
`outfit_changed` for an outfit he is already wearing.

**Fix:** do every merge against the current document inside the transaction, with a compare-and-set on
each plan:
- **jobs:** run the pure `sync(d, entries, span, zone, now)` inside `s.change(uid, apply)`, where `apply`
  returns `d` unchanged when `d.choice.calendar != cal`. Then repick each touched plan in its own change:
  `lambda d: d.put(fresh) if d.plan(pid) == seen else d` (frozen models compare by value).
- **refresh:** in `_onto`, put `p` only when `doc.plan(p.id) == before[p.id]` (the snapshot's version).
  Otherwise re-run `_changed` once.
- **actions and `_code`:** `_merge` refuses "That plan changed meanwhile: try again." when
  `current.plan(pid) != doc.plan(pid)`.
- **prefs:** recompute inside the transaction:
  `s.change(uid, lambda d: d.model_copy(update={"prefs": prefs.apply(d.prefs, rules, args)[0]}))`.
- **Test:** `race.py` turned into a test (release and wear during the read; both survive).

### M2. A bad argument echoes his words into the log, the audit chain and the model's error (D10 "logs, audit: ids only")

**Where:**
- `src/jarvis/wardrobe/styling/prefs.py:73-84`. `exclude` builds `Exclusion(piece=piece)` from an unchecked
  string, so pydantic raises with `input_value='<his words>'`. `include` echoes the raw string in its
  message (`:80`).
- `src/jarvis/wardrobe/styling/tools.py:158`: `int(args.get("days"))` echoes the input.

**Scenario (reproduced):** the model passes a name instead of an id, as models do:
`outfit_prefs(action="exclude", piece="my red lace briefs")`. The gateway's `_run` then:
1. calls `log.exception("tool failed")`, which puts the full message in Cloud Logging;
2. writes `_safe_detail(exc)` into the audit entry's `detail` (Firestore, in clear);
3. returns the same text to the model.

The probe's audit `detail` held
`...input_value='my red lace briefs'...`. That names a private piece outside the Wardrobe tab, in two
sinks D10 limits to ids and counts.

**Fix:**
- In `prefs.apply` (both `exclude` and `include`), refuse in fixed words before building any model:
  ```python
  from jarvis.wardrobe.model import PIECE_ID
  if not isinstance(piece, str) or not PIECE_ID.match(piece):
      raise PlanRefused("Name the piece by its id (wi_ and 12 letters or digits).")
  ```
  `tools.prefs` also checks `piece in view.pieces` for `exclude`.
- In `tools.plans`:
  `raw = args.get("days", 7); if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 14: return _refused("Ask for 1 to 14 days.")`.
- Defence in depth: add `hide_input_in_errors=True` to `ConfigDict` in `plans._M`, `calendar._M` and
  `outlook._M`.
- See L2 for the general `check=`.
- For I1: the gateway's `log.exception` prints any tool's exception text, which affects every part.
- **Test:** an `exclude` with a name, then assert the needle is absent from the audit chain, the
  captured log and the result.

### M3. A key change (`KEY_ID`) or one unreadable cache stops Part C for him: the clock, the tools and the routes. INTEGRATION-C §6.9 describes behaviour that doesn't happen.

**Where:**
- `src/jarvis/wardrobe/styling/sealed.py:76-86`. `Unreadable` is raised, and the document is never
  overwritten, for all three documents.
- `src/jarvis/wardrobe/styling/jobs.py:61-64`. The weather step runs first, and any exception aborts the
  owner's whole run.
- `src/jarvis/wardrobe/styling/outlook.py:152`. `sealed.read` sits outside the `try`.
- `src/jarvis/api/outfits.py:82,153`. Nothing handles `Unreadable`, so the routes return a bare 500.
- `docs/plans/r13-integration/INTEGRATION-C.md:200-202`.

**Scenario (reproduced in `keychange.py`):** with a new keyring over the same documents:
- every clock tick returns `{"failed": 1}`, so the calendar sync and `outfit_ready` never run again;
- `outfit_suggest` raises `Unreadable`, which reaches him as the generic "The tool failed";
- `GET /v1/outfits` and `PUT /v1/outfits/settings` return 500.

That contradicts §6.9 ("the next read makes new calendar plans … Settings asks him to pick his calendar
again"). The only way out is Privacy delete, and D's row "Laundry, outfits and wear history" may clear B's
data too.

A one-off undecryptable `wardrobe_outlook` (a cache that is "overwritten" anyway) has the same effect on
the clock.

**Fix:**
- `jobs._owner`: put each step (weather, calendar, ready, prune) in its own `try/except` with the class
  name in the counts.
- Give `SealedDoc` a `reset_unreadable: bool` that is True only for `wardrobe_outlook` and `wardrobe_cal`
  (derived caches): on `Unreadable` they read as empty and the next write replaces them. `wardrobe_plans`
  keeps "never overwrite".
- Tools (`StylingTools._ready`) and routes: catch `Unreadable` → `_refused` / `_err(503, …)` with fixed
  words: "Your outfit plans can't be opened (JARVIS's key changed): delete them in Privacy to start
  again."
- Correct §6.9 and the runbook note to describe this behaviour.
- Consider a C-only reset (delete C's three documents and its claims) so B's data is not lost.
- **Tests:**
  - with a new keyring, the clock still syncs the calendar;
  - the routes answer 503 in words.

### M4. `outfit_plan` and `outfit_prefs` cards say only the verb (12 raw characters of the model's `action`); a whole-plan "release" is a permanent delete with no undo

**Where:**
- `src/jarvis/wardrobe/styling/tools.py:287-292` (`_plan_words` and `_prefs_words` use `str(action)[:12]`);
- `:310-321` (no `preview` for either tool);
- `src/jarvis/wardrobe/styling/actions.py:72-74` (`release` without a piece calls `d.drop(plan.id)`).

**Scenario:**
- A round that read outside content, or a spoken turn, makes these R2 writes into cards that read
  "Outfit plan: release." or "Outfit rule: exclude.".
- The card does not say which plan, piece or occasion, so he approves blind. Approve-all can run a batch
  of them, since only merge and retire are in `NO_BULK_TOOLS`.
- An injected `outfit_plan(action="release", plan=…)` series deletes his manual plans, with their locks,
  reservations and shared bases. There is no Recently-deleted entry.
- `action` is not enum-checked by the gateway, so any 12 characters the model emits are printed on
  Telegram and stored in the card's summary in clear.

This misses D10's rule that "a card's words come from `Tool.preview` through `redact.py`" and the
project's rule that deleting data needs confirmation.

**Fix:**
- Fixed summaries:
  `PLAN_WORDS = {"save": "Save an outfit plan", …}; return "Remove an outfit plan." if action == "release" and not args.get("piece") else f"{PLAN_WORDS.get(action, 'Change an outfit plan')}."`.
  Do the same for `PREFS_WORDS`.
- Add read-only `preview=` functions that name the plan by its time and day and each piece through
  `redact.card_words`. Examples:
  - "Remove tomorrow's 10:00 outfit plan."
  - "Reserve a pair of brown dress shoes for tomorrow's 10:00 outfit."
  - "Leave a private basic out of Holi looks."
- Make whole-plan release a card every time:
  `ask_when=lambda a: a.get("action") == "release" and not a.get("piece")`.
  Or keep a released plan restorable for 30 days.
- Needs I1: propose `outfit_plan` for `NO_BULK_TOOLS` (`core/guardrails.py` is I0's).
- **Tests:**
  - card text for each action;
  - a release from a tainted round is a card naming the plan.

## LOW

### L1. `lock` with a piece skips the reservation check (STY-14), so both plans lose the piece
`src/jarvis/wardrobe/styling/actions.py:137-140`. `reserve` refuses at `:117-122`; `lock` calls
`with_pick` directly. In the reproduction, `reserve` was refused, then `lock` returned "Done.". Both plans
then held `shoe_l`, and **neither look showed it**: each saw it reserved by the other. This is an integrity
issue, not a leak.

**Fix:** pass `doc` and `here` to `_lock`. When a piece is named, run
`reserve.conflict(doc, plan, unit, here.zone)` and raise `PlanRefused(words)` exactly as `reserve` does.
Test: lock a piece another plan holds → the same refusal as reserve.

### L2. The tools' JSON-schema limits aren't enforced: the gateway's `validate` checks only required and unknown keys
`src/jarvis/tools/base.py:108-121`; `src/jarvis/wardrobe/styling/tools.py:47-80`. `maxLength` (`query` 80,
`occasion` 60), `maxItems` (`pieces` 20), `enum` (`action`) and the 1–14 `days` range only advise the model.
Effects:
- `wear_log(pieces=[…duplicates…])` writes duplicate wear events in one commit (`tools.py:256-261`, `wear.start_events`).
- An unbounded `query` or `occasion` costs O(n·pieces) in `wear.resolve` and `Rules.occasion_of`.
- A missing id is echoed whole in `"<ids> isn't in your wardrobe."` (`tools.py:258-260`).

**Fix:** give each of the five tools a pure `check=` (the gateway runs it before the policy step), raising
`ValueError` with fixed words. It enforces:
- `action` is in the enum;
- `plan` and `from_plan` match `PLAN_ID`;
- `piece` matches `PIECE_ID`;
- `pieces` holds at most 20 unique `PIECE_ID`s;
- `day`, `code`, `slot`, `start` and `end` are str ≤ 24;
- `occasion` ≤ 60 and `query` ≤ 80;
- `days` is an int from 1 to 14.

### L3. Free-text `occasion` on the R2 write tools lands in clear in a card's stored arguments
`src/jarvis/wardrobe/styling/tools.py:59,68`; `actions.py:53`; `prefs.py:73-74`. D10 and M4 allow his words in
stored card arguments only for `wear_log` and `laundry_move` `query`. `outfit_plan` and `outfit_prefs` also
take free `occasion` text. A model that copies an event title it saw elsewhere into `occasion` stores that
title in clear in the approvals store, while C itself keeps only the matched key.

**Fix:** for `outfit_plan` and `outfit_prefs`, make `occasion` an `enum` of the rules' occasion keys
(`holi`, `festival`, `meeting`, `sport`, `function`) and check it in `check=`. Keep free-word matching only
in `outfit_suggest`, which is R1 and never a card.

### L4. Calendar read: no pagination signal, and the title and location are used even when he turned those fields off
`src/jarvis/wardrobe/styling/calendar.py:66-71,197-210,137,265-271`.
- `fields=items(...)` drops `nextPageToken` and `maxResults=50`. On a busy 48 h the later events are absent,
  so `sync` cancels their plans because the read "covered" their window.
- `to_item` reads `summary` and `location` whatever `fields` he chose. Google honours `fields` today, but
  the code should not rely on that.

**Fix:**
- Request `items(...),nextPageToken`. When a token comes back, mark the read partial and skip
  absence-based cancellation, or page up to a small cap.
- Pass `fields` to `to_item` and read `summary` only if `"title" in fields` and `location` only if
  `"location" in fields`.
- Test: a mock that returns a summary when the title is off → no occasion.

### L5. Switching the calendar off (or to another) keeps the last read in `wardrobe_cal/{uid}` indefinitely
`src/jarvis/api/outfits.py:147-153`. Event fingerprints, times and codes from a calendar he no longer uses
stay sealed with no expiry. They are not needed once the calendar is off.

**Fix:** when `moved`, also `await calendar.sealed.delete(uid)` (or write an empty `CalDoc`) in
`put_settings`. Test it.

### L6. `Unreadable(...) from exc` chains decrypted plaintext into tracebacks
`src/jarvis/wardrobe/styling/sealed.py:83-86`. When `model_validate` fails after a successful decrypt, the
chained `ValidationError` carries `input_value=<decrypted values>`. That happens after a rollback past a
release that added a field (`extra="forbid"`) or after a tightened limit. The gateway's `log.exception` and
Starlette's 500 handler print the chain. The proof is in the review notes: `extra_forbidden` shows the
values in the traceback.

**Fix:** `raise Unreadable(self._collection) from None`; the class name is already logged at `:85`. Add
`hide_input_in_errors=True` (see M2).

### L7. `rules.json` packaging: the part degrades safely, but the planned call from A's sweep does not
`src/jarvis/wardrobe/styling/rules.py:181-193`; `pyproject.toml:82-114` (no entry yet);
`INTEGRATION-C.md:173-183`.
- Confirmed: without the file, `load_rules()` raises `RulesError` (it catches `OSError`). `build` raises,
  the wiring (`api/r13_wiring.py:119-124`) marks the part "setup failed", and the other parts run.
- Needs I1 #3, however, has A's `wardrobe_sweep` call `load_rules()` directly. A missing or broken file
  would then raise inside A's sweep and could stop A's other daily work.

**Fix (I1):**
- Land the package-data line.
- In A's sweep, take the checked rules from C's part (`part_of(..., "styling").services["refresh"].styling.rules`).
  When C is "setup failed", skip the close step, wrapped in `except RulesError`.
- Load the rules once, not on every run.

### L8. `wear_log` ignores the ledger's verdict
`src/jarvis/wardrobe/styling/tools.py:232,246`.
- A's `Refused` (plain words) propagates and reaches him as the generic "The tool failed, so it may not
  have been done".
- A commit whose marks are `duplicate` or `superseded` still answers "Noted: you're wearing …".
- Separately, `reserve.transfer` (`reserve.py:108`) raises `KeyError` for a piece purged since it was
  planned.

**Fix:**
- Wrap `wear.commit` in `except Refused as exc: return _refused(str(exc))`.
- Say "already noted" when `got.already` is set or no mark is `applied`.
- In `transfer`, refuse "That piece isn't in your wardrobe any more." when `pid not in view.pieces`.

## Checked and holding

**1. Tools and routes**
- The five tools are on the `outfits` row (`outfit_*`, `wear_*`, `permissions/groups.py:600-606`), with agent `outfits` and fixed `activity_words`.
- Telegram's personal switch covers `outfit_*` and `wear_*` (`telegram/rules.py:73-74`).
- Only `wear_log` is `spoken_ok`.
- Only the two reads vouch. Every string in their results is a fixed word, an id, a time or a rules-file word. The occasion passes through `OCCASION_WORDS`. Sets appear only by `ws_` id, never by label.
- Routes:
  - `require_auth` with the CSRF header on PUT;
  - uid from `current_user` (the session);
  - `limited(...)` before any work;
  - `no-store`;
  - errors in plain words, except the 500 in M3.
- The settings audit is `{"calendar": bool, "fields": [...]}` and never carries an id.

**2. OPS-04**
- Every read goes through `BackgroundReads` on `calendar_list_events` ("Allow" only). The route has no gateway context, so "Ask first" never reads.
- One kind-only audit line per read.
- Only `items(id,status,updated,start,end[,summary][,location])` is requested; description and attendees are never requested.
- The calendar id:
  - offered only as a keyed 16-hex reference;
  - accepted only from his live list;
  - stored sealed;
  - URL-encoded with `quote(safe="")` on a fixed Google host.
- Titles are matched in memory only. `CalEntry` and `Plan` have no title field.
- Cancelled events are handled by `status` and by absence; see L4 for the gap.
- No calendar text reaches the model: only `your HH:MM event (a meeting)`.

**3. Weather**
- Fixed URL `https://api.open-meteo.com/v1/forecast`, enforced by `_check_url` (https and a host allow-list).
- No redirects, a 256 KB cap and a timeout.
- Params are built by R11's `request_params` from the R11-validated point, rounded to 2 decimals, and the zone key. httpx encodes them, so there is no SSRF.
- At most twice a day; a failure waits an hour.
- Sealed under `wardrobe` with AAD `wardrobe_outlook/<uid>/v1`.
- No R11 file is in the diff.

**4. Private pieces**
- `fixed_words`, `piece_words` and `unit_words` say "a private basic" in every reason, compromise, gap, stale line, LND-16 line, "Which one", the `wear_log` card and `outfit_changed`.
- `outfit_ready` names no piece.
- The model view gives a private piece's id, slot and "a private basic".
- The panel shows a private piece's words only with `show_private`.
- Logs carry class names only. The one exception is M2's echo.

**5. Sealed documents**
- One purpose, `wardrobe`.
- AAD `<collection>/<uid>/v1`, so a document can't be swapped between collections or owners.
- Paths come from the session or tool-context uid.
- No key → "off: no token key", and nothing is written in clear.
- Claims in `wardrobe_told` hold only `uid`, `part`, a 16-hex hash and a time.

**6. Concurrency**
- `outfit_ready` uses a create-only claim before the send.
- `outfit_changed` is a transactional `every` claim per plan per 2 h before the send. Neither alert can be sent twice.
- See M1 for lost updates and L1 for reservations.

**7. Repository hygiene**
- No secrets or personal data in the diff or the tests: `example.com` ids, a test keyring `bytes(range(40, 72))`, a public district-centre point.
- No local paths.
- The eval controls restore `AVAILABILITY` and `WEAR_RULE` in `finally`.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:41 IST | R13 | First edition: a fresh-context security review of Part C at `r13-c` @ `54f95f4`: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 8 LOW, each with file:line, a scenario (five reproduced by probes) and the exact fix; what was checked and holds; verdict WARNING | 🛠 Mark XXI (security review) |
