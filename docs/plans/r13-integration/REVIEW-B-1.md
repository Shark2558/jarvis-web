Version v13.0.1 · 16 Nov 2026, 10:13 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context security + code + silent-failure review, Part B)

# R13 Part B (Laundry): security + code + silent-failure review 1

**Scope.** The reviewer did not write this code, and this is a fresh-context review.
- Branch `r13-b` @ `d4a4703`, in a detached, read-only worktree (`/tmp/rv-b-sec`).
- Diff `r13-i0..r13-b`: 33 files, +5,998 / -23. `git diff --name-only` lists only B's row
  (`wardrobe/laundry/*`, `api/laundry.py`, `tests/test_r13_b_*`, `tests/r13_fakes_b.py`,
  `evals/r13/laundry.py`, `INTEGRATION-B.md`).
- The review followed `.claude/agents/security-reviewer.md`, `code-reviewer.md`,
  `python-reviewer.md` and `silent-failure-hunter.md`; `CLAUDE.md` and `.claude/rules/ecc/`
  (common and python); the plan v13.0.2 (Part B, D3–D5, D10, D11, D18, D19, H1, H4);
  `PLAN-REVIEW-1.md`, `BRIEF-COMMON.md`, `INTEGRATION-B.md`; the workbook's LND-01–08,
  LND-10–15, OPS-02 and end-to-end tests 1–4.
- For the seams, I read A's store, fold and sweep (`r13-a` @ `b8de963`) and C's staleness
  check (`r13-c` @ `54f95f4`), read-only.

**Verdict: WARNING (changes requested). No CRITICAL, 4 HIGH, 9 MEDIUM, 12 LOW.**

The security posture is sound:
- the uid always comes from the session (`current_user`) or the tool context;
- both documents are sealed with per-owner AAD, an unopenable one is never overwritten, and
  no key means "off", never clear text;
- no argument can order, pay, call or message anyone, and no stored field builds a URL or a link;
- the shop label is refused in a tainted round, both at check time and at run time;
- alerts, cards, Activity, logs and the audit carry fixed words, counts and ids only, and a
  private piece is "a private basic" everywhere outside his panel.

The four HIGH findings are about correctness where B meets A's needs, and about delivery.
Three of them make a check either lie ("Done") or put a dirty piece back in outfits.

**Before I1 merges Part B:**
- Fix H1–H4. H1, H2 and H4 are local to B. H3 needs one contract line from I1, plus a B
  stop-gap.
- Fix M1–M5 and M7, or have the Workshop accept them in writing.
- I1 owns M8 and M9 (the scan route and `place_at`).

**Verified here.** Every run used the workspace's Python 3.11 and went behind
`flock /tmp/heavy.lock`.
- `pytest tests/test_r13_b_*.py`: **162 passed**.
- `evals/r13/run.py --mock --part laundry`: **15/15**, and the negative control failed the suite.
- `ruff check` and `ruff format --check` are clean on all 33 files.
- `mypy` on B's modules shows only the baseline error (`memory/redis_store.py:67`).
- The five mutation claims were re-run in a scratch copy (results under "Tests" below).
- Five scratch probe files reproduce H1–H4, M1–M5, M7, L2–L4 and L10, against the branch's own
  fakes. They are outside the repo, in `/tmp/rv-b-probe/`.
- No whole suite was run.

---

## CRITICAL

None.

## HIGH

### H1. Answering A's post-correction "rescan" with "these" records a clean return: a dirty piece becomes Ready
- **Where:** `resolve.py:43-46` (`_family`), `resolve.py:176-178` (`e.step or "ready"`),
  `review.py:87-96` (`from_need`, the rescan branch).
- **Snippet:**
  ```python
  if e.kind == "rescan":
      return "hold" if e.reason == "blind" else "which"   # every other rescan is "which one?"
  ...
  step = loads.plan_step(view, laundry, e.step or "ready", picked, ...)  # no step: a return
  ```
- **Scenario:**
  1. A's fold asks for `ReviewNeeded("rescan", piece, ev, reason="corrected")` when a
     correction makes later events conflict (`r13-a` `catalog/fold.py:189-195`; D4.3, LND-05's
     "request a rescan").
  2. `from_need` turns it into a `rescan` entry with no `step`. Its words are "Which of these
     did you mean?" and its one candidate is the piece.
  3. He taps the piece (`these`). `_which` then runs `plan_step("ready")`, and a
     `returned` event moves an In-laundry or Washing piece to **Ready**.
  4. Probe `test_probe_b4.py`: the shirt was in the basket. The answer was "Done: a light blue
     shirt is back and ready", and its state became `ready`.
- **Why nothing catches it:**
  - `plan_step("ready")` legitimately accepts every laundry state.
  - Only B's own "which" entries ever carry a `step`, and no test answers a need from another
    part with `these`. (`test_needs_from_another_part_still_become_entries` only checks that
    the entry exists.)
  - This breaks STY-10, and e2e 8's pass line ("unavailable pieces suggested = 0").
- **Fix:**
  1. Only B's "which" entries take a laundry step, and never a default one. Every other rescan
     is a check (a sighting, a new place, or dismiss):
     ```python
     def _family(e: Entry) -> str:
         if e.kind == "rescan":
             if e.reason == "blind":
                 return "hold"
             return "which" if e.reason == "which" and e.step else "stale"
         return "stale" if e.kind == "place" else e.kind
     ```
  2. In `_which`, raise `Refused(texts.OUTCOME_BAD)` when `e.step is None`.
  3. Give `entry_words` a line for `reason="corrected"`, such as "Two later steps disagree:
     check this piece."
  4. Test: A's rescan answered `these` leaves an In-laundry piece In laundry. It records a
     `seen` and nothing else.

### H2. A hold repaired by A's sweep can never be released, yet every answer says "Done: the check is closed."
- **Where:** `resolve.py:118` and `:124-126` (`expected = e.reason`; a target whose
  `p.hold != expected` is silently skipped), `resolve.py:134` (`texts.CLOSED`),
  `resolve.py:200-203` (`none` only when the *entry's* reason is "unverified").
- **Scenario:**
  1. A's `wardrobe_sweep` gives a hold with no entry its entry, as
     `ReviewNeeded("hold", pid, back_to=…, reason="sweep")` (`r13-a`
     `catalog/jobs.py:104-108`).
  2. The entry's `reason` is therefore "sweep", while the piece's `hold` is
     "held" / "unverified" / "blind" / "missing".
  3. Every `these` or `moved` answer skips the piece, writes no event, closes the entry and
     answers "Done: the check is closed." The piece stays "Missing or in review", out of every
     outfit.
  4. The next morning the sweep reopens the entry, and the cycle repeats forever.
  5. An unverified hold repaired this way also loses its `none` answer and its "confirm"
     path (`_confirmed` needs `e.reason == "unverified"`).
  6. Probe `test_probe_b3.py`: the answer was "done · Done: the check is closed.", and the state
     stayed `review`.
- **Why nothing catches it:**
  - INTEGRATION-B §3 assumes the sweep passes `reason=<the piece's hold>`, but A passes
    "sweep".
  - B matches holds on the entry's reason instead of the piece's hold.
  - Closing an entry with nothing done is reported as success.
- **Fix:**
  - Match on the piece, not the entry. In `_hold`, use
    `if p is None or p.state != "review" or p.hold is None: continue`.
  - Base `none` and `_confirmed` on `p.hold == "unverified"`, read from the view. In
    `Desk._originals`, gate on the pieces' hold.
  - When every target was skipped, close the entry with honest words, such as "Nothing to
    change: it was answered another way." Never use `CLOSED` ("Done") then.
  - I1 should still make A pass `reason=p.hold` (see "Needs I1" below).
  - Test: a sweep-repaired hold answered `these` releases the piece.

### H3. LND-05: striking out a release puts the piece back on hold with no entry to answer (H4 broken)
- **Where:** `flows.py:312-319` (`Desk.correct`), which goes straight to A's `correct()`. The
  `corrected` event yields no `ReviewNeeded` in the reference fold
  (`tests/r13_fakes_store.py:133-140`) or in A's (`r13-a` `catalog/fold.py` `needs` and
  `rescans`).
- **Scenario:**
  1. A "one of" deposit holds two shirts. He answers "there was no deposit", which writes
     `released` and closes the entry.
  2. He then uses "Strike out a laundry step" on the shirt. With no event named, the newest
     step is the release.
  3. The re-fold puts the shirt back in `review` (`hold="held"`), and **no entry** is written.
  4. Probe `test_probe_b.py::…correct_released…`: state `review`, hold `held`, no open entries.
  5. The plan's invariant is "a hold never exists without the entry that resolves it"
     (D4.4, H4). The piece is out of every outfit, and the queue has nothing to answer.
  6. A's sweep repairs it only the next morning, and the repaired entry then hits H2 and can
     never be answered.
  7. The same happens when striking out a `found`, or any event that ended a hold.
- **Fix (atomic, contract):**
  - The fold should emit `ReviewNeeded("hold", piece, <corrected id>, back_to=f.back_to,
    reason=f.hold)` when a `corrected` event leaves the piece held and it wasn't held before.
  - That means one line in the reference fold, one in A's `_refold`, and a conformance case:
    "striking out a release reopens its check, in the same commit".
- **Fix (B, until then):**
  - In `Desk.correct`, after `wardrobe.correct`, check whether
    `done.view.piece(piece).state == "review"` and no open entry has the piece in `pieces`.
  - If so, commit `review.from_need(ReviewNeeded("hold", piece, None, back_to=…,
    reason=p.hold))` through `self._commit`. The sweep stays the backstop.
  - Test: `test_lnd_05_striking_out_a_release_reopens_its_check`.

### H4. An undelivered alert counts as told: a once-only "short" alert is lost for good, and the job still says "ok"
- **Where:** `jobs.py:110-122` (`_tell` ignores the `Delivery` that `notify()` returns) and
  `jobs.py:60-61` (the short key `laundry_short_{batch}` is once-only).
- **Snippet:**
  ```python
  try:
      await notifier.notify(uid, Signal(source="system", kind=kind), said)   # Delivery dropped
  except Exception: ... release
  return "overdue" if kind == "laundry_overdue" else "review"              # told
  ```
- **Scenario:**
  1. At the morning tick, Telegram is down or not linked and no push device answers.
  2. `NotifyService.notify` returns `Delivery(action="ring", telegram=False, push=0)` and
     rolls the storm back, so that its retry is not counted as a storm
     (`notify/service.py:152-153`).
  3. B keeps the claim anyway.
  4. The short alert is never tried again. The overdue alert is lost for that day.
  5. `run` reports `{"overdue": 1}`, so the job is "ok" and R14's self-health sees nothing.
  6. Probe `test_probe_b.py::…undelivered_short…`: one send, then nothing the next day.
- **Why nothing catches it:**
  - `FakeNotifier` (`r13_fakes_b.py:70-84`) only ever rings with `telegram=True` or holds.
  - The codebase's own rule is "a channel took it, it is held, or the owner settled it"
    (`home/watchdog.py:64-73` `took`, `notify/sink.py:22-29`, `camera/events.py:77`). B
    doesn't apply it.
- **Fix:**
  ```python
  SETTLED = frozenset({"switched_off", "feed_only"})  # his own choice: nothing to retry

  def _took(d: Delivery) -> bool:
      if d.telegram or d.push or d.action == "hold":
          return True
      return d.action == "drop" and d.reason in SETTLED

  got = await notifier.notify(...)
  if not _took(got):
      await self._store.release(uid, key)
      return "not_sent"
  ```
  - Better still, lift `took` into `notify/ports.py` as one shared rule (Needs I1).
  - Release the claim on cancellation too. A `TimeoutError` from the tick's budget is not an
    `Exception` inside the coroutine. Use `try/finally` with a sent flag and
    `asyncio.shield(release)`.
  - Test: a notifier that rings with no channel gets the short alert tried again on the next
    run.

## MEDIUM

**M1. `laundry_correct` leaves B's own documents stale.**
- **Where:** `flows.py:312-319` changes only A's ledger.
- **Effects:**
  - Striking out a `load_started` leaves the piece in the load. `loads.step_of` (`:81`) then
    reports the load as **"washing" while the piece sits in the basket**, which is the exact
    failure H4 names. The load can't close until that piece is returned
    (probe: `closed_at None`, `back` = the other piece).
  - Striking out a `sent_out` leaves the batch outstanding, so a false `laundry_overdue` goes
    out every day.
  - Striking out a `held` or `blind` event leaves an open entry about a Ready piece. It counts
    in the morning alert, and answering it does nothing (probe).
- **Fix:**
  - Run the correction through B's own `_commit`. The planner builds the same `corrected`
    event A's `correct()` builds (`tap(piece, "corrected", now, voids=target)`).
  - In `extra`, reconcile B's documents: drop the piece from its open load (`load_started`) or
    batch (`sent_out`), and shrink or close the entry whose `events` holds the voided id.
  - Alternatively, refuse those five kinds in `history.to_correct`, with a pointer such as
    "answer its check" or "mark it back from its batch".

**M2. H1 gap: a worn piece sent to the dry-cleaner keeps its wear and names no plan.**
- **Where:** `providers.py:113-119` and `:149`.
- **Scenario:**
  - `allowed("sent_out", "in_use")` is true, so the send writes a bare `sent_out`.
  - The piece ends up `with_provider` with `wear="pl_meeting"` and `wears=0`.
  - C's observer hears `PieceChange(kind="sent_out", before="in_use", plan=None)` and marks the
    plan he is wearing it for. Within 36 h that means an `outfit_changed` alert, which is
    plan review H1's exact failure.
  - The wear is never counted (STY-17), and A's 04:00 sweep then tries a `wear_done` from
    `with_provider`, which is a conflict entry.
  - Probe confirmed.
- **Fix:** For an In-use piece, emit
  `tap(p.id, "wear_done", now, to="in_laundry", plan=p.wear)` before `sent_out`, like
  `holds.basket_event`.
- **Test:** `test_h1_a_worn_blazer_to_the_dry_cleaner_closes_its_wear_for_its_plan`.

**M3. A piece can be stranded "With laundry provider" with no batch.**
- **Three ways in:**
  - (a) `plan_receive` (`providers.py:171-186`) adds every named piece to `back` and may
    close the batch, but writes `received` only for pieces that are `with_provider`. A piece
    held meanwhile is "received" with no event and stays in review with
    `back_to="with_provider"` (probe: the batch closed, the state `review`).
  - (b) `FOUND_TO` (`checks.py:28`) lets a `moved` answer land a piece in `with_provider`.
  - (c) `holds.pending` (`holds.py:153`) holds any `one_of` candidate, including a piece at the
    shop (probe: the twin at the cleaner was held with `back_to=with_provider`).
- **The dead end:**
  - Once released, the piece is `with_provider` with no open batch.
  - "basket" and "ready" both refuse it with "mark it back from its batch", and that batch
    doesn't exist (probe).
- **Fix:**
  - Refuse a receive for a piece that isn't `with_provider` (`texts.held(p)` for one in
    review), and add to `back` only the pieces that get a `received` event.
  - Remove `with_provider` from `FOUND_TO`.
  - Hold only `one_of` candidates in `BASKET_FROM` (as `resolve_query` already filters) and
    refuse the rest.

**M4. OPS-02: a blind report skips pieces already held by another check, and that check then frees them unverified.**
- **Where:** `blind.py:54-57`.
- **Scenario:**
  - Pieces in the touched area that are already in review are excluded from the blind entry.
  - When the other check is answered "none", they go straight back to Ready. The blind check
    never covered them, yet the workbook says "questionable items are verified before they
    appear in a ready plan".
  - Probe: two rack shirts on a pending deposit were Ready again while the other ten rack
    pieces still waited.
  - When everything touched is held elsewhere, the answer is "Already done: nothing changed."
    That is an "already" which hides that no blind check exists.
- **Fix:**
  - List the already-held pieces in the blind entry's `candidates`.
  - In every release path (`_pending`, `_hold`), re-hold a piece still named by an open blind
    entry with `released` + `blind`, moving it into that entry's `pieces`, instead of
    returning it to `back_to`.
  - Say "already" only when every touched piece is in an open *blind* entry.

**M5. One piece's history gives the place label unfenced and unmasked, and vouches.**
- **Where:** `tools.py:77-81` fences only `got["piece"]["label"]`. `history.py:78` and `:81`
  put the place label raw into both `piece.place` and the top-level `place`.
- **Impact:**
  - Probe: `'place': 'Shirt rack'` came back bare, in a `trusted=True` result.
  - `shown()` fences places, and INTEGRATION-B §5.5 says places are fenced. They are not
    masked on spoken or Telegram turns either.
- **Fix:** Build the piece with `cards.shown(view, pid)` and `fence()` the top-level place.
- **Test:** the history result wraps and masks its place.

**M6. A notifier that raises never reaches self-health.**
- **Where:** `jobs.py:118-121`.
- **Scenario:**
  - A notifier that raises is counted `not_sent`, and the job answers "ok"
    (`ticks.py:117` only fails on `failed`).
  - The test pins this (`test_r13_b_jobs.py:92`: `counts.get("failed", 0) == 0`).
  - A dead notifier is therefore invisible to R14's `job_failing`, which is "a failing job
    reports itself".
- **Fix:** Count a raising send under `FAILED_COUNT`, keep `not_sent` for "no channel took
  it", and change the pin.

**M7. Privacy "delete everything" silently deletes nothing for laundry when the key is missing.**
- **Where:** `store.py:247-251` and `:269-278`.
- **Scenario:**
  - Without a keyring, `count` and `export` report 0 / empty, and `delete` returns 0 without
    deleting, even though the sealed documents and claims exist.
  - Deleting needs no key.
  - Probe: "deleted 0, still there True".
- **Fix:**
  - `delete` needs only `docs`: delete `laundry_path`, `review_path` and the claims, whose query
    needs no key (split `_need` into `_need_docs`).
  - `count` and `export` should raise `LaundryUnavailable(OFF)` when `docs` holds B's documents
    but there is no key.

**M8 (I1). Needs I1 §6.4 is not "B needs nothing": a stale check reopens every day.**
- **Where:** C reads `place_at` (`r13-c` `styling/rank.py:123`, `service.py:141`).
- **Scenario:**
  - B's `these` answer to a stale check records a `seen` at the same place
    (`resolve.py:150-156`).
  - Both folds mark that a `duplicate` and leave `place_at` unchanged (`_apply_place`).
  - C flags the piece stale again the next day, so the queue and the morning alert repeat what
    he just answered.
- **Fix:** See "Needs I1" below.

**M9 (I1). The scan route can desync B's documents.**
- **Where:** I0's `EventIn` (`wardrobe/http_views.py:180-204`).
- **What it accepts:** any `EventKind` (`released`, `held`, `blind`, `load_started`,
  `sent_out`, `received`, `found`), a client-chosen `verified` and a client-chosen
  `source="camera"`.
- **Effects:**
  - A signed-in console, or anything that runs in it, can clear a hold behind its entry, or
    start "washing" outside any load.
  - It can also claim camera evidence, which makes LND-02's `admit` moot.
- **B's own tools hold up:**
  - no answer releases another check's hold (`ours`, `resolve.py:70-75`);
  - a replayed resolve is refused (`ENTRY_GONE`);
  - a retried move with a `client_id` is `known`.
- **Fix:** See "Needs I1" below.

## LOW

- **L1.** Provenance comes from the model.
  - `via` (`tools.py:116,144,157,177,189`) and `how` (`checks.py:26-27`, `resolve`) are tool
    arguments, so the AI can store its call as `via="panel"` / `how="qr"`.
  - This skews the history and e2e 8's pilot counts.
  - Fix: derive `via` from the context, and allow `how` only from the panel's route.
- **L2.** `pieces` plus a `query` that matches the same piece double counts: "Done: 2 pieces
  are in the laundry." with the id listed twice (`flows.py:180`; `plan_basket` doesn't dedupe,
  `holds.py:180`). Fix: `ids = list(dict.fromkeys(ids + list(hit)))`.
- **L3.** A retry with the same `client_id` of `load`, `washing`, `send` or `receive` is refused
  with misleading words ("isn't in the laundry basket", "with an outside laundry") instead of
  "Already done" (M3). B's state check runs before A's dedupe can mark the retry `known`.
  - Fix: before planning, look the `client_id` up in the named pieces' history and answer
    `ALREADY`.
- **L4.** A blind report with `day` = today before 12:00 is refused: "A time can be at most 30
  days back and never ahead" (`flows.py:253-254`, `blind.py:29-31`; probe at 09:01 IST).
  - Fix: `since = min(noon, now)` when the day is today.
- **L5.** A blind report over more than 200 pieces at rest raises a raw pydantic
  `ValidationError` (`Entry.pieces` max 200, `store.py:96`). Past roughly 497 pieces it would
  also exceed Firestore's 500 writes per commit.
  - Neither is caught by `_guarded`.
  - Fix: refuse in words ("Name fewer places") past 200.
- **L6.** The shop label's number rule can be bypassed with `12_345_67_890`, `1234·567·890` or
  `12x34x56x78x90`, and `raj@example.com` passes (`providers.py:33`).
  - Fix: count the digits after stripping every non-alphanumeric character and `_`, and
    refuse `@`.
- **L7.** The writer's staging is never released after a commit (`writer.py:42-56`). It keeps up
  to 32 tx objects with their transactions. Fix: `weakref.WeakKeyDictionary` keyed by `tx`.
- **L8.** Test gaps.
  - The explicit refusal at `resolve.py:79-80` is untested: removing it leaves 162 green,
    because `wrong_state` refuses first.
  - LND-02's phone half (`test_r13_b_lifecycle.py:50`) asserts a state no code path touched.
  - Its camera half calls an `admit` that nothing in production calls (§6.3).
- **L9.** An entry id that never existed is answered "That check is already closed."
  (`flows.py:268-269`, `resolve.py:197-198`). Fix: "That check isn't in your list."
- **L10.** `Desk.resolve` doesn't check `place` against his places, though `move` does
  (`flows.py:181-182`). A `moved` answer set `place="wl_deadbeef"` (probe).
- **L11.** `latest_verified.words` for a `released` is always "Ready" (`history.py:54-56`:
  `target_of(kind, None)` gives no `back_to`). After a blind release in the basket, the history
  says Ready while the state says In laundry. Fix: use the piece's state after the event, from
  the history.
- **L12.** A card naming two private pieces reads "a private basic and a private basic"
  (`texts.names`). D10's card form is "a private basic (No. 17)" (`redact.card_words` with the
  label number).

---

## Acceptance checks (item 5)

Each check has a real, named test on fakes that passes. The verdicts below include the gaps.

- **LND-01** ✓ The shirt leaves the eligible set, and the owned count is unchanged.
- **LND-02** ✓ partly.
  - The phone form is D's (press "Put in laundry").
  - The camera rule is a unit test of an `admit` that nothing calls yet (§6.3, M9, L8).
- **LND-03** ✓ The bundle gets no guessed id. The plausible pieces are held, and with none
  plausible there is an entry and no hold.
- **LND-04** ✓ Both near-identical shirts are withheld, and "no deposit" clears both to
  `back_to`. M3(c) is an edge case.
- **LND-05** ✓ A correction can't overwrite a later clean return, but see H3 and M1.
- **LND-07, LND-08** ✓ One commit, and a failed write leaves neither. Steps refuse a piece
  outside the load, and three of five move. The whole-load form works.
- **LND-10** ✓ Damp and needs-prep pieces stay unavailable.
- **LND-11** ✓ Same id, same owned count, and C hears `returned` once.
- **LND-12** ✓ Four of six come back, two stay out, and the load closes on the last.
- **LND-13** ✓ The half pair stays out, and B never re-pairs.
- **LND-14** ✓ Two of three back, flagged short, then overdue past `due`. See H4 and M3.
- **LND-15** ✓ "Drying since …" in his local day, at 23:30 / 00:30 IST and at year end. See L11.
- **OPS-02** ✓ Blind periods hold the pieces at rest, except those already held (M4).

## H1 and H4 (item 6)

**H1.**
- Basket from In use writes `wear_done → in_laundry` with the wear's plan ✓ (tested).
- The plausible pieces include In use ✓.
- The send-out path misses it (M2).

**H4.**
- B's own holds and entries are written in one commit ✓.
- On `r13-a`, A passes the same `tx` to `fn` and to the writer, and writes `extra` before the
  writer's entries (`catalog/store.py:307-309`, `_write`). So §6.2's two lines already hold
  there.
- §6.2's conformance case is right as written. Add it.
- Gaps:
  - a correction can re-expose a hold without an entry (H3);
  - a sweep-repaired entry can't be answered (H2);
  - B's documents don't follow a correction (M1).

## Deviations (§5)

1. **Three extra modules.** Accept.
2. **Blind holds recorded at report time.** Accept.
   - A verified `blind` dated at `since` would turn every later verified event into a conflict
     (D4.3).
   - Keeping `since` on the entry is the right compromise.
   - Fix L4 and M4 with it.
3. **A short batch with no `due` is told once.** Accept. It is the only reading that keeps
   both lines of the plan, and the panel keeps showing "short". But a once-only alert must be
   delivered or retried: fix H4 first.
4. **The shop label is refused after untrusted content.** Accept.
   - It follows R11's UPI rule and is enforced twice (`content_tainted()` at check time,
     `ctx.outside` at run time).
   - It keeps outside words out of the approvals store.
5. **Place labels are fenced.** Accept, but M5 is the one path that misses it.
6. **`laundry_review(action="blind")`.** Accept, because the 18 names are fixed. Note: its
   Activity line reads "Answered a laundry check".

## Needs I1: the cleanest option for each item

- **§6.3 `holds.admit`.**
  - Move the rule into the contract, beside the table (`wardrobe/states.py` or `model.py`,
    pure).
  - Have **A's store** apply it inside `transact` to every incoming event, rather than the
    route, so no caller can skip it. Add a conformance case.
  - In the same change, `POST /v1/wardrobe/scan`:
    - refuses `source="camera"` and `evidence.released` until R8;
    - takes only the checkpoint kinds (`registered`, `seen`, `deposited`, `wear_*`,
      `returned`, `lifted`).
  - B then stays the only writer of the kinds its documents track (M9).
  - B's `holds.admit` becomes a re-export or goes.
- **§6.4 `place_at`.**
  - A's fold sets `place_at = e.at` on every verified, non-voided `seen`, including one at the
    same place.
  - The mark stays `duplicate`: no entry and no observer, so M3's "one change" holds.
  - Add a conformance case.
  - C keeps reading `place_at`. Don't have C read the history: that would be a log read per
    planned piece on every 5-minute clock.
- **§6.6 `ReviewEntry`.**
  - Add `reason` as a `Literal` of the closed set, not a free `str`, so the needles guarantee
    stays: `unverified`, `held`, `missing`, `restored`, `blind`, `which`, `pending`,
    `refused`, `stale`, `corrected`, `sweep`.
  - Add `count: int (0-20)`.
  - Compute `answers` from **one** function shared with `resolve._OUTCOMES`, so the panel and
    the resolver can't drift.
  - B's `from_need` should map an unknown reason to a safe family instead of failing the whole
    commit (`Entry.reason` has `max_length=24`).
- **New, from this review:**
  - The fold emits the hold need after a correction (H3).
  - A's sweep passes `reason=p.hold` (H2).
  - `took(delivery)` moves into `notify/ports.py` as one shared rule (H4).

## Tests (item 8)

- **Clocks:**
  - Every test uses `FixedClock` / `ist(...)`, from 16 Nov 2026 09:00 IST.
  - Day sentences are asserted whole at 23:30 / 00:30 IST and at the 2026→2027 edge.
  - There is no `datetime.now(`, `date.today(`, `time.time(` or `utcnow` under `laundry/`.
  - There are no date bombs.
- **Imports:** fakes are imported bare (`from r13_fakes_b import …`), never `from tests.`.
- **Eval:** 15/15. The holds-off control fails exactly `lnd_03`, `lnd_04` and `ops_02`.
- **Mutations:** re-run in a scratch copy.
  - Cap off: caught by `…fold_into_place_checks`.
  - Wear not closed: caught by `test_h1_…` and `test_lnd_03_…wear_is_closed`.
  - Load membership off: caught by `test_lnd_08_…not_in_that_load…`.
  - Shop number off: caught by three cases plus `…plain_words`.
  - Another check's hold released: caught when the `ours` filter widens to every candidate, but
    **not** when the refusal at `resolve.py:79-80` is removed (L8).
- **Gaps that let the HIGH findings through:**
  - no notifier that rings undelivered;
  - no need from A or C answered with `these`;
  - no correction of a release.

## Size and quality (item 9)

- **Sizes:** every module is ≤ 400 lines (largest `flows.py`, 355) and every function is
  ≤ 50 lines (largest `plan_resolve`, 43).
- **Ownership:** clean.
- **Lint and types:** ruff and format are clean; mypy shows the baseline only.
- **Typing:** clean, with frozen pydantic records throughout. `tools.py:58` (`work: Any`) could
  be `Awaitable[dict[str, Any]]`.

## Review Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0 | pass |
| HIGH | 4 | warn |
| MEDIUM | 9 | info |
| LOW | 12 | note |

**Verdict: WARNING. Fix H1–H4 before I1 merges Part B.**
- H1, H2 and H4 are local to B, each a few lines.
- H3 needs I1's one fold line, plus B's stop-gap now.
- M1–M5 and M7 should go with them. M8 and M9 are I1's.
- The security model (uid, seals, taint rule, fixed words, no outbound action) passes.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 16 Nov 2026, 10:13 IST | R13 | First edition: a combined fresh-context security, code, Python and silent-failure review of Part B @ `d4a4703`, with 4 HIGH, 9 MEDIUM and 12 LOW findings, each with a probe or a line. Also covers the acceptance checks, H1/H4, the six deviations, the cleanest option for each Needs I1 item, tests, mutations and sizes | 🛠 Mark XXI |
