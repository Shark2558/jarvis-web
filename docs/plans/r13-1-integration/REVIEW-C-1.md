Version v13.1.1 · 17 Nov 2026, 19:55 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (review C-1)

# R13.1 — Part C review 1: See it on me

A fresh context that did not build Part C reviewed it as `security-reviewer`, `code-reviewer`,
`python-reviewer` and `silent-failure-hunter` (`.claude/agents/`), with `CLAUDE.md`,
`.claude/rules/ecc/common/*` and `.claude/rules/ecc/python/*`.

- **What:** branch `r13-1-c` at `96b5507`, against `r13-1-i0` at `eb8b7e4` (31 files, +6,058 −30).
- **Read against:** `BRIEF-COMMON.md` v13.1.2, `BRIEF-C.md` v13.1.2, `INTEGRATION-C.md` v13.1.2
  (§6.10 and §4.17 included), `I0-NOTES.md`, and the plan v13.1.3 (D10–D16, D22).
- No code was changed. No call reached Google.

This review is the agent review that INTEGRATION-C §7 asked I1 or the Workshop to run.

## Verdict

**WARNING. Fix the one HIGH on `r13-1-c` before the merge. I1 decides the two MEDIUMs.** There is
no CRITICAL.

The core of the money path holds:

- the gates run in order, each before any spend;
- the reserve is atomic, with `busy` and the cap inside one transaction;
- every exit after the reserve settles or releases the hold, and a crash leaves it for
  `seeme_daily`;
- a repeated request id is answered from `done`;
- GST is in every ₹ figure.

So are the console-only rule, the image handling, the refusal of a private piece, the adapter's
billed-or-not split, untrusted content, retention and OPS-05's order.

The findings:

- **HIGH (1).** His T-shirts can never go in a picture: the adapter refuses their words, and the
  press says Google is unavailable.
- **MEDIUM (2).** The consent is not bound to the cache line or to the words he read (§6.10; a
  fix is given). A press already in flight outlives OPS-05 and his withdrawal.

| Grade | Count | Status |
|---|---|---|
| CRITICAL | 0 | pass |
| HIGH | 1 | fix before the merge |
| MEDIUM | 2 | I1 |
| LOW | 9 | as time allows |

## What I ran

| Check | Result |
|---|---|
| `tests/test_r131_c_*.py` (Python 3.11, behind the lock) | **163 passed** |
| `evals/r13_1/run.py --mock --part seeme` | **26/26 passed**; the control failed the part: True |
| `test_r131_seams.py`, `test_r131_wiring.py` | 230 passed, 2 failed. Both failures are I0's "not built yet" pins (INTEGRATION-C §6.1) |
| `ruff check`, `ruff format --check` (C's 27 files) | clean |
| `mypy` on C's 15 modules | the baseline error only (`memory/redis_store.py:67`) |
| Sizes, by the AST | largest module `api/seeme.py` (394 lines); longest function `Press.press` (33 lines) |
| Real clocks under `wardrobe/seeme`, `llm/tryon_gemini.py`, `api/seeme.py` | none |
| The eight tick pins (diff read) | only the pinned lists moved |

I also ran five scratch checks, outside the repository and not committed. Each one is named under
its finding:

1. one of his T-shirts through the adapter (finding 1);
2. OPS-05 during a press (finding 3);
3. `done` on a store that doesn't keep a map's order (finding 4);
4. the consent digest with the cache off and on (finding 2);
5. a client disconnect under this app's `@app.middleware("http")` (Starlette 1.10). The handler
   is NOT cancelled, so a closed tab doesn't strand a hold.

## Checked and holding

- **Authorisation.**
  - Every route is under `require_auth`, so a cookie write needs the CSRF header.
  - The 12 console rows check `session_email` first: before the limit and before the body.
  - A bearer token gets 403 `console_only` (a test and an eval case).
  - The uid always comes from `current_user`.
  - `tg_` and `tp_` ids are checked by `fullmatch` before a path is built.
  - Every read checks the plain `owner` field, and the AAD binds the uid.
- **Limits.**
  - 30 changes, 60 reads and 6 presses a minute, checked before the body is read.
  - JSON bodies are capped at 16 KB.
  - JPEGs are capped at `tryon_photo_max_kb` by `read_capped` (from Content-Length, then while
    streaming).
- **Images.**
  - JPEG only, by content type and by magic bytes.
  - `sanitise_jpeg` drops every APPn and COM segment (EXIF, GPS, XMP, ICC), allows one SOF and
    at most 2,048 px a side. Then the SOF side must be at most 1,568 px.
  - The server never decodes a picture, so there is nothing for a decompression bomb to hit.
  - Read back with `PICTURE_HEADERS` (`no-store`, `default-src 'none'`, `nosniff`, CORP
    same-origin), typed by magic bytes.
- **Private pieces.**
  - Each piece asked for is checked on a FRESH view (`split` → `_piece_refusal`), before the
    reserve.
  - A private piece is never named: no id, only the "covered" words, in the estimate, the pairing
    and the picture.
  - The eval's control `_lax` turns that case red.
- **Consent.**
  - Exactly `YES` once trimmed. `ＹＥＳ` and `YES` followed by a zero-width space are refused.
  - The ₹ is never in the hash: tested both ways, and a control proves it.
  - Withdrawing is one write.
- **The cap.**
  - The reserve is ONE transaction. A refusal writes nothing (the transaction function raises).
  - A counter that can't be read refuses.
  - `released` is set before the first await and reset when the write fails.
  - The transaction functions are pure, so Firestore's retries are safe.
  - The 34th picture fits and the 35th is refused. Ten presses at once: one reserves, nine are
    `busy`.
- **Every exit after the reserve.**

  | What happened | What the hold does |
  |---|---|
  | `TryOnNotBilled` | released |
  | `TryOnMaybeBilled`, a timeout, an unknown error | settled at the hold |
  | a blocked 200 | settled at the hold, counted as blocked |
  | a picture | settled from its usage, in `finally` |
  | a process crash | stays held; `busy` for 10 minutes; `seeme_daily` settles it at the hold after an hour |

  The outer deadline is 125 s.
- **The adapter.**
  - Plain REST: no SDK, no API key.
  - The bearer comes from `tokens.headers()`; `invalidate()` on a 401.
  - The project is checked against a pattern.
  - Redirects are off, and there are no retries, so nothing is billed twice.
  - Timeouts: 10 s to connect, 120 s for the call, inside an outer `asyncio.timeout`. A `sent`
    flag records whether the request may have left.
  - Text parts are never read. `blockReason` maps to a fixed word.
  - The picture's type comes from its magic bytes. The usage is parsed defensively.
  - Logs hold class names and statuses only (`httpx` and `httpcore` are at WARNING in
    `jarvis.logging`).
- **Untrusted content.**
  - Only the garment's bytes are used.
  - The prompt is built from fixed words under `WORDS`.
  - Neither Google's text parts nor its `blockReasonMessage` are read (the eval's needle case).
- **Never his.** No write to any R13 collection; R13's `rev` is unchanged. The AVT-12 test proves
  it on R13's real catalog, and an eval control backs it.
- **Retention.**
  - Pictures go after 30 days, tested at 23:30 and 00:30 IST.
  - At most 24 are kept.
  - A garment photo stays while a kept picture shows it.
  - A picture goes when one of its pieces is made private or purged.
  - The spend is kept 13 months.
  - Across 28 May 2027, tested at 23:30 and 00:30 IST.
- **Privacy and OPS-05.**
  - Three rows, all on `privacy`. Exports never hold bytes. The spend can't be deleted.
  - `erase` deletes the pictures, then the garment photos, his photo and his YES, in one write.
    It never deletes the spend. `OnceCache` is cleared.
- **Style.**
  - Modules ≤ 400 lines and functions ≤ 50 lines.
  - No real clock.
  - No `$` in a sentence he reads.
- **The deploy's R13.1 block.** I concur with INTEGRATION-C §7: it holds. Its notes stand:
  - (a) MEDIUM: the comment says more than the role does;
  - (b) LOW: an existing role is reused unchecked;
  - (c) not verifiable here.

  I also concur with §6.2, which makes `tryon_cache` default to true.

## Findings

### 1. HIGH — His T-shirts can never be sent: the adapter refuses their words, and the press blames Google

**Evidence.**

- R13 gives a T-shirt display words with a capital letter and a hyphen.
  `src/jarvis/wardrobe/redact.py:48`:

  ```python
  special = {"t_shirt": "T-shirt", "dress_shoe": "dress shoe", "work_gear": "work gear"}
  ```

- C sends those display words to Google.
  - `src/jarvis/wardrobe/seeme/pair.py:67-73`: `mine_words(p)` is R13's `piece_words(p)` without
    its article, so a grey T-shirt becomes `"grey T-shirt"`.
  - `pair.py:112` puts it in `Mine.words`.
  - `src/jarvis/wardrobe/seeme/make.py:232` sends it as the garment's words.
- The adapter refuses them.
  - `src/jarvis/llm/tryon_gemini.py:72`: `WORDS = re.compile(r"^[a-z][a-z ]{0,59}$")`.
  - `:128-129`: `_check` raises `TryOnNotBilled("a garment's words are not fixed words")` before
    anything is sent.
- The press blames Google. `make.py:244-247` releases the hold on every `TryOnNotBilled` and
  answers `503 provider_unavailable` with `texts.UNAVAILABLE`: "Google's image model isn't
  available just now. Nothing was charged."

**Failure.** Take any `t_shirt` of his (a sendable top) with a front crop, in `PictureIn.pieces`,
on the real adapter:

1. the estimate lists it as sent;
2. the press reserves the hold;
3. `_check` refuses before anything is sent;
4. the hold is released;
5. he reads that Google is unavailable.

This happens every time, in every colour. The pairing may offer the piece too: `from_look` takes
it as sendable.

The scratch check reproduced it on the seeded pilot's grey tee: the estimate's `sent` was
`["grey T-shirt"]`, the press answered `503 provider_unavailable`, and 0 requests reached the
fake Google. Every type with a garment slot was also tried with every colour in `COLOURS`. Only
`t_shirt` is refused, and every new garment's words pass.

**Why the guards miss it.**

- The press tests, the AVT-12 test and the eval's `fake1` runs use `ScriptedTryOn`, which doesn't
  apply `WORDS`.
- The adapter's tests feed it hand-written words.
- The eval's Gemini runs send only the jeans and the trousers.

**Fix** (test first):

- Build the words sent to Google from C's own fixed lists, not from R13's display words. In
  `pair.py`, `prompt_words(p)` = colour and type with `_` turned into spaces ("grey t shirt"),
  used for `Garment.words`. `mine_words` stays for what he reads. Keep `WORDS` strict.
- Tests:
  - a table test: every `TEMPLATE_OF` type with a garment slot × every `COLOURS` value passes
    `tryon_gemini._check`, and so does every `NEW_TYPES` × `COLOURS` value through `short_words`;
  - a press with `T.tee` on the adapter (a recorded answer) makes a picture.
- Words that JARVIS itself can't send are JARVIS's fault, not Google's. Refuse them before the
  reserve, not as "Google isn't available".

### 2. MEDIUM — The consent is not bound to the cache line or to the words he read (INTEGRATION-C §6.10): the fix

**Evidence.**

- `src/jarvis/wardrobe/seeme/consent.py:54-62`: `template_text` and `digest` cover only
  `{version, provider, model, location, location_words}`.
- `consent.py:65-78`: the words he reads change with `cache` (`CACHE_OFF_LINE` or
  `CACHE_ON_LINE`).
- `part.py:66` passes `cache` to the words only.
- `make.py:152` checks `current(uid, provider.describe())`, with no cache.
- `consent.py:138-139`: `give` checks only the constant `VERSION` ("c2").
- `config.py:648`: `tryon_cache` defaults to false.

**Failure.**

- **(a) A change in what Google keeps, without a new YES.** He types YES under "Google's own
  short-term cache of requests is switched off for JARVIS." A later deploy whose cache PATCH
  fails sets `JARVIS_TRYON_CACHE=true`. The digest doesn't change (the scratch check: the same
  with the cache off and on), so his YES stays current. Yet Google may now keep each request for
  up to 24 hours. D11 counts "what Google keeps" as part of what he agrees to.
- **(b) An edited line keeps every YES.** If any line (`SENT_LINE` and the rest) is edited
  without a manual bump of `VERSION`, every YES stays current.
- **(c) Not bound to what he saw.** The YES is not bound to the lines his console showed: `give`
  compares a constant.

**Fix** (recommended for I1; C's file, plus its callers):

```python
# src/jarvis/wardrobe/seeme/consent.py
def template_text(desc: TryOnDescription, *, cache: bool) -> str:
    """What the hash covers: the version, who and where, the cache, and every line he reads.
    The lines hold no ₹ figure (PRICE_LINE is words only), so a moved rate never asks again."""
    fixed = {"version": VERSION, "provider": desc.provider, "model": desc.model,
             "location": desc.location, "location_words": desc.location_words,
             "cache": cache, "lines": list(words(desc, cache=cache))}  # fmt: skip
    return json.dumps(fixed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(desc: TryOnDescription, *, cache: bool) -> str:
    return hashlib.sha256(template_text(desc, cache=cache).encode()).hexdigest()


def shown_version(desc: TryOnDescription, *, cache: bool) -> str:
    """The version the card shows and sends back: 15 characters (ConsentIn allows 20)."""
    return f"{VERSION}-{digest(desc, cache=cache)[:12]}"
```

The callers change too:

- `ConsentView.version` becomes `shown_version(...)`.
- `give` refuses (`422 consent_needed`, `OLD_WORDS`) unless `version == shown_version(desc,
  cache=cache)`.
- `current(uid, desc, *, cache)` compares `digest(desc, cache=cache)`.
- `Press._on` and `view` pass `cache=self.kit.ctx.s.tryon_cache`.
- The eval's `_priced_text` control takes `**kw`.

No contract change: `template_version` is a string of at most 20 characters.

Tests:

- cache off, then on: asks again;
- a changed line: asks again;
- a YES sent with the earlier `version`: refused;
- 95.24 → 96.10: still current (unchanged).

Pair it with INTEGRATION-C §6.2 (`tryon_cache` defaults to true), so pictures switched on outside
the deploy say "up to 24 hours".

### 3. MEDIUM — A press already in flight outlives OPS-05 and his withdrawal: the picture is kept after "Delete all my try-on data"

**Evidence.**

- `src/jarvis/wardrobe/seeme/make.py:267-287`: `_keep` saves the picture once the call returns.
  Nothing checks that his photo and his YES still exist.
- `part.py:224-238` (`erase`), `vault.py:130-137` (`PersonPhoto.delete`, the withdrawal) and
  `privacy.py:82-88` (the pictures row) delete only what exists at that moment.

**Failure** (reproduced by the scratch check):

1. He presses.
2. While the provider answers (up to 125 s), A's OPS-05 path runs `erase(uid)`: 3 documents
   deleted, his photo gone, his consent no longer current.
3. The provider answers, and `pictures.save` writes `tryon_picture/{uid}_tp_…`. It is listed and
   kept 30 days.

A withdrawal (deleting his photo) or the pictures row's Privacy delete during a press ends the
same way. So a picture made from a photo he has just withdrawn outlives the delete he confirmed
with his passkey.

`delete_photo` also leaves `OnceCache` alone, so a shown-once picture can still be taken for 10
minutes after he withdraws.

**Fix.**

- In `_keep`, before `pictures.save`, check again that his photo is kept and his consent is
  current (with finding 2's `cache=`).
- When either is gone:
  - don't keep the picture;
  - still settle and record it: it was billed;
  - answer `422 no_photo` in fixed words ("Your photo was deleted while the picture was being
    made, so it isn't kept. It may still be charged (about ₹9).");
  - set `done` so that a repeat says the same.
- `delete_photo` and the photo row's delete clear his `pictures.once` entries.
- Test: a provider held at a gate, with OPS-05 (and, separately, a withdrawal) during the call.
  Afterwards there is no `tryon_picture` document, and the hold is settled.

### 4. LOW — `done` keeps "the last 50" by insertion order, which a Firestore map doesn't keep

**Evidence.**

- `src/jarvis/wardrobe/seeme/cap.py:134`: `done = dict(list(m.done.items())[-DONE_MAX:])`.
- `src/jarvis/storage/firestore_docs.py:61-63`: `to_dict()`. A map comes back from a protobuf map,
  which has no insertion order.
- `cap.py:218-219` puts the new outcome last in Python only.
- `tests/test_r131_c_cap.py:174-181` passes because `MemoryDocs` keeps Python's order.

**Failure.** The scratch check used a store that returns maps sorted by key: 50 answers, then
press A, then press B. A's outcome is pruned at B's reserve, so a retry of A reserves again: a
second call and a second charge. It needs 51 or more answers in one IST month, and a lost reply
retried after the next press.

**Fix.**

- Keep `at` in each outcome and prune the oldest by `at`, or keep a `done_order` list.
- Test on a store whose `get` returns maps sorted by key.

### 5. LOW — A failed release or settle after the call is never retried, and a failed settle skips his usage month

**Evidence.**

- `make.py:244-247`: the release, then the refusal.
- `make.py:283-287`: `finally` runs the settle, then `_record`.
- `cap.py:224-228`: `released` is reset so the call can be tried again, but nothing tries again.
- `cap.py:239-249`: `settle_old` never calls `Billing.record`.
- `api/seeme.py:90-92`: any other exception answers 503 "can't be reached just now".

**Failure.**

- **After a not-billed call.** A storage error on the release after a 429 leaves the hold in
  place. `seeme_daily` later turns it into ₹11.22 of spend (`maybe_billed`) for a call that
  Google never billed.
- **After a made picture.** A failed settle raises out of `finally`. Then:
  - `_record` is skipped, so his overall monthly limit never hears of a billed picture;
  - the picture is saved, but he gets 503 "can't be reached" with no ₹ note;
  - the hold keeps a retry `busy` until the morning.

A crash ends the same way, and that is accepted. These two cases can be put right while the
process is still running.

**Fix.**

- Retry `_close` 2 or 3 times, with a short wait, inside `release` and `settle`. The flag already
  allows it.
- Run `_record` in its own `try/finally`, so it happens whatever the settle does.
- On a final failure, log at ERROR with the request id, and answer in `MAYBE_BILLED`'s words.
- Decide whether `settle_old` also records the hold to `Billing.record`, and pin the choice.
- Tests: a store whose next transaction fails, once on the release and once on the made path.

### 6. LOW — The end date has two sources: the gate reads the setting, the consent reads the adapter

**Evidence.**

- `make.py:102-109`: `Kit.ends` reads `s.tryon_model_retires`.
- `part.py:180-189`: the notice and `ProviderView.retires_on` read the setting.
- `consent.py:76-77`: `END_LINE` reads `desc.retires_on`.
- `llm/tryon.py:51`: `RETIRES_ON` names a date for `gemini-3.1-flash-image` only.
- `config.py:645`: the setting defaults to 2027-05-28.

**Failure.** D18 says a newer model "is a setting". Switch to `gemini-nano-banana-2.1` at `global`
(the other priced pair) without also editing `tryon_model_retires`. Then:

- See it on me still turns itself off on 28 May 2027;
- the panel says "Google may retire this image model on 28 May 2027" about the new model;
- the new model's consent names no end date.

**Fix.**

- Use one source: the model's own `RETIRES_ON` entry, through `provider.describe().retires_on`.
  The gate, the notice and `ProviderView` all read that value.
- If I1 wants an override, make it per model.
- Test: the second priced model, with the default setting, is not retired on 28 May 2027.

### 7. LOW — Owner question 13's default and the check of his photo rest on the console alone

**Evidence.**

- The plan's data model says `tryon_person/{uid}` holds "the device's check (people, faces
  counts)".
- `vault.py:106-111` and `garments.py:81-92` receive no check and store none.
- `api/seeme.py:154-172` and `226-249` take only the JPEG (and the garment's type and colour).

**Failure.** Suppose a console regression, or another client of these routes (a future phone
screen), sends a garment photo with someone's face. The server never decodes, so it can't tell,
and the photo goes to Google. Owner question 13's default is that no one else's face goes to
Google. The server can't check pixels, so this rule trusts the client. Today it isn't even
recorded.

**Fix** (I1, a contract change):

- The door adds the device check's counts to both uploads as query fields (`?people=&faces=`).
- The server refuses a garment photo with `faces > 0`, and his photo with `people != 1` (422, in
  fixed words).
- It keeps the counts as plain fields, as the data model says.
- One test per upload.

### 8. LOW — The audit of a paid press can't tell made, released and maybe-billed apart

**Evidence.**

- `api/seeme.py:336-343`: the audit's args are `{request_id, garment, pieces}`, and its detail is
  "a picture made" or "no picture".
- `api/settings_audit.py:36`: `risk=ActionRisk.REVERSIBLE` on every line.
- `api/seeme.py:362-391`: Keep and a picture's delete write no audit line.

**Failure.** The audit shows the same "no picture" line for three different outcomes:

- a 409 `busy`: nothing was reserved;
- a 503 that was released: nothing was charged;
- a 503 maybe-billed: ₹11.22 became spend.

A made picture's line carries no ₹ either. So the spend can be reconciled only from
`tryon_spend`, never from the audit.

**Fix.**

- Add `code` (the refusal code, or `made`) and `inr` (settled, or kept at the hold) to the press's
  args. Still ids and numbers only.
- Audit Keep and a picture's delete by ids.
- Whether a paid line deserves a stronger risk than REVERSIBLE is I1's call (`record_change` is
  shared).

### 9. LOW — Silent fallbacks, and a provider bug charged as "maybe billed"

**Evidence and failure.**

| Where | What happens | Logged? |
|---|---|---|
| `part.py:141-142` (`_room`) | any exception reads as ₹0 of room | no |
| `garments.py:111-112` | a garment document that can't be read is None, so 404 `no_garment` | no |
| `consent.py:101-104` | a record whose JSON won't parse reads as "no consent" | no |
| `api/seeme.py:90-92` (`_run`) | any other exception is a 503 | the class name only: no route, no request id |
| `make.py:248-254` | any error from `make` other than `TryOnNotBilled` (a `TypeError` in an adapter too) is "maybe billed": settled at ₹11.22, with the worst-case dollars added to his month | at WARNING |

**Fix.**

- Log each fallback at WARNING, with ids and class names only.
- `_run` adds the route's name, and the request id for the press.
- In `_make`, catch `TryOnMaybeBilled` and `TimeoutError` as "maybe billed". Treat any other error
  as a provider bug: log it at ERROR, and still keep the hold, because the request may have left.

### 10. LOW — Google's answer is read whole before its size is checked (accepted in INTEGRATION-C §7; a cheap fix)

**Evidence.**

- `tryon_gemini.py:254`: `await self.http.post(...)` buffers the whole body.
- `:274`: `r.json()`.
- `:180`: the 16 MB check comes after the decode.

**Failure.** An oversized 200 (from a misbehaving endpoint or proxy) is buffered and parsed before
it can be refused as `too_large`. The instance has 512 MiB (`deploy/cloudrun.sh:600`). If it runs
out of memory and restarts, the hold is left for `seeme_daily`.

**Fix.**

- Use `async with self.http.stream("POST", ...)` and read under a byte cap of about 23 MB (16 MB in
  base64, plus the JSON around it).
- Past the cap, raise `TryOnMaybeBilled("too_large")`.

### 11. LOW — Wrong or missing words: a piece in a taken slot, the shown-once picture, unused texts

**Evidence.**

- `pair.py:106-108` and `make.py:325-330`: one of his tops sent beside a new shirt is refused with
  `NOT_SENDABLE` ("Only a top, a bottom or an outer layer of yours goes in the picture."). But it
  IS a top.
- `texts.py:58`: `SAME_SLOT` is never used.
- `texts.py:97`: `NOT_KEPT` never reaches him. `pictures.py:145-147` returns a shown-once picture
  whose view differs only by `kept=False, until=None`, and `PictureView` has no words field.
- `texts.py:39`, `52`, `60`: `PHOTO_KEPT`, `CONSENT_GIVEN` and `UNTICKED` are never used.

**Fix.**

- Refuse a piece in a taken slot with `SAME_SLOT`. Tell it apart from `not_a_garment` inside
  `check`; the contract's `NotSent.why` stays as it is.
- Tell D and I1 that `kept=False` with `until=None` means "shown once", and that `NOT_KEPT` is its
  words (or add those words at I1).
- Remove the texts that are never used.

### 12. LOW — Gaps in the tests of the money paths

**Evidence.**

- `tests/test_r131_c_press.py:64` is the only test that pins `Billing.record`, and only on the
  made path. Nothing pins:
  - the worst-case record on a maybe-billed or blocked press;
  - the absence of a record on a release;
  - what `settle_old` records (today: nothing).
- No test makes the cap's settle or release fail after the call (finding 5).
- `test_r131_c_cap.py:174-181` relies on `MemoryDocs` keeping insertion order (finding 4).
- No test sends a real sendable type's words through the adapter (finding 1).
- No test erases during a press (finding 3).

**Fix.** Add these tests, each seen failing first, as the loop says. The table test of types ×
colours through `tryon_gemini._check` is the cheapest guard against finding 1's kind of bug.

## Concurring with INTEGRATION-C (not graded again here)

- §6.2: `tryon_cache` defaults to true.
- §6.3: Vitals shows the ₹ before GST.
- §7 deploy notes (a), (b) and (c).
- §4.12: the 20-garment limit is a query, then a write.
- §4.17: the two edges at the month's end.
- §7: a settle from usage may pass the hold, and is recorded as billed.

## Next steps

1. **Part C, on `r13-1-c`:** fix finding 1, test first (the table test and the press with
   `T.tee`).
2. **I1:** take finding 2's diff together with §6.2, and finding 3's check before the save.
3. **The LOWs** as time allows. Findings 4, 5 and 12 are the ones on the money path.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 19:55 IST | R13.1 | First edition. The fresh-context review of Part C at `96b5507`, as the security, code, Python and silent-failure reviewers. The checks run, with their numbers, and five scratch checks. What holds. 12 findings: 0 CRITICAL, 1 HIGH (T-shirt words refused by the adapter), 2 MEDIUM (the consent's binding with a recommended fix; OPS-05 during a press), 9 LOW. The verdict WARNING, with next steps | 🛠 Mark XXIII (review C-1) |
