Version v13.1.1 · 17 Nov 2026, 23:50 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — I1 notes (the four parts joined)

Written by the R13.1 I1 integrator on `r13-1-i1`, cut from `r13-1-i0` @ `eb8b7e4`. Merged with
`--no-ff` in this order: A `4dd58f6` (`dad08f8`), C `3660d24` (`8c63019`), B `eb7ea8d`
(`f42253e`), with no conflicts; D after its fixer finished (section "D" below). `main` is not
merged here.

Sources: the four `INTEGRATION-<X>.md` files ("Needs I1", A §8 and §11, B §6 and §8, C §6 and
§10.4, D §6), the four `REVIEW-<X>-1.md` reviews' notes for I1, `I0-NOTES.md` §5, and the plan's
I1 steps (`docs/plans/r13-1-try-on.md` v13.1.3: "Tests and evals", "Exit check").

States: **done** (commit), **declined** (the reason), **left** (for the integrated reviews, the
Workshop or a later release, with the reason). "Red first" means the test was run and failed for
the stated reason before the change; "a pin" means a test of behaviour the joined parts already
had, green when first run.

## Items

1. **I0's three stub pins** (INTEGRATION-A 8.1, B 6.1, C 6.1). Done `ef63076`. With no keyring,
   `tryon` reads A's `OFF_NO_KEY` and `seeme` C's "off: …" words; no part says "not built yet";
   the wired app's `GET /v1/tryon` is 503 `off` in A's words, `GET /v1/seeme` 503
   `not_configured`, both 401 signed out. B's engine keeps the engine contract and `mount()`
   with no host throws "The 3D view needs a place on the page.".
2. **A's contract changes against B, C and D** (INTEGRATION-A 11.3). Checked:
   - `rgb: null` → B draws it mid-grey and names `colour` in `approx` (`console-tryon-cloth.js`
     `rgbOf`, `GREY`); D: at D's merge.
   - `LookSlot.refs` → C does not read A's look: it finds a piece's front crop in R13's own photo
     records (`pair.front_of`, INTEGRATION-C §4.10). Both read the same `view` field, and a
     joined test pins that A's `refs` front and C's pick are the same crop. Done `20e6db4`.
   - The new codes (`refused`, `left_out`, `changed`, `not_whole`, `too_large`, `internal`) are
     D's to branch on: at D's merge.
3. **A's look route takes `?pieces=` with `&plan=`** (INTEGRATION-D §5). A pin `20e6db4`:
   readiness is read in that plan's context, so its own pieces are Ready; the same pieces with
   no plan read "Draft: reserved for your plan" (why D sends the plan along).
4. **The end date, one source** (INTEGRATION-C 10.4 b, review C-1 finding 6). Done `7b7c2c5`:
   `tryon_model_retires` is removed from `Settings` (the model's own `RETIRES_ON` is the one
   date; a second could only disagree), with its unused `_DAY` pattern; `config.py` is 789 lines.
5. **`tryon_cache` defaults to true** (INTEGRATION-C 6.2 and 10.4 d, review C-1). Done `7b7c2c5`,
   red first: fail toward disclosure. The deploy passes `JARVIS_TRYON_CACHE` explicitly and sets
   false only after its PATCH worked, so the deploy is unchanged. C's cache test now builds its
   world with the cache proved off.
6. **The deploy's role** (INTEGRATION-C §7 (a), (b)). Done `7b7c2c5`, red first: an existing
   `jarvisTryOn` is set back to `aiplatform.endpoints.predict` only (a note if that fails; the
   role is still used, never the broader fallback); the comment says what the role allows:
   prompt requests to any Agent Platform model, with the cap and the `jarvis-tryon` budget alert
   as the brakes. (c), whether the cache PATCH covers the `us` endpoint, can't be checked here.
7. **The fake server's consent version** (INTEGRATION-C 10.4 a). Done `c9d4c44`, red first:
   "c2-0123456789ab", the shape of C's "c2-" + 12 hex.
8. **A decodable fake picture** (INTEGRATION-D §7). Done `c9d4c44`, red first:
   `r131_fake_tryon.PNG` is a drawn 120 × 160 RGB PNG (407 bytes: a plain figure in a navy top);
   every test that compares bytes with it still does.
9. **SciPy in CI** (INTEGRATION-B 8, "Needs I1" 4). Done `9b35767`, red first: the 3.12 leg
   installs `scipy==1.18.1` (the script's own pin) after the homebridge extra. Checked with CI's
   own pins (3.12, numpy 2.5.4, scipy 1.18.1): B's two files 74 passed, 2 skipped, the release
   rebuilt byte for byte; the script's tests take about 11 s; coverage is measured on `jarvis`
   only, so the floor is not moved. 3.11, the browser and docs jobs are untouched.
10. **F8, F9, F10 on I0's files** (INTEGRATION-A 11.4, items 3–5). Done `044d636`, red first:
    `BodyIn`'s fields are `StrictInt`; `model.Body` reads with `extra="ignore"` (a rollback
    opens his figure; `BodyIn` stays strict); "All your try-on data" counts documents and says
    "The month's Try-on spend (numbers only) stays 13 months for your monthly limit.".
11. **One rule for the words a garment is sent in** (INTEGRATION-C 10.4 c). Done `1dcbaec`, red
    first: `llm.tryon.FIXED_WORDS`; C's `pair.PROMPT_WORDS` and the adapter's `WORDS` are that
    one object. `StrictTryOn` stays in C's fakes (it runs the adapter's whole check); I0's
    `ScriptedTryOn` is unchanged so no earlier test moves.
12. **A press in flight during OPS-05, A with C** (review A-1 F12, review C-1 finding 3). A pin
    `20e6db4`: OPS-05 through A's own `tryon_all` row while a press is held at the provider:
    422 `no_photo`; no picture, photo, YES, garment photo or figure left; the spend stays; the
    hold closed at what Google made; the wardrobe's `rev` unchanged. C's own fix closes it three
    ways (a re-check after the call, the check inside the save's transaction, the sweep after
    the delete); removing only the check in the save keeps this test green.
13. **The `e2e` suite** (plan "Tests and evals"). Done `2c5acb7`: BUILT through the real app
    (`evals/r13_1/wired.py`), five cases: "Meeting outfit update", "Layer and rotate", "Private
    items and photos" (OPS-05 through the Privacy service), See it on me's life (30 days, gone by
    `seeme_daily`), and row 388 typed and spoken through the mock brain. Its control (the look
    built from a stale view) fails "Meeting outfit update" for its own reason.
14. **The `needles` suite** (plan; INTEGRATION-A 11.4 item 7, C 6.7). Done `ab89c1d`: 9 classes ×
    13 sinks, a positive control per sink, `planted_all`, and the one request to Google decoded
    (exactly his photo, the garment, the chosen crop; one fixed text part). Allowed: the two
    photos in the request to Google; his measurements in `tryon_figure`'s own export (A 8.4,
    decided at review A-1); a private piece's label in R13's own export of his catalog
    (`wardrobe_pieces`). Its control (the adapter logging its request body) fails exactly the
    two photo needles.
15. **Console-only on the wired app** (I0-NOTES §5 item 2). A pin `6dede8d`: all 12 routes the
    contract marks console-only, the garment photo's three included, answer 403 `console_only`
    to a script holding his token and reach C from his console.
16. **The vitals line before GST** (INTEGRATION-C 6.3). Declined: `Billing.record` adds the
    pre-GST ₹ as every brain's line does; the Try-on panel and the cap show GST. One rule for
    every Vitals line.
17. **A port method for a photo's view** (INTEGRATION-C 6.4). Declined: not needed; C reads R13's
    plain `view` field read-only, and item 2's pin keeps it in step with A.
18. **The device check's counts sent with each upload** (INTEGRATION-C 10.4 f, review C-1
    finding 7). Left for a later release: a contract change across the door, D's photo panel and
    `http.QUERIES`; the server cannot decode a picture, so the check stays the device's (as R13's
    console face check is, card C63).
19. **The audit's risk level for a paid press** (INTEGRATION-C 10.4 g). Declined for R13.1:
    `record_change` is shared; the press's audit line already carries `code` and `inr`, the
    spend is in `tryon_spend` and Vitals, and every press sits behind his YES and a ₹ confirm.
20. **The data model's new fields** (INTEGRATION-C 10.4 h): `tryon_spend/{uid}_{YYYY-MM}` gains
    `done_order`, the consent record gains `cache`, and `tryon_spend/{uid}_prefs` holds his
    switch, cap and keep days (C §4.1). Recorded here; the plan is not re-versioned for them.
21. **Serve the figure's files compressed** (INTEGRATION-B 8, "Needs I1" 5). Declined for R13.1:
    the 2.6 MB come once a device and are cached a year (the release is in the URL); nothing in
    the app is compressed today (R7's vision files are served the same way). One app-wide change
    later, with the `.gz` beside each file under the manifest's sums.
22. **The book's licences for B's test source** (INTEGRATION-B 8, "Needs I1" 6). Declined: the
    book lists what ships; `tests/fixtures/r13_1/b_source.bin.xz` is CC0 test data that never
    ships.
23. **A sole and a longer coat** (INTEGRATION-B 8, "Needs I1" 7). Left for a later release: a slot
    carries its template, not its type, so it needs a contract word.
24. **I0's `fake_routes` at 126 lines** (INTEGRATION-A 11.4 item 9). Declined: a test fake, not
    product code.
25. **The fresh-context reviews** (A 8.5 and 11.4 item 10, C §7 and 10.4 i, D §6 item 5). Left for
    the integrated reviews (`code-reviewer`, `python-reviewer`, `security-reviewer`), which the
    Workshop runs on this branch.

## Known limits (recorded, not fixed)

- **"Use this look" refuses a look with a removed watch, belt, outer layer or socks** (409
  `left_out`): R13's engine re-adds a removable slot on every read, so a plan can't keep one
  empty. The durable fix is R13's (`Plan.omit`, INTEGRATION-A 11.4 item 1), a later R13 change.
- **Garment poke-through at inseam 66 and waist 120** (B's two documented limits, capped in its
  layer check): a ledge on the trousers with a thin line of the base layer (5.6 cm²) at inseam 66,
  and a waistband gaping 1.2 cm² under the belly at waist 120.
- **The watch strap's edge looks ragged in close-up.**

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 23:50 IST | R13.1 | First edition: A, C and B merged; items 1–25 (the stub pins, the contract checked against B and C, the end date and cache settings, the deploy's role, the fakes, SciPy in CI, F8–F10, one fixed-words rule, OPS-05 in flight, the e2e and needles suites, console-only on the wired app, and what was declined or left with reasons); the known limits | 🛠 Mark XXIII (I1) |
