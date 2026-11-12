Version v11.1.2 · 12 Nov 2026, 10:42 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 Part A · Brain and calendar — integration note for I1

Branch `r11-1-a` (from `r11-1-i0` @ 9250be1). Observations O1, O2, O2b and O12 of
`docs/plans/r11-1-observations.md` (decisions D0–D7, D20, D21-A). Everything is in Part A's own files:
no wiring file, no seam test and nothing on the brief's never-edit list was touched. What Part A
needs from those files is in §3, each with the exact diff.

**Two merge gates (v11.1.2, after three fresh-context reviews; §9 lists every finding).** I1 must
not merge Part A without both, each with the test written out in full here, which passes with the
diff and fails without it (checked on a copy of this branch outside git):

- **GATE 3.12** (security HIGH-1): `gmail_inbox_summary` joins Telegram's private reads, and
  the R11.1 parts' tools join the Telegram guard test.
- **GATE 3.4** (security MEDIUM-1, silent-failure H3): the brief's `InboxSection` gains its five
  fields and the real `BriefService` reads mail through the governed path.

## 1. What was built

| Obs. | What you asked for | Where | State |
|---|---|---|---|
| O1 | No reply is ever "I have nothing to add, Sir." | `core/finish.py` (new logic), `core/brain.py`, `core/window.py`, `core/rounds.py` | **Built.** A turn that works with tools or attached files may write `work_output_tokens` (`finish.output_cap`, `working_turn`; a plain reply, an approval's narration and a training brain keep 1,024). An answer the cap cut off with no usable words is asked for ONCE more (`finish.asked` / `retried`, `empty_reply_retries`) with the fixed instruction and the working cap (a training brain keeps its own: `Tries.boost`), admitted and metered like any call; its half-written tool calls never run and it is never stored. **Fail safe:** any stop reason other than `end_turn`, `tool_use`, `stop` or `stop_sequence` counts as cut off. Still nothing: a fixed line chosen by code from what happened (approvals waiting, steps that ran, steps that failed, cut off, simply empty): "I did 2 steps and 1 failed, but ...". The same on the round-limit summary call and on the stream (`finish.StreamMeter`, `stream_end`; a stream that simply ended empty is not asked again, D2). The fixed lines live in the leaf `core/fixed_lines.py`; one is stored marked `tool_derived` and `core/window.py` leaves it, and every stored old filler turn, out of every model's window. `_chat`, `_run_loop` and `_chat_stream` are under 50 lines; `brain.py` 741 → 704. |
| O2 | Many calendar events on one approval | `tools/calendar_batch.py` (pure rules), `series/batch.py` (the run), `series/batch_result.py`, `tools/calendar_cards.py`, `tools/reply_cards.py` (`BatchCard`) | **Built.** `calendar_create_events` (1–100 events, no guests) is R2 with `ask_when` always: ONE card whatever the row says, typed or spoken, tainted round or not. The card is written by code (how many, first and last date, the prefix, the plan) and holds the whole list in its arguments. Approved: five creates at a time, each stamped with private markers; per-item results; one reply card with "Undo all" and "Retry the N". A run repeated adds nothing twice (by number, and for an unnumbered list sent again with the batch id, by what JARVIS wrote). `calendar_undo_events` (R2, `ask_when` always) removes the batch's events he has not changed, each through the existing undo-able delete (Recently deleted, 30 days). A brain that still makes many single `calendar_create_event` calls in one round is gathered into one batch card (`tools/calendar_gather.gathered`, used by `Brain._run_calls`); a call the batch's own limits refuse is answered alone with its reason, the good ones still go on the card. **The card shows what it will write:** its text says how many events carry a description or alerts and, from a round that read a file, that other people's words wrote them; repeated events are flagged; the console lists each event's description (120 characters, "…more", text only, a link as "[link: host]") and alerts. An event Google did not confirm is "not confirmed", never "failed"; an event he recoloured or gave a video link or attachment counts as his. |
| O2b | A followed series: check-in, done / skipped, re-plan | `src/jarvis/series/` (`models`, `store`, `service`, `replan`, `calendar`, `cards`, `tools`, `job`, `phrases`, `privacy`, `brief`, `part`), `api/fix_plan.py` | **Built.** With `series {name}` the approved batch is remembered in `series/{uid}` (≤ 10 plans, ≤ 200 sessions). The clock job `series_checkin` asks once per session, 15 minutes after it ends (a claim in `series_told` before the alert; kind `series_checkin`; held at night, never dropped; no model). `series_checkin {answer}` marks done or skipped (a spoken answer runs without a card); "skipped" proposes `series_reschedule` through the gateway: ONE card listing every "old date → new date", with the count before and after. `replan.verify` refuses in code any re-plan that would lose, double-book, reorder or back-date a session, before the card and again when it runs. No-AI phrases included. **The plan follows his calendar** (`series/sync.py`): before a check-in the session's event is read once (a session he deleted by hand is `removed` and never asked; one he moved takes the new time); a re-plan first brings the plan up to date, plans around the sessions that stay at their real times, leaves out the ones he placed himself or that now have guests or repeat (named on the card and in the result), moves every skipped session that has no new date yet, and shows and patches only the moves that change a time. Applying it (`series/moving.py`): a patch whose answer was lost is read again ("Google didn't confirm 1"); a plan record that could not be updated after the calendar moved is said. A check-in that reached nobody (dropped, no channel, an error, a cancelled send) gives its claim back and counts "failed". |
| O12 | The whole inbox, counted and grouped | `tools/gmail_digest.py` (`gmail_inbox_summary`, `read_inbox`), `brief/collect.py`, `brief/render.py` | **Built for the tool and the brief's own read; the brief's grouped lines wait for §3.4.** Unread count from the INBOX label (one call, exact); at most `mail_summary_max_reads` (30) metadata reads of the last 7 days across every category; groups People, Bills and orders, Updates (listed), Promotions, Social and forums (counted only). Codes and bank messages are withheld by the existing `spoken_sensitive` rule **in every category, Primary included** (never listed, their preview never reaches the summariser; their number is kept) and what is kept is masked. Messages that could not be read are counted and logged by class name: "I couldn't read 3 of the 10 newest unread messages just now", never "none of them is from a person"; a missing Gmail count is "about N". The brief's collector can read through `tools/background.py` (the "Search and read email" row: "Never" and "Ask first" mean no read), once I1 passes it the reader (§3.4). |
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
4. **`calendar_gather.gathered`**: more than three valid single creates without guests in one round
   become one batch call (one card); the others are answered "on the single approval card" (or
   "that batch was not made" when it was not). A call with a guest, or invalid for the single
   tool, is left as it was; one the batch's own limits refuse is answered alone with its reason.
5. **A cut-off answer's tool calls never run** (`finish.unfinished`): an answer that stopped at the
   cap may hold half-written arguments.
6. **The brief's inbox read** (`brief/collect.Collector(reads=…)`, GATE 3.4) and the
   withholding of codes and bank mail: in every category, Primary included, a message that looks
   like a code or a bank message is not listed and its preview never reaches the AI.
7. **Words.** Alerts, card heads and results are fixed templates by code: numbers, dates, the
   plan's name only when it is his own typed word (`Plan.words`; a plan made in a round that read a
   file is "your plan"). A re-plan that could not be proposed repeats only JARVIS's own reasons
   (`series/tools.own_reason`, which accepts only the gateway's own fixed words, whole), never a
   connector's error text. Results never carry a title.
8. **The batch card's contents** (security MEDIUM-3): every field a batch writes is shown before
   the approval: the card counts descriptions and alerts and says when a file wrote them; the
   console lists each, as text. Telegram still only points to the console (§3.10).

## 2. How to check it

Run as the brief says (from the checkout, `PYTHONPATH=$PWD/src`, heavy commands behind its lock):

```
pytest -q -p no:cacheprovider tests/test_r11_1_a_*.py                       # 244 passed
pytest -q -p no:cacheprovider tests/test_r11_1_seams.py tests/test_r1_seams.py \
  tests/test_r6_wiring_seams.py tests/test_arch_coverage.py \
  tests/test_r51_console_assets_linked.py                                    # all pass
python evals/r11_1/run.py --mock --part plan                                # 24/24; control fails
python evals/brief/run.py --mock                                            # GATE: PASS
JARVIS_BROWSER_TESTS=1 python -m pytest -q tests/browser -m browser -k "r11_1_a or ui_audit" # 124 passed
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

v11.1.2 (after the reviews' fixes): A's tests, the existing tests of A's files and the brief's
guard tests together (81 files): 2,798 passed, 2 failed: the two failures that are there on
`r11-1-i0` already (`test_book_gen_code` and `test_trust_flag`, §3.11). The plan eval 24/24 with
its control failing it; the brief eval GATE: PASS; ruff and ruff format clean; `mypy src` the 9 old
errors only; `arch_coverage` and `check_doc_versions` OK.

Coverage was measured at v11.1.1 (coverage.py over `tests/test_r11_1_a_*.py` and the brief's own
tests): `core/finish.py` 100 %, `tools/calendar_batch.py` 97 %, `src/jarvis/series/` 88–100 % per
module, `tools/gmail_digest.py` 95 %, `brief/collect.py` 93 %, `api/fix_plan.py` 86 %. It was **not
re-measured** for v11.1.2: coverage.py is not installed in the shared environments, and nothing
was installed. Every new branch of v11.1.2 has a test that was seen to fail first (§8, §9).
Module sizes: every new module ≤ 400 lines (`api/fix_plan.py` 400, `series/service.py` 385,
`core/finish.py` 376, `series/batch.py` 340, `tools/calendar_batch.py` 337); `core/brain.py` 704;
the stylesheet 27 lines. Functions ≤ 50 lines in every new module; in `core/brain.py` only
`__init__` (51, as before R11.1) is over; `tools/gmail_digest.DigestAPI.digest` (58) is R1's.

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

### 3.4 **GATE**: the brief's inbox, its model's fields and the governed read

Security MEDIUM-1 and silent-failure H3. Today `BriefService` builds `Collector(google,
approvals)` with no reader, so the 07:00 brief reads the whole inbox **without the "Search and
read email" row**, and `InboxSection` silently drops `groups` / `withheld` / `exact` / `failed` /
`listed` (`model_validate` ignores unknown fields), so the grouped line, the withheld count,
"about N" and "couldn't read N of M" never reach the brief. Part A's collector, renderer and
console already use all five when they are there.

Until this lands, Part A keeps the brief honest on its own: when no listed message could be read
and the section cannot say so, the inbox section is "Your inbox could not be read just now"
(`collect.InboxUncertain`), never "none of them is from a person". The one thing it cannot do
without the fields is say "about N" when Gmail's own count is missing (the estimate is shown as
before).

The exact diff (applied and run on a copy of this branch: the four new tests pass with it and all
four fail without it; with it, the brief, inbox, Part A and Telegram guard tests pass, 591, and
`evals/brief` passes):

```diff
--- a/src/jarvis/brief/models.py
+++ b/src/jarvis/brief/models.py
@@ -121,9 +121,20 @@
     when: str = Field(description="'07:42' or 'yesterday 21:10'")
 
 
+class InboxGroup(Frozen):
+    key: str
+    label: str
+    unread: int = 0
+
+
 class InboxSection(Frozen):
     total: int = 0
     items: tuple[InboxItem, ...] = ()
+    groups: tuple[InboxGroup, ...] = ()  # R11.1 D20: Gmail's own categories, counted
+    withheld: int = 0  # not listed: they look like a code or a bank message
+    exact: bool = True  # False: the INBOX label could not be read; `total` is "about"
+    failed: int = 0  # listed messages that could not be read just now ...
+    listed: int = 0  # ... of these
 
 
 class JarvisSection(Frozen):
--- a/src/jarvis/brief/service.py
+++ b/src/jarvis/brief/service.py
@@ -76,6 +76,7 @@
 from jarvis.llm.router import ModelTier
 from jarvis.logging import get_logger
 from jarvis.tools.audit import AuditTrail
+from jarvis.tools.background import BackgroundReads
 
 log = get_logger(__name__)
 T = TypeVar("T")
@@ -280,10 +281,13 @@
         home_overnight: HomeOvernightBrief | None = None,
         vitals: VitalsSource | None = None,
         helpers: HelpersSource | None = None,
+        reads: BackgroundReads | None = None,
+        mail_max_reads: int = 30,
     ) -> None:
         self._store = store
         self._google = google
-        self._collector = Collector(google, approvals)
+        # R11.1 D20: the inbox read obeys the owner's "Search and read email" row (`reads`)
+        self._collector = Collector(google, approvals, reads=reads, max_reads=mail_max_reads)
         self._summarizer = summarizer or Summarizer(brains)
         self._audit = audit
         self._delivery = InboxDelivery(google, store, audit) if google is not None else None
--- a/src/jarvis/api/app.py
+++ b/src/jarvis/api/app.py
@@ -127,6 +127,7 @@
 from jarvis.telegram.alerts import ALERT_TEXT
 from jarvis.telegram.rules import wrap_rules
 from jarvis.tools.audit import AuditLog, AuditTrail
+from jarvis.tools.background import BackgroundReads
 from jarvis.tools.gateway import Gateway
 from jarvis.tools.r1_tools import build_family_service
 from jarvis.tools.setup import attach_activity, build_gateway
@@ -171,6 +172,9 @@
         ai_daily_cap=s.brief_ai_daily_cap,
         retention_days=s.brief_retention_days,
         billing=getattr(app.state, "billing", None),
+        # R11.1 D20: the brief's inbox read obeys the "Search and read email" row
+        reads=BackgroundReads(lambda: getattr(app.state, "gateway", None), audit=audit),
+        mail_max_reads=s.mail_summary_max_reads,
         # R1 D: Deliveries and Family today (only with the Google link they read through)
         deliveries=DeliveriesBrief(PackageScanner(app.state.google))
         if getattr(app.state, "google", None) is not None
```

The tests I1 adds with it (the real `BriefService`, not the collector alone: "Never" and "Ask first"
on the mail row mean no Gmail read at all; an allowed read brings the groups, the withheld count
and "about N" to the rendered brief; the app's own brief reads through the governed path). The
second hunk is the brief API's pinned shape:

```diff
--- a/tests/test_brief_service.py
+++ b/tests/test_brief_service.py
@@ -72,6 +72,8 @@
     docs: MemoryDocs | None = None,
     ai_cap: int = 6,
     approvals: InMemoryApprovalStore | None = None,
+    messages: list[dict[str, Any]] | None = None,
+    reads: Any = None,
 ) -> Rig:
     fake = BriefGoogle(
         events=[timed("e1", "Standup", "2027-01-15T09:30", "2027-01-15T10:00")],
@@ -83,7 +85,9 @@
                 snippet="please sign",
                 internal_ms=ms("2027-01-15T06:40:00+05:30"),
             )
-        ],
+        ]
+        if messages is None
+        else messages,
     )
     conn = await connector(fake, linked=linked, insert=insert) if configured else None
     docs = docs if docs is not None else MemoryDocs()
@@ -99,6 +103,7 @@
         default_tz="Asia/Kolkata",
         ai_daily_cap=ai_cap,
         clock=clock,
+        reads=reads(conn) if reads is not None else None,
     )
     return Rig(svc, fake, docs, audit, provider, clock, store)
 
@@ -761,3 +766,86 @@
     assert done[-1].outcome == "executed"
     assert "offline=true" in done[-1].detail and "model=qwen2.5:7b" in done[-1].detail
     assert "unknown" not in done[-1].detail
+
+
+# ---- R11.1 I1 gate (INTEGRATION-A 3.4): the real brief reads the whole inbox, as his row says ---
+def _mail_row(effect: Any) -> Any:
+    """BackgroundReads over a gateway whose only tool is gmail_inbox_summary, with his "Search
+    and read email" row set to `effect` (None: the default)."""
+    from jarvis.core.guardrails import ConfirmationGate
+    from jarvis.tools.background import BackgroundReads
+    from jarvis.tools.gateway import Gateway
+    from jarvis.tools.gmail_digest import inbox_tools
+    from jarvis.tools.policy import Policy, PolicyRule
+    from jarvis.tools.registry import ToolRegistry
+
+    def reads(conn: Any) -> Any:
+        reg = ToolRegistry()
+        for t in inbox_tools(lambda: conn, max_reads=30):
+            reg.register(t)
+        rules = (
+            [PolicyRule(tool_pattern="gmail_*", effect=effect, source="owner")] if effect else []
+        )
+
+        class Rows:
+            async def rules_for(self, user_id: str) -> list[Any]:
+                return rules
+
+        gw = Gateway(
+            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=Rows()
+        )
+        return BackgroundReads.of(gw)
+
+    return reads
+
+
+@pytest.mark.parametrize("effect", ["deny", "ask"])
+async def test_r111_never_or_ask_first_on_the_mail_row_means_the_brief_reads_no_mail(
+    effect: str,
+) -> None:
+    from jarvis.tools.policy import Effect
+
+    r = await _rig(reads=_mail_row(Effect(effect)))
+    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
+    b = view.brief
+    assert b is not None and b.data is not None
+    assert [q for q in r.fake.requests if "/gmail/" in q.url.path and q.method == "GET"] == []
+    assert b.data.sections_status.inbox == "unavailable" and "Budget" not in b.text
+    assert b.data.calendar.today[0].title == "Standup"  # the other sections are untouched
+
+
+async def test_r111_an_allowed_read_brings_the_groups_withheld_and_about_n_to_the_brief() -> None:
+    from jarvis.tools.policy import Effect
+
+    otp = mail(
+        "m2",
+        "Bank <alerts@bank.example>",
+        "482913 is your one-time password",
+        snippet="Use OTP 482913 to sign in.",
+        internal_ms=ms("2027-01-15T06:50:00+05:30"),
+    )
+    people = mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2027-01-15T06:40:00+05:30"))
+    r = await _rig(messages=[people, otp], reads=_mail_row(Effect.ALLOW))
+    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
+    b = view.brief
+    assert b is not None and b.data is not None
+    box = b.data.inbox
+    assert box.exact is False and box.withheld == 1 and box.failed == 0  # no INBOX label here
+    assert [(g.key, g.unread) for g in box.groups if g.unread] == [("people", 1)]
+    assert "INBOX · about 2 unread (showing 1)" in b.text
+    assert "Gmail didn't give its own count just now: the number is an estimate." in b.text
+    assert "1 from people" in b.text and "1 more looks like a code or a bank message" in b.text
+    assert "482913" not in b.text and "one-time password" not in b.text
+
+
+async def test_r111_the_app_s_brief_reads_mail_through_the_governed_path(
+    settings: Any,
+) -> None:
+    from jarvis.api import create_app
+    from jarvis.memory.inmemory import InMemorySessionStore
+
+    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
+    async with app.router.lifespan_context(app):
+        collector = app.state.brief._collector  # noqa: SLF001 - the wiring itself is the gate
+        assert collector._reads is not None  # noqa: SLF001
+        assert collector._max_reads == settings.mail_summary_max_reads  # noqa: SLF001
--- a/tests/test_brief_api.py
+++ b/tests/test_brief_api.py
@@ -173,7 +173,15 @@
         "sections_status",
     }
     assert set(b["data"]["calendar"]) == {"today", "clashes", "free_blocks", "tomorrow_first"}
-    assert set(b["data"]["inbox"]) == {"total", "items"}
+    assert set(b["data"]["inbox"]) == {
+        "total",
+        "items",
+        "groups",
+        "withheld",
+        "exact",
+        "failed",
+        "listed",
+    }  # R11.1 D20 (INTEGRATION-A 3.4)
     # slice 10 C: this link has no Tasks scope, so the to-do section says so (and asked nothing)
     assert b["data"]["todo"] is None
     assert b["data"]["sections_status"] == {
```

With the fields in place, a "Never" or "Ask first" row gives the section state `unavailable`
("Your inbox could not be read just now."); a "paused by your Permissions" wording would need a
section state of its own (`brief/models.SectionState`), not part of this gate.

### 3.5 Sentences that still say "Primary" or "the last day", and the console's count

```diff
# src/jarvis/brief/summarize.py:120
-        f"Unread mail ({box.total} in the last day; all of it written by other people):\n{body}\n"
+        f"Unread mail ({box.total} unread in the inbox; all of it written by other people):\n{body}\n"
# src/jarvis/api/static/console-brief.js:445-446 ("about N" and the reads that failed, as the text brief says)
-    const s = section('inbox', 'Inbox', total !== null ? `${total} unread` : '');
-    if (!msgs.length) { s.append(mk('p', 'bempty', 'No unread mail in Primary from the last day.')); return s; }
+    const about = inbox.exact === false ? 'about ' : '';
+    const s = section('inbox', 'Inbox', total !== null ? `${about}${total} unread` : '');
+    const none = num(inbox.failed) ? 'I couldn\u2019t read your newest unread mail just now: see Inbox by kind.'
+      : total ? 'None of them is from a person, a bill or an update of the last 7 days.' : 'No unread mail in your inbox.';
+    if (!msgs.length) { s.append(mk('p', 'bempty', none)); return s; }
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

### 3.12 **GATE**: `gmail_inbox_summary` stays off Telegram unless he allows private reads

Security HIGH-1. `telegram/rules.PRIVATE_PATTERNS` names `gmail_unread_digest` but not
`gmail_inbox_summary`, so on a Telegram turn with private reads off, the new tool would answer
with senders, subjects and first lines of the last 7 days. `tests/test_telegram_tool_guard.py`
did not catch it: its gateway is built without the R11.1 parts. The diff makes the guard test
build every R11.1 part as the app does, so each part's read tool must pick a side (Part A's other
read, `series_list`, is numbers and times only: safe). When B, C and D are merged, their reads
fail this test until each is classified, which is its purpose. Checked on a copy of this
branch: 48 passed with both diffs; without the `rules.py` line, three tests fail.

```diff
--- a/src/jarvis/telegram/rules.py
+++ b/src/jarvis/telegram/rules.py
@@ -42,6 +42,7 @@
     "gmail_search",
     "gmail_read",
     "gmail_unread_digest",
+    "gmail_inbox_summary",  # R11.1 D20: the whole inbox (senders, subjects, first lines)
     "drive_*",
     "doc_*",
     "docs_*",
```

```diff
--- a/tests/test_telegram_tool_guard.py
+++ b/tests/test_telegram_tool_guard.py
@@ -96,11 +96,15 @@
         "recipe_list",
         "recipe_suggest",
         "nutrition_of",
+        # R11.1 I1: his followed plans: counts, numbers and times only (never a title)
+        "series_list",
     }
 )
 # R11 I1: the helpers' reads that stay off Telegram (telegram.rules.PRIVATE_PATTERNS): amounts and
 # UPI IDs, grocery spend, breach notices about his accounts, and his contacts' birthdays
 R11_PRIVATE = ("bill_list", "spend_month", "breach_status", "contacts_birthdays")
+# R11.1 I1: the observation parts' reads of private data (Part A: the whole inbox)
+R111_PRIVATE = ("gmail_inbox_summary",)
 
 
 class DriveTokens(StaticTokens):
@@ -148,9 +152,24 @@
         belongings=BelongingsService(BelongingsStore(docs, ring), undo),
         home=home_parts(docs, ring),  # R3 I1: home, camera and faces tools (the third group)
         r11=r11_parts(google, ring),  # R11 I1: every helper part's tools
+        r111=r111_tools(google, docs),  # R11.1 I1: every observation part's tools
     )
 
 
+def r111_tools(google: Any, docs: Any) -> tuple[Any, ...]:
+    """The four R11.1 parts built on fakes, as the app builds them, so each of their reads must
+    pick a side here too (security review HIGH-1: gmail_inbox_summary was not covered)."""
+    from jarvis.api.r11_1_wiring import build_parts, fix_tools
+    from jarvis.fixes.ports import FixContext
+    from jarvis.tools.audit import AuditLog
+
+    state = {"google": google}
+    ctx = FixContext(
+        s=get_settings(), docs=docs, audit=AuditLog(), state=state.get, notifier=lambda: None
+    )
+    return fix_tools(build_parts(ctx))
+
+
 def r11_parts(google: Any, ring: Keyring) -> dict[str, Any]:
     """The four R11 parts on fakes, linked and sealed, so every one of their reads is listed."""
     from r11_fakes import ctx
@@ -208,6 +227,7 @@
         "drive_read",
         "doc_read",
         *R11_PRIVATE,
+        *R111_PRIVATE,
     ],
 )
 async def test_private_titles_are_denied_on_telegram_by_default(tool: str) -> None:
@@ -382,3 +402,12 @@
     assert "Telegram" in (out.error or "") and "both" in (out.error or "")
     item = await undo.get(UID, ids[kind])
     assert item is not None and not item.restored and item.restoring_since is None
+
+
+async def test_every_r111_part_read_is_registered_and_classified() -> None:
+    """R11.1 I1 gate (INTEGRATION-A 3.12): the parts' tools are in the linked gateway, and every
+    read of private data among them (A: gmail_inbox_summary) is denied on Telegram by default."""
+    reads = read_tools(await linked_gateway())
+    assert set(R111_PRIVATE) <= set(reads)
+    assert await denied_on_telegram(list(R111_PRIVATE)) == set(R111_PRIVATE)
+    assert "series_list" in reads  # the plan part is really there (numbers and times only)
```

### 3.13 `work_output_tokens` may be set where a non-streaming call is refused (`config.py`)

Code review L2. The setting allows 1,024–64,000; a non-streaming Anthropic call asked for more
than about 21,000 output tokens is refused by the vendor's SDK ("streaming is strongly
recommended"), and the tool loop does not stream. The default (8,192) is fine. Lower the maximum
to 32,000 for non-streaming calls, or stream the working calls:

```diff
# src/jarvis/config.py:439
     work_output_tokens: int = Field(
         default=8192,
         ge=1024,
-        le=64_000,
+        le=32_000,  # the tool loop does not stream; above this the vendor refuses the call
# tests/test_r11_1_seams.py:97
-        ("work_output_tokens", 64_001),
+        ("work_output_tokens", 32_001),
```

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
7. Delete one planned session in Google Calendar by hand. Its check-in never comes. Move another
   by hand to the next morning: the check-in asks after the new time.
8. Attach a CSV whose rows carry long notes with a link. The batch card says how many carry a
   description, "written from an attached file or other people's words"; each line in the list
   shows its notes (120 characters, "…more" for the rest) with the link as "[link: host]".
9. On Telegram with private reads off, ask "any unread mail?". Expect the private-reads refusal
   (after GATE 3.12).

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
| 11 | One-time codes withheld "exactly as today" (D20) | v11.1.2: in every category, Primary included, on the brief too (security MEDIUM-2): a code or bank message is never listed and its preview never reaches the summariser; its number is kept. Before, Primary mail on the brief was listed unfiltered (`AS_BEFORE`, removed). |
| 12 | Telegram shows the count and the range (D4) | Not yet: Telegram's own rule shows a several-line card only by its label and sends you to the console (§3.10 has the two-line change). |
| 12a | — | "Undo all" needs two taps (armed, then run): one tap must not remove up to 100 events. |
| 12b | The batch and the inbox summary "work without plans" | Outside dev, on a server where the Google tools are off (no Google client, or no key to keep its tokens), the part offers no tool and runs no job, and says "off: Google is not set up on this server": the existing rule that such a server offers no `calendar_*` / `gmail_*` tool (`tests/test_web_auth.py`). Its privacy row stays. |
| 13 | — | An approved card answers with the tool's own sentence when no model can narrate (`finish.said_by_code`), for the four plan tools only. |
| 14 | — | A conversation id sent by the page that is gone or not yours is never used and never loses a press: a new conversation of yours holds the card. |
| 15 | Session states `planned · done · skipped · moved` (D6) | A fifth, `removed`: he deleted its event in Google Calendar. It is never asked about or moved; the session count stays (the row stays). A session also keeps its batch item number, so a list sent again after a hand deletion fills the old row. |
| 16 | "Skipped" moves that session and every later one (D6) | Also every other skipped session that has no new date yet (a second skip never strands the first). Sessions he placed himself, or that now have guests or repeat, stay where they are and are named; their times count as busy. Only moves that change a time are shown and patched (a gap he left may let later sessions keep theirs). |
| 17 | Unanswered sessions asked again in the brief (D6) | Only those of the last 7 days, so an abandoned plan does not fill every morning. |
| 18 | Cut off = `max_tokens` / `length` (D2) | Fail safe: any stop reason other than `end_turn`, `tool_use`, `stop`, `stop_sequence` is cut off. An answer with no stop reason at all is still judged by its words: several test doubles and some local servers report none, and treating them as cut off would stop their tool calls. |
| 19 | An empty or cut-off answer is retried once (D2) | Kept as built: only a cut-off answer is retried, on the stream too; the docstrings now say so (silent-failure M6). |

## 6. Existing tests and fixtures changed on purpose

| File | What changed | Why |
|---|---|---|
| `tests/test_brief_collect.py` | the inbox query constant and `maxResults == "30"` | D20: the whole inbox, 30 reads |
| `tests/test_brief_render.py` | two inbox strings ("INBOX · N unread (showing k)", the empty lines) | D20 |
| `evals/brief/cases_compose.jsonl` | c08 and c10: the same two strings; v11.1.2: c10's bank statement (`alerts@bank.example`) is now withheld and only its count stays, and its count line reads "25 unread (showing 1)" so it holds before and after GATE 3.4 ("about 25"); c17's subject loses an IP address that the withhold rule now catches in Primary (its purpose, the sender's addr-spec, is unchanged; IP defanging stays tested in `test_brief_render.py`) | D20, security MEDIUM-2 |
| `tests/test_r11_1_a_series.py` (A's own) | the brief's line counts 5, not 7, sessions at the same clock | code review L7: the last 7 days only |

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
- The brief's group line and the governed read were tested on the collector and a widened model,
  and on the real `BriefService` with GATE 3.4 applied to a copy; the deployed brief shows them
  only after GATE 3.4.
- Reconciling a plan with the calendar: a real Google Calendar keeps private extended properties
  through a hand edit and lists a deleted event as gone; *unverified* live (the fake does).
- The batch card's description list was checked in headless Chromium with a hostile list (an
  `<img onerror>`, a link with a user and a port, an RTL mark), not on a phone.

## 8. Test-first evidence

Each behaviour has a test that was written and seen to fail first; the ones that found real gaps:
`test_a_brain_that_makes_sixty_single_calls_still_ends_in_one_card` (until `gathered` was wired),
`test_a_re_plan_that_would_lose_a_session_is_refused_in_code` (a dropped session was still
proposed until `verify` ran inside `proposal`),
`test_the_whole_list_sent_again_with_the_batch_id_adds_nothing_twice` (it was added twice),
`test_a_card_goes_into_the_open_conversation_when_there_is_one` (a second press made a second
card), `test_an_approved_batch_says_its_own_count_when_no_model_can_report_it` ("Done, Sir: Add 5
events" for 4 of 5).

v11.1.2: every fix in §9 has its test, each seen to fail before the fix. Ones that found more than
the review said: `test_a_gap_he_left_absorbs_the_shift_and_later_sessions_keep_their_times` (a
re-plan around a hand-moved session listed 49 moves to the same time), the gated copy of
`test_brief_service.py` (the first wording of "about N" read like a failed section), and
`test_a_retry_s_batch_id_must_be_exactly_a_batch_id` (its first version passed for the wrong
reason).

## 9. The three reviews and what became of each finding (v11.1.2)

Silent-failure (S), security (Sec) and code (C) reviews of `d81fc32`. "I1" items are in §3.

| Review | ID | What | Done | Proving test(s) |
|---|---|---|---|---|
| S | H1 | an undelivered check-in counted as asked | fixed | `test_a_check_in_that_reached_nobody_is_a_failure_and_is_asked_again[no_channel,drop]`, `test_at_night_it_is_held_not_dropped_and_still_asked_only_once` |
| S | H2 | inbox read failures swallowed; "none is from a person" | fixed | `test_messages_that_could_not_be_read_are_counted_and_said`, `test_when_every_read_failed_the_tool_never_says_the_inbox_is_quiet`, `test_an_unread_count_that_could_not_be_read_is_logged`, `test_the_brief_says_how_many_it_could_not_read`, `test_when_no_message_could_be_read_the_brief_never_says_none_is_from_a_person`, browser `test_the_brief_says_what_it_could_not_read` |
| S | H3 | `InboxSection` drops groups / withheld / exact | **GATE 3.4** | gate tests in §3.4 (`test_r111_*` in `test_brief_service.py`) |
| S | M1 | store update after a move unguarded | fixed | `test_a_plan_record_that_could_not_be_updated_after_a_move_is_said` |
| S | M2 | an uncertain PATCH called failed | fixed | `test_a_move_whose_answer_was_lost_is_read_again_before_it_is_called_failed` |
| S | M3 | console shows an empty panel on failure | fixed | browser `test_a_plans_view_that_could_not_be_read_says_so` |
| S | M4 | plan record after an undo dropped silently | fixed (retried once, then said) | `test_a_plan_record_not_updated_after_an_undo_is_retried_then_said[1,9]` |
| S | M5 | "I did N steps" counted tools that raised | fixed | `test_steps_that_failed_are_counted_apart`, `test_steps_that_failed_are_said_apart_from_steps_that_ran` |
| S | M6 | empty stream: docstring promised a retry | fixed (docstring: D2 retries only a cut-off answer) | `test_a_simply_empty_stream_is_not_asked_again`, `test_a_silent_stream_says_why_and_stores_no_empty_reply` |
| S | L1 | one `_ask` or `on_run` error stops the run | fixed | `test_one_broken_session_or_set_up_never_stops_the_others`, `test_a_claim_that_cannot_be_given_back_is_logged_not_raised` |
| S | L2 | a cut batch listing silently truncated | fixed (logged; never taken for "deleted") | `batch_listing` (used by `test_a_session_deleted_by_hand_is_marked_removed_and_never_asked`) |
| S | L3 | all-day / unreadable entries ignored as busy | fixed (busy all-day blocks; unreadable logged) | `test_an_all_day_entry_marked_busy_blocks_a_re_plan_slot[None,transparent]` |
| S | L4 | unconfirmed creates reported as failed | fixed | `test_events_google_did_not_confirm_are_never_called_failed` |
| S | L5 | unconfirmed events not followed, not said | fixed | `test_a_followed_event_google_did_not_confirm_is_said_not_followed` |
| S | L6 | "Done, Sir." for a result with no words | fixed | `test_a_result_without_words_is_never_reported_as_done` |
| S | L7 | brief "Never" says "could not read"; phrasebook warning every run | phrasebook fixed; the section state is I1 (§3.4, last paragraph) | `test_a_full_phrasebook_is_logged_once_not_every_run` |
| Sec | HIGH-1 | `gmail_inbox_summary` not private on Telegram | **GATE 3.12** | gate test `test_every_r111_part_read_is_registered_and_classified` (§3.12) |
| Sec | MEDIUM-1 | the brief's governed read not wired | **GATE 3.4** | gate tests in §3.4 |
| Sec | MEDIUM-2 | Primary exempt from withholding; snippets to the summariser | fixed | `test_a_code_in_primary_is_withheld_on_the_brief_and_never_reaches_the_ai`, eval c10 |
| Sec | MEDIUM-3 | the batch card hides descriptions and alerts | fixed | `test_the_card_says_how_many_carry_notes_or_alerts_and_where_they_came_from`, `test_a_card_from_a_round_that_read_a_file_says_so`, browser `test_a_file_fed_batch_shows_what_each_event_will_write_as_text[desktop,phone]` |
| Sec | LOW-1 | `own_reason` unanchored | fixed (`fullmatch` on the gateway's fixed words) | `test_own_reasons_are_read_only_from_the_gateway_s_fixed_words` |
| Sec | LOW-2 | `RetryBody.batch` unanchored | fixed | `test_a_retry_s_batch_id_must_be_exactly_a_batch_id` |
| Sec | LOW-3 | only `max_tokens` / `length` are cut off | fixed (fail safe; no stop reason: §5 #18) | `test_any_stop_that_is_not_a_known_finish_is_cut_off`, `test_a_known_finish_is_not_cut_off` |
| Sec | LOW-4 | a cancelled send keeps the claim | fixed (released, shielded) | `test_a_cancelled_send_gives_the_claim_back` |
| Sec | LOW-5 | a move ignores guests; "changed" ignores colour, link, attachments | fixed (left and named; those fields count as his) | `test_a_session_that_now_has_guests_is_left_and_named`, `test_a_colour_link_or_attachment_he_added_counts_as_his_change` |
| Sec | LOW-6 | no 401 / CSRF tests on the new routes | fixed | `test_every_plan_route_refuses_a_caller_who_is_not_signed_in`, `test_a_cookie_write_without_the_console_s_header_is_refused` |
| Sec | INFO-1, 2, 4, 5 | dev accepts all; double tap is UI-only; `is_fixed` matches identical model text; every DENIED is "Permissions" | declined: existing rules or the safe direction; no change | — |
| Sec | INFO-3 | merged calls told "done" when the batch failed | fixed | `test_calls_gathered_into_a_batch_that_was_not_made_are_not_told_it_is_done` |
| C | M1 | the plan never reconciled with the calendar | fixed (`series/sync.py`) | `test_a_session_deleted_by_hand_is_marked_removed_and_never_asked`, `test_a_session_moved_by_hand_takes_its_new_time_and_is_asked_after_it`, `test_a_question_already_asked_reads_nothing_more_from_google`, `test_a_re_plan_leaves_a_hand_placed_session_where_he_put_it_and_avoids_it`, `test_a_gap_he_left_absorbs_the_shift_and_later_sessions_keep_their_times`, `test_sending_the_list_again_after_a_hand_deletion_adds_no_second_row` |
| C | M2 | one long event sinks a gathered batch | fixed | `test_a_single_call_too_long_for_the_batch_is_refused_alone_and_the_rest_merge` |
| C | M3 | a second skip strands the first | fixed | `test_a_second_skip_moves_the_earlier_skipped_session_too` |
| C | M4 | `_chat_stream` 67, `_run_loop` 55, `_chat` 51 lines | fixed (all ≤ 50; `brain.py` 704) | `test_the_brain_s_long_functions_are_split` |
| C | M5 | private `CalendarAPI._body` calls; one API per item | fixed (`CalendarAPI.event_body`; one per call) | `test_a_batch_uses_one_calendar_object_and_no_private_method` |
| C | M6 | an estimate shown as Gmail's exact count | fixed in A ("about N"); shown once GATE 3.4 lands | `test_the_brief_says_about_n_when_gmail_s_count_could_not_be_read`, gate test `test_r111_an_allowed_read_brings_the_groups_withheld_and_about_n_to_the_brief` |
| C | M7 | O12 only partly live until I1 | **GATE 3.4** | §3.4 |
| C | M8 | `core/window.py` imports `core/finish.py` | fixed (`core/fixed_lines.py`, a leaf) | `test_the_fixed_lines_are_a_leaf_and_the_window_no_longer_pulls_in_finish` |
| C | L1 | the retry uses the working cap for a training brain | fixed (`Tries.boost`) | `test_the_retry_of_a_training_brain_keeps_its_plain_cap` |
| C | L2 | `work_output_tokens` up to 64,000 | I1 (§3.13: `config.py`) | — |
| C | L3 | duplicate events not flagged | fixed | `test_duplicates_in_one_list_are_flagged_on_the_card` |
| C | L4 | `_span` sorts text | fixed (times, in his zone) | `test_the_first_and_last_days_are_read_as_times_in_his_zone` |
| C | L5 | busy all-day entries never block | fixed | `test_an_all_day_entry_marked_busy_blocks_a_re_plan_slot` |
| C | L6 | a slot too short is consumed for the next session | declined: a later session must start after the one before it (`verify` refuses a reordering), so a slot before the last chosen one can never be used by a later session; nothing is lost | `test_two_sessions_a_day_keep_their_own_lengths` (order and lengths) |
| C | L7 | the brief's line counts every old check-in | fixed (last 7 days) | `test_the_brief_line_counts_only_the_last_seven_days` |
| C | L8 | Primary codes listed and sent to the summariser | fixed (= Sec MEDIUM-2) | as MEDIUM-2 |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 09:15 IST | R11.1 | First edition: Part A built (O1, O2, O2b, O12, the console pieces, the eval with four controls), how to check it, Needs I1, owner checks, departures, what is not verified live | 🛠 Mark XV |
| v11.1.2 | 12 Nov 2026, 10:42 IST | R11.1 | After three fresh-context reviews: every finding fixed with its test, declined with a reason, or made an I1 item; two merge gates (3.4 the brief's inbox model and governed read, 3.12 the Telegram private reads) with exact diffs and tests checked on a copy; 3.13 `work_output_tokens`; §9 the findings table; §1, §2, §4–§8 brought up to date | 🛠 Mark XV |
