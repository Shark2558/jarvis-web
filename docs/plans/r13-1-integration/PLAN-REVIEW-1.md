Version v13.1.1 · 17 Nov 2026, 14:00 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (plan review 1)

# R13.1 plan review 1 (fresh context, 17 Nov 2026)

Plan reviewed: `docs/plans/r13-1-try-on.md` v13.1.1 (Draft), all 881 lines, on `r13-1-plan` @ `281510d`
(the code is `main` @ `3f265cb`: `git diff 3f265cb 281510d` touches only the plan).
Checked against: that code; the owner's wardrobe workbook (sheet "Use Cases", rows AVT-01 … AVT-15 and
OPS-05, read with openpyxl `data_only=True`) and the requirements workbooks v13.0.7 and v13.0.8 (rows
349–367, 386); the proposal "3D maps and try it on" v1.0; preview v2 (`mannequin-preview-v2/`),
**rebuilt here** from the local Anny clone at `8f35dc2…` (numpy 2.5.3, scipy 1.18.1); Google's own
pages on cloud.google.com and docs.cloud.google.com, read today (sources at the end).
Reviewer: a fresh-context agent for 🛠 Mark XXIII applying `.claude/agents/code-reviewer.md`,
`security-reviewer.md` and `planner.md` to a plan. Read-only apart from this file. "L" numbers are the
plan's lines at `281510d`.

**Verdict: APPROVE WITH CHANGES.** No CRITICAL finding. Three HIGH findings (H1–H3) must be written
into the plan before I0; the MEDIUM ones should be; the LOW ones are the planner's call. H1 adds one
owner question with a safe default, so nothing waits for him. The design holds: the figure is free
and drawn on the device, the paid path is console-only behind his typed YES, an atomic durable cap and
a server-side private-piece refusal, the provider sits behind a port in `jarvis.llm`, and the four
parts own disjoint files.

What this review could not check:
- A real Vertex AI call (no paid call without his YES): the answer shape in his project, latency,
  whether a deprecated model still serves a project that never used it, whether a filtered 200 is
  billed, and the INR SKU price and GST on his invoice.
- Gemini image models' try-on quality ("looks like me", true colours) and their person-generation
  setting's exact name: the pilot's job.
- The figure on his phone's GPU, WebGL2 in CI's Chromium, SSD and UltraFace on a real full-length photo.

## What holds (checked against the code, the build and the web)

| Claim (plan) | Result |
|---|---|
| Sizes: `app.py` 732 (≤ 735), `gateway.py` 760 (= 760), `brain.py` 713, `config.py` 780 (< 800), `console.html` 782 byte-identical, `console-helpers.js` 238, `console-r7-send.js` 145, `console-camera-panel.js` 481, `console-helpers-wardrobe.js` 290, `console-wardrobe.css` 51, `r13_wiring.py` 346, `api/console.py` 453 (fact 1) | Right (`wc -l`; `test_r13_seams.py:221–222`, `:547–552`, `:589–602`; `test_r14_seams.py:477–482`) |
| three.js r187 vendored alone; no addon; the CSP refuses an import map, a CDN and Google Fonts (fact 2) | Right (`api/console.py:196–197`, `:224–229`); preview v2 does load three and its addons from jsDelivr through an inline import map and Orbitron from Google Fonts (`index.html:8`, `:159–162`, `:246–248`) |
| The manifest-checked vision route; `application/octet-stream` allowed; no `StaticFiles` mount that could bypass it (fact 3) | Right (`api/console.py:333–421`); the 2-segment `/static/vendor/{release}/{name}` route can't shadow a 3-segment `/static/vendor/mannequin/{release}/{name}` |
| The wardrobe contract, the wiring, the fail-closed Privacy rows (facts 4, 5) | Right (`wardrobe/ports.py:63–138`, `:260–302`; `api/r13_wiring.py:72–142`; `wardrobe/phone/privacy.py:44–90`) — but see M4 for the seam wording |
| Types, private-by-default, colours, slots, `PRIVATE_SLOTS`, `outfit_plan`'s actions (facts 6, 7) | Right (`wardrobe/model.py:77–108`, `:200`; `styling/rules.json` slots; `styling/look.py:24`; `styling/actions.py:27`); every type in D5's template table exists |
| The pixel and drawing lists, the door the only caller (fact 9) | Right (`test_r13_seams.py:478–535`) |
| Money: `ensure_allowed`, `reserve_free`/`release_free`, `record`, `LABELS`, `reserve_units`/`release_units` with a `Hold` that remembers its month and `released` set before the first await (fact 10) | Right (`billing/service.py:59`, `:222`, `:300–331`, `:333`; `billing/meter.py:203–212`, `:330–372`) |
| ADC tokens, the deploy's region, optional APIs, `try_bind`, `--timeout 300 --memory 512Mi`, `console_only`, `record_change`, the 2.1 MB body cap (facts 11–13) | Right (`voice/adc.py:50`; `deploy/cloudrun.sh:48`, `:87–102`, `:453–470`, `:542–543`; `api/book_gate.py:56`; `api/settings_audit.py:24`; `api/body.py:25`); `--max-instances 1` (`cloudrun.sh:542`) |
| Cookie writes need `X-Requested-With: JARVIS`; the session cookie is `SameSite=Lax` | Right (`api/auth.py:117–127`; `api/app.py:561–565`): new routes under `require_auth` get CSRF for free |
| A sealed 740 KB photo fits a Firestore document | Right: the envelope is base64 (`integrations/vault.py:80–83`): 740 KiB → ≈ 1.01 MB < 1 MiB |
| Preview v2's files, sums and triangles (L211–216) | Right, **rebuilt here twice**: `body.glb` 2,437,524 B `850782a4…`, `outfit.glb` 1,523,852 B `91e81621…`; dressed (tucked) 24,566, base layer only 26,134 |
| Licences in the clone (L219–224) | Right: `src/anny/data/mpfb2/LICENSE.md` is CC0 1.0; `LICENSE` Apache-2.0 "Anny, Copyright (C) 2025 NAVER Corporation"; no NOTICE; README §License: mpfb2 CC0, `smplx` non-commercial (download only); the 46-index waist loop is `src/anny/anthropometry.py:7…`; `helper-tights` is a face group of `3dobjs/base.obj` (CC0) |
| The workbook's 14 titles and acceptance checks (first table) | Right, word for word (one apostrophe, L11) |
| Google: `virtual-try-on-001` GA, released 20 Jan 2026; legacy page "Discontinuation date: January 20, 2027"; current page "Deprecation date: September 14, 2026", "Retirement date: March 15, 2027", "Models may remain accessible through the Gemini API after these dates"; 2 images a prompt; ≤ 7 MB (legacy 10 MB); 1–4 outputs; the 16 regions, none in India, `asia-southeast1` listed; 50 requests a minute (legacy); `:predict` REST sample; $0.06 per image | Right (G1, G2, G4, G5). `productImages[]`: "Required. A single product image to try on the person" (G3b): one garment a call is confirmed |
| Data use: no training without permission; may log prompts for abuse; 24-hour caching names Gemini models | Right (G6, updated 17 Nov 2026) |
| ₹5.71 a step at ₹95.24 | Right ($0.06 × 95.24 = ₹5.714) |

## Coverage of the 14

All 14 rows have a named test whose words are the workbook's acceptance check, and an eval case of
the same name. The fallbacks the plan takes are his own (AVT-02's "configurable basic avatar … when the
user chooses to skip photos", AVT-05's "approximate silhouette"). Two gaps: most eval cases have no
control of their own (M8), and the figure suite's measure-table case fails on preview v2 as it stands
(H3). The three end-to-end tests follow the workbook's "Build and Test" sheet in their avatar halves.

## CRITICAL

None.

## HIGH

**H1. "See it on me" is built on a model Google has already deprecated; a current Gemini image model
on the same Agent Platform is the better primary provider, and the port should not bake in one
garment a call (D10 L426–448; D13 L482–508; D18 L562–567; Risks L782–786).**
- Evidence: the model page says "Deprecation date: September 14, 2026" and the legacy page
  "Discontinuation date: January 20, 2027" (G1, G2): it was deprecated two months before this plan,
  and D18 switches it off on 20 Jan 2027, so the owner gets "about 2 months of use" at most (the plan's own Risks line, L784). Google's
  own try-on how-to lists as **supported models** `virtual-try-on-001`, `gemini-nano-banana-2.1`,
  `gemini-3.1-flash-lite-image`, `gemini-3.1-flash-image` and `gemini-3-pro-image` (G5, updated
  11 Nov 2026); Google's lifecycle table sends every retired Imagen model to a Gemini image model
  ("recommended upgrade `gemini-2.5-flash-image`", G8). `gemini-3.1-flash-image` is GA, "Maximum images
  per prompt: 14", retirement "May 28, 2027 or later", GenerateContent, regions `global`, `us`, `eu`
  (ML processing `us`/`eu`) (G9); `gemini-nano-banana-2.1` is GA (6 Oct 2026), 14 images a prompt,
  `global` only (G10). Whether a deprecated model still serves a project that never called it is not
  said on any page read.
- Price, from Google's pricing page (G4), at ₹95.24 a dollar (the console's fallback rate,
  `config.py:359`), before tax (M1):

  | One picture of him in … | `virtual-try-on-001` (Singapore) | `gemini-3.1-flash-image` (`us`/`eu`: non-global $0.55/M in, $66/M image out; 1,120 tokens an input image, 1,120 for a 1K output) | `gemini-nano-banana-2.1` (`global`: $1.50/M in, $30/M image out; 1,120 + 1,120) |
  |---|---|---|---|
  | the top | $0.06 = ₹5.71 | ≈ $0.0752 = ₹7.17 | ≈ $0.0372 = ₹3.54 |
  | top and trousers | 2 calls, $0.12 = ₹11.43 (the second on the first's picture) | 1 call, ≈ $0.0759 = ₹7.22 | 1 call, ≈ $0.0388 = ₹3.70 |
  | top, trousers and jacket | 3 calls, ₹17.14 | 1 call, ≈ ₹7.28 | 1 call, ≈ ₹3.86 |

  (A ~150-token fixed prompt adds under ₹0.01; text or thinking tokens, if any, are extra and must be
  settled from `usageMetadata`.)
- Why it matters: the release builds consent, a cap, an adapter, recorded fakes, evals and a paid
  trial for about two months of use, then needs "a later small release: a new adapter, a new price, and his new
  YES" (D18). A Gemini adapter speaks GenerateContent, so its successors are a model-id setting (and a
  new YES, D11), not a new adapter. One call for the whole look removes the chain's drift (Risks
  L785–786) and two of three holds. Against it: no Singapore (`us`/`eu` or `global`, which "can be
  served from any region", G6), a general model whose identity fidelity is unproven, implicit caching
  on by default (G6), and per-token billing.
- Change: (1) The port becomes plural: `TryOnAsk(person: bytes, garments: tuple[Garment, ...], …)`
  with `describe()` adding `max_garments` and `location_words`; a one-garment provider chains inside
  its adapter, so D13's steps, holds and words are the adapter's concern, not the wardrobe's.
  (2) Part C builds `llm/tryon_gemini.py` first: `POST https://{loc}-aiplatform.googleapis.com/v1/
  projects/{p}/locations/{loc}/publishers/google/models/{model}:generateContent` (Agent Platform with
  ADC, never `gemini_provider.py`'s Developer-API key, which may train on content, `config.py:765`),
  person + up to 3 garment images and one fixed prompt, `responseModalities: ["IMAGE"]`, a 1K image,
  every text part discarded unread (untrusted), the hold at a worst case and the settle from
  `usageMetadata`; the deploy sets the project's `cacheConfig` `disableCache: true` (a note when
  refused, like Drive). (3) Add owner question 12: "Which Google model makes your picture?" —
  **default `gemini-3.1-flash-image` in the `us` multi-region** (about ₹7.2 a picture with top and
  trousers together; the plan already offers "a US region" in question 4), or `virtual-try-on-001` in
  Singapore until 20 Jan 2027 (then C builds `tryon_vertex.py` as planned), or `gemini-nano-banana-2.1`
  (about ₹3.7, location not fixed). (4) The `seeme` suite runs both fakes through the port; the pilot's
  3 pictures (owner question 11) judge "looks like me". (5) Rewrite summary 6, 7, 10, D11's words, D13,
  D18, the cost table and the risks for the chosen default.

**H2. R13's `outfit_plan` `lock` does NOT refuse a piece that isn't ready, and "Use this look" as
written is a check-then-act over several writes (D7 L399–405; seam 12 L690–692).**
- Evidence: `_lock` with a `piece` (`wardrobe/styling/actions.py:137–146`) checks only that the piece
  exists and has a slot (`_slot_of`, `:38–43`) and that no other plan reserves it
  (`reserve.conflict`, `styling/reserve.py:92–99`); `reserve` (`:117–123`) is the same. Nothing reads
  `Piece.eligible` (`wardrobe/model.py:216–217`). D7 locks "one slot at a time", each a separate
  `gateway.execute`, each its own `s.change` write and, with the outfits row on Ask, its own card
  (`api/wardrobe.py:284–309` parks a card in a conversation).
- Failure: today the AI can already lock a jacket that is In laundry into tomorrow's plan. In R13.1
  the confirm's fresh check passes, the jacket goes to the laundry a second later, and `lock` writes
  it anyway; or slot 3 of 5 is refused after slots 1–2 were locked, leaving a half-confirmed plan; or
  he gets five approval cards for one press.
- Change: (1) Seam 12 is a fix, not a check: `_lock` and `reserve` refuse unless every piece of the
  unit is `eligible` in the view they read ("The navy jacket is in the laundry: it can't be locked
  into this plan."), with tests (a laundry piece through the tool → `PlanRefused`, nothing written;
  R13's STY-12 and STY-14 tests unchanged). (2) `lock` accepts `pieces` (one per slot; the schema
  already has `pieces`, `styling/tools.py:85`) and applies them in ONE `s.change`, all or nothing.
  (3) `POST /v1/tryon/confirm` makes one `outfit_plan` call and reuses `api/wardrobe.py`'s card
  handling (a shared helper, an I0 seam) instead of its own `gateway.execute`; at most one card. Its
  fresh check stays as the plain-words early refusal; the tool's own check is the guarantee.
  (4) AVT-09's test adds: the jacket goes to the laundry between the check and the call → refused,
  plan unchanged.

**H3. The figure's measure-table claim is wrong, its eval fails on preview v2, and the fix competes with
the 3.5 MB budget (L216–218; D3 L311–314; `figure` suite L753).**
- Evidence (rebuilt here, identical to the plan's sums): preview v2 makes ONE morph per slider, "the
  solved shape at the slider's top value, minus the sample shape" (`build_assets.py` `main`), so every
  value below the sample is a linear extrapolation. `measure-table.txt`: **waist 62 → 63.9 cm** (1.9 cm
  off on its own slider; the plan says "every slider value comes back within 0.5 cm"); height 150 gives
  chest 99.3 (+3.3); tall-and-heavy's worst is chest 108 → 106.2 (−1.8), not "3.0 cm". The suite's case
  "each measurement within 0.5 cm on its own slider" therefore fails on day one.
- Size: quantising v2's set as D3 says (int16 positions and morph deltas padded to 8 bytes a vertex,
  int8 normals padded to 4, float32 UVs, uint16 indices) gives ≈ 1.30 MB + 0.81 MB ≈ 2.1 MB; the new
  templates (tee, kurta, shorts, wrap, jacket open and closed, sneaker, sandal, 24-segment sleeves)
  add roughly 0.8–1.3 MB, so ≈ 2.9–3.4 MB against the 3.5 MB cap. Two-sided morphs (12 targets) would
  add ≈ 1.5 MB and break it.
- Change: (1) Correct L216–218 from the table. (2) Pick one and write it: one corrective "waist down"
  morph (≈ +0.26 MB), or the waist range 66–120 (the slider's linear part; then 62–65 is refused in
  words), or an own-slider tolerance of 2.0 cm on the low side with "estimated" shown. (3) Load
  garments per template (one GLB per template, fetched only for the look's templates) so the cap
  becomes "body + base ≤ 1.6 MB first load; `m1/` ≤ 4 MB in all", or keep one file and name what is
  dropped if 3.5 MB is hit (morph normals of accessories first). (4) The eval's control stays "two
  morphs swapped".

## MEDIUM

**M1. GST: the cap's default lets his bill pass ₹300 (owner question 10 L825–826; D15 L534–535; Risks
L789–790; cost table L647).** Google's tax page: customers in India contracted with Google Asia Pacific
pay "18% India GST" without a valid GSTIN, and services sold by Google Cloud India "are subject to 18%
India GST regardless of the GSTIN status" (G11). An owner without a GSTIN pays ₹354 for a ₹300 cap.
Also, "If you pay in a currency other than USD, the prices listed in your currency on Cloud Platform
SKUs apply" (G4): his bill uses Google's INR price, not USD × the day's rate. Change: question 10's
default becomes **count 18% in the cap and in every ₹ shown** (₹6.74 a VTO step, 44 a month; or the
H1 default ₹8.52, 35 a month); a setting `tryon_tax_pct` 18 (0–28); the words say "about, with GST";
the pilot compares one picture with his bill.

**M2. The backups line is wrong: R14 keeps backups 7 days, not "at most 14 weeks" (summary 9 L52–53;
D16 L550–552).** R14 D3: "Firestore's daily schedule, kept 7 days" and "a deleted item leaves … the
backups within 7 days" (`docs/plans/r14-hardening.md:208–218`); the setup script creates
`--retention=7d` (`deploy/backup_setup.sh:138`) and checks `604800s` (`:61`). 14 weeks is Firestore's
maximum (`r14-hardening.md:174`). The Privacy "Backups" row and persona p14.0 already say 7 days.
Change: "Copies inside JARVIS's own backups stay locked and are gone within 7 days", read from R14's
Backups row (not a second literal), and the summary likewise.

**M3. The consent hash includes the day's ₹, so he is asked for YES again whenever the rate moves
(D11 L451–457).** The card shows "the price a step in ₹ and the cap" and the record keeps "a SHA-256
of the shown text"; "new words asks again". ₹5.71 → ₹5.76 is new words. Change: hash a fixed template
with named fields (provider, model, location words, what is sent, data-use words, the USD list price,
the template's version), never the rendered ₹ or the cap; the ₹ and the cap are shown on every
estimate instead (D13.3). Test: the rate moves 95.24 → 96.10, consent stays current; the model or the
location changes, it doesn't.

**M4. Try-on's Privacy rows must ride `WardrobePart.privacy`, never `data` (seam 6 L665–668; D16
L536–545; fact 5).** `_with_kept` today puts stand-ins into `data` (`api/r13_wiring.py:137–142`), and
`data` feeds R13's Wardrobe rows, which fail closed on any source whose `row` isn't pieces, history,
plans or photos (`wardrobe/phone/privacy.py:44–46`, `:84–88`). Seam 6's "`_with_kept` gives the two
parts their stand-in Privacy sources" reads as that path. Change: `_with_kept` branches by part: R13's
four as today; `tryon` and `seeme` get I0's `wardrobe/tryon/kept.py` **PrivacySource** rows (section
"Try-on") in `privacy`, and their `data` stays empty; `check_part` refuses a `tryon`/`seeme` part with
`data`. Test: with both R13.1 parts failed, R13's five Wardrobe rows still read, and the Try-on rows say
"Couldn't check right now" and delete by path.

**M5. The request's enum spellings disagree with Google's reference (D10 L436–437; G-table L242).** The
current `VirtualTryOnModelParams` lists `allow-adult`, `dont-allow`, `allow-all` and
`block-medium-and-above` etc. with hyphens, while its default text says `block_medium_and_above` (G3a);
the plan sends `"allow_adult"` and `"block_medium_and_above"`. A spelling the API rejects is a 400 on
every call: the feature is dead on arrival and only the paid pilot would show it. Change: send neither
(both defaults are what D10 wants: `allow-adult`, `block_medium_and_above`), nor `addWatermark`
(default `true`); a recorded 400 in `r131_fake_vertex.py`; the live picture checks the answer. The same
rule for the Gemini adapter: send only what Google's sample sends.

**M6. The server can spend outside the ₹ cap (seam 13 L693–695; D15).** `roles/aiplatform.user` on
`jarvis-run` lets the service call any Agent Platform model in the project (Veo video at roughly
₹50–70 a second, the proposal's own figure), and enabling `aiplatform.googleapis.com` is new: JARVIS
uses no Vertex model today (`llm/` speaks the Developer API). The cap lives only in JARVIS. Google's
access page names `aiplatform.endpoints.predict` for "Make prompt requests" and allows custom roles
(G7). Change: the deploy creates a custom role `jarvisTryOn` with only `aiplatform.endpoints.predict`
(falls back to `roles/aiplatform.user` with a note), and the runbook adds a Cloud Billing budget alert
on Vertex AI at the cap (his step, his billing account; no JARVIS code). `security-reviewer` checks it.

**M7. The door can't meet the server's 700 KB limit (D12 L472–476).** The door redraws through R11.1's
`shrink`, which stops at the first JPEG quality that fits `picture_max_kb`, the attach limit **900 KB**
(`console-r111-files.js:24`, `:193–208`; `config.py:497–502`), at 1,568 px. A full-length photo at
quality 0.85 often lands between 700 and 900 KB and the server refuses it. Change: `door.person`
re-encodes the redrawn bitmap down `JPEG_TRIES` until ≤ `tryon_photo_max_kb` (sent in `GET /v1/seeme`),
else says "This photo is too detailed to send: try a plainer background"; the pin's budget (≤ 165)
stays. Test: a 1,568 px fixture whose first encode is 820 KB arrives ≤ 700 KB.

**M8. Most eval cases have no control that must make them fail (Tests L746–757).** The suites have
controls for AVT-07, AVT-09, AVT-14, AVT-15, the cap, the consent and the measure table; AVT-02, -03,
-04, -05, -06, -08, -10, -11, -12 and OPS-05 have none. Change: one control each, run by the I1 sweep:

| Case | Control (must turn it red) |
|---|---|
| AVT-02 | Side returns Front's yaw |
| AVT-03 | a new version rewrites a saved comparison's piece ids |
| AVT-04 | the look drops the `back` view of the kurta |
| AVT-05 | the template choice is kept in page memory, not `tryon/{uid}.assets` |
| AVT-06 | the slot thumbnail stays W1's after the swap |
| AVT-08 | Back resets the tuck state |
| AVT-10 | the closed variant is the open variant |
| AVT-11 | the second figure's readiness words are dropped |
| AVT-12 | the piece list is taken from the plan, not from what was sent |
| OPS-05 | erase also deletes the wardrobe's photos (the catalog's `rev` changes) |

**M9. The share caption breaks the pixel rule the plan pins (D9 L419–424; seam 10 L680–684).** D "adds
a caption image beneath" B's PNG, which needs `drawImage` and `toBlob` in a D module; `DRAWING` gains
only B's two files, and `test_only_the_two_named_panels_take_pixels` (`test_r13_seams.py:494–503`)
fails any other module using those APIs. Change: `Stage.snapshot({caption: string[]})` in B draws the
fixed-word lines under the figure on its own canvas; D only passes the words. The static test stays
as it is.

**M10. OPS-05's passkey is unspecified (D16 L546–548; HTTP L611).** "The passkey, like a Privacy
passkey delete" names no purpose or target. `Purpose` is a pinned Literal and `privacy_delete` is
bound to "(category id, rev)" (`permissions/models.py:64–91`; `privacy/service.py:14`). Change:
OPS-05 is a Privacy delete of the category `tryon_all` through the existing service (its passkey
ceremony, its IRREVERSIBLE audit line, its words), and `POST /v1/tryon/erase` is what that category's
delete calls; no new passkey code in A. Test: no assertion → nothing deleted; a replayed assertion →
refused.

## LOW

**L1. Pins I0 will trip over (facts 1, 14; seams 1, 2).** `__version__` is pinned five times
(`test_about.py:25`, `test_r7_seams.py:111`, `test_r11_1_seams.py:74`, `test_r13_seams.py:72`,
`test_r14_seams.py:99`) plus `v13.0.0` in `test_r13_wiring.py:306` and `tests/r13_fake_server.py:126`
(the plan says four). The keyring's positional pins move too: `test_r14_seams.py:260`
(`PURPOSES[-3] == "backup_probe"`) and `test_r7_seams.py:294` (`PURPOSES[-6:-3]`). `R13_JOB_NAMES` is
pinned at `test_r13_seams.py:237`.

**L2. `_VisionFiles(folder)` must read the folder at call time (D3 L315–316; seam 9 L678).** Five R7
tests monkeypatch `console._VISION` (`test_r7_seams.py:696`, `test_r7_b_assets.py:144`, `:223`,
`test_r7_i1_fixes.py:306`, `test_r7_i1_vision_cache.py:33`): a folder captured at construction breaks
"R7's tests unchanged". Keep `vision_files = _VisionFiles(lambda: _VISION)`.

**L3. Paths and layers (seam 14 L696–698).** The layer map is `buildbook/gen/layers.py`, keyed by
top-level package (`"wardrobe": "L5"`, `:55`); `wardrobe/tryon`, `wardrobe/seeme` and `llm/tryon*`
are already covered, so drop the two new rows or say how subpackages map.

**L4. Google facts to tidy (Google table; D12 L469; Risks L789–793; sources G3).** (a) Billing: "You're
charged only for requests that return a 200 response code. Requests returning any other response
codes, such as 4xx and 5xx codes, aren't charged" (G4): release the hold on 5xx; keep it only for a
timeout after sending, a cut 200 and a filtered 200. (b) `allow-adult` is documented as "Allow
generation of adults only"; no page says what it does with a child's photo: soften D12 and the risks.
(c) The model page lists "GenerateContent API: Supported" and `candidateCount`, while the how-to's
sample is `:predict`: keep the sample, as the plan says. (d) The AVT-12 row says "SynthID / Content
Credentials" while the fact row says SynthID is not named: say "Content Credentials (C2PA)".
(e) Replace G3's appspot mirror with the docs.cloud.google.com reference pages (G3a, G3b).

**L5. Google's output and its Content Credentials (D10 L438–439).** `sanitise_jpeg` drops every APPn
segment (`photos/imaging.py:67–101`), which removes C2PA (APP11) and the ICC profile. Say which: keep
the bytes as returned (structure checked, never decoded, served with their detected type, `nosniff`),
or sanitise and stop promising the watermark note.

**L6. Error shape (HTTP L600–618).** `JarvisConsole.api` sets `err.code` from `{"error": code}`
(`console.js:80–89`); R13's `err()` sends only `{"detail": …}`. The seeme routes answer
`{"error": "price_changed", "detail": "…"}` so D can branch.

**L7. The section's life (D1 L267–270).** `draw()` rebuilds every section on each `load()` and
Helpers' `refresh()` (`console-helpers-wardrobe.js:82–90`, `:286–287`): mount Try it on once in
`mount()`, never in `draw()`; pass fresh readiness by event; `dispose()` on tab hide and `pagehide`;
one WebGL context; "Turn around" stays still under Motion Off.

**L8. CSP traps for B.** `fetch(dataURL)` is refused by `connect-src 'self'`: decode the door's crops
with an `Image` (`img-src 'self' data:`); `blob:` is not in `img-src`, so preview the snapshot from a
canvas or a data: URL. `Fullscreen` on the stage is not offered by iPhone Safari: hide the button
where `requestFullscreen` is missing.

**L9. The press's own state (D13 L496, L505).** Make `busy` part of `TryonCap.reserve`'s transaction
(refuse while a fresh hold exists) rather than an in-process flag: a revision rollout runs two
instances. Keep `done {request_id: outcome}` (≤ 50, pruned with the month) in `tryon_spend` for the
repeat answer. A tighter limit on `POST /v1/seeme/pictures` (6 a minute) than R13's 30.

**L10. Owner-facing consistency.** Summary 11 says the existing screens don't change while D1 adds two
buttons to every plan row, and the `console` suite compares "the existing tabs' screenshots" with
R13's: compare with Try-on off. Question 11's default (3 paid pictures) disagrees with exit check 7
(one, only after YES): align on one. `outfit_suggest`'s `see_it` (D17) fixes "about ₹5.7" in a tool
result: say "the price is shown before each picture". The `tryon_device` row promises "undo steps and
checklist ticks" on the device while D7 keeps undo in page memory: "Nothing is kept on this device".
"Wearing it" after an unconfirmed swap logs the plan's old pieces: run the confirm first.

**L11. Small wording and inputs.** AVT-03's title in the workbook uses ’ (U+2019): copy it if an eval
compares titles. `capture="user"` opens the front camera: drop `capture` for a full-length photo.
`GET /v1/seeme/photo` and `GET …/pictures/{id}` are not marked console-only though D12 says "shown back
only to his console": mark them, and add `Cross-Origin-Resource-Policy: same-origin`. The requirements
workbook v13.0.8 row 363 still says "Subscription" (paperwork).

**L12. Contracts I0 should pin.** How C gets the provider (`WardrobeContext.tryon: Callable[[],
TryOnProvider | None]`) and where the project id comes from (`firestore_project`, else ADC's);
`Stage.show(figures)`'s field list in `engine_contract.mjs`; the Apache-2.0 header and NOTICE line on
`scripts/mannequin/measure.py` (the indices live in the script, not in the GLB).

## Builder split and scope

- Ownership is disjoint: I0 writes every stub that a part later replaces (the R13 pattern: `part.py`,
  `api/tryon.py`, `api/seeme.py`, the JS stubs, the eval stubs); A, B, C and D own their packages,
  routes, modules and suites; no part edits a wiring or shared file. The gaps are H2 (the R13 `lock`
  fix and the shared card helper are I0 seams), M4 (`_with_kept`), M9 (`snapshot(caption)` in the
  engine contract) and L12 (the provider in the context).
- B on Fable 5.2 alone, every other agent on Opus, matches the owner's rule. B's first steps (port the
  script with tests, the private-zone removal, quantisation, then templates) are right; add H3's
  waist decision before quantisation.
- Scope matches the owner's decisions of 17 Nov: AVT-01 declined, AVT-13 and row 386 later, the free
  figure on preview v2, "See it on me" in with a ₹300 cap, his typed YES, ₹ first, private pieces never
  sent, a swappable provider. H1 keeps "Google's try-on" (Google lists the Gemini models as try-on
  models) and changes only which model by default, as an owner question.
- Cost stays ₹0 a month fixed; the paid path is bounded by the cap once M1 counts GST and M6 bounds
  the role.

## Owner questions (each has a safe default; none blocks the build)

Questions 1–9 have safe defaults. Question 10's default is not safe for his money (M1): flip it.
Question 11's default should match exit check 7 (L10). Add question 12 (H1): the model, default
`gemini-3.1-flash-image` in `us`. If he answers `virtual-try-on-001`, Part C builds the plan's adapter
as written; the port and the suites are the same either way.

## Verdict

**APPROVE WITH CHANGES.** Fold H1–H3 into the plan before I0 (H1 with owner question 12 and its
default; nothing waits for him); fold in M1–M10; the LOW items are the planner's call. The plan's code
facts are right where it counts (every size guard, pin location, file:line, the build's sums and
triangles, the licences and Google's dates, regions and price re-checked); what needs changing is the
provider choice (H1), one R13 gap the plan suspected and the review confirms (H2), the figure's
measured claim and its budget (H3), and the edges of money and privacy (M1–M7, M10).

## Sources (read 17 Nov 2026)

| # | Source |
|---|---|
| G1 | Virtual Try-On 001, legacy Vertex AI page (updated 10 Nov 2026) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/imagen/virtual-try-on-001 |
| G2 | Virtual Try-On, Gemini Enterprise Agent Platform (updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/vto/virtual-try-on-001 |
| G3a | `VirtualTryOnModelParams` — https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/VirtualTryOnModelParams |
| G3b | `VirtualTryOnModelInstance` — https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/VirtualTryOnModelInstance |
| G4 | Generative AI pricing (Imagen "Virtual Try-On … $0.06"; Gemini image models; "charged only for requests that return a 200"; currency) — https://cloud.google.com/vertex-ai/generative-ai/pricing |
| G5 | Generate Virtual Try-On images (supported models; `:predict` sample; updated 11 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/generate-virtual-try-on-images |
| G6 | Data governance (training, abuse logging, caching, global endpoint; updated 17 Nov 2026) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance |
| G7 | Access control (`roles/aiplatform.user`, `aiplatform.endpoints.predict`, custom roles) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/access-control |
| G8 | Model versions and lifecycle (retired Imagen models → `gemini-2.5-flash-image`; updated 17 Nov 2026) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions |
| G9 | Gemini 3.1 Flash Image (updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-image |
| G10 | Gemini Nano Banana 2.1 (updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/nano-banana-2-1 |
| G11 | Cloud Billing, taxes in your country (India GST) — https://docs.cloud.google.com/billing/docs/resources/vat-overview |
| S1 | The owner's wardrobe workbook and requirements workbooks v13.0.7 and v13.0.8; the proposal v1.0; preview v2 and its rebuild; the Anny clone at `8f35dc2df1c4062fd2fae86734f9705de50c0c2b` — not in the repository |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 14:00 IST | R13.1 | First edition: fresh-context review of `r13-1-try-on.md` v13.1.1 on `281510d` (code `3f265cb`). What holds (sizes, pins, file:lines, CSRF and cookie rules, the Firestore fit, preview v2 rebuilt with identical sums, the licences, the workbook's 14 rows, Google's dates, regions, price and data use re-read); no CRITICAL; HIGH H1–H3 (a deprecated model as the primary provider and the Gemini alternative priced in ₹, R13's `lock` takes a piece that isn't ready, the measure table and the size budget); MEDIUM M1–M10; LOW L1–L12; owner question 12 proposed; verdict APPROVE WITH CHANGES | 🛠 Mark XXIII (plan review 1) |
