Version v13.1.0 · 17 Nov 2026, 18:20 IST · Release R13.1 · Status: Draft · Owner: 🛠 Mark XXIII

# R13.1 — Part D: Console and phone (INTEGRATION-D)

Builder D's notes for I1 (branch `r13-1-d`, from `r13-1-i0` @ `eb8b7e4`). Plan:
`docs/plans/r13-1-try-on.md` v13.1.3 (D1, D4, D7, D8, D9, D11–D13, D16, D21, D22); brief:
`BRIEF-COMMON.md` v13.1.2 and `BRIEF-D.md` v13.1.2.

## 1. The plan (written before the code)

What D builds, all inside its own files (`console-tryon.js`, `console-tryon-list.js`,
`console-tryon-me.js`, `console-tryon-photo.js`, `console-tryon-card.js`, `console-tryon.css`), in
this order, each behaviour test first:

1. **The fakes** (`tests/r131_fakes_d.py`): D's routes ahead of I0's fake server (a plan in
   "Today and tomorrow", drawn crops for the image cards, a jacket in the laundry, both watches
   with photos, a recording tools route, a fake `/v1/chat` that answers "what should I wear?"
   with I0's real `TryOnCard` builder, a reset hook), and a contract-keeping fake engine
   (`tests/fixtures/r13_1/d_engine.mjs`: records every call, honours `__glFail`, draws a labelled
   stand-in), loaded in the browser in place of B's file by Playwright's routing only.
2. **Row 388** (`console-tryon-card.js`, `inline()`): a reply's `tryon` card opens the figure
   under the reply with no tap, dressed through `GET /v1/tryon/look?pieces=`; a private slot
   covered; the checklist under `__glFail`; a spoken reply the same; no card, nothing drawn; one
   stage on the page.
3. **The viewer and AVT-15** (`console-tryon.js`, `console-tryon-list.js`): the section opens
   dressed in the first look by itself; the stage; the checklist when 3D can't run (no WebGL2,
   a lost context, an asset, a 10 s first render, I0's throwing stub), with each piece's image
   card and readiness, Change, Wearing it (confirm first after a swap), Use this look, Retry 3D
   once a page.
4. **The controls** (D7): Front, Side, Back, Turn around, Closer look, zoom, Full screen; tuck,
   open, layers; swap with readiness words, Remove, undo (≤ 20); compare (one `show` with two
   figures, two lists with readiness), Save this comparison, saved comparisons re-opened.
5. **The measurements form** (D4) and the template choice (AVT-05), Delete all my try-on data
   (OPS-05, `JarvisPrivacy.remove('tryon_all')`).
6. **Save a picture of this look** (D9): the caption lines to `snapshot({caption})`, previewed
   from a `data:` URL, saved to Downloads.
7. **See it on me** (`console-tryon-me.js`, D11–D13, D22): the new garment's photo (file or the
   share tray), type and colour from lists, the device check, the pairing, his photo panel
   (`console-tryon-photo.js`, the third pixel panel), the YES dialog, the ₹ estimate and
   `.bdialog` confirm (Cancel sends nothing), progress, the picture with its words, Keep and
   delete, his garment photos.
8. **The eval** (`evals/r13_1/console.py`), the screenshots, the reviews, this file.

Tests that prove it: the named tests of BRIEF-D section 3 (browser, `tests/browser/test_r131_d_*.py`),
behaviour tests in Node (`tests/test_r131_d_*.py` over `tests/fixtures/r13_1/d_dom.mjs`), static
rules, and the eval's cases with their controls.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 18:20 IST | R13.1 | The plan, before the code | 🛠 Mark XXIII |
