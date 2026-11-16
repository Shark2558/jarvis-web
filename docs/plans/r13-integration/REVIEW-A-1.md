Version v13.0.1 · 16 Nov 2026, 10:01 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context security + code review, Part A)

# R13 Part A (Catalog and the ledger): security + code review 1

**Scope.** The reviewer did not write this code, and this is a fresh-context review.
- Branch `r13-a` @ `b8de963`, in a detached, read-only worktree.
- Diff `r13-i0..r13-a`: 42 files, +7,647 / -22.
- The review followed:
  - `.claude/agents/security-reviewer.md`, `code-reviewer.md` and `python-reviewer.md`;
  - `CLAUDE.md` and `.claude/rules/ecc/` (common and python);
  - the plan `docs/plans/r13-wardrobe.md` v13.0.2 (Part A, D2–D4, D7, D9, D10, D16, D17, H2–H4) and `PLAN-REVIEW-1.md`;
  - `BRIEF-COMMON.md`, `I0-NOTES.md` and `INTEGRATION-A.md`;
  - the owner's acceptance checks, INV-01–17, OPS-03 and OPS-06.

**Verdict: WARNING (changes requested). No CRITICAL, 4 HIGH, 8 MEDIUM, 9 LOW.**

Most of the design holds:
- everything is sealed, with per-owner and per-document AAD;
- the uid always comes from the session or the tool context;
- the fold is pure and agrees with I0's reference on all 21 conformance cases;
- photos are never decoded, are cleaned by structure, and are capped by side and size;
- the tag call goes only through `BrainEyes`, with no vendor SDK;
- cards, the bin, the audit and the logs never name a piece.

**Before I1 merges Part A:**
- Fix H1–H4. Each fix is small and local to A.
- Fix M1–M8, or have the Workshop accept them in writing.

Verified here:
- The targeted suites ran behind `flock /tmp/heavy.lock`: A's nine test files plus `tests/test_r13_fold_conformance.py`, **176 passed** (132 A + 44 conformance, 21 of them on A's store).
- `evals/r13/run.py --mock --part catalog` gave **19/19**, and the negative control failed the suite.
- `ruff check` and `ruff format --check` are clean on A's 41 Python files.
- Three scratch probes reproduced H1–H4, M1, M2, M3, M5, M6 and L1, against the branch's own fakes. They are outside the repo, in `/tmp/r13-probe-a/`.
- No whole suite was run.

---

## CRITICAL

None.

## HIGH

### H1. `correct()` can void an `archived` or `restored` event, so archive and restore happen without their card (D16, INV-17)

**Where:**
- `src/jarvis/wardrobe/catalog/store.py:209-223` accepts any event id that is in the log.
- On `r13-b`, `laundry/history.py:164-178` (`to_correct`) leaves out only `registered`, `corrected` and `merged`.

**Scenario:**
1. He archives a belt with the `wardrobe_retire` card.
2. Later, on an ordinary typed turn, the model calls B's `laundry_correct(piece=belt)`. That tool is R2, and it becomes a card only on tainted rounds.
3. The newest live event is the `archived` one, so it is voided. The belt is Ready and active again, and no card was shown.

The same path in the other direction re-archives a restored piece. It also voids the bin's `archived` event of a removed piece, which leaves a stale bin entry behind.

**Probe:** `correct()` on the archive event, and the piece is `ready`.

**Why nothing catches it:** the store checks only that the event is in the log, and the scan route's `SCAN_KINDS` guard does not apply to `correct`.

**Fix (A):** in `correct`'s `fn`, look up the target event and refuse the card-only kinds:
```python
CARD_ONLY = frozenset({"registered", "archived", "restored", "merged", "corrected"})
target = next((e for e in await self._read_log(tx.get, uid, p) if e.id == event_id), None)
if target is None:
    raise Refused(NOT_IN_LOG)
if target.kind in CARD_ONLY:
    raise Refused("That change is undone with its own button: archive, restore or merge.")
```
At I1, B's `to_correct` should leave out the same kinds. Add a test: correcting an archived belt is refused and leaves it archived.

### H2. A stale Recently-deleted entry purges a piece he later retired: record, history, photos and fingerprints are lost

**Where:** `src/jarvis/wardrobe/catalog/undo.py:108-120` (`purge`) and `:98-106` (`restore`). Both treat any `archived` state as "the removal this entry made".

**Scenario:**
1. `wardrobe_remove` on a belt creates bin entry E1. The belt is archived with `via="bin"`.
2. He brings it back with a `wardrobe_retire` restore card instead of the bin. E1 stays live in the bin.
3. Later he archives it on purpose, again with a card. INV-17 says to keep the record.
4. On day 30, the bin's sweep purges E1. The state is `archived`, so the record, every log page, the photos and the fingerprints are deleted.

**Probe:** the piece is gone after the stale entry's purge.

A related effect: a bin "Restore" of E1 un-archives the deliberately retired piece without the retire card.

**Fix:** bind the bin entry to the event it made, and act only while that event is still the piece's newest applied state-setting event.
- In `remove`, return the `archived` event's id from the commit, and store `{"ref": pid, "ev": <event id>}`.
- In `purge` and `restore`, read the piece's history (`self.store.history(uid, ref)`) and act only when the newest applied state-setting item has `event.id == snapshot["ev"]`.
- Otherwise:
  - `purge` returns without changing anything;
  - `restore` raises `StillThere`.
- Add a test of exactly the sequence above.

### H3. `GET /v1/wardrobe` pagination repeats and drops pieces once he has more than 200

**Where:** `src/jarvis/wardrobe/catalog/views.py:75-76` and `:80`.

**Why:** the list is sorted by `(category, type, id)`, but the cursor filter keeps `p.id > after` over the whole sorted list. Ids are random hex, so page 2 contains about half of page 1 again and misses pieces from later categories that have smaller ids.

**Probe:** with 260 active pieces, page 1 had 200 and page 2 had 113. 78 pieces were repeated and 25 were never shown.

The plan expects a wardrobe of 150–400 pieces, so this will hit the owner. No test covers `after` or `next`.

**Fix:** continue from the cursor's position in the same order.
```python
if after:
    at = next((i for i, p in enumerate(shown) if p.id == after), None)
    shown = shown[at + 1:] if at is not None else []
```
Add a route test with 260 pieces: the pages are disjoint, and their union equals `active()`.

### H4. A restore writes back the fingerprints of pieces that are private now, or purged and not ticked (breaks D9 and D17)

**Where:** `src/jarvis/wardrobe/catalog/restore.py:196-206` (`_photo_ops`). When no current piece has `fp_model`, the first chunk `Set`s every fingerprint shard from the file, as it is.

**Scenario:**
1. He makes a backup with photos, while shirt A is not private and sock B exists.
2. He marks A private, which drops its fingerprint, and he removes and purges B.
3. He restores the backup without ticking B.

**Probe:** the stored shards now hold fingerprints for both A (private) and B (purged, not ticked). This breaks two binding rules:
- D9: a private piece never has a fingerprint;
- D17: a purged piece comes back only when he ticks it.

`Prints.items` filters them out when listing, so they are never served. But they stay sealed at rest, and they come back again with every later restore of this file.

**Fix:** never write the file's shards wholesale. Filter the entries of `parsed.prints` to the pieces that are:
- restored in this chunk, and
- not private in the record that will be kept (the current record for a piece in both).

Then merge them into the current shards through `Prints._writes` inside the same transaction. Read the current shards via `tx.get`, and write each chunk's pieces, not only the first chunk's.
```python
allowed = {p.id for p in recs if not p.private}
entries = [e for shard in sorted(parsed.prints) for e in self.store.sealer.open(
    "wardrobe_photos", aad_prints(uid, shard), parsed.prints[shard]["blob"]) if e["p"] in allowed]
```
Add a test with exactly the probe's sequence.

---

## MEDIUM

### M1. The ₹30 tagging cap can be raced (H2's "the counter can't be raced")

**Where:** `src/jarvis/wardrobe/catalog/tagging.py:158-173` (`_check` reads the month-to-date), `:187-197` (the call) and `:199-208` (`_record` adds the cost afterwards, in a separate commit).

**Scenario:** at ₹0.99 of a ₹1 cap, five concurrent `POST /tag` requests all pass `_check`. For example, the phone and the laptop at once.

**Probe:** 5 calls made, 5 accepted, month-to-date ₹1.035 against the ₹1 cap.

The overshoot is bounded by the rate limit (30 changes a minute) times the per-call cost, about ₹0.26 on Sonnet.

**Fix:** reserve before the call, then settle after it.
1. Run a `rewrite` that re-reads the month, refuses when `so_far + estimate > cap`, and adds the estimate.
2. After the call, a second `rewrite` adds `spent - estimate`.
3. On `CantLook` or a timeout, refund the estimate.

When `_estimate_inr()` is 0.0 because the model is not in `PRICES`, also refuse once `so_far >= cap`. Add a test that runs five concurrent calls against the cap.

### M2. A restore re-adds pairs he unpaired since the backup, so one piece ends up in two pairs; deleted places come back

**Where:** `src/jarvis/wardrobe/catalog/restore.py:222-231` (`_links`). Old pairs and sets are merged in whenever all their pieces exist, and `places = {**old.places, **fresh.places}`.

**Scenario:**
1. The backup holds pair P1 {L1, R1}.
2. He unpairs it and pairs L1 with R2 (LND-13: re-pairing a replacement half himself).
3. He restores the backup into the same wardrobe.

**Probe:** the pairs are `(L1, R1)` and `(L1, R2)`. Three socks count as two pairs. This breaks:
- "A piece is in at most one pair" (`links.py`);
- D17's "the current record's attributes win";
- LND-13.

Places he removed come back the same way.

**Fix:** take from the file only the links whose pieces are all newly added in this restore.
```python
added = set(fresh.pieces) - set(current_ids_before_restore)
pairs = {**{k: v for k, v in old.pairs.items() if set(v.pieces) <= added}, **fresh.pairs}
sets = {**{k: v for k, v in old.sets.items() if {x.piece for x in v.parts} <= added}, **fresh.sets}
used = {fresh.pieces[i].place for i in added}
keep_all = not current_ids_before_restore  # an empty wardrobe takes every place back
places = {**{k: v for k, v in old.places.items() if keep_all or k in used}, **fresh.places}
```
Also skip any old pair or set that would put a piece in a second pair. Pass `current_ids_before_restore` from `apply`. Add a test of the probe's sequence.

### M3. A restore into an empty wardrobe re-opens a review entry for every historic conflict and hold

**Where:** `src/jarvis/wardrobe/catalog/store.py:255-261` (`_refold` asks `needs()` for every added event), which runs on a restore (`as_stored=True`) too.

**Scenario:** after data loss, he restores a backup of a shirt whose history has five old conflicts. All of them were resolved long ago, and the shirt is Ready.

**Probe:** B's writer is asked for five `conflict` entries. A year of history floods his review queue.

The acceptance check says the restore must not duplicate wardrobe or laundry records.

**Fix:** when `as_stored`, skip the per-event `needs`. After the fold, ask only for the current state's entry:
```python
if as_stored:
    if f.state == "review" and f.hold:
        w.needed.append(ReviewNeeded("hold", pid, back_to=f.back_to, reason="restore"))
else:
    ...  # today's loop
```
Add a test: a restore of a piece with past conflicts asks for no entry, and a restore of a piece that is held now asks for exactly one.

### M4. His labels and place names land in clear in a card's stored arguments, on spoken and tainted rounds (D10, the I1 needles)

**Where:**
- `src/jarvis/wardrobe/catalog/tools_write.py:99-125` (`wardrobe_add` `pieces[].label`);
- `:148-168` (`wardrobe_edit` `label`);
- `:185-216` (`wardrobe_places` `label`).

On a spoken turn the gateway makes every write a card. On a tainted round every write is a card. A's own test shows both (`test_a_spoken_label_never_vouches…`, `lifecycle.py:176-183`).

`PendingAction.arguments` is stored in clear in `approvals`, including "Brown belt" or "Lucky boxers" for a private type. The needles eval searches `approvals` for "his free-text labels", and D10 allows only a `query` there. INTEGRATION-A §6 item 11 flags only `wardrobe_edit`'s `query`.

**Fix:**
- **Tainted rounds (A):** in the tools' `check`, refuse a `label` while `content_tainted()` is set. The run drops it anyway (`origin == "outside"`), so nothing is lost, and the label stays out of the card.
- **Spoken rounds (A + I1):** either refuse `label` on a spoken turn ("Type its label in Helpers, Wardrobe"), or have I1 add these three fields to the needles' allowed places and D10's text (Things' `put` precedent).

The first option is recommended for private-by-default types at least.

### M5. "Today" stated as a day is refused every morning

**Where:** `src/jarvis/api/wardrobe.py:120-122` (a stated `day` is 12:00 his time) and `src/jarvis/wardrobe/catalog/fold.py:169-172` (a stated time ahead of now is refused).

**Scenario:** at 09:00 IST he marks a shirt "returned, today" with `day` = today. 12:00 is ahead of now, so he gets "A time can be at most 30 days back and never ahead." The same happens for any `day` = today before noon, including the brief's 00:30 IST boundary.

**Probe:** the store refused it.

**Fix:** a stated day without a time is 12:00 that day, or now if that is still ahead.
```python
noon = datetime.combine(e.day, time(12, 0), tzinfo=await desk.ctx.zone(uid))
return min(noon, now), None
```
Add route tests at 09:00 and 00:30 IST with `day` = today, each asserting the stored `at` whole.

### M6. N+1: each piece's log read re-reads and re-opens the whole sealed index (backup, pilot, export, the restore check)

**Where:**
- `src/jarvis/wardrobe/catalog/store.py:169-172`: `events()` calls `self.view(uid)` every time.
- It is used per piece by `backup.py:75-77`, `pilot.py:35-36`, `data.py:39-41` and `restore.py:146`.

**Probe:** with 400 pieces, `GET /pilot` and a backup each made **801** document reads: 400 of them read the index, which can reach 900 KB, then decrypted, parsed and validated it. That took about 1.3–1.5 s on in-memory docs. On Firestore it adds about 400 round trips. It also uses roughly 1.6 % of the free tier's 50k reads a day per call, against the "₹0 a month" rule. The pilot route allows 60 reads a minute.

**Fix:** read the view once and pass the piece.
```python
async def events(self, uid: str, pid: str, *, view: WardrobeView | None = None) -> list[Event]:
    p = (view or await self.view(uid)).piece(pid)
```
The four callers pass the view they already hold. Add a test that counts `docs.get` calls: N+1 for N pieces.

### M7. A restore card with a `condition` hides it, so availability is never confirmed separately (INV-17)

**Where:** `src/jarvis/wardrobe/catalog/tools_life.py:80-82` (`preview_retire`: "Restore a black belt") and `:113-122` (restore with a `condition` writes `restored` and `found(to=condition)` in one commit).

**Scenario:** the model calls `wardrobe_retire(piece, action="restore", condition="ready")`. He approves "Restore a black belt", and the belt is Ready. He never confirmed its condition, which INV-17 requires: "confirms availability separately".

**Fix:**
- Refuse `condition` while the piece is archived ("Restore it first; then tell me its condition").
- When `condition` is present for a piece in review, the card reads "Mark a black belt Ready" (fixed words).
- Add a test.

### M8. The rewear rule exists twice, and the copies already differ (`festive_layer`)

**Where:** `src/jarvis/wardrobe/catalog/jobs.py:34-41` (`WORN_AGAIN`), against C's `styling/rules.json` `reusable` on `r13-c`.
- C's copy has `festive_layer`; A's does not.
- A forgotten festive-layer wear closed by A's 04:00 sweep goes to In laundry. One he closes himself through C's `wear_log` goes to Ready.

**Recommended single source:** put the default in I0's contract, not in either part. Add `REWEAR_DEFAULT: frozenset[str]` (with `festive_layer`) to `wardrobe/states.py`, beside `STATED_CHOICES`: the wear lifecycle is D3 data.
- A's `after_wear` imports it.
- C's `rules.py` either reads it, or checks at start that `rules.json["reusable"] == REWEAR_DEFAULT` (and the part is "setup failed" otherwise).

Do not have A import C's `rules.json`. A broken C would then break A's sweep. C's review L7 found the same coupling.

Until I1: add `festive_layer` to `WORN_AGAIN`, and add a test pinning A's list to C's.

---

## LOW

**L1. The backup's clear head is not authenticated, and lines can be spliced across two of his backups** (`backup.py:37-38`, `:70-71`; `restore.py:56-64`, `:78`).
- **Probe:** flipping `"photos":false` to `true` is accepted (`check.photos == True`). The AAD is `wardrobe/backup/{uid}/v1/{n}`, with no file id, so line *n* of one of his files opens in another of his files.
- **Fix:**
  - Draw a random `fid` into the head.
  - Seal line 1 with AAD `…/v1/{fid}/1|{sha256(head)}`, and the other lines with `…/v1/{fid}/{n}`.
  - Add tests for a flipped head and for a line from another file.

**L2. The restore token** (`restore.py:107-122`). The construction is sound: an HMAC from its own HKDF domain over the uid, the digest, the expiry and `empty`; `compare_digest`; one hour; 160 bits.
- **The `empty` flag:** a token minted while the wardrobe was empty keeps `empty=1` for its whole hour. Re-applying it after he purged a piece brings the piece back unticked.
  - Fix: on apply, honour `empty` only for pieces that are not in the bin's purge record, or put the bin's purge count into the MAC.
- **A non-ASCII token:** `hmac.compare_digest` raises `TypeError` on it, and the reply is a generic 422.
  - Fix: `if not token.isascii(): return None`.
- **Tests:** add one for a flipped `empty` digit and one for another owner's token.

**L3. Restore chunks are counted in pieces, not bytes** (`restore.py:37`, `:166`). One chunk writes every log page of 50 pieces. With heavy, old histories near the 25 MB cap, one commit can pass Firestore's 10 MiB, and it then fails on every retry (INTEGRATION-A §8 says this was not measured).
- **Fix:** close a chunk at 50 pieces **or** about 8 MiB of sealed pages plus the index, whichever comes first.

**L4. A backup without photos is never checked against the restore cap** (`backup.py:60-66`; `routes_files.py:194-195`), and `check_size` counts only the photo documents. After a few years of events, he can download a file that the restore then refuses with a 413.
- **Fix:** estimate the index plus the logs too, and warn or refuse in words before the download.

**L5. The restore parses up to 25 MB synchronously on the event loop** (`restore.py:67-86`, called from async routes). Opening every line, the JSON and pydantic for tens of thousands of events stall voice and chat for seconds.
- **Fix:** `parsed = await asyncio.to_thread(parse, self.store, uid, body)` in `check` and `apply`.

**L6. `GET /tag/estimate` says `allowed: true` in No-AI mode** (`tagging.py:175-185`). The tag itself is refused (503), but the ₹ button is offered.
- **Fix:** `if (cant := await self.eyes().state(uid)) is not None:` return `allowed=False, why=str(cant)`.

**L7. `unknown_place` returns his place names unfenced in a tool result** (`places.py:40-44` via `tools.failed`).
- **Fix:** fence them with `tools.say(...)` when the refusal goes to the model. The panel route can keep plain words.

**L8. `wardrobe_edit` is several commits, and it reports "refused" after a partial write** (`tools_write.py:148-168`).
- **Example:** `wardrobe_edit(piece, colour="navy", label_code="zzzzzzzz")` saves the colour and then answers "That isn't one of your JARVIS labels."
- **Fix:** validate everything before the first commit: the place, `number_of(code)`, the pair's type and the set's size.

**L9. Smaller items:**
- **Labels:** `labels.number_of` (`labels.py:86-87`) recomputes from today's key. After a key change, a printed label already in his index can't be moved or freed. Look the code up in `view.labels` first.
- **Merge:** a non-private piece merged into a private one keeps its photos and fingerprints on the tombstone (`merge.py:66-67`). Drop them in the same commit when `keep` is private.
- **INV-14 test** (`tests/test_r13_a_catalog.py:312-329`): it checks only the end state after a missing sock **and** a deposit. Also assert the step in between: after the missing sock alone, owned is still 4 and complete pairs are 1.

---

## The use cases against their acceptance checks (item 7)

| ID | Named test | Holds? |
|---|---|---|
| INV-07 | `test_inv07_identical_vests_…`; QR verification through the route: `test_a_qr_read_counts_only_…` | Yes |
| INV-08 | `test_inv08_twenty_frames_…`: 20 adds with one `client_id` give one piece and one `registered` | Yes |
| INV-11 | `test_inv11_two_shoes_…`: owned 2, pairs 1, then 0 complete with the half named | Yes |
| INV-12 | `test_inv12_a_kurta_set_…`, `…two_to_six…` | Yes |
| INV-14 | `test_inv14_a_missing_sock_…`: owned stays at 4 and scope is shown | Yes, but the step in between should be asserted (L9) |
| INV-16 | `test_inv16_merging_…`: a card; history `registered, registered, seen, merged`; labelled copies stay two | Yes |
| INV-17 | `test_inv17_archiving_a_belt_…`: cards, the same id, review until the condition | Yes, but H1 and M7 bypass it |
| OPS-03 | the conformance test (21 cases on A), `test_as_fold_agrees_…500_seeded…` | Yes |
| OPS-06 | `test_ops06_…` (empty, cut after chunk 2, 3 MB through the app, 31 MB refused) | Ids, pairs and "never duplicates" hold for an empty target. In a non-empty one, M2 duplicates pairs and M3 re-opens entries; H4 |

INV-01–06, 09, 10, 13 and 15 each have a named test that asserts the workbook's sentence.

## The fold and the conformance test (item 8)

`fold.py` is pure and order-independent:
- it sorts by `(at, recorded, id)` and never writes marks back;
- `settle` is the one time rule.

`tests/test_r13_fold_conformance.py` found `r13_fakes_a.conformance_store` and ran its 21 cases on A's sealed store, plus the two cases that walk every factory: **44 passed**. `test_as_fold_agrees_with_the_reference_on_500_seeded_histories` uses seeded RNGs.

## The deviations in INTEGRATION-A §5 (item 9)

1. **Stateless restore token: accept.** It is better than a stored token, because the check really writes nothing. Drop the plan's `wardrobe_restore/{uid}` collection at I1, or mark it planned-unused. Close L2's `empty` replay.
2. **Derived QR codes: accept.** HMAC(uid, N), 40 bits, keyed; the GET writes nothing; `resolve` still requires an assigned label. Fix the key-change edge in L9.
3. **Remove as an `archived` event: accept, only with H2.** Without a link from the bin entry to its event, removal and retirement can't be told apart, and the purge deletes retired pieces.
4. **The 500/550/600 limits against the default cap of 400: accept.** Every wardrobe within the default cap fits even at maximal histories. The byte guard refuses in words before Firestore's 1 MiB.
   - At I1, either cap `wardrobe_max_pieces` at 500, or document that 550–600 fit only with sparser records.
5. **The vouch rule uses `locked`: accept.** Tested.
6. **`wardrobe_edit` takes `query` for moves only, against D10: D10 should win.**
   - Drop `query` from `wardrobe_edit`.
   - D's No-AI router resolves first (`wardrobe_find`, then `wardrobe_edit(piece=id, place=…)`), as A's §6 item 10 already proposes. This is two gateway calls, each on its row, with no model and no ₹.
   - That keeps D10's single allowed place in the needles, and amends D6's wording at I1.
7. **The scan route, and a stated day: A wins.** The plan (D4.1), BRIEF §4 and the contract docstring (`http_views.py:180-183`) all say 12:00 his local time.
   - I0's fake server (`tests/r13_fake_server.py:109`) uses a *naive* midnight and must change at I1 to `datetime.combine(e.day, time(12), tzinfo=zone)`. D's browser tests then expect noon.
   - Apply M5's clamp in both places.
8. **Statuses when the part is off: accept.** They match each row's list.
9. **A new conversation per card: accept** (`fix_plan` precedent). `ToolCall.session_id` at I1 is the better end state.
10. **The rewear rule copied: reject as is.** See M8 for the single-source fix (I0's `states.py`).

## Checked and holding

**Photos (D9)**
- JPEG content type only, read with `read_capped` at `wardrobe_photo_max_kb` (413 or 422 in words).
- `sanitise_jpeg` keeps exactly one frame, drops APPn and COM (EXIF and GPS), and never decodes. There is no decoder bomb on the server.
- The side comes from the SOF marker, at most 512.
- Sealed under `wardrobe_photos`, with AAD `wardrobe/photo/{uid}/{photo}/v1`; `get` also checks `owner`.
- A private piece is refused from the **record**, and marking a piece private drops its photos and fingerprints in the same commit (`service.py:127-130`).
- Archived and merged pieces are refused.
- At most 3 views; ids are validated before any path is built.

**Tagging (H2)**
- Off by default, and a cap of ₹0 means never.
- Refused from the record for a private or private-by-default type, and for an unsaved, archived or merged piece.
- Only through `BrainEyes.look` (fast tier, No-AI refused, `Billing.ensure_allowed` first).
- No import outside `jarvis.llm`.
- The answer is cut to the fixed lists.
- Exception: the race (M1).

**Backup and restore**
- AES-GCM per line, with the uid and the line number in the AAD. Cut, reordered and other-owner files, and another key, are refused in one sentence (tested).
- The check writes nothing (tested on an empty store).
- Body caps: the middleware allows 30 MB + 64 KB, and the route reads 25 MB (tested at 31 MB).
- Writes are chunked and idempotent by id and client id (tested by cutting after chunk 2).
- No path traversal: every path comes from a validated id (`check_owner`, `check_piece`, `check_photo`, a shard range). There is no archive extraction.
- Another owner's data can't enter, because the AAD names the uid and the photo and shard `owner` is checked.

**QR labels**
- `labels.svg` writes nothing.
- The SVG holds only numeric path data and `escape(f"No. {int}")`.
- Served with `default-src 'none'`, `nosniff` and as an attachment.
- A read code counts only when it is `jw1:` plus 8 characters **and** assigned. The scan route marks a QR event unverified on a piece without a label.

**Tools and routes**
- Eight tools on the `wardrobe` row (agent `wardrobe`, none `spoken_ok`).
- Merge and retire use `ask_when` always and are in `NO_BULK_TOOLS`.
- Remove is `undoable`, with the fixed title "A wardrobe piece" and snapshot `{ref}`.
- Card words come from `preview` through `card_words`.
- Every route has `require_auth` (CSRF header on writes), `current_user`, `limited(...)` first and `no-store`.
- Errors are plain words or fixed text. Logs carry class names only, with `from None` (no plaintext in tracebacks).

**Private pieces outside the tab**
- The bin, the card words, the audit (args hash), the logs and Activity (fixed words) hold.
- Tool results give "a private basic" (`model_view`).
- Exception: M4's stored card arguments.

**Tests (item 10)**
- No `datetime.now`, `utcnow`, `date.today` or `time.time` in `wardrobe/catalog/`, A's tests, the fakes or the eval.
- Fakes are imported bare.
- The RNGs are seeded.
- The eval control really fails INV-05, INV-08 and OPS-03.

**Quality (item 11)**
- Every module is at most 400 lines (`store.py` 393), and every function at most 50 (the longest are `life_tools` at 46 and `write_tools` at 42).
- Records are frozen. The mutable working sets (`_Work`, `_Acc`) are private to one call.
- No dead code.

**Ownership (item 12)**
- `git diff --name-only r13-i0..r13-a` is exactly A's row in BRIEF-COMMON §3: `wardrobe/catalog/*`, `api/wardrobe.py`, `tests/test_r13_a_*.py`, `tests/r13_fakes_a.py`, `evals/r13/catalog.py` and `INTEGRATION-A.md`.
- No wiring, contract or shared file was touched.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 16 Nov 2026, 10:01 IST | R13 | First edition: a fresh-context security + code + Python review of Part A at `r13-a` @ `b8de963`: 0 CRITICAL, 4 HIGH, 8 MEDIUM, 9 LOW, each with file:line, a scenario (ten reproduced by probes) and the exact fix; the use-case table, the conformance result, a ruling on each §5 deviation (the rewear rule's single source in I0's `states.py`; the stated day's 12:00 wins over the fake server's midnight); verdict WARNING | 🛠 Mark XXI (review) |
