Version v13.1.1 · 17 Nov 2026, 20:50 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (review A-1)

# R13.1 Part A, review 1: Try-on data (a fresh context)

**What was reviewed.** Branch `r13-1-a` at `08d4ed0`, against its base `r13-1-i0` @ `eb8b7e4`
(`git diff eb8b7e4..08d4ed0`: 25 files, +4,922 −24). The reviewer did not build Part A.

**Roles.** Security reviewer, code reviewer, Python reviewer and silent-failure hunter
(`.claude/agents/*.md`), with `CLAUDE.md` and `.claude/rules/ecc/{common,python}/*`.

**Inputs.**

- BRIEF-COMMON v13.1.2, BRIEF-A v13.1.2, INTEGRATION-A v13.1.1 and I0-NOTES v13.1.1.
- The plan v13.1.3: D4, D7, D16, D20 and D21, and rows 350, 353–363, 365, 366 and 388 with the
  owner's checks.

No code was changed. Every probe below ran in a scratch folder outside the tree, on the branch's
own fakes (`r131_fakes_a`, fixed clock).

## Verdict

**WARNING. Fix F1 before the merge. Nothing blocks.**

| Grade | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 3 |
| LOW | 8 |

Part A is careful, well-tested work:

- Owner-only routes, CSRF, rate limits and the depth guard hold.
- The sealing and the private rule hold.
- The fresh check and D20's lock hold.
- OPS-05's order holds, and the backup words are honest.

The one HIGH: "Use this look" answers a refusal by `outfit_plan` as 200 `executed` (F1). The
console can therefore say "confirmed" while the plan is unchanged.

## 1. What holds (checked, with evidence)

| Area | What holds | Evidence |
|---|---|---|
| Owner only | Every route sits on the router's `require_auth` and `current_user`. | `api/tryon.py:53`. `test_without_his_sign_in_every_route_is_refused`: all 11 rows give 401. |
| CSRF | Every write is a PUT, POST or DELETE, so a cookie session needs `X-Requested-With`. No CORS headers are served. The one GET with `private=1` changes nothing. | `api/auth.py:126` |
| Rate limits | `r13_status.limited` runs before the service and before the body is read. Reads and changes keep their own buckets per route (60 and 30 a minute). | `api/tryon.py:122`. Two tests on a frozen limiter. |
| Body size and depth | The app caps bodies at 2.1 MB (`api/body.py`). JSON nested too deep (`RecursionError`) is a 422. `raise _Bad from None` keeps his values out of any trace. Query values are at most 1,000 characters and 24 entries. | `api/tryon.py:139`, `looks.MAX_ENTRIES` |
| Sealing | `tryon/{uid}` is `{owner, rev, blob, updated_at}`. It is sealed with AES-GCM under the keyring's `tryon` purpose, with AAD `tryon/{uid}/v1` (distinct from C's four AADs). The 200 KB cap is measured on the sealed string. The bounds are checked again on every write. An unreadable document is never overwritten, because `change` opens before it writes. No key means Off, and nothing is kept in clear. | `store.py:132-169`, `model.py:281-298`, 11 store tests |
| Private pieces (AVT-14), including pieces made private later | See the list under this table. | `looks.py:92-96`, `options.py:142, 163`, `looks.py:208-218`, `assets.py:52-57`, `part.py:81`, `saved.py:48-51, 98` |
| Fresh readiness | See the list under this table. | `confirm.py:87-98`, `styling/actions.py:180-206`, the AVT-09 named test and its race |
| OPS-05 | See the list under this table. | `erase.py:27-40`, the OPS-05 named test, `deploy/backup_setup.sh:138` |
| Concurrency | Every change is one transaction on the stored document (`store.change`). The bounds (≤ 10 saved, ≤ 5 earlier) are checked inside it. Captured results are reset on each attempt (`made[:] = …`). | Probe: 10 drafts at once all gave 200. Of 3 "Use" presses at once, one gave 200 and two gave 404 `no_draft`. |
| Sizes and style | The largest module is `looks.py` (355 lines). Every function is ≤ 50 lines (the longest, a test, is 42). `ruff check` and `ruff format --check` are clean on the 24 files. `mypy` on A's modules shows the baseline error only. There is no real clock and no `$`. | the commands in section 4 |
| Measurements kept private | Logs carry class names only. The audit keeps the hash of the field names. No tool, alert or Google call carries them. R13's backup file never reads `tryon` (`catalog/backup.py`). | `test_r131_a_needles.py`, the audit test |

**Private pieces (AVT-14).** Including pieces made private later:

- A slot is covered when it is a private slot, or when any piece of its unit is private or
  missing.
- A private slot has no options.
- No private piece appears among another slot's options.
- A gap that names a private id is replaced.
- Figure choices are tidied of private pieces on every read. None are listed while R13 can't be
  read.
- Saved comparisons never keep a private piece, and never serve one made private later.
- C's `tryon_looks` view is never `private=1`.
- A refusal names a private piece only as R13's "a private basic" (`redact.fixed_words`).

**Fresh readiness.**

- Every look, option, saved comparison and confirm reads R13's view and plans per request. Nothing
  is cached: `Styling.view` goes straight to `store.view`.
- The confirm checks every unit before any tool call: its state, one shoe, its set, another plan's
  hold, and STY-13's shared base.
- It then makes ONE `lock` with `pieces`. D20's `_one` checks again inside `outfit_plan`.

**OPS-05.**

- The order is C's service, then C's paths, then `tryon/{uid}` last. The spend is kept.
- The catalog is untouched: `GET /v1/wardrobe` returns the same pieces and `rev`.
- It runs through `PrivacyService`: a passkey, or the typed DELETE plus a fresh sign-in, bound to
  the row's id and `rev`. Its audit line is IRREVERSIBLE, and what is left is read back.
- A keeps no cache.
- The backup words are honest. `kept.BACKUP_WORDS` is built from `RETENTION_DAYS` (7), and R14's
  schedule really keeps each copy 7 days (`--retention=7d`).

## 2. Findings

### F1 · HIGH · "Use this look" answers a refusal by `outfit_plan` as 200 `executed`

**Evidence.** `src/jarvis/api/tryon.py:246-248`:

```python
    reply = panel_reply(run)
    if reply.status_code < 400:
        return reply
```

R13's `outfit_plan` refuses by returning `{"refused": true, "message": …}` as an EXECUTED result
(`styling/answers.py:24`, `styling/tools.py:207-229`). `_tool_reply` serves that as 200
`{"status": "executed", …}`.

Probe, the race (the navy jacket goes to the laundry between A's check and the call): 200
`{"status": "executed", "message": "The navy jacket is in the laundry: it can't be locked into
this plan."}`, with `result.refused` true. The same 200 comes back for every other `PlanRefused`
of the lock, and some of those are more likely than the race:

- "That plan changed meanwhile: try again." (R13's M1 conflict);
- "Your wardrobe isn't ready yet …";
- "One piece a slot …".

**Failure.**

- D's console branches on `err.code` (BRIEF-COMMON section 4).
- D is built against `tests/r131_fake_server.py`. That server's confirm (lines 231–240) answers
  only 409 `draft` or 200 "Done.", so D never sees this reply's shape.
- BRIEF-D does not mention `result.refused`. Only INTEGRATION-A §7.5 says it.

So a console that takes a 200 as done tells him the look is locked for the event, while the plan
is unchanged. AVT-09's "cannot be confirmed" then holds in the data but fails on his screen.

BRIEF-A says "`Refusal` on every refusal". A already turned the gateway's error into a `Refusal`
(`01607e1`) for this same reason.

**Fix** (A's own file, a few lines). In `_panel`, before a reply below 400 is returned:

```python
    res = run.result
    if res.outcome is GatewayOutcome.EXECUTED and isinstance(res.result, dict) \
            and res.result.get("refused"):
        return no(409, "refused", str(res.result.get("message") or DOWN))
```

409 is already in the row's errors (`wardrobe/tryon/http.py:80`).

- Pin it in the AVT-09 named test's race: `409 {"error": "refused", "detail": LOCK_REFUSED}`.
  Pin it in the eval's race case too.
- I1 makes the fake server answer the same for a scripted race, and D shows `detail`.
- A `denied` reply (his Permissions) can stay R13's `ToolReply`: its `status` already says
  "denied".

### F2 · MEDIUM · After "Remove", "Use this look" leaves the removed piece in the plan

**Evidence.**

- `confirm.py:98` locks only the slots the console sends.
- R13's `lock` with `pieces` applies each one through `reserve.with_pick`
  (`styling/actions.py:199-206`, `styling/reserve.py:76-80`). That keeps every other pick.

Probe: the meeting plan's look, with the watch removed, then confirmed. The answer is 200
`executed`, and the plan still holds `watch wi_000000000015` (unlocked).

D7 offers **Remove** for the outer layer, belt, watch and socks. AVT-09 wants the figure and the
checklist to change together. After this confirm, the figure has no watch but the plan does.

**Fix** (I1 decides; the R13 half is I0's file). Choose one:

- (a) `ConfirmIn.removed`, a tuple of slots (`REMOVABLE_SLOTS` only). `lock` with `pieces` then
  drops those picks in the same `s.change`. That is still one call, all or nothing. Add a test with
  a removed watch.
- (b) Until (a) is built, A refuses in words before any call when the plan holds a removable slot
  that the body leaves out. The words name the slot and say to release it from the plan first. That
  way the screen never claims what the plan doesn't hold.

### F3 · MEDIUM · An unexpected error is logged as a warning with its class name only, and answered as storage trouble

**Evidence.** Two places do this:

- `api/tryon.py:105-106`, every route's catch-all;
- `wardrobe/tryon/part.py:75-77`, `_read`, used by `GET /v1/tryon`.

Both log `log.warning(..., extra={"error": type(exc).__name__})`.

A `TypeError`, a `KeyError`, or a `ValidationError` while building a reply is a bug, in A or in
R13's engine. Today it becomes "That couldn't be done just now. Try again in a minute." (503, or
404 or 422 by `down`: see F5). The warning line says only `TypeError`: no module, no line, and the
wrong severity. In `_read` the same bug turns into "every saved comparison is Draft, and no figure
choice is listed".

Not logging values is right: a message or a traceback's text can carry his numbers. But the
location of the error carries none of them.

**Fix.** Use one helper in both places:

- `where = traceback.extract_tb(exc.__traceback__)[-1]`, then
  `extra={"error": type(exc).__name__, "at": f"{Path(where.filename).name}:{where.lineno}:{where.name}"}`;
- log at `error`, unless the error is a known storage one (`WardrobeUnavailable`, the docs
  layer's errors);
- never `exc_info`, never `str(exc)`.

The needles guard (`test_r131_a_needles.py`) then proves the new field carries no measurement.

### F4 · MEDIUM · Two AVT-14 guards are not pinned: another slot's options, and the eval's colour needle

**Evidence: the options filter.** A scratch mutation drops `p.private or` from `options.py:142`. It
is a pytest plugin, and no file was changed. With it, **all 147 tests stay green and the eval's
AVT-14 case still passes.**

The cause: the fakes' only private pieces are the vest and the underwear. Their slots have no
options at all (`options.py:163`). So no test or case ever has a private piece among the types of
a slot that is shown.

Without the filter, a top he made private would be offered under the shirt slot, with:

- its `wi_` id;
- the words "a private basic";
- its template.

**Evidence: the colour needle.** The eval's AVT-14 case searches the served text for "maroon"
(`evals/r13_1/looks.py:211`). A look serves colour as `rgb` numbers, never as a name, so that
needle can never fire. Only the private slots' `rgb` is checked.

**Fix.**

- Add `test_avt14_looks_a_piece_made_private_is_never_another_slots_option`. Make `T.white`
  private, then read `for_plan` and `for_pieces("top:" + T.shirt)`. `T.white` must be in no option
  and nowhere in the JSON.
- Extend the eval's AVT-14 case the same way, and also search for `list(model.rgb_of("maroon"))`.
- Add the control "options keep private pieces" (the mutation above) to `_controls()`.

### F5 · LOW · Server trouble answered as 404 or 422 on five routes

**Evidence.** `api/tryon.py:233, 263, 289, 301, 313` pass `down=422` or `down=404`, because those
rows of the contract have no 503 (`wardrobe/tryon/http.py:79-84`).

Probe:

- storage failing on `GET /v1/tryon/saved/{id}` gives 404 `unavailable`;
- the `DELETE` of the same gives the same;
- R13 off on that GET gives 404 `off`.

The error code tells D what happened, but the status doesn't. Anything that looks only at the
status reads a 404 as "gone", and a 422 says his request was wrong.

**Fix** (I1, the contract). Add 503 to those five rows, then drop `down=` here. Storage trouble is
then 503 `unavailable` or `off` everywhere.

### F6 · LOW · A reply card's covered slot has an empty readiness

**Evidence.** `looks.py:176`. An id-less `slot:` is how I0's card sends a private slot, or a top
he made private. It is served with `readiness: ""` and `eligible: false`.

`private=1` can't add its piece, because there is no id. D's checklist row then has no words.

**Fix.**

- When the card carries `plan`, take that slot's piece from the plan itself (`found.slot(slot)`,
  read fresh). Its readiness is then real, and with `private=1` so are its words.
- Otherwise, serve one fixed word.

### F7 · LOW · "Use these measurements" isn't bound to the draft he saw

**Evidence.** `versions.py:90-96`, `api/tryon.py:180-187`: Use takes no argument.

With the section open on two devices, a press on the laptop makes the phone's newer draft current
without his seeing it. That goes against his "Keep the current version available until the
replacement is approved".

**Fix** (I1, the contract). `POST /v1/tryon/body/use?at=<draft.at>`, refused 409 `changed` when
the draft isn't that one.

### F8 · LOW · Bodies: lax numbers and no per-route cap

**Evidence: lax numbers.** `BodyIn` (`wardrobe/tryon/http_figure.py:102-107`) is lax. Probe:

- `"172"` and `172.0` are accepted as a typed 172;
- `true` reaches the range words;
- `172.5` gets "That request can't be read." instead of words about whole centimetres.

**Evidence: no cap.** `body_of` (`api/tryon.py:138`) reads up to the app's 2.1 MB cap, though A's
largest body is a few KB. A 1.5 MB body was read and parsed before the 422.

**Fix.**

- Use `read_capped(request, 16_384, too_large=…)` in `body_of`, answering a 413 `too_large`
  `Refusal`. `api/book.py` caps its settings body at 4 KB the same way.
- I1 makes `BodyIn`'s fields `StrictInt`, or A answers a fraction with `versions.NOTHING`'s
  "whole centimetres" words.

### F9 · LOW · Privacy rows: stale count and export entries, an empty document, the spend not mentioned

**Evidence.**

- `privacy.py:32-48` counts and exports `doc.assets` without tidying. Choices of purged or merged
  pieces stay until his next figure choice (`assets.py:84`).
- `privacy.py:62` makes a present but empty document not deletable from `tryon_figure`. That
  happens after he drops a draft with no current version. Only `tryon_all` removes it then.
- `tryon_all` counts documents, under the unit "items" (`privacy.py:84`, `kept.SPECS`).
- `tryon_all`'s words list what goes, but not that the month's spend stays (`kept.SPECS`, I0's).
  D16 says it stays.

**Fix.**

- Tidy against R13's view when it can be read; otherwise keep the entries as stored.
- Set `deletable=True` whenever the stamp exists.
- I1: give `tryon_all` the unit "documents", and add "The month's Try-on spend (numbers only)
  stays 13 months for your monthly limit." to its words.

### F10 · LOW · The rollback promise doesn't hold for `Body`, and the unreadable words blame the key

**Evidence.**

- `store.py:14-15` promises that records ignore a field a later release adds. A's `_Rec` does.
- But `model.Body` is `extra="forbid"` (`model.py:102`, I0's). After a release that adds a
  measurement field, a rollback can't open `tryon/{uid}`.
- `api/tryon.py:59-61` then says "JARVIS's key changed: delete it in Privacy to start again". That
  tells him to delete data that is only from a newer release.

**Fix.**

- I1 reads stored bodies with `extra="ignore"`, and keeps `forbid` on `BodyIn`.
- The words say "can't be opened on this server", without naming a cause.

### F11 · LOW · A's AVT-11 case has no control

**Evidence.** `evals/r13_1/looks.py:346-358` has eight controls, none for
`avt11_saved_rechecked`. M8's AVT-11 control belongs to B and D.

The unit tests catch a saved comparison that stops re-checking
(`test_avt11_saved_a_piece_that_changed_state_opens_as_a_draft`), but the eval can't show that it
would.

**Fix.** Add a ninth control: `saved.look_view` answers the stored slots as Ready. It must turn the
AVT-11 case red.

### F12 · LOW · OPS-05 and a See it on me press already in flight (for I1, with C)

**Evidence.** `erase.py:27-40` deletes what is on disk. Nothing stops a picture whose Google call
started before the delete from being written after it. A can't close this alone. C's write path
was not read here: it is on C's branch.

**Fix** (I1, with C).

- C's picture write checks his YES again (gone after OPS-05) in the same transaction, and drops
  the picture if the YES is gone.
- The OPS-05 test gains a press that finishes after the erase.

## 3. The three items for I1 (INTEGRATION-A §8.2–8.4)

### 8.2 `LookSlot.refs`: yes, as named pairs

I agree with this item.

**Why the slot needs it.** `views` names the views kept, but the slot carries only one crop (the
texture's). So:

- D's `test_avt04_cards_*` can't show the front AND the back card.
- C can't find the front crop when the texture is `detail`.
- Today's AVT-05 test finds the front card through `LookOption.photo`, which is `p.photos[0]`.
  That is the front only because of R13's capture order.

**The recommendation.** Use `refs: tuple[RefCard, ...]`, with `class RefCard(_M): view: View;
photo: PhotoId`, rather than bare 2-tuples. The contract uses named fields everywhere, and
`[["front", "wh_…"]]` invites index mix-ups in JavaScript.

- Order the refs front, back, detail; leave them empty on a covered slot.
- A builds them from the same `kept` map as `views` (`looks.py:194`), so the two can't disagree.
- The fake server's `look_slot` and D's cards use `refs`. C takes the front crop from it.
- Pin them in AVT-04's named test: `kurta.refs` is front `…a001`, then back `…a002`.
- Add them to the AVT-04 control: its back ref is gone.
- Keep `views`: B and D already read it.

### 8.3 "No colour set": choose (a), `rgb: null`

Serve `rgb: null` for a drawn piece with no colour.

**Why (a).**

- B changes nothing. BRIEF-B already draws null as mid-grey ("`rgb` [r, g, b] (0–255) or null
  (mid-grey)").
- D's rule is one line: a slot with a `template`, not `private`, whose `rgb` is null says "no
  colour set".
- No JavaScript keeps a copy of (128, 128, 128), and `NO_COLOUR_RGB` stays the server's one
  source.
- Choice (b), a `no_colour` flag, would be a second field that can disagree with `rgb`.

**The change.**

- In `looks.py:199`: `rgb=rgb_of(p.colour) if p.colour else None`. The palette covers every one of
  R13's colours (checked), so only "no colour" becomes null.
- The same in the fake server.
- One test: a piece with no colour has `rgb is None`, its `template` is set, and `approximate`
  still has "colour".

### 8.4 The `tryon_figure` export and the `needles` suite: keep the numbers

**The export keeps his measurements.**

- The Privacy export is his own copy of his own data. An export of "Your measurements and your 3D
  figure" without the six numbers he typed is not that.
- R13's pieces row already exports his labels (`catalog/data.py:39-57`).
- The same numbers go to the same signed-in session through `GET /v1/tryon`. So hiding them from
  the export, or putting a passkey on it, protects nothing.
- `PrivacyService` audits an export with a count only, and `export_all` already needs a proof.

**The `needles` suite allows the measurement needle in exactly one place:** the payload of
`tryon_figure`, both its single export's `data` and `export_all`'s `categories.tryon_figure`.

- It must find the needle nowhere else: in no other category, not in `unavailable`, not in the
  export's audit line, and in no log.
- Its positive control: the needle planted in another category's export is found.

`test_the_figure_row_counts_exports_and_deletes_with_a_confirm` stays as it is.

(INTEGRATION-A §8.1's two wiring pins: confirmed. `tests/test_r131_wiring.py` fails exactly those
two, 227 passed with the seam tests, and the proposed diff is right.)

## 4. The checks this review ran (head `08d4ed0`)

Each check ran one at a time; the heavier ones ran behind the shared lock.

| Check | Result |
|---|---|
| `pytest tests/test_r131_a_*.py`, Python 3.11 | **147 passed** |
| Coverage of A's 11 modules | 95–100 % each (`api/tryon.py` 96 %, `looks.py` 95 %, the others 98–100 %) |
| `evals/r13_1/run.py --mock --part looks` | **9/9 passed; the negative control failed the suite.** Each of the 8 controls turned its own case red for its own reason (each failure list was printed and read). |
| `tests/test_r131_wiring.py` and `tests/test_r131_seams.py` | 227 passed, 2 failed: the two I0 pins of INTEGRATION-A §8.1, as expected until I1 |
| `ruff check` and `ruff format --check`, A's 24 files | clean |
| `mypy src/jarvis/wardrobe/tryon src/jarvis/api/tryon.py` | the baseline error only (`memory/redis_store.py:67`) |
| Static checks: real clocks, `$`, module and function sizes | clean |

The scratch probes (outside the tree, on the branch's fakes):

| Probe | Finding |
|---|---|
| the race's reply | F1 |
| a removed watch, confirmed | F2 |
| the options' private filter dropped (tests and eval) | F4 |
| storage down on the saved routes | F5 |
| a card's covered slot | F6 |
| odd and big bodies | F8 |
| concurrent drafts and Use | holds |

**What this review could not verify here:**

- real Firestore transactions;
- a real WebAuthn passkey;
- the browser;
- C's erase and picture write (on C's branch);
- how D's console treats the confirm's replies.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 20:50 IST | R13.1 | Review 1 of Part A at `08d4ed0`, in a fresh context (security, code, Python, silent failures). Verdict WARNING: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 8 LOW. F1 HIGH: "Use this look" answers `outfit_plan`'s refusal as 200 `executed`. Recommendations on INTEGRATION-A §8.2 (`refs` as named pairs), §8.3 (`rgb: null`) and §8.4 (keep the numbers; the needles suite allows them only in `tryon_figure`'s export). The checks with their numbers. | 🛠 Mark XXIII (review A-1) |
