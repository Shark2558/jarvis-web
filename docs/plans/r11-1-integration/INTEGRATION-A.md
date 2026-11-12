Version v11.1.1 · 12 Nov 2026, 09:25 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 Part A · Brain and calendar — integration note for I1

Branch `r11-1-a` (from `r11-1-i0` @ 9250be1). Observations O1, O2, O2b and O12 of
`docs/plans/r11-1-observations.md` (decisions D0–D7, D20, D21-A). Everything is in Part A's own files:
no wiring file, no seam test and nothing on the brief's never-edit list was touched. What Part A
needs from those files is in §3, each with the exact diff.

## 1. What was built

| Obs. | What you asked for | Where | State |
|---|---|---|---|
| O1 | No reply is ever "I have nothing to add, Sir." | `core/finish.py` (new logic), `core/brain.py`, `core/window.py`, `core/rounds.py` | **Built.** A turn that works with tools or attached files may write `work_output_tokens` (`finish.output_cap`, `working_turn`; a plain reply, an approval's narration and a training brain keep 1,024). An answer the cap cut off with no usable words is asked for ONCE more (`finish.asked` / `retried`, `empty_reply_retries`) with the fixed instruction and the working cap, admitted and metered like any call; its half-written tool calls never run and it is never stored. Still nothing: a fixed line chosen by code from what happened (approvals waiting, steps that ran, cut off, simply empty). The same on the round-limit summary call and on the stream (`finish.silent`). A fixed line is stored marked `tool_derived` and `core/window.py` leaves it, and every stored old filler turn, out of every model's window. |
| O2 | Many calendar events on one approval | `tools/calendar_batch.py` (pure rules), `series/batch.py` (the run), `series/batch_result.py`, `tools/calendar_cards.py`, `tools/reply_cards.py` (`BatchCard`) | **Built.** `calendar_create_events` (1–100 events, no guests) is R2 with `ask_when` always: ONE card whatever the row says, typed or spoken, tainted round or not. The card is written by code (how many, first and last date, the prefix, the plan) and holds the whole list in its arguments. Approved: five creates at a time, each stamped with private markers; per-item results; one reply card with "Undo all" and "Retry the N". A run repeated adds nothing twice (by number, and for an unnumbered list sent again with the batch id, by what JARVIS wrote). `calendar_undo_events` (R2, `ask_when` always) removes the batch's events he has not changed, each through the existing undo-able delete (Recently deleted, 30 days). A brain that still makes many single `calendar_create_event` calls in one round is gathered into one batch card (`calendar_batch.gathered`, used by `Brain._run_calls`). |
| O2b | A followed series: check-in, done / skipped, re-plan | `src/jarvis/series/` (`models`, `store`, `service`, `replan`, `calendar`, `cards`, `tools`, `job`, `phrases`, `privacy`, `brief`, `part`), `api/fix_plan.py` | **Built.** With `series {name}` the approved batch is remembered in `series/{uid}` (≤ 10 plans, ≤ 200 sessions). The clock job `series_checkin` asks once per session, 15 minutes after it ends (a claim in `series_told` before the alert; kind `series_checkin`; held at night, never dropped; no model). `series_checkin {answer}` marks done or skipped (a spoken answer runs without a card); "skipped" proposes `series_reschedule` through the gateway: ONE card listing every "old date → new date", with the count before and after. `replan.verify` refuses in code any re-plan that would lose, double-book, reorder or back-date a session, before the card and again when it runs. No-AI phrases included. |
| O12 | The whole inbox, counted and grouped | `tools/gmail_digest.py` (`gmail_inbox_summary`, `read_inbox`), `brief/collect.py`, `brief/render.py` | **Built for the tool and the brief's own read; the brief's grouped lines wait for §3.4.** Unread count from the INBOX label (one call, exact); at most `mail_summary_max_reads` (30) metadata reads of the last 7 days across every category; groups People, Bills and orders, Updates (listed), Promotions, Social and forums (counted only). Codes and bank messages are withheld by the existing `spoken_sensitive` rule and what is kept is masked. The brief's collector can read through `tools/background.py` (the "Search and read email" row: "Never" and "Ask first" mean no read), once I1 passes it the reader (§3.4). |
| D0 | Console pieces, look unchanged | `console-r111-plan.js` / `.css` (24 lines), small hooks in `console-approvals.js` and `console-media.js`, "Inbox by kind" in `console-brief-sections.js` | **Built.** The batch card's scrolling list of every event, the re-plan card's list of moves, the check-in question with Done / Skipped above Approvals, "Propose new dates", and the reply card with "Undo all" (armed by a first tap, run by a second) and "Retry the N". Existing classes and tokens only; `textContent` only; ASCII source. |
| — | Eval | `evals/r11_1/plan.py` | **Built**, `BUILT = True`: 24 cases, four negative controls (§2). |

Routes (`api/fix_plan.py`, owner-only, `no-store`, changes limited to 30 a minute per owner; every
action is a tool call through `app.state.gateway`): `GET /v1/series`, `POST /v1/series/answer`,
`POST /v1/series/replan`, `POST /v1/series/batches/retry`, `POST /v1/series/batches/{id}/undo`.

Works, or says plainly why not:

- **No-AI mode.** The check-in job, the two buttons, "Undo all", "Retry", the phrases ("session
  done", "session 7 skipped", "show my plans", "re-plan my sessions") use no model. Approving a
  card answers with the tool's own sentence ("58 events added, 2 failed, Sir.": `finish.said_by_code`).
  Making a batch from a file needs the AI: No-AI mode answers as it does for any such request.
- **Laptop off.** Nothing in Part A uses the laptop.
- **Google not linked.** No card is made: "Google is not linked, Sir. Link it in Integrations, then
  ask again." (batch, undo, retry); a skipped session is still recorded and says "Google is not
  linked, Sir, so I can't look at your calendar."; the inbox says "Google is not linked, Sir. Link it
  in Integrations to see your inbox."
- **Past the monthly limit.** The one retry is admitted like any call; refused, the reply is the
  cut-off line. The check-in, the buttons and Undo use no model. An approved card answers with the
  tool's own sentence.
- **Google tools off on the server** (outside dev: no Google client, or no key to keep its
  tokens). The part offers no tool and runs no job; `GET /v1/series` says "off: Google is not set
  up on this server" and every press answers `plans_off`. The privacy row stays.

Security choices worth a reviewer's eye (in the order I would read them):

1. **"Undo all" (`api/fix_plan.undo`, D21-A).** `calendar_undo_events` always asks, so the model can
   never run it without a card. The owner's own press proposes that card in the route's own scope
   (`<uid>:plan`, never a conversation's) and approves it in the same request under
   `approved_via("owner: Undo all")` and `presenting_proof(None)`: policy, the owner's rows, the
   approval guard and the audit all apply ("awaiting_confirmation", then "confirmed; owner: Undo
   all"). A refusing guard leaves nothing removed and no card. It then withdraws his other waiting
   cards that ask to remove the same batch. This is the one place where a request approves a card
   it has just proposed.
2. **The nested proposal in `series_checkin`** (`series/tools._propose`): a tool that ran calls
   `gateway.execute(series_reschedule, …)` in the same scope to PROPOSE a card. It can only ever
   propose (`ask_when` always); the card's text comes from a read-only look-up, and the gateway
   looks again when it is approved.
3. **Retry from the browser** (`/v1/series/batches/retry`): the events come back from the page, so
   the card is made as in a round that read outside words (`context_trust(untrusted=True)`: the
   events carry the outside mark) and every field is checked again by the tool.
4. **`calendar_batch.gathered`**: more than three valid single creates without guests in one round
   become one batch call (one card); the others are answered "on the single approval card". A call
   with a guest or a bad field is left as it was.
5. **A cut-off answer's tool calls never run** (`finish.unfinished`): an answer that stopped at the
   cap may hold half-written arguments.
6. **The brief's inbox read** (`brief/collect.Collector(reads=…)`) and the withholding of codes
   and bank mail: in the categories the brief did not show before, a message that looks like a
   code or a bank message is not listed and its preview never reaches the AI. Primary mail is listed
   as it has been since slice 7 (`AS_BEFORE`).
7. **Words.** Alerts, card heads and results are fixed templates by code: numbers, dates, the
   plan's name only when it is his own typed word (`Plan.words`; a plan made in a round that read a
   file is "your plan"). A re-plan that could not be proposed repeats only JARVIS's own reasons
   (`series/tools.own_reason`), never a connector's error text. Results never carry a title.

## 2. How to check it

Run as the brief says (from the checkout, `PYTHONPATH=$PWD/src`, heavy commands behind its lock):

```
pytest -q -p no:cacheprovider tests/test_r11_1_a_*.py                       # 177 passed
pytest -q -p no:cacheprovider tests/test_r11_1_seams.py tests/test_r1_seams.py \
  tests/test_r6_wiring_seams.py tests/test_arch_coverage.py \
  tests/test_r51_console_assets_linked.py                                    # all pass
python evals/r11_1/run.py --mock --part plan                                # 24/24; control fails
python evals/brief/run.py --mock                                            # GATE: PASS
JARVIS_BROWSER_TESTS=1 python -m pytest -q tests/browser -m browser -k "r11_1 or ui_audit"   # 120 passed
ruff check src tests evals scripts && ruff format --check src tests evals scripts           # clean
mypy src                                                                    # the 9 old errors only
python scripts/arch_coverage.py && python scripts/check_doc_versions.py     # OK; all documents versioned
```

The whole unit suite on the final code (`pytest tests`): 12,063 passed, 112 skipped, 6 failed, 5
errors. Two failures are R11 wiring assertions that the plan's clock job changes by design
(§3.1b, with the checked diff). The other four failures and the five errors are there on
`r11-1-i0` already (§3.11; checked on an export of 9250be1). An earlier run of the suite found
one failure that was Part A's and is fixed: a server without Google still offered the batch and
inbox tools (`tests/test_web_auth.py`, now 21 passed).

The eval's four controls, each of which must fail a case of its own observation (else the part
reports "too weak" and the suite does not count as failed):

| Control | What it restores | Cases it fails |
|---|---|---|
| `filler` | `reply = completion.text or FILLER`, no retry | all seven `o1-*` |
| `singles` | many single creates are not gathered | `o1-sixty-single-calls-one-card` |
| `drop_last` | `replan.build` loses its last session | `o2b-skip-7-moves-54-count-stays-60`, `o2b-busy-evening-avoided`, `o2b-no-ai-answer` |
| `primary` | `is:unread in:inbox category:primary newer_than:1d` | `o12-every-category-counted`, `o12-code-withheld`, `o12-brief-counts-the-whole-inbox` |

Coverage (coverage.py over `tests/test_r11_1_a_*.py` and the brief's own tests): `core/finish.py`
100 %, `tools/calendar_batch.py` 97 %, `src/jarvis/series/` 88–100 % per module, `tools/gmail_digest.py`
95 %, `brief/collect.py` 93 %, `api/fix_plan.py` 86 %. New modules ≤ 400 lines (`api/fix_plan.py` 395,
`tools/calendar_batch.py` 377, `series/service.py` 370, `series/batch.py` 368); `core/brain.py` 741
(779 at R11; seam guard ≤ 770); the stylesheet 24 lines. Functions ≤ 50 lines in every new module.
In `core/brain.py` four functions were over 50 before R11.1 and still are: `_run_loop` 55 (61
before), `_chat` 51 (59), `__init__` 51 (51) and `_chat_stream` 67 (62: five lines longer).

## 3. Needs I1

### 3.1 Two seam assertions (`tests/test_r11_1_seams.py`)

`finish.FILLER` is kept only as an alias of the new line so the I0 seam still passes. After this
diff, delete `FILLER = EMPTY` and its `__all__` entry from `core/finish.py`.

```diff
@@ test_... (l.226)
-    assert finish.reply_text(_completion("")) == finish.FILLER  # I0: unchanged; Part A replaces it
+    assert finish.reply_text(_completion("")) == finish.EMPTY  # R11.1 A: a plain sentence, by code
+    assert finish.OLD_FILLER not in finish.EMPTY
@@ test_the_eval_runner_passes_with_every_part_still_a_stub (l.364)   # once all four parts are built
-    assert "not built yet" in run.stdout
+    assert "not built yet" not in run.stdout
```

### 3.1b Three assertions in `tests/test_r11_wiring.py` (the plan's job rides the helpers' clock)

By design (`r11_1_wiring`: "the parts' clock and daily jobs ride the helpers' two composites"),
`series_checkin` is now on `helpers_clock`, and two R11 wiring tests pin the clock's exact job
list. Checked in place: with this diff the file passes on this branch (13 passed); the file was
then restored untouched. Part C's two jobs will need the same once it is built.

```diff
+from jarvis.api.r11_1_wiring import fix_clock_jobs
@@ test_the_helpers_start_with_four_empty_parts_and_both_composites (l.76)
         jobs = st.helpers_clock.job_names
-        assert sorted(jobs) == sorted(j for p in PARTS for j in CLOCK_JOBS[p]), jobs
+        fixes = {j.name for j in fix_clock_jobs(a)}  # R11.1: the parts' jobs ride the same clock
+        assert sorted(set(jobs) - fixes) == sorted(j for p in PARTS for j in CLOCK_JOBS[p]), jobs
+        assert "series_checkin" in fixes
@@ test_a_failing_part_is_left_empty_and_the_others_run (l.157, l.170)
-        assert st.helpers_clock.job_names == ("bills_due",)
+        assert st.helpers_clock.job_names == ("bills_due", "series_checkin")
-        assert status is not None and status["jobs"] == {"bills_due": "ok"}
+        assert status is not None and status["jobs"] == {"bills_due": "ok", "series_checkin": "ok"}
```

### 3.2 A slot for a part's No-AI phrases (`api/r11_1_wiring.py`, `api/r11_wiring.py`)

`FixPart` has no `phrases` field, so the plan's phrases go into `BrainMode` lazily
(`services["ensure"]`: the clock job's every run and every `/v1/series` request call it; it adds
`route` once). Until the first of those after a start, "session done" in No-AI mode is not
recognised. The slot:

```diff
# src/jarvis/api/r11_1_wiring.py
+def fix_phrases(app: FastAPI) -> tuple[Any, ...]:
+    """The parts' No-AI routers (`BrainMode.add_phrases`), for `r11_wiring._wire`."""
+    return tuple(r for p in _parts(app).values() for r in p.services.get("phrases", ()))
# src/jarvis/api/r11_wiring.py  (_wire, after the helpers' own phrases)
     if mode is not None:
         mode.add_phrases([r for p in parts.values() for r in p.phrases])
+        mode.add_phrases([r for r in fix_phrases(app) if r not in mode.phrases])
```

With the helpers switched off `_wire` does not run; the lazy `ensure` then still does the job.

### 3.3 The brief's line for open check-ins (`api/r11_wiring.helpers_brief`)

D6: unanswered sessions are asked again in the brief's Helpers lines, never nagged.
`series.brief.PlansBrief` is a `helpers.ports.BriefContributor` ("2 planned sessions have no
check-in: say 'session done' or 'session skipped'."), at `r111_parts["plan"].services["brief"]`:

```diff
     def contributors() -> list[Any]:
-        return [c for p in parts() for c in p.brief]
+        fixes = (getattr(st, "r111_parts", None) or {}).values()
+        extra = [c for p in fixes if (c := p.services.get("brief")) is not None]
+        return [*(c for p in parts() for c in p.brief), *extra]
```

### 3.4 The brief's inbox: the model's fields and the governed read

`brief/models.py` is not Part A's file. `brief/collect.shape_inbox` already passes the three
fields (`InboxSection.model_validate` drops them today); `brief/render.py` and
`console-brief-sections.js` already draw them when they are there
(`tests/test_r11_1_a_inbox.py::test_the_groups_are_read_once_and_light_up_a_wider_inbox_section`).

```diff
# src/jarvis/brief/models.py
+class InboxGroup(Frozen):
+    key: str
+    label: str
+    unread: int = 0
+
 class InboxSection(Frozen):
     total: int = 0
     items: tuple[InboxItem, ...] = ()
+    groups: tuple[InboxGroup, ...] = ()  # R11.1 D20: Gmail's own categories, counted
+    withheld: int = 0  # not listed: they look like a code or a bank message
+    exact: bool = True  # False: the INBOX label could not be read; `total` is what was read
# src/jarvis/brief/service.py  (BriefService.__init__)
+        reads: BackgroundReads | None = None,
+        mail_max_reads: int = 30,
-        self._collector = Collector(google, approvals)
+        self._collector = Collector(google, approvals, reads=reads, max_reads=mail_max_reads)
# src/jarvis/api/app.py  (build_brief_service)
+        # R11.1 D20: the brief's inbox read obeys the "Search and read email" row
+        reads=BackgroundReads(lambda: getattr(app.state, "gateway", None), audit=audit),
+        mail_max_reads=s.mail_summary_max_reads,
```

Until then the brief reads the whole inbox (count, people, bills, updates) but without the row
check, exactly as its Primary-only read did before, and shows no group line. With the reader in
place a "Never" or "Ask first" row gives the section state `unavailable` ("Couldn't read your mail
just now."); a "paused by your Permissions" wording would need a section state of its own.

### 3.5 Two sentences that still say "Primary" or "the last day"

```diff
# src/jarvis/brief/summarize.py:120
-        f"Unread mail ({box.total} in the last day; all of it written by other people):\n{body}\n"
+        f"Unread mail ({box.total} unread in the inbox; all of it written by other people):\n{body}\n"
# src/jarvis/api/static/console-brief.js:446
-    if (!msgs.length) { s.append(mk('p', 'bempty', 'No unread mail in Primary from the last day.')); return s; }
+    if (!msgs.length) { s.append(mk('p', 'bempty', total ? 'None of them is from a person, a bill or an update of the last 7 days.' : 'No unread mail in your inbox.')); return s; }
```

### 3.6 Persona sentences (Part D owns `core/prompts.py`)

The tool descriptions already say this; the persona makes it hold on weaker brains:

- "More than three calendar events in one request: one `calendar_create_events` call, never many
  single calls. When they are sessions of a plan to follow, give `series: {name}` and a
  `title_prefix`."
- "When the owner says a planned session happened or was skipped, call `series_checkin`. Never
  move sessions yourself: `series_reschedule` puts the new dates on one approval card."
- "To see all unread mail, by kind: `gmail_inbox_summary`."

### 3.7 Recently deleted lists 50 (`undo/store.MAX_LISTED`)

An "Undo all" of 60 puts 60 items in Recently deleted; the panel lists the newest 50. All 60 can
be restored (by id), but ten are not on the list. Raise `MAX_LISTED` to 100 (a batch's maximum), or
page the panel.

### 3.8 Approve all's plain reply (`core/approve_all.py`)

A single approved card now answers with the tool's own sentence when no model can narrate
(`finish.said_by_code`, used in `Brain._decide_locked`). Approve all words its own plain reply
(`_said`: "Done, Sir: <the card's first line>."), so a batch card approved with Approve all in
No-AI mode still reads "Done, Sir: Add 60 events to your calendar: …" when 2 of the 60 failed (the
reply card under it shows the true count). Use `finish.said_by_code(tool, result)` there too.

### 3.9 A card proposed outside a conversation cannot be approved (R11, found here)

A card proposed under a scope whose second part is not a stored conversation (R11's kitchen blocks:
`<uid>:helpers_kitchen`) cannot be approved in Approvals: `Brain.approve` loads the conversation
and raises `SessionNotFound`. Part A's routes therefore always put a card into a real
conversation (the open one, or a new one). The kitchen's "Ask to add to my calendar" needs the same.

### 3.10 Telegram shows only the card's label (`telegram/service.py`)

D4 says Telegram shows the count and the range and "open JARVIS to see the list". Telegram's own
rule (`_fits`) shows a card's words only when they are one short line, so the batch card and the
re-plan card (several lines) arrive as "Approve in the console (too long to show here): calendar
create events". That is the safe side (the list is judged where all of it shows), but the count
and range are missing. Their first line is written by code alone and fits; show it, still with no
button:

```diff
+HEAD_BY_CODE = frozenset({"calendar_create_events", "calendar_undo_events", "series_reschedule"})
+OPEN_TO_APPROVE = "Open JARVIS to see the full list and approve it."
             if card.tool_risk == ActionRisk.REVERSIBLE.value:  # too long to judge on a phone
-                await self._say(link.chat_id, CONSOLE_FIRST + label)
+                head = card.summary.strip().splitlines()[0] if card.tool in HEAD_BY_CODE else ""
+                words = f"{head} {OPEN_TO_APPROVE}" if _fits(head) else CONSOLE_FIRST + label
+                await self._say(link.chat_id, words)
```

### 3.11 For the record

- `tests/test_evals_brief.py` runs `evals/brief/run.py` in a subprocess. In a worktree it imports the
  main checkout's `jarvis` unless `PYTHONPATH=$PWD/src` is set (the venv's install points there);
  with it, it passes. Nothing to change in the repository.
- `tests/test_trust_flag.py::test_a_chat_request_carries_no_history_or_blocks` fails on `r11-1-i0`
  already (`ChatRequest.heard`, Part B's seam); not Part A's.
- The build book's generator has no layer for the five packages I0 added (`fixes`, `series`,
  `understand`, `facegroups`, `picture`), and its plan test still expects R11's plan to be the
  newest: `tests/test_book_gen_code.py`, `test_book_gen_determinism.py`, `test_book_gen_plans.py`
  and the five `tests/test_r6_show_facts.py` set-ups fail on `r11-1-i0` already. For Part A's
  package, in `buildbook/gen/layers.py`: `"series": "L5",  # R11.1: a followed series of calendar
  sessions` (`fixes` holds only the parts' contract: L3 with `ticks`, or wherever I1 puts it).

## 4. Owner checks (after deploy)

1. Attach a 60-row plan (CSV) and say "add these to my calendar as my CCA study plan". Expect ONE
   card in Approvals with a scrolling list of 60 lines; approve; expect "All 60 events are in your
   calendar, Sir." and a card under the reply with "Undo all".
2. Twenty minutes after a session ends, expect one alert: "Session 1 of 60 in your CCA plan was at
   19:00. Did it happen, Sir? Say 'session done' or 'session skipped'." At night it waits until
   morning.
3. Say "session skipped" (or press Skipped above Approvals). Expect one card "Move N sessions of
   your CCA plan to their next free slots (session 1 was skipped). 60 sessions before, 60 after:
   none is dropped." with every old and new date. Nothing moves until you approve. A card runs
   out after ten minutes; "Propose new dates" brings it back.
4. Press "Undo all" under the batch reply, twice (the first tap only arms it). Expect "Removed 60
   events, Sir. Each is in Recently deleted for 30 days." An event you changed yourself stays.
5. Ask "what is in my inbox?". Expect Gmail's own unread number and counts by kind; no one-time
   code read out.
6. Switch to No-AI mode and say "session done". Expect "Session N of 60 in your CCA plan is marked
   done, Sir." with no AI call.

## 5. Decisions and departures from the plan

| # | The plan said | What was built, and why |
|---|---|---|
| 1 | One marker `jarvisBatch = <id>:<n>` (D5) | Two more private markers: `jarvisBatchId` (Google's filter matches a whole value, so a batch is listed by its id) and `jarvisBatchSig` (a fingerprint of what JARVIS wrote: an event you changed since is told apart from Google tidying spaces or zones). |
| 2 | A retry lists by the marker (D5) | The batch id is derived from owner + the list, so the same list is the same batch without the model remembering an id. An unnumbered list sent again WITH the id is matched by what JARVIS wrote. Found by the eval: it had been added twice. |
| 3 | The model is told "more than three → the batch tool" (D4) | Also enforced: `gathered()` turns many single calls of one round into one batch card. The root cause of O1 was exactly a brain that did not follow the description. |
| 4 | An empty or cut-off answer is retried once (D2) | Only an answer the cap cut off is retried; a finished empty answer goes straight to its fixed line (a second identical call would cost and say nothing new). A cut-off answer's tool calls never run. The fixed lines combine (cards + steps + cut off) so what happened is never hidden. |
| 5 | The alert names the plan (D6) | Only when the name is your own typed word. A plan made in a round that read a file is "your plan" in alerts, cards and results, and its name is blank in `/v1/series`. |
| 6 | The check-in is asked once (D6) | Once, and only within 24 hours of the session's end; older ones are in the console and the brief's line. If the alert could not be sent, the claim is given back and a later run asks. |
| 7 | "Skipped" moves that session and every later one (D6) | Later sessions that have not started. A past session with no answer stays where it is and keeps waiting for its answer. |
| 8 | `series/{uid}` (D6) | One document per owner holds all plans (≤ 10 × 200 sessions, well under the document limit), changed in a transaction. |
| 9 | `series_reschedule` lists every move (D6) | Its arguments are `{series, session}`; the moves are computed by the read-only look-up that writes the card, and again when it is approved (a calendar that changed since withdraws the card). The console lists the moves from the card's own lines. |
| 10 | "Undo all" as today's Undo presses (D21-A) | Today's presses restore through an owner-only route outside the gateway. The brief requires R11.1 routes to act through the gateway, so the press proposes and approves the always-asking tool's card in one request (§1, security 1). |
| 11 | One-time codes withheld "exactly as today" (D20) | In the newly shown categories. Primary mail on the brief is listed unfiltered, as it has been; the tool `gmail_inbox_summary` withholds in every category. |
| 12 | Telegram shows the count and the range (D4) | Not yet: Telegram's own rule shows a several-line card only by its label and sends you to the console (§3.10 has the two-line change). |
| 12a | — | "Undo all" needs two taps (armed, then run): one tap must not remove up to 100 events. |
| 12b | The batch and the inbox summary "work without plans" | Outside dev, on a server where the Google tools are off (no Google client, or no key to keep its tokens), the part offers no tool and runs no job, and says "off: Google is not set up on this server": the existing rule that such a server offers no `calendar_*` / `gmail_*` tool (`tests/test_web_auth.py`). Its privacy row stays. |
| 13 | — | An approved card answers with the tool's own sentence when no model can narrate (`finish.said_by_code`), for the four plan tools only. |
| 14 | — | A conversation id sent by the page that is gone or not yours is never used and never loses a press: a new conversation of yours holds the card. |

## 6. Existing tests and fixtures changed on purpose

| File | What changed | Why |
|---|---|---|
| `tests/test_brief_collect.py` | the inbox query constant and `maxResults == "30"` | D20: the whole inbox, 30 reads |
| `tests/test_brief_render.py` | two inbox strings ("INBOX · N unread (showing k)", the empty lines) | D20 |
| `evals/brief/cases_compose.jsonl` | c08 and c10: the same two strings | D20 |

No test was weakened. No existing test pinned the old filler.

## 7. Not verified live

- No real Google: the batch, the markers, the PATCH moves, the INBOX label count and the category
  labels ran against `tests/r11_1_fakes_a.PlanGoogle` only. *Unverified* on a real calendar:
  `privateExtendedProperty` filtering at 100 events, and Google's rate limits at five writes at a
  time (a refused create is reported by item and can be retried).
- No real model: the cut-off and empty answers are scripted (`stop_reason` `max_tokens`). How often
  a real brain still makes single calls, and whether it passes `series {name}` unasked, is
  *unverified* (§3.6).
- No real Telegram or push: the check-in went to a fake notifier.
- The console was checked in headless Chromium with mocked routes (§2), not on a phone.
- The brief's group line and the governed read were tested on the collector and a widened model;
  the deployed brief shows them only after §3.4.

## 8. Test-first evidence

Each behaviour has a test that was written and seen to fail first; the ones that found real gaps:
`test_a_brain_that_makes_sixty_single_calls_still_ends_in_one_card` (until `gathered` was wired),
`test_a_re_plan_that_would_lose_a_session_is_refused_in_code` (a dropped session was still
proposed until `verify` ran inside `proposal`),
`test_the_whole_list_sent_again_with_the_batch_id_adds_nothing_twice` (it was added twice),
`test_a_card_goes_into_the_open_conversation_when_there_is_one` (a second press made a second
card), `test_an_approved_batch_says_its_own_count_when_no_model_can_report_it` ("Done, Sir: Add 5
events" for 4 of 5).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 09:25 IST | R11.1 | First edition: Part A built (O1, O2, O2b, O12, the console pieces, the eval with four controls), how to check it, Needs I1, owner checks, departures, what is not verified live | 🛠 Mark XV |
