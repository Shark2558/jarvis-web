Version v13.1.3 · 17 Nov 2026, 16:45 IST · Release R13.1 · Status: Ready · Owner: 🛠 Mark XXIII

# Release R13.1 — Try-on: the 3D figure and "See it on me" (`v13.1.0`)

**Phase:** 3 (profile and personalisation) on R13's wardrobe skill, with one Phase 2 paid tool path and
Phase 7 evals. **Type:** free by default: ₹0 a month fixed, no new Scheduler job, no new secret; ONE paid
path ("See it on me", a Google image model on Google Cloud's Agent Platform) that is off until the
owner's typed YES, shows its ₹ before every picture and stops at a ₹300 monthly cap, GST included. **Scope (the owner's decisions of 17 Nov 2026, ≈ 12:50
IST):** 14 rows of his workbook (353–363, 365, 366 and 350: AVT-02 … AVT-12, AVT-14, AVT-15, OPS-05); the
free figure starts from the Fable 5.2 preview v2 ("Build on v2"); the 3D work is ONE part built by ONE
builder on Fable 5.2 (his rule of 15 Nov), every other agent on Opus. **Not in scope:** AVT-01 (declined),
AVT-13 and the extras (later), row 386 (a 3D model made from his own photo, cloud, ≈ ₹21 a look: later),
R13.2 maps. **Branches:** plan `r13-1-plan` (from `main` @ `3f265cb`, R13 live as `v13.0.0`) → I0
`r13-1-i0` → parts `r13-1-a` … `r13-1-d` → integration `r13-1-i1` → PR `v13.1.0 · R13.1 Try-on · Mark
XXIII`. Every commit carries `JARVIS-Version: v13.1.0` and `JARVIS-Mark: XXIII`. Read on `3f265cb`; every
file:line below is from that commit. The owner's wardrobe workbook (sheets "Use Cases", "Wardrobe Rules",
"Build and Test") was read on 17 Nov 2026, 13:05 IST: each row's title and acceptance check below are HIS
words. v13.1.2 writes in plan review 1 (`docs/plans/r13-1-integration/PLAN-REVIEW-1.md`: H1–H3, M1–M10,
L1–L12, with the Workshop's decisions on H1–H3, M1 and M2; the table "Plan review 1 — how each finding
was handled" near the end) and is Ready for I0. It also ships one R13 fix (D20). v13.1.3 records the
owner's two answers of 17 Nov 2026 (≈ 14:25 IST): the model is **Gemini 3.1 Flash Image, processed in the
United States** (question 12, the default, confirmed), and a "See it on me" picture is kept **30 days**
unless he presses Keep (question 3; the default was 7 days); every other question keeps its safe default.

## Summary for the owner (plain words)

1. **A 3D figure of your size, free.** In Helpers → Wardrobe a new section, **Try it on**, shows a
   plain grey figure shaped from six measurements you type (height, shoulders, chest, waist, hips,
   inseam). No photo is needed for it. It is drawn on your phone or laptop; nothing about it leaves them
   except your measurements, which JARVIS keeps locked with its own key.
2. **Dressed in your own clothes.** Each piece in the suggested outfit is drawn on a ready-made shape
   (shirt, T-shirt, kurta, trousers, shorts, blazer or jacket, shoes, belt, watch, socks) in that piece's
   colour and a patch of its own photo. Every shape is marked **Approximate**, and the piece's real photo
   stays beside the figure.
3. **What you can do with it:** turn it (front, side, back), zoom, tuck the shirt in or out, open or
   close the jacket, show all layers or only the base layer, swap a piece and undo, and compare two looks
   side by side. A swap with a piece that isn't ready (in the laundry, say) is shown as a **draft** and
   can't be confirmed for the event.
4. **Private stays covered.** Underwear and vests are never drawn as themselves: the figure always wears
   a plain base layer. "Save a picture of this look" makes a picture on your device with only the details
   you approve, never a private piece.
5. **If 3D can't run** (an old browser, a weak phone, a file that didn't load), you get the plain outfit
   checklist with each piece's photo, and you can still change a piece or confirm the outfit.
6. **"See it on me" (optional, paid).** One full-length photo of you, kept locked by JARVIS. When you press
   **See it on me**, JARVIS sends that photo and the photos of the outfit's top, trousers and jacket to
   Google's image model (Gemini 3.1 Flash Image, in Google Cloud, made in the United States) and shows
   ONE picture of you wearing them, marked **"Generated 2D style preview"**, with the exact pieces listed
   beside it. The first time, you type **YES** after reading what is sent and to whom; you are asked again
   only if the model or the country changes.
7. **The money.** About **₹9 a picture with GST** (₹8.5 to ₹9; Google bills the exact amount), for the
   whole outfit at once. The ₹ is shown before every picture and nothing is sent until you confirm.
   JARVIS stops at **₹300 a month, GST included** (about 33 pictures); you can lower it any time, and
   raising it asks you first.
8. **Never sent to Google:** underwear, vests, thermals or anything you marked private; your measurements;
   anyone else's photo. JARVIS checks on your phone that your photo shows one person, but it can't tell an
   adult from a child, so use only your own photo.
9. **What is kept:** your measurements and your photo until you delete them; each try-on picture 30 days
   unless you press **Keep** (your answer of 17 Nov). **Delete all my try-on data** (with your passkey) removes the figure, your
   measurements, your photo, your YES and the pictures; your wardrobe stays as it is. JARVIS's own daily
   backups keep a locked copy for up to 7 days, and the button says so.
10. **Cost otherwise: ₹0 a month.** The figure's files (about 3–3.5 MB) download once to each device.
    Google supports this image model until at least 28 May 2027; a newer model needs your YES again.
11. **The same look.** One new section in Helpers → Wardrobe and two buttons on each outfit there; no new
    dock button; every other screen stays exactly as it is.

## What is built: the 14 rows (his workbook's words), and where each goes

Release group "Try-on" of his workbook has 15 rows; AVT-01 stays declined and its photo-based figure is
row 386 (later). The table gives each row's **use case** and **acceptance check** exactly as in his
workbook, the part that builds it, and the named test that proves it (the eval case of the same name
runs it through the wired app at I1).

| Row · ID | His use case | His acceptance check | Part | The test (what must hold) |
|---|---|---|---|---|
| 353 · AVT-02 | Create a rotatable personal avatar | The owner can rotate the model and inspect a distinct front, side and back view. | B (figure), D (controls), A (store) | `test_avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views`: with only typed measurements (his fallback "a configurable basic avatar … when the user chooses to skip photos"), the Front, Side and Back buttons give three different camera yaws (0°, 90°, 180° ± 1°), drag turns it, the figure is labelled "Estimated from your measurements" (his "Mark estimated geometry") |
| 354 · AVT-03 | Adjust the avatar’s measurements and shape | Correcting height updates the avatar and its previews while retaining saved outfit selections. | A (versions), B (shape), D (form) | `test_avt03_correcting_height_reshapes_the_figure_and_keeps_every_saved_selection`: 172 → 178 cm changes the figure's height to 178 ± 0.5 cm and every open look and saved comparison redraws; their piece ids per slot are byte-identical before and after; the old version stays in use until "Use these measurements" (his "Keep the current version available until the replacement is approved"); an untyped measurement is shown "estimated" |
| 355 · AVT-04 | Capture visuals for a garment’s preview | A kurta has recognisable front and back references and remains linked to its original inventory record. | A (views), D (cards) | `test_avt04_a_kurta_shows_its_front_and_back_references_under_its_own_id`: a kurta with R13's `front` and `back` crops lists both as reference cards in its look slot, under the same `wi_` id as in the catalog; a kurta with only a front asks for the back view only (a link to Camera → Wardrobe), and stays selectable |
| 356 · AVT-05 | Assign a 3D asset to a wardrobe item | A patterned shirt can use an approximate silhouette while its actual reference image stays visible. | A (association), B (template, texture), D (card) | `test_avt05_a_patterned_shirt_draws_on_an_approximate_shape_beside_its_real_photo`: a checked shirt gets template `shirt` (saved against its id), its texture from its own crop, the label "Approximate", and its front photo card visible beside the figure; a type with no template shows an image card only |
| 357 · AVT-06 | Preview shoes, belts and watches | Swapping a watch changes the correct wrist accessory or its linked thumbnail. | B (models), A (options), D (swap) | `test_avt06_swapping_the_watch_changes_the_left_wrist_and_its_thumbnail`: swapping watch W1 for W2 changes the strap colour on the left wrist and the slot's thumbnail to W2's photo; shoes and belt likewise in their own places |
| 358 · AVT-07 | Dress the avatar layer by layer | A blazer covers the shirt sleeves and torso where appropriate without hiding the shirt collar or watch by mistake. | B | `test_avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch` (geometric, Node): with shirt + blazer + watch, the blazer shell contains the shirt's torso and sleeve vertices from shoulder to 1 cm above the cuff; every shirt-collar vertex and every watch-case vertex lies outside the blazer shell |
| 359 · AVT-08 | Rotate and inspect an outfit | Changing the viewpoint from front to back preserves outfit and avatar identity. | B, D | `test_avt08_front_to_back_keeps_the_same_pieces_layers_and_figure`: after Front → Back the engine reports the same slot → piece ids, the same tuck/open/layers state and the same measurement weights; a photo-only piece stays as a labelled card beside the 3D view |
| 360 · AVT-09 | Swap, remove or undo a piece on the avatar | Swapping a ready jacket changes the avatar and checklist together. A jacket in laundry cannot be confirmed for the event. | A (fresh check), D (swap, undo), B (redraw) | `test_avt09_a_ready_jacket_swaps_figure_and_checklist_together_and_one_in_laundry_stays_a_draft`: the swap changes the drawn outer layer and the checklist row in one step; a jacket In laundry is offered as "Draft: in the laundry", "Use this look" is refused by the server's fresh check (no `outfit_plan` call is made); a jacket that goes to the laundry between that check and the call is refused by `outfit_plan` itself (D20), the plan unchanged; one press makes at most one card; undo returns to the last still-eligible pick |
| 361 · AVT-10 | Try different styling options | Toggling jacket open to closed updates shirt visibility and leaves the same jacket selected. | B (variants), D (toggles) | `test_avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket`: open → closed hides the shirt placket region, keeps the jacket's piece id; tucked ↔ untucked likewise for a shirt (belt shown only when tucked); a kurta offers no tuck (said in words) |
| 362 · AVT-11 | Compare two looks side by side | A formal and festive look can be compared without losing either item list or its availability state. | B (two figures), D, A (saved, re-check) | `test_avt11_a_formal_and_a_festive_look_compare_with_both_lists_and_their_readiness`: two figures, one figure and light set, each with its own item list and each piece's readiness word; a saved comparison whose piece changed state opens marked "Draft" |
| 363 · AVT-12 | Generate a quick photo-style preview | A still preview is labelled as 2D and the checklist still identifies the exact clothes used in the plan. | C (provider, consent, cap), D (card) | `test_avt12_the_picture_is_labelled_a_generated_2d_preview_and_lists_the_exact_pieces`: a made picture shows "Generated 2D style preview — not a photo" and the list of the exact piece ids sent (top, bottom, jacket: the ones in the request) with their words; pieces not sent are listed as not in the picture; the 3D view stays |
| 365 · AVT-14 | Keep underwear and vests private in previews | Sharing a look displays the dressed avatar and only the approved item details. | B (covering), A (views), D (share) | `test_avt14_a_shared_look_shows_the_dressed_figure_and_only_approved_details`: "Save a picture of this look" makes a PNG of the dressed figure plus a caption with only fixed words of non-private pieces; a private piece's label, colour and id appear nowhere in it; in every layer state the private zone is covered |
| 366 · AVT-15 | Keep outfit planning usable when rendering fails | If a render fails, the user can still confirm a ready outfit or change a piece from its checklist. | D (checklist), B (failure signals) | `test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm`: with no WebGL (the `__glFail` hook), a lost context, an asset that fails its sum, or a 10 s render timeout, the checklist shows each piece with its image card and readiness; "Change" swaps a piece and "Wearing it" confirms the ready outfit through R13's tools |
| 350 · OPS-05 | Manage and delete avatar photos and models | Deleting an avatar removes it from the viewer and disables dependent previews while retaining the item catalog. | A (erase), C (its data), D (button) | `test_ops05_deleting_the_figure_empties_the_viewer_disables_previews_and_keeps_the_catalog`: after the Privacy delete of `tryon_all` ("Delete all my try-on data", his passkey) the viewer says "No figure yet", saved comparisons and pictures are gone, "See it on me" asks for a photo again, and `GET /v1/wardrobe` returns the same pieces and `rev` as before |

**Where his workbook goes further than what he approved, and what this plan does.**

| His words | What he approved (17 Nov) | This plan |
|---|---|---|
| AVT-01/AVT-02: "a personal 3D body model" from front, side and back photos | AVT-01 declined; a 3D model from his photo (row 386) later | AVT-02 is built in **his own fallback form**: "a configurable basic avatar … when the user chooses to skip photos", labelled as estimated geometry. No photo is used for the figure |
| AVT-03: "version the avatar … re-render affected saved looks on request" | the mannequin from his measurements | Measurements are versioned (current, a draft, 5 earlier); looks redraw on the device at once (free). A paid picture is never re-made by itself: only by a new press and its ₹ |
| AVT-04: capture front, back and details on a hanger or flat surface | R13 already keeps up to 3 views a piece | No new camera code: the look lists which views exist and links to Camera → Wardrobe for a missing **useful** one only (back for tops, outerwear and traditional) |
| AVT-05: "an approved 3D garment shape or a fitted template" | templates from preview v2 | Templates only (one approximate shape per garment kind); every one labelled **Approximate**, with the image card; a real per-garment 3D asset is AVT-13 (later) |
| AVT-06/AVT-08: "mark estimates of dimensions or appearance" | — | The template's scale, the texture's scale and an untextured colour are each marked "approximate" |
| AVT-09: "allow an unavailable piece in a clearly labelled visual draft … require a fresh availability check before confirming" | — | Built exactly so: options carry the server's fresh readiness; a draft can't be confirmed; "Use this look" re-checks on the server before R13's `outfit_plan` is called |
| AVT-10: "jacket open or closed" | tucked or untucked | A blazer/jacket template with an open and a closed variant (Part B) |
| AVT-12: "Mark it as a generated style preview" | "See it on me" with Google's model | Labelled "Generated 2D style preview — not a photo; the fit is not exact"; Google embeds Content Credentials (C2PA); the exact pieces are listed beside it |
| AVT-14: "Sharing a look" | private layers always covered | "Save a picture of this look": a PNG made on his device, with only approved details; JARVIS itself sends it nowhere |
| OPS-05: "default to local processing where supported and require specific consent for external processing … honour backup retention" | delete all try-on data | The figure is drawn on his device; storage is sealed on his own JARVIS server; the one outside step needs his typed YES, bound to that provider, model and location (never to the day's ₹); R14's daily backups keep sealed copies for up to 7 days, and the delete says so |

## How it fits the architecture

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| The figure from typed measurements, versioned | L1 web, L8 rich output, L7 sealed · Task & Productivity (wardrobe) | 3 | Build now |
| Garment templates, textures from his crops, layers, styling, swaps, compare | L8 rich output, L5 skill · Task & Productivity | 3 | Build now |
| The checklist fallback, "Save a picture of this look" | L8 · Task & Productivity | 3 | Build now |
| "See it on me": provider port and adapter | L4 (a vendor model behind `jarvis.llm`), L6 tools · Creative | 2/3 | Build now; off until his YES |
| Consent, the ₹ cap, the sealed photo and pictures, Privacy rows, OPS-05 | L7 data, cross-cutting security and cost · Security Advisor | 3/7 | Build now |
| A figure made from his photo (AVT-01, row 386) | L2 vision, cloud | 3 | Later (owner) |
| Fabric behaviour (AVT-13) | L8 | — | Later |

No change to the reference architecture: Try-on is part of R13's wardrobe skill (Layer 5) and draws on
Layer 8 with three.js, which JARVIS already ships. One rule is widened in the open, as R13 did: a third
console panel may see pixels (his own photo's check), and two drawing modules may draw his saved crops on
their own canvases (D12, D5). The paid model sits behind a port in `jarvis.llm` (the model-agnostic
rule); the wardrobe never names a model.

## What the code says today (`main` @ `3f265cb`)

1. **Version and limits.** `__version__ = "13.0.0"` (`src/jarvis/__init__.py:3`; pinned
   `tests/test_about.py:25`, `test_r7_seams.py:111`, `test_r11_1_seams.py:74`, `test_r13_seams.py:72`,
   `test_r14_seams.py:99`; `v13.0.0` also in `test_r13_wiring.py:306` and `tests/r13_fake_server.py:126`). `api/app.py` **732** lines (guard ≤ 735:
   `test_r13_seams.py:590`, `test_r14_seams.py:477`): 3 left. `tools/gateway.py` **760** (pinned `== 760`,
   `test_r13_seams.py:591`). `core/brain.py` 713 (≤ 741). `console.html` 782, **byte-identical** to
   `9a8392b` (`test_r13_seams.py:546–552`). `config.py` **780** (< 800: `test_r13_seams.py:222`,
   `test_r14_seams.py:480`): 19 left. `console-helpers.js` 238 (pinned ≤ 238, `test_r13_seams.py:597`):
   full. `console-r7-send.js` 145 (≤ 145, `:596`): full. `console-camera-panel.js` 481 (≤ 483). Every
   `console*.js` ≤ 800; every module under `wardrobe/` ≤ 400 (`:600–601`); `api/r13_wiring.py` ≤ 400
   (`:602`; 346 now).
2. **three.js in the console.** Only `three.module.min.js` r187 is vendored (`api/console.py:196–197`:
   `THREE_RELEASE = "three-0.187.0"`, `VENDOR_FILES`); `console-3d.js:218` and `console-book-3d.js:17`
   import it from `/static/vendor/three-0.187.0/three.module.min.js`. **No addon** (OrbitControls,
   GLTFLoader, RoomEnvironment) is vendored. The console CSP (`api/console.py:224–229`) is `script-src
   'self' 'wasm-unsafe-eval'`, `connect-src 'self'`, `img-src 'self' data:`, `font-src 'self'`: an inline
   import map, a CDN script and Google Fonts are all refused. The console self-hosts Orbitron, Rajdhani and
   Share Tech Mono (`static/fonts/`, `console.css:11–16`). `console-3d.js:1–18` already has the patterns
   R13.1 reuses: a WebGL2 probe, one AbortController for teardown, a frame-rate governor that steps down
   and retires 3D, `jarvis:theme` for day/night.
3. **A manifest-checked asset route exists.** `GET /static/vendor/vision/{release}/{name}`
   (`api/console.py:358–420`): a file is served only when the release's `MANIFEST.json` lists it with a
   matching SHA-256 and a media type from `VISION_TYPES` (incl. `application/octet-stream`), with a year's
   immutable cache. The vendor folder is 50 MB today.
4. **The wardrobe's contract** (`wardrobe/ports.py`): `PartName` = catalog, laundry, styling, phone
   (`:63–64`); `TOOL_FAMILIES` (`:90`), `ROUTE_PREFIX` (`:109`), `COLLECTIONS` (`:119`), `SERVICE_OWNER`
   (`:133`), `PhotoVault` with only `count` and `delete_all` (`:260`), `PrivacyRow` (`:269`),
   `WardrobePart` (`:288`). `api/r13_wiring.py`: `PART_MODULES` (`:72`), `build_parts` leaves out a part
   that breaks the contract (`:122`), `_with_kept` gives a failed part stand-in data (`:137`;
   `wardrobe/kept.py:109` `stand_ins` knows only catalog and styling), `install_r13_routes` (`:317`).
   Pinned: `ports.PARTS == (…)` and `set(ROUTE_PREFIX) == set(COLLECTIONS) == set(PARTS)`
   (`test_r13_seams.py:230–236`), the status route's part list (`test_r13_wiring.py:307`).
5. **The Wardrobe Privacy section fails closed** (`wardrobe/phone/privacy.py:45–46`, `:84–88`): a
   `WardrobeData` whose `row` is not one of pieces, history, plans, photos makes EVERY wardrobe row say
   "Couldn't check right now". So R13.1's data must not ride `WardrobePart.data`.
6. **Pieces and photos.** `wardrobe/model.py`: 8 categories and their `TYPES` (`:77–100`),
   `PRIVATE_BY_DEFAULT` underpants, briefs, boxers, vest, undershirt, thermal (`:103–105`), 18 colours plus
   multicolour (`:107`; `vision/results.py:38–41`), patterns (`:108`), `Piece.photos` ≤ 3 ids (`:200`).
   `wardrobe/catalog/photos.py`: a photo is one view (front, back, detail), a cleaned JPEG ≤ 512 px read
   from its SOF marker (`frame_size`, `:46`), sealed `wardrobe_photos`; a private piece never has one,
   refused from the record; `PhotoVault.get` (`:200`) opens one for his console. The door's `thumb(id)`
   (`console-r7-send.js:128–136`) returns a saved crop as a `data:` URL.
7. **What to wear.** `wardrobe/styling/rules.json` slots: top, bottom, shoes, socks, belt, watch, outer,
   base (vest, undershirt, thermal), underwear, tie, cap, scarf; `styling/look.py` `PRIVATE_SLOTS =
   {base, underwear}`. The HTTP contract's `Look` is `pieces: (SlotPick{slot, piece, words, locked})`,
   reasons, compromises, gaps (`wardrobe/http_parts.py`); `PlanView` per plan; `GET /v1/outfits` gives
   today's and tomorrow's. `outfit_plan`'s actions are save, lock, change, reserve, transfer, release,
   share (`styling/actions.py:27`); `lock` puts a piece he names into its slot.
8. **Helpers → Wardrobe** (`console-helpers-wardrobe.js`, 290 lines): six sections built in `mount()`
   (`:277`); each plan is drawn by `plan(day, p)` (`:117`) with "Wearing it" and "Done for today"; every
   change goes through `POST /v1/wardrobe/tools/{tool}` (the gateway: rows, cards, audit). Placement CSS
   `console-wardrobe.css` (51 lines) is checked by `test_r13_seams.py` to hold no colour or font literal.
9. **Pixels.** `test_r13_seams.py:478–487`: only `console-camera-panel.js` and `console-wardrobe-scan.js`
   may call `JarvisVision.run`/`stream` or `JarvisCamera.frame`/`photo`; outside `DRAWING`
   (`console-fx.js`, `console-3d.js`, `console-r111-files.js`) no console module may use `drawImage`,
   `getImageData`, `toBlob`, `createImageBitmap` or `captureStream`. The door is the only caller of the
   wardrobe's picture routes (`:528–535`). R13's `person` (SSD) and `face` (UltraFace) tasks already run
   on a still bitmap (Camera → Wardrobe's "Choose a photo").
10. **Money.** `billing/service.py`: `ensure_allowed` (`:222`, a paid brain against his monthly limit,
    fail closed), `reserve_free`/`release_free` (`:300–331`, R6.2's atomic hold of a free allowance), `record`
    (`:333`, a cost added to his IST month under a label; never raises), `LABELS = {"voice": "Voice"}`
    (`:59`). `billing/meter.py:330–372` `reserve_units`/`release_units`: check-and-hold in ONE
    transaction, a `Hold` that remembers its month, `released` set before the first await. `config.py:359`
    `usd_inr_rate` 95.24 (the fallback when the day's rate can't be fetched). R6.2's confirm-before-spend is
    `confirm_cost: true` on an owner-only patch (`buildbook/owner.py:13`, `:121`).
11. **Google from Cloud Run.** `voice/adc.py:50` `AdcTokens`: Application Default Credentials (the
    `jarvis-run` service account) with the cloud-platform scope, refreshed off the event loop, never logged;
    google-auth already arrives with Firestore. `drive/token.py` reads the metadata server directly.
    `deploy/cloudrun.sh`: region `asia-south1` (`:48`), optional APIs switched on with a note when refused
    (`:87–102`), `try_bind` for optional roles (`:470`), `--timeout 300 --memory 512Mi` (`:539–548`).
12. **Console-only.** `api/book_gate.py:56` `console_only`: a signed-in browser session only, no
    token-mode shortcut (R6.2 G11). `api/settings_audit.py:24` `record_change` writes an owner's change to
    the audit chain.
13. **Bodies.** Every request body is capped at 2,100,000 bytes before routing (`api/body.py:25`); a
    photo of ≤ 700 KB needs no new cap.
14. **Keyring** (`keyring.py:42–78`): 24 cipher purposes, the last `wardrobe`, `wardrobe_photos`; pinned
    `test_r13_seams.py:105–106`, `test_r14_seams.py:261`, `test_r7_seams.py:295`, `test_r11_seams.py:166`,
    the set in `test_r3_seams.py:850–872`; positionally `test_r14_seams.py:260` (`PURPOSES[-3] ==
    "backup_probe"`) and `test_r7_seams.py:294` (`PURPOSES[-6:-3]`).
15. **The morning tick's job lists are pinned** in eight wiring tests (R13 I1-NOTES, fix F3): a new daily
    job moves them; `R13_JOB_NAMES` is pinned at `test_r13_seams.py:237`.
16. **R13's `outfit_plan` takes a piece that isn't ready** (plan review 1, H2): `_lock` with a `piece`
    (`styling/actions.py:137–146`) checks only that it exists and has a slot (`_slot_of`, `:38–43`) and that
    no other plan reserves it (`reserve.conflict`); `reserve` is the same; nothing reads `Piece.eligible`
    (`wardrobe/model.py:216–217`). The panel's tool route (`api/wardrobe.py:284–309`) runs one call and,
    when a card is needed, parks it in his conversation.
17. **Backups are kept 7 days** (R14): `backup/status.py:51` `RETENTION_DAYS = 7`;
    `deploy/backup_setup.sh` creates `--retention=7d`. 14 weeks is only Firestore's maximum.
18. **The door's redraw stops at 900 KB:** R11.1's `shrink` (`console-r111-files.js:193–208`,
    `JPEG_TRIES` 0.85 → 0.4 at `:24`) stops at the first quality under `picture_max_kb` (900), at
    1,568 px. `JarvisPrivacy` exposes only `refresh` (`console-privacy.js:259`).
19. **Cookie writes need `X-Requested-With: JARVIS`** (`api/auth.py:117–127`): new routes under
    `require_auth` get CSRF protection as they are. A sealed envelope is base64
    (`integrations/vault.py:80–83`): 740 KiB raw still fits a 1 MiB document. Cloud Run runs
    `--max-instances 1` (`cloudrun.sh:542`), but a rollout can run two revisions at once.
20. **The deploy already keeps one budget alert**, `jarvis-any-charge` (`cloudrun.sh:385–389`), with the
    Budgets API switched on (`:381`).

## The 3D figure: preview v2 as found, and what JARVIS keeps of it

Read in `.project-notes/scratch-in/mannequin-preview-v2/` (not JARVIS code): `index.html` (544 lines),
`build_assets.py` (769), `mq_core.py` (262), `measure-table.txt`.

- **Body.** The MakeHuman/MPFB2 base mesh (19,158 vertices, 13,380 on the body), its targets and the
  standard rig weights, read with numpy from NAVER's `naver/anny` repository data (`src/anny/data/mpfb2`).
  A neutral young male average, six measurement morphs solved by Newton steps (height, shoulder width,
  chest, waist, hips, inseam), posed relaxed, eyes filled, face softened to a mannequin head.
- **Garments.** From the CC0 `helper-tights` helper mesh, offset and smoothed: shirt tucked and untucked
  (collar stand and leaf, placket, buttons, cuffs), trousers, belt and buckle, shoes and soles, socks, a
  watch on the left wrist, and an always-on vest and shorts base layer. Every mesh carries the same six
  morphs.
- **Measured here (this workspace, 17 Nov 2026):** the anny clone at commit
  `8f35dc2df1c4062fd2fae86734f9705de50c0c2b` (26 Oct 2026); the build ran (≈ 3 s, numpy 2.5.3, scipy 1.18.1)
  and twice gave identical files: `body.glb` 2,437,524 bytes, SHA-256
  `850782a4dfe4cd3f682bd3834b2ce615da60061e163cecba9178e9c30a1ba212`; `outfit.glb` 1,523,852 bytes,
  `91e816210b9b46819f6fb8d29df9542121ba6bbc30bbc6ed1f3fc41e2a417e2d` (gzip -9: 1.87 + 1.10 MB).
  Triangles: dressed and tucked 24,566; base layer only 26,134. Its measure table (corrected by plan review 1,
  H3): v2 makes ONE morph a slider (the shape at the slider's top minus the sample), so a value below the
  sample is a straight-line extrapolation: **waist 62 comes back 63.9 cm** (1.9 cm off on its own
  slider); the other five come back within 0.5 cm on their own sliders; the worst cross-effect is chest
  99.3 cm at height 150 (+3.3 cm); tall-and-heavy's worst is chest 108 → 106.2 (−1.8). D3 fixes the waist.
- **Licences, checked in the clone:** `src/anny/data/mpfb2/LICENSE.md` is **CC0 1.0 Universal** (the
  MakeHuman assets "adapted from MPFB2", README §License); Anny's code is **Apache-2.0** (`LICENSE`,
  "Copyright (C) 2025 NAVER Corporation"; no NOTICE file). `mq_core.py` copies one list of 46 vertex
  indices (the waist loop) from Anny's `anthropometry.py`: Apache-2.0 applies to that, so JARVIS ships
  Anny's LICENSE and a NOTICE line saying so. The `smplx` topology (non-commercial download) is never
  touched; Anny's own "anny" topology (with its edits) is not used either: the raw MakeHuman base is.
- **What is not JARVIS-ready:** three.js and its addons from a CDN through an inline import map, Google
  Fonts, base64 JSON wrappers around the GLB, sample pieces in the page, a day/night button of its own, a
  continuous render loop, OrbitControls and RoomEnvironment, a 2-state layer toggle that can leave the
  pelvis uncovered when an outfit has no bottom, no tests for the build script. Known rough spots (from the
  brief): vest neckline, high collar, shoulder pinch on the check shirt, simple shoes, straight fingers,
  12-segment sleeves.

## Google's image models for "See it on me", verified on Google's own pages (17 Nov 2026)

Prices at ₹95.24 a dollar (the console's fallback rate; JARVIS uses the day's rate), before and with 18 %
GST (M1). "A picture" is one picture of him in the look's top and trousers.

| | **`gemini-3.1-flash-image`** (default, H1) | `gemini-nano-banana-2.1` | `virtual-try-on-001` (not built, D19) |
|---|---|---|---|
| Status | GA 28 May 2026; retirement "May 28, 2027 or later" (G9) | GA 6 Oct 2026 (G10) | deprecated 14 Sep 2026; discontinued 20 Jan 2027 (legacy page) or retired 15 Mar 2027 (current page) (G1, G2) |
| Try-on | "Virtual try-on" and "person generation" supported; listed in Google's try-on how-to (G9, G5) | listed in the how-to (G5) | the dedicated model (G5) |
| Images in one call | up to 14 (G9) | up to 14 (G10) | 2: one person, one garment (G2, G3b) |
| API | GenerateContent (G9) | GenerateContent | `:predict` (G5) |
| Where | `global`, or the multi-regions `us` and `eu`, whose ML processing stays inside that boundary; `global` "can't control or know which region" (G9, G12) | `global` only (G10) | 16 regions, none in India; Singapore nearest (G2) |
| Endpoint | `https://aiplatform.us.rep.googleapis.com/v1/projects/{p}/locations/us/publishers/google/models/gemini-3.1-flash-image:generateContent` (G12) | `https://aiplatform.googleapis.com/v1/projects/{p}/locations/global/…` | `https://{region}-aiplatform.googleapis.com/…:predict` |
| Price | non-global: input $0.55/M, text and thinking output $3.30/M, image output $66/M; 1,120 tokens an input image, 1,120 a 1K picture (G4) | input $1.50/M, image output $30/M (G4) | $0.06 an output image (G4) |
| One picture (top + trousers) | ≈ $0.0759 = **₹7.22, ₹8.52 with GST**; ≈ ₹8.9 with GST if Google bills about 1,000 thinking tokens; top + trousers + jacket ₹8.59 | ≈ ₹3.70, ₹4.37 with GST | 2 calls: ₹11.43, ₹13.49 with GST |
| Marking | Content Credentials (C2PA) (G9) | — | watermark, Content Credentials (G1, G2) |

Common to all (G4, G6, G7, G11): "You're charged only for requests that return a 200 response code …
4xx and 5xx codes, aren't charged"; "If you pay in a currency other than USD, the prices listed in your
currency on Cloud Platform SKUs apply" (his bill uses Google's INR price: JARVIS's ₹ is an estimate);
Google "won't use your data to train or fine-tune any AI/ML models without your prior permission";
Google "may log prompts to detect potential abuse"; implicit caching of Gemini requests is on by default
and kept at most 24 hours, and can be switched off for the project (`disableCache`); the role "Agent
Platform User" (`roles/aiplatform.user`) or a custom role with `aiplatform.endpoints.predict` ("Make
prompt requests"); an Indian customer without a GSTIN pays 18 % India GST, and services sold by Google
Cloud India carry 18 % GST whatever the GSTIN status.

## Decisions (binding)

**D0 · Scope, parts, order, and what does not change.** R13.1 builds the 14 rows in four parts after
I0: **A · Try-on data** (measurements and their versions, looks for the figure, each piece's figure
choice, saved comparisons, the fresh readiness check, the Try-on Privacy rows, OPS-05), **B · The 3D
figure** (the asset build, the figure engine, garment templates and textures; **Fable 5.2, one builder,
its own files only**), **C · See it on me** (the provider port's Gemini adapter, his photo, consent, the
cap, pictures), **D · Console and phone** (the Try it on section, every control, the checklist, the photo
panel, the See it on me card). No new model-callable tool, no new permission row, no new alert kind, no
persona change, no new Telegram pattern, no new Scheduler job, no new secret. The figure is free; the one
paid path is owner-only and console-only (D13). `api/app.py`, `tools/gateway.py`, `core/brain.py` and
`console.html` are not edited. One R13 fix ships with it (D20: `outfit_plan` refuses a piece that isn't
ready).

**D1 · Where it lives: one new section inside Helpers → Wardrobe.** A new Helpers tab would push
`console-helpers.js` past its pinned 238 lines; a dock button needs `console.html` (782, byte-identical) and
a 23rd button. So:
- `console-helpers-wardrobe.js` gains a seventh section, **Try it on**, between "Today and tomorrow" and
  "Laundry", which `console-tryon.js` (D) mounts; and each plan row in "Today and tomorrow" gains **Show in
  3D** (free) and, while "See it on me" is on, **See it on me** (its ₹ shown on the confirm). Both open
  the section with that plan's look. I0 writes this hook (≤ 16 lines) and pins it. The section is mounted
  ONCE in `mount()`, never in `draw()` (which rebuilds every section on each load); fresh readiness
  reaches it by an event; the engine is disposed on tab hide and `pagehide`; one WebGL context; **Turn
  around** stays still under Motion Off (L7).
- The stage sits in the section (56 % of the viewport's height on a phone, 480 px tall on a laptop) with a
  **Full screen** button (the Fullscreen API on the stage; Escape returns), hidden where
  `requestFullscreen` is missing, as on an iPhone (L8).
- **The look does not change**: only existing components (`.hp-sec`, `.hp-h`, `.hp-row`, `.btn.sact`,
  `.sacts`, `.bsw`, `.minput`, `.snote`, `.sfine`, `.bdialog`); new CSS `console-tryon.css` ≤ 200 lines only
  places things (the R13 static test extended to `console-tryon*.css`); the 3D scene takes its accent, ink
  and background from `window.JarvisFX.tokens()` and follows `jarvis:theme` (day and night), as
  `console-3d.js` does. Mockup screenshots (360 × 800, 1280 × 800, day and night) go to the orchestrator
  before release.

**D2 · The figure in JARVIS: preview v2, made CSP-clean.** The engine imports only
`/static/vendor/three-0.187.0/three.module.min.js` (fact 2). It does NOT vendor three's addons: they import
the bare specifier `three`, which needs an import map, and the CSP refuses inline scripts. Instead B
writes (i) `console-tryon-glb.js`, a reader for exactly the GLB subset the build script writes (a JSON and
a BIN chunk; accessors for positions, normals, UVs, indices and morph targets, `KHR_mesh_quantization`'s
normalised int16 and int8) into `BufferGeometry` with `morphAttributes`; anything else is refused; (ii)
turntable controls of its own (drag turns the figure, pinch and wheel zoom within limits, arrow keys and
+/- for the keyboard, double-tap resets; pitch limited as v2's 0.22π–0.56π); (iii) lights without
`RoomEnvironment`: v2's hemisphere, key (with a 1024 shadow map), fill, rim and back lights. Render on
demand (a change, a drag, the spin), never a continuous loop; device pixel ratio ≤ 1.5; the governor of
`console-3d.js:13–17` (two slow windows → shadows off and DPR 1 → 3D retired, the checklist takes over,
D8). WebGL2 only; `webglcontextlost` → the checklist. The mannequin's body grey and the base layer's grey
are v2's colours (constants in the engine, not CSS).

**D3 · The assets: built by a pinned script, committed, checked when served.**
- `scripts/mannequin/` (B; a dev tool run by hand, never in the image; `numpy==2.5.3`, `scipy==1.18.1` in
  `scripts/mannequin/requirements-dev.txt`): v2's `mq_core.py` and `build_assets.py` split into modules
  ≤ 400 lines (`core.py`, `pose.py`, `measure.py`, `tops.py`, `bottoms.py`, `outer.py`, `feet.py`,
  `accessories.py`, `glb.py`, `build.py`), each function ≤ 50 lines. Its input is a local clone of
  `naver/anny` at `8f35dc2df1c4062fd2fae86734f9705de50c0c2b`; it reads only `3dobjs/base.obj`,
  `mesh_metadata/basemesh_vertex_groups.json`, `rigs/standard/rig.default.json`,
  `rigs/standard/weights.default.json` and the `macrodetails/`, `torso/measure-*` and `legs/measure-*`
  targets it names, refuses any whose SHA-256 differs from its table, and never reads the `smplx` folder.
- Output in `src/jarvis/api/static/vendor/mannequin/m1/`: `body.glb`, `garments.glb`, `MANIFEST.json`
  (`sha256`, `bytes`, `type` `application/octet-stream`, `source` with the anny commit, `licence`, `changes`
  (Apache-2.0 §4(b)), `sliders`, `ranges`, `sample`, `sole`, the templates and their variants, triangle
  counts, and the measure table), `LICENSE-mpfb2-CC0.txt` (the clone's `LICENSE.md`),
  `LICENSE-anny-Apache-2.0.txt`, `NOTICE-mannequin.txt` ("Body and garment base: MakeHuman/MPFB2 assets
  (CC0 1.0) as shipped in NAVER's Anny at <commit>; the waist measurement loop from Anny's
  anthropometry.py (Apache-2.0, NAVER Corp.); shaped, posed, cut and quantised by JARVIS"). The same lines
  go to `buildbook/gen/libs.py`.
- **The waist below the sample (H3).** B adds ONE corrective morph, `waist_down` (the solved shape at
  waist 62 minus the sample), used only below 82 cm: seven morph targets in all. **Measured here** on the
  rebuilt v2 (17 Nov 2026, the build's own measure, `/tmp` script): each measurement changed alone comes
  back within **0.48 cm** at both ends of its range and at mid points (v2: 1.90 cm); when several change
  together, or at a height extreme, another measurement can drift up to **3.33 cm** (height 150 → chest
  99.3, which this fix does not touch), shown as "estimated" ("each within about half a centimetre;
  changing several can move another by up to about 3 cm"). Measured and not taken: two-sided morphs for
  all six (0.35 cm and 2.36 cm, but ≈ +1.5 MB, over the budget); a linear calibration of the weights (worst
  1.83 cm, but it pushed waist 120 to 121.5: worse on its own slider); refusing waist 62–65 (a slim owner
  would be refused).
- **Size budget:** `m1` ≤ **3.5 MB** in all (a test). Positions and morph deltas as normalised int16 with a
  per-accessor scale (padded to 8 bytes a vertex), normals int8 (padded to 4), UVs float32, uint16 indices:
  v2's set comes to ≈ 2.1 MB (plan review 1's count; v2's float32 build is 3.96 MB), the new templates add
  ≈ 0.8–1.3 MB and `waist_down` ≈ 0.26 MB: ≈ 3.2–3.7 MB. Over 3.5 MB, B drops, in this order and says so in
  INTEGRATION-B: the morph normals of the small parts (buttons, buckle, watch, soles, socks), then those of
  the garments (their shading under a morph is then the sample's), then splits the garments into one file
  a template, fetched only for the look's templates (the first load body + base ≤ 1.6 MB). Quantisation
  keeps every measurement within 0.2 cm of the float build. `scripts/mannequin/measure.py` carries the
  Apache-2.0 header and the NOTICE line (the waist indices live there, not in the GLB, L12). **Triangles:** a dressed
  figure ≤ 32,000; two figures (compare) ≤ 64,000.
- **Served** by `GET /static/vendor/mannequin/{release}/{name}` (I0): the vision route's manifest check
  generalised to a folder read at call time (`_VisionFiles(lambda: _VISION)`, so R7's tests that
  monkeypatch `console._VISION` stay unchanged, L2), JavaScript never, a year's
  immutable cache (the release is in the URL). A file that fails its sum is a 404, and the engine falls
  back to the checklist (D8).
- **Reproducible:** a test (skipped without `JARVIS_ANNY_DIR`) rebuilds into a temporary folder and
  compares measurements within 0.1 cm and triangle counts exactly (byte equality is not required: another
  BLAS can change float bits).

**D4 · Measurements, typed, versioned, estimated where not typed (AVT-02, AVT-03).**
- Six measurements in whole cm, v2's ranges: height 150–195, shoulder width 36–54, chest 76–124, waist
  62–120, hips 78–126, inseam 66–92. A value outside its range is refused in words ("The figure can be
  150 to 195 cm tall"). Each measurement records whether he **typed** it; one he didn't is estimated from
  his height with v2's sample proportions and shown "estimated" (his "Show which measurements are
  estimates"); the figure is labelled "Estimated from your measurements".
- **Versions:** `current`, one `draft` and up to 5 `earlier` versions (each with its time). While he types,
  the figure shows the draft; **Use these measurements** makes it current; **Keep the current** drops it.
  Saved selections (his plans' piece ids, his saved comparisons) never change with a version.
- The figure is MakeHuman's male base (the owner's). A second base is not built (YAGNI).
- Kept sealed in `tryon/{uid}` (purpose `tryon`). Never in a tool result, a log, an alert or the audit's
  text (the audit keeps "measurements changed" with an argument hash, as `record_change` does); never sent
  to Google; not in the R13 wardrobe backup file.

**D5 · Garment templates, colours and textures (AVT-04, AVT-05, AVT-06).**
- **The template table** (I0's `wardrobe/tryon/model.py`, the one source; the JS gets it in the look):

  | Template | Types | Variants |
  |---|---|---|
  | `shirt` | shirt | tucked, untucked |
  | `tee` | t_shirt, polo (a small collar), top | tucked, untucked |
  | `kurta` | kurta | to the knee, always untucked |
  | `trousers` | trousers, chinos, jeans, joggers, pyjama | — |
  | `shorts` | shorts | — |
  | `wrap` | mundu, dhoti | ankle length |
  | `jacket` | blazer, jacket, coat (longer), hoodie, sweater, rainwear, festive_layer | open, closed |
  | `shoe` | dress_shoe, boot, sneaker (a white sole) | — |
  | `sandal` | sandal, slipper | — |
  | `belt` · `watch` · `socks` | belt · watch · sock | — |
  | none: an image card only | tie, cap, scarf, jewellery, bag, eyewear, activity types, `unknown`, his own types | — |

  Every template is labelled **Approximate** (his AVT-05 fallback). The base layer (neutral vest and
  shorts) is the figure's own, never a piece.
- **His choice is saved against the piece** (`tryon/{uid}.assets[piece_id] = {template, texture_view,
  card_only}`, his AVT-05 "save its association to the item ID"); the default comes from the table; he can
  pick another template of the same slot or "image card only". A merged-away or purged piece's entry is
  dropped (A's daily tidy inside `tryon_*` code, run on read).
- **Colour** from the piece's fixed colour (18 + multicolour; the palette's RGB values in
  `wardrobe/tryon/model.py`, sent in the look); no colour → mid-grey with the card "no colour set".
- **Texture** (B's `console-tryon-cloth.js`): the piece's `detail` crop if kept, else its `front` crop,
  fetched through the door's `thumb` (read-only) and decoded with an `Image` from its `data:` URL (the
  CSP's `connect-src 'self'` refuses `fetch` of a `data:` URL, L8); the centre 40 % square, mirror-tiled 2 × 2 into its own
  512 px canvas; the tile's size in metres is an assumption per template (shirt 0.22 m, trousers 0.25 m,
  jacket 0.25 m: "texture scale approximate"). A crop that can't be read → colour only. Nothing leaves the
  device; nothing is stored.
- **Reference views (AVT-04):** the look lists each piece's kept views; a **useful** missing view is asked
  for once, with a link to Camera → Wardrobe (front for every garment; back for tops, outerwear and
  traditional; details optional). A piece without photos stays selectable (colour only, "no photo yet").
- **Accessories (AVT-06):** shoes on both feet (a pair is drawn only when both pieces are eligible, else
  "Draft: one shoe missing"), the belt at the trouser top (only when tucked), the watch on the left wrist
  (strap colour from its `strap` feature or colour; steel case); each linked to its own piece id; a missing
  model → its thumbnail card.

**D6 · Layers and styling (AVT-07, AVT-10, AVT-14).**
- Order: base layer → main (top, bottom) → outer → socks → shoes → belt → watch. **The private zone is
  never drawn by the body mesh** (pelvis and seat faces are removed from `bodyCore` at build time) and the
  base shorts are always drawn (inside the trousers' ease, so they never poke through); the base vest is
  drawn whenever no top is drawn. So no combination of layers, missing slots, views or variants can show
  the zone (a Node test walks every combination).
- **Private pieces are never drawn as themselves:** a `base` or `underwear` slot is shown only as "Base
  layer (covered)" on the figure and in any shared output; his own checklist names them only behind his
  "Show private basics" (R13 D10). A private piece has no photo (R13), so it can't be a texture.
- Layers control: **All**, **Without the outer layer**, **Base layer only**.
- Tucked / untucked for `shirt` and `tee` (the belt shows only when tucked; v2's rule), the default from the
  dress code (business formal and business casual tucked); a kurta says "A kurta is worn out". Open /
  closed for `jacket` (the default: open). His AVT-07 check fixes the blazer's shape: the sleeve ends at
  least 1 cm above the shirt cuff, the collar sits under the shirt collar, the watch case stays outside the
  sleeve.

**D7 · Turn, swap, undo, compare (AVT-08, AVT-09, AVT-11).**
- **Views:** Front, Side, Back buttons (yaw 0°, 90°, 180°), drag, zoom, **Turn around** (a slow spin),
  **Closer look** (frames the upper body); one scene state for every view.
- **Options per slot** (A's look route): every non-private, non-archived, non-merged piece of that slot's
  types, at most 12, each with its readiness word from a FRESH read of the view and the plan (Ready,
  "Draft: in the laundry", "Draft: reserved for your 18:00 event", "Draft: one shoe missing" …, from R13's
  `eligible` and reservations). **Remove** clears a slot that isn't required (outer, belt, watch, socks).
- **Undo:** up to 20 steps in page memory; an undo that lands on a pick no longer eligible lands as a draft.
- **Use this look for the plan:** the console posts the slots to A's `POST /v1/tryon/confirm`, which
  re-checks every piece from a fresh view and refuses a draft in plain words ("The navy jacket is in the
  laundry: it can't be confirmed for this event") **before** any tool call; when all are eligible it makes
  ONE R13 `outfit_plan` call (`lock` with `pieces`, every slot at once, all or nothing) through the shared
  `run_panel_tool` (D20), so the cards, rows and audit are R13's and one press makes at most one card. The
  early check is for the words; **the tool's own check is the guarantee** (D20): a piece that goes to the
  laundry between the two is refused, the plan unchanged.
- **Compare:** two figures 0.9 m apart under one camera and one light set (v2), each with its item list
  and readiness; a formal plan against a festive one, or a plan against its alternative. **Save this
  comparison** keeps ≤ 10 in `tryon/{uid}.saved` (piece ids per slot, tuck, open, layers; never a
  picture); a saved one is re-checked on opening and shown "Draft" while any piece isn't eligible.

**D8 · The checklist (AVT-15).** Always one tap away (**Show as a list**), and shown by itself when:
WebGL2 is missing, three.js or an asset fails to load or its sum, the context is lost, a first render takes
more than 10 s, or the governor retires 3D. Each row: the slot, the piece's words (private ones as R13
shows them), its image card, its readiness; actions **Change** (the same options as D7) and the plan's
**Wearing it** / **Use this look** (R13's tools and D7's confirm). Readiness is refreshed from the server
on its own, never waiting for the render ("Preparing the 3D view…" stays separate). **Retry 3D** tries
again once a page. "Wearing it" after a swap that isn't confirmed runs D7's confirm first (L10).

**D9 · "Save a picture of this look" (AVT-14's sharing; M9).** B's `snapshot({caption})` draws the
current figure(s) and, beneath them on the same canvas, the caption lines D passes (D's modules use no
pixel API): the date or event's time, and each non-private piece in fixed words (type and colour: "Navy shirt · Charcoal
trousers · Brown belt"), "Base layer (covered)" for any private slot, never his labels unless he ticks
"Use my own labels", never a piece id. The PNG is
previewed from the canvas or a `data:` URL (`blob:` is not in `img-src`, L8) and saved to his Downloads like the label sheet; JARVIS sends it
nowhere. A "See it on me" picture is never part of it.

**D10 · The provider port and the Gemini adapter (AVT-12; H1, M5, L4, L5, L12).**
- **The port** (I0, `src/jarvis/llm/tryon.py`): `TryOnProvider.make(ask) -> TryOnResult`;
  `Garment(image: bytes, words: str)` (the words come from the fixed lists only: "a navy shirt");
  `TryOnAsk(person: bytes, garments: tuple[Garment, ...], timeout_s: float)`; `TryOnResult(picture: bytes
  | None, mime, usage: TryOnUsage | None, blocked: str | None)`; `describe()` → `{provider, model,
  location, location_words, max_garments, retires_on}` (what the consent names); `estimate(n)` →
  `(typical_usd, worst_usd)`. A provider whose model takes one garment a call (`max_garments = 1`) chains
  inside its own adapter: the wardrobe never sees steps. Errors say what was billed (G4): `TryOnNotBilled`
  (any non-200, or never sent) and `TryOnMaybeBilled` (a timeout after sending, a cut 200); a 200 without
  a picture (`blocked`) is billed. The price table `TRYON_PRICES` (per model and location: input, text,
  image per million tokens, tokens an image) lives there too; the wardrobe asks for "the try-on
  provider" (`WardrobeContext.tryon`, I0), never a model id.
- **The adapter** (C, `src/jarvis/llm/tryon_gemini.py`): plain REST with httpx to the Agent Platform's
  GenerateContent at the `us` multi-region (the endpoint in the table above; `eu` and `global` by
  setting), with a bearer token from an injected token source (the wiring passes `voice.adc.AdcTokens`,
  loaded only when pictures are on; the project is `firestore_project`, else ADC's). NEVER
  `gemini_provider.py`'s Developer-API key, which may train on content (`config.py:765`). The body holds
  only what Google's own image sample holds: one `user` turn with `inlineData` parts (his photo, then each
  garment's crop) and one fixed English text part ("Show the person in the first image wearing the
  clothes in the other images: a navy shirt (image 2), charcoal trousers (image 3). Keep the person's
  face, body shape, pose and background as they are. One full-length picture, no text."), and
  `generationConfig` with `responseModalities: ["IMAGE"]` and `maxOutputTokens: 8192` (C checks both
  names on Google's GenerateContent reference before writing the adapter, M5; no safety, person or size
  setting is sent: Google's defaults). The answer: the first `inlineData` image part (JPEG or PNG by its
  magic bytes, ≤ 16 MB); **every text part is discarded unread** (untrusted, never logged, shown or
  kept); `usageMetadata` for the settle; a `promptFeedback.blockReason` or a finish without an image is
  `blocked`. Redirects never followed; the token, bodies and bytes never logged (class names and statuses
  only). **No SDK:** `google-genai` would be a new heavy dependency (its own retries and logging, a
  licence entry) for one POST; google-auth is already here, and REST is testable with `httpx.MockTransport`
  like Drive and voice.
- **Google's own caching** is switched off for the project at deploy (`cacheConfig` `disableCache: true`,
  G6; a note when refused, and then the consent says requests may stay in Google's memory up to 24 hours).
- **The picture is kept as Google returned it** (L5): its structure checked (JPEG or PNG magic, size),
  never decoded or re-encoded, so its Content Credentials stay; served with its detected type and
  `nosniff`.
- **Swappable:** `gemini-nano-banana-2.1` or a successor of the same family is a setting (model and location)
  and a new YES; another family is a new adapter file. The suite in `evals/r13_1/seeme.py` runs any
  provider through the port (I0's one-garment fake and C's adapter on recorded answers).

**D11 · Consent: his typed YES, specific and bound to provider, model and location (AVT-12, OPS-05; M3).**
- The first time, the card shows (fixed words): what is sent (his photo and the look's garment photos;
  never a private piece, his measurements or anything else), to whom (Google Cloud's Agent Platform,
  Gemini 3.1 Flash Image, processed in the United States), what Google says it keeps (no training without
  permission; may log for abuse checks; caching switched off, or "up to 24 hours" if Google refused that),
  that every picture shows its ₹ first under his monthly cap, Content Credentials, the model's end date,
  and how to withdraw. He types **YES** (exactly, letters only; trimmed): anything else changes nothing.
- The record (`tryon_consent/{uid}`, sealed `tryon`): when, and a SHA-256 over a FIXED template: its
  version, provider, model, location and location words. **Never the day's ₹ or the cap**: those are shown
  on every estimate (D13.3), so a moved rate never asks again. A different provider, model, location or
  template version asks again (tests: the rate 95.24 → 96.10 keeps consent current; a model or location
  change does not).
- Only from a signed-in browser (`console_only`'s rule, fact 12); never from chat, voice, Telegram, a tool,
  No-AI mode or a script with a bearer token. **Withdraw** = delete his photo (the consent goes with it).

**D12 · His photo (AVT-12): one, checked on his device, sealed on his server (M7, L4, L11).**
- "Your photo for See it on me" in the section: **Take or choose a photo** (`<input type=file
  accept="image/jpeg,image/png">`, no `capture`: the front camera can't take a full-length photo); advice
  in words: standing, head to feet, plain background, fitted everyday clothes, good light.
- **The check runs on his device** in a third pixel panel, `console-tryon-photo.js` (D): R13's `person`
  (SSD ≥ 0.5) and `face` (UltraFace ≥ 0.7) tasks on one bitmap; exactly one person and at most one face
  pass; none or several → "This photo should show only you"; a person box under 60 % of the height →
  "Step back so your whole body is in the picture" (advice, not a refusal). The words say JARVIS can't
  tell ages, so use only your own photo; Google's own rules on pictures of people apply. I0 adds the panel
  to R13's `PANELS` allow-list in the open with the scan module's rules (no `fetch`, XHR, storage,
  beacons; `JarvisConsole.api` only to `/v1/seeme…`; picture bytes only through `door.person`).
- **The door** (`console-r7-send.js`, I0): `person(blob)` redraws through R11.1's `shrink(file, {maxKb})`
  (I0 gives `shrink` an optional lower limit, `console-r111-files.js:193–208`: it tries `JPEG_TRIES` down
  to the limit), so the photo is ≤ 1,568 px and ≤ `tryon_photo_max_kb` before it leaves; still bigger →
  "This photo is too detailed to send: try a plainer background", nothing sent. Counted in "Pictures sent
  from this device today", posted to `POST /v1/seeme/photo`. `picture(id)` and `myPhoto()` read back as
  `data:` URLs. The pin moves 145 → ≤ 165.
- **On the server** (C): JPEG only, the side ≤ 1,568 px from its SOF marker (R13's `frame_size`), ≤ 700 KB,
  cleaned by `photos.imaging.sanitise_jpeg` (EXIF and GPS dropped; never decoded), sealed `tryon_photos`
  (AAD `tryon/person/{uid}/v1`) in `tryon_person/{uid}`; a new photo replaces the old in one write. Read
  back only by his signed-in console (`console_only`; `Cache-Control: no-store`, `Content-Security-Policy:
  default-src 'none'`, `nosniff`, `Cross-Origin-Resource-Policy: same-origin`). Never in the Vault panel
  (a Vault item can be attached to a chat and listed to the AI), never in the R13 backup file or any
  export, never to the AI.

**D13 · "See it on me", press to picture (AVT-12; H1, L9, L10).**
1. **Which pieces.** Every garment of the look that can be sent, in ONE picture: the top (`shirt`, `tee`,
   `kurta`), the bottom (`trousers`, `shorts`, `wrap`) and the outer layer (`jacket`); he may untick any
   before he presses. A private piece, a piece without a `front` crop, and a slot that isn't a garment
   (shoes, belt, watch, socks) are never sent; the card lists them as "not in the picture", with their
   thumbnails (his AVT-12 fallback). One picture a press.
2. **Estimate** (`GET /v1/seeme/estimate`): Google's token prices for the model and location × the day's
   rate (FxRates; ₹95.24 when unknown) × (1 + `tryon_tax_pct`), rounded up to 10 paise: the **typical**
   figure (the image, the inputs and about 1,000 thinking tokens: ≈ ₹8.9) and the **hold** (the worst case
   the request allows: `maxOutputTokens` 8,192 and three garments: ≈ ₹11.2); the cap left; his monthly
   limit's room.
3. **Confirm** (D's `.bdialog`): "Make 1 picture of you in the navy shirt and charcoal trousers? About ₹9
   with GST. ₹54.3 of ₹300 used this month." **Make the picture** sends `confirm_cost: true`, `inr_shown`
   and a fresh `request_id`; **Cancel** sends nothing.
4. **The server's gates**, in order, each refusing before any spend: console-only; 6 presses a minute;
   pictures on in this deployment (`tryon_pictures`) and before `tryon_model_retires`; not No-AI mode
   (`BrainMode.load`); consent current (D11); his photo kept; every piece sendable (from the record);
   `confirm_cost`; the fresh typical figure ≤ `inr_shown` + ₹0.01, else 409 `price_changed`; his overall
   monthly limit (`billing/spend.py` `ensure_spend_allowed`, fail closed); **the cap's atomic reserve of
   the hold**, which also refuses while another fresh hold exists (`busy`, inside the same transaction,
   so two instances during a rollout can't both pass; D15).
5. **The call:** one GenerateContent request (D10), a 120 s deadline (Cloud Run allows 300 s). A blocked
   answer → "Google didn't make this picture (its safety check). It may still be charged (about ₹9). Try
   another photo of you: standing, plain background, fitted clothes."
6. **Settle:** from `usageMetadata` (input, image and text or thinking tokens × the price × the rate × GST)
   into the cap and into his usage month under the label `tryon` (Vitals shows "Try-on"); no usage in the
   answer → settled at the hold. Released in full on `TryOnNotBilled`. The picture is kept if ≤ 700 KB,
   else shown once and not kept (said); `done {request_id: outcome}` (≤ 50, pruned with the month) answers
   a repeated `request_id` with the same result.
7. **Shown** with **"Generated 2D style preview — not a photo; the fit is not exact"**, the made-at time,
   the ₹, the exact pieces sent (ids and words), the pieces not in it, and "Google adds Content Credentials
   (C2PA)"; the 3D view stays where it was. "Wearing it" after a swap that isn't confirmed runs D7's
   confirm first, so the wear is logged on the pieces he sees (L10).

**D14 · What is kept, and for how long.**

| What | Kept | Gone when |
|---|---|---|
| His measurements, versions, figure choices, saved comparisons | sealed `tryon/{uid}` | he deletes them (Privacy, OPS-05) |
| His photo | sealed `tryon_person/{uid}` | he deletes or replaces it, or OPS-05 |
| His YES | sealed `tryon_consent/{uid}` | his photo is deleted, or OPS-05 |
| A try-on picture | sealed `tryon_picture/{uid}_{id}` | 30 days after it was made (`tryon_keep_days`; owner question 3), unless **Keep** (then until he deletes it; at most 24 kept); also when a piece in it is later made private or purged; OPS-05 |
| The month's try-on spend | `tryon_spend/{uid}_{YYYY-MM}`, numbers only | 13 months after its month (it is his cap's record) |

C's daily job `seeme_daily` (the morning tick) deletes pictures past their time and pictures of pieces now
private or gone, turns holds older than an hour into spend at their hold (a call that may have been
billed), and from 30 days before the model's end date writes the panel's notice. Nothing else in R13.1
runs on a clock.

**D15 · The ₹ cap: atomic, his month, GST counted, fail closed (M1, L9).** `tryon_spend/{uid}_{YYYY-MM}`
(his IST month, `UsageMeter.month_of`): `{spent_inr, held_inr, holds {request_id: {inr, at}}, done
{request_id: outcome}, pictures, blocked, updated_at}`. `TryonCap.reserve(uid, request_id, hold_inr)`
reads and writes in ONE transaction: refused with nothing written when a hold under 10 minutes old exists
(`busy`) or when `spent + held + hold > cap` ("This month's try-on limit of ₹300 is used: ₹291.6 spent.
It resets on 1 Dec, or raise it in Try-on settings."); a counter that isn't a finite number ≥ 0 is
unreadable and refuses (never "₹0 spent"); `settle(hold, billed_inr)` moves the hold into spend;
`release(hold)` gives it back (never below 0), with `released` set before the first await and a failed
release retryable (R6.2's `Hold`, fact 10). The cap is `tryon_month_cap_inr` (₹300; his own setting
0–2,000; 0 = off; raising it needs `confirm_cost: true` and the new figure shown). **Every ₹ shown and
the cap include `tryon_tax_pct` (18 %) GST** ("about, with GST"); his Google bill uses Google's INR
price, so JARVIS's ₹ is an estimate the pilot compares with the bill. With each picture at ≈ ₹8.5–8.9 and
a hold of ≈ ₹11.2, ₹300 makes about 33–34 pictures a month.

**D16 · Privacy rows and OPS-05 (M2, M4, M10, L10).**
- **Section "Try-on"**, its own; R13's Wardrobe section is untouched (fact 5). Every row rides
  `WardrobePart.privacy`, never `data` (M4): `tryon_figure` "Your measurements and your 3D figure" (A;
  count, export, delete with a confirm); `tryon_photo` "Your photo for See it on me, and your YES" (C;
  export says when and how big, never the bytes; passkey); `tryon_pictures` "See it on me pictures" (C;
  export lists them, never the bytes; passkey); `tryon_spend` "Try-on spend" (C; numbers per month; not
  deletable: "kept 13 months for your monthly limit"); `tryon_all` "All your try-on data" (A: the three
  above in one delete; passkey; this is OPS-05); `tryon_device` "Only on this device: nothing is kept on
  this device". A part that is off or failed still answers for what it left on disk: I0's
  `wardrobe/tryon/kept.py` stand-in **PrivacySources** say "Couldn't check right now" and delete by path
  with no key (R13 I1's M1 rule), `owner` kept as a plain field on every R13.1 document.
- **OPS-05 "Delete all my try-on data"** is the Privacy delete of `tryon_all` through the existing
  `PrivacyService` (its passkey ceremony bound to the category id and `rev`, its IRREVERSIBLE audit line,
  its words; no new passkey code). The Try-on settings button opens that same delete (I0 adds
  `JarvisPrivacy.remove(id)` to `console-privacy.js`, which exposes only `refresh` today, `:259`). The
  row's delete calls A's `erase_all(uid)`: C's pictures, his photo and his YES (through C's `seeme`
  service, or C's stand-in paths), then `tryon/{uid}`; the spend counters stay. Afterwards the viewer
  says "No figure yet: type your measurements", saved comparisons and pictures are gone, "See it on me"
  asks for a photo again; the wardrobe catalog is untouched. The dialog says: "Copies inside JARVIS's
  own daily backups stay locked and are gone within 7 days", the number read from R14
  (`backup/status.py:51` `RETENTION_DAYS`), never a second literal; a figure is only ever rebuilt from
  measurements he keeps.

**D17 · Version, persona, the AI's words, guide (L10).** `__version__ = "13.1.0"` at I0 (its seven pins
move, L1). The persona stays **p13.0** (no new tool). R13's `outfit_suggest` result gains one fixed field
while Try-on is on: `see_it: "In Helpers, Wardrobe you can see this look on your 3D figure, free, or press
See it on me; its price is shown before each picture."` (I0; C's R13 result pins move). Guide cards
**C72** Try-on figure (R13.1) and **C73** See it on me (R13.1), PLANNED at I0 with every collection and
route, built at I1; C63's pixel sentence becomes "Three panels see pixels: Camera, Camera → Wardrobe and
Try-on's own photo check …", pinned by a test in the same I1 commit.

**D18 · The model's end date (H1).** `tryon_model_retires` = 2027-05-28 (Google: "May 28, 2027 or later",
G9). From 30 days before, the Try-on section says "Google may retire this image model on 28 May 2027";
from that day "See it on me" is off until a newer model is set ("JARVIS will offer the next one, with
your YES again") while everything else keeps working. A newer model of the same family is a setting
(model, location, its prices in `TRYON_PRICES`) plus his new YES (D11), not a new adapter.

**D19 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| A figure from his photos (AVT-01, row 386) | Declined / later by the owner; photo-to-3D needs a large GPU or a cloud service |
| `virtual-try-on-001` as a second adapter | Not built (H1, the planner's call): deprecated since 14 Sep 2026 and switched off by Google by 20 Jan 2027, one garment a call (₹13.5 with GST for top and trousers), and no page says a deprecated model still serves a project that never used it. The port keeps `max_garments` and adapter-side chaining, so it can be added in a day if the pilot shows Gemini's likeness is poor and Google still serves it; it would switch itself off at its date |
| Fabric behaviour, garment measurements (AVT-13) | Extras, later |
| Ties, caps, scarves, jewellery, bags, eyewear on the figure | Image cards in R13.1; shapes later |
| A second figure base | Not needed for one owner (YAGNI) |
| "See it on me" from the chat or voice | Kept out on purpose (a typed or injected request can't spend); the AI says where the button is |
| Re-making pictures by themselves after a change | Each picture costs money: only by a press |
| Inches | cm only in R13.1 (owner question 6) |

**D20 · An R13 fix shipped in R13.1: `outfit_plan` refuses a piece that isn't ready (H2).** Today `_lock`
with a `piece` (`styling/actions.py:137–146`) checks only that the piece exists and has a slot (`_slot_of`,
`:38–43`) and that no other plan reserves it; `reserve` is the same; nothing reads `Piece.eligible`
(fact 16). So the AI can already lock a jacket that is In laundry into tomorrow's plan. I0, test first:
1. `_lock` and `reserve` refuse unless every piece of the unit is eligible by the engine's own rule
   (`states.eligible`, the pair and set rules, and `look.py`'s shared-plan rule for an In-use piece, so
   R13's STY-12, STY-13 and STY-14 tests stay green): "The navy jacket is in the laundry: it can't be
   locked into this plan." Nothing is written. Tests: a laundry piece through the tool → `PlanRefused`,
   the plan unchanged; R13's tests unchanged.
2. `lock` accepts `pieces` (one per slot; the schema already has `pieces`, `styling/tools.py:85`) and
   applies them in ONE `s.change`, all or nothing.
3. `api/wardrobe.py`'s panel-tool handling (`:284–309`: run, and when a card is needed park it in his
   conversation) becomes a shared helper, `run_panel_tool`, that A's confirm route calls: at most one
   card for one press.
4. Release note line: "R13 fix: a piece that isn't ready can't be locked or reserved into a plan."

## Data model (prefix `jarvis_`; flat ids; every document carries `updated_at` and a plain `owner`)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `tryon/{uid}` | A | measurements (`current`, `draft`, ≤ 5 `earlier`, each typed or estimated per field), `assets` {piece → template, texture view, card only}, `saved` ≤ 10 comparisons (slots → piece ids, tuck, open, layers), his figure preferences; ≤ 200 KB sealed | `tryon` | until deleted |
| `tryon_person/{uid}` | C | his one photo (cleaned JPEG ≤ 700 KB, ≤ 1,568 px), when, its size, the device's check (people, faces counts) | `tryon_photos` (AAD `tryon/person/{uid}/v1`) | until he deletes it |
| `tryon_consent/{uid}` | C | his YES: when, the template's version and hash, provider, model, location | `tryon` | with his photo |
| `tryon_picture/{uid}_{id}` | C | one picture as Google returned it (JPEG or PNG ≤ 700 KB), made at, piece ids sent, plan id, the ₹ settled, its tokens, kept flag | `tryon_photos` (AAD `tryon/picture/{uid}/{id}/v1`) | 30 days, or until deleted if kept (≤ 24) |
| `tryon_spend/{uid}_{YYYY-MM}` | C | spent, held, holds, `done` (≤ 50), pictures, blocked | no (numbers only) | 13 months |

Ids: a picture `tp_` + 12 hex; a request id `tq_` + 16 hex (the console's). Keyring purposes 24 → **26**
(`tryon`, `tryon_photos`). **Never stored:** a camera frame, his photo's check bitmap, a texture, a
snapshot of the figure, a text part of Google's answer, a picture Google blocked, a request body or a token
in a log, his measurements outside `tryon/{uid}`, anything about another person. Sizes: `tryon/{uid}` ≈
5–20 KB; his photo ≈ 0.4–0.95 MB sealed (base64 envelope, `integrations/vault.py:80–83`: 740 KiB raw
still fits a 1 MiB document); pictures ≈ 0.3–0.95 MB each sealed. R14's drill counts the new root
collections (flat ids, `updated_at`: no change there, R13's plan fact 22).

## The HTTP contract (I0's `wardrobe/tryon/http.py`; `tests/r131_fake_server.py` serves it for D)

Every route is the signed-in owner's, rate-limited like R13's (30 changes and 60 reads a minute; 6 a
minute for `POST /v1/seeme/pictures`), `no-store`, CSRF as every cookie write (`X-Requested-With`,
`api/auth.py:117–127`), and answers `{"error": <code>, "detail": <plain words>}` on a refusal so the
console can branch (`console.js:80–89`, L6). Routes marked **console** pass a signed-in browser only.

| Route | Part | What |
|---|---|---|
| `GET /v1/tryon` | A | the figure's release and files, his measurements (current, draft, earlier), which are typed, the ranges, his figure choices, saved comparisons (ids), the section's ready word |
| `PUT /v1/tryon/body` · `POST /v1/tryon/body/use` · `DELETE /v1/tryon/body/draft` | A | save a draft · make it current · drop it (each `record_change`) |
| `GET /v1/tryon/look?plan=` / `?day=today\|tomorrow&alt=0\|1\|2` | A | `TryonLook`: slots → {slot, piece, words, template, variants, rgb, pattern, texture view and photo id, views kept and missing, readiness, approximate flags, private → covered only}, ≤ 12 options a slot with readiness, the tuck and open defaults, gaps |
| `PUT /v1/tryon/assets/{piece}` | A | his template choice for a piece (or "image card only") |
| `POST /v1/tryon/confirm` | A | `{plan, slots, session_id}`: the fresh check (409 with the draft's words), then ONE `outfit_plan` `lock` with `pieces` through `run_panel_tool` (D20); at most one card |
| `GET/POST/DELETE /v1/tryon/saved[/{id}]` | A | saved comparisons (≤ 10), re-checked on GET |
| `GET /v1/seeme` | C | on or off and why, provider words (model, location words, end date, `max_garments`), his photo (kept, when, size), consent (given, when, current), the month (spent, held, cap, pictures), the typical ₹ and the hold, `tax_pct`, `photo_max_kb`, pictures (≤ 50: id, when, pieces' words, ₹, kept, until) |
| `POST /v1/seeme/photo` · `GET` · `DELETE` | C | **console** (all three); the door's JPEG · his photo for his console · delete (and the consent) |
| `POST /v1/seeme/consent` | C | **console**; `{typed, template_version}`; 422 unless exactly YES and the template is current |
| `GET /v1/seeme/estimate?plan=&pieces=` | C | the typical ₹ and the hold (with GST), the pieces sent and not sent (with reasons), the cap left, the limit's room |
| `POST /v1/seeme/pictures` | C | **console**; `{pieces, plan?, confirm_cost, inr_shown, request_id}` → the picture's view; 402 `cap_reached` / `budget_reached`, 409 `consent_needed` / `price_changed` / `busy`, 422 `private_piece` / `no_photo` / `not_a_garment`, 502 `blocked` (with the ₹ note), 503 `not_configured` / `retired` / `no_ai` / `provider_unavailable` |
| `GET /v1/seeme/pictures/{id}` · `POST …/{id}/keep` · `DELETE …/{id}` | C | **console**; the picture (its detected type, `default-src 'none'`, `nosniff`, `Cross-Origin-Resource-Policy: same-origin`) · keep or not · delete |
| `PUT /v1/seeme/settings` | C | **console**; `{on, cap_inr, keep_days}`; a higher cap needs `confirm_cost: true` |

OPS-05 has no route of its own: it is the Privacy delete of `tryon_all` (D16, M10).

## Tools: none new (R13's `outfit_plan` is fixed, D20)

R13.1 adds no model-callable tool, so no permission row (52 stay), no Telegram pattern, no skill-register
group, no persona line. The panel's plan changes still go through `gateway.execute` (D7, D20). The paid
path is an owner-only console route with `confirm_cost`, the pattern R6.2 set for spending (fact 10), so
no e-mail, web page or chat message can start a spend or send his photo (security-reviewer to confirm).
The AI learns where Try-on is from `outfit_suggest`'s `see_it` words (D17).

## Per part: failures, security, cost

| Part | Failure modes and handling | Security and privacy | ₹ a month |
|---|---|---|---|
| A · Try-on data | no key → Try-on is off (never in clear) and says so; an unreadable `tryon/{uid}` is never overwritten; a value out of range refused in words; a look for a plan that isn't there → "That plan isn't there any more"; the fresh check refuses a draft before any tool, and `outfit_plan` refuses it again (D20); R13's store down → the look says so and the checklist stays | measurements sealed, never to the AI, logs or Google; private slots covered in every view; one confirm, one tool call, at most one card; OPS-05 through Privacy's passkey | 0 |
| B · The 3D figure | no WebGL2, an asset 404 or sum mismatch, a lost context, a 10 s first render, a slow device → the checklist (D8); a crop that can't be read → colour only | draws his crops on its own canvas only; no network but the vendored files and the door's `thumb`; nothing stored; private zone never drawn | 0 (≈ 3–3.5 MB to each device once) |
| C · See it on me | not configured / no role / API off → 503 in words; any non-200 → released, in words ("busy, try in a minute" for 429); a timeout after sending or a cut answer → "may be charged" (kept at the hold); blocked → its words (billed); his photo missing or unreadable → asks again; the cap or limit unreadable → refused (fail closed); past the end date → off | his photo and pictures sealed; consent typed and bound to provider, model and location; console-only; private pieces refused from the record; only his photo and garment crops leave, to one named model and location; Google's text parts never read; the token, bodies and bytes never logged; a custom role that can only make prompt requests (M6) | ≈ ₹9 a picture with GST, capped at ₹300 |
| D · Console and phone | the engine missing or failing → the checklist; the photo check's models not installed → "The photo check isn't available on this device" (no photo is saved); offline → R13's words | textContent only; the third pixel panel's rules; the door is the only sender; nothing kept on the device | 0 |

## Cost (₹; no new Scheduler job, no new secret)

| Item | ₹ |
|---|---|
| Firestore: measurements, his photo (≤ 0.95 MB), pictures for 30 days (≈ 10 a week, ≈ 43 at a time ≈ 13–40 MB) and ≤ 24 kept (≤ 23 MB), inside the free 1 GiB | 0 |
| R14's daily backups, when he has them on (≈ ₹3.8 per 100 MB a month) | ≤ 3 |
| The figure's files to each phone and laptop, once a release (≈ 3–3.5 MB from asia-south1) | < 0.1 once |
| Cloud Run time for a press (≈ 10–40 s, inside the free vCPU-seconds) | 0 |
| **See it on me**, `gemini-3.1-flash-image` in `us` (G4): one picture of the whole outfit ≈ ₹7.2 before GST, **≈ ₹8.5–9 with 18 % GST** (≈ ₹8.5 with no thinking tokens, ≈ ₹8.9 with about 1,000); the hold ≈ ₹11.2 | 0 unless used |
| The cap: ₹300 a month with GST ≈ 33–34 pictures | ≤ 300 |
| For comparison (owner question 12): `gemini-nano-banana-2.1` ≈ ₹4.4 a picture with GST (any country); `virtual-try-on-001` ≈ ₹6.7 a garment with GST (not built) | — |

## The I0 seam list (branch `r13-1-i0`; the integrator owns these files)

1. **Version** `13.1.0`: `__init__.py` and its five pins (`test_about.py:25`, `test_r7_seams.py:111`,
   `test_r11_1_seams.py:74`, `test_r13_seams.py:72`, `test_r14_seams.py:99`), plus `v13.0.0` in
   `test_r13_wiring.py:306` and `tests/r13_fake_server.py:126` (L1).
2. **Keyring** +2 → **26** (`tryon`, `tryon_photos`): the count pins of fact 14 and the positional ones,
   `test_r14_seams.py:260` (`PURPOSES[-3] == "backup_probe"`) and `test_r7_seams.py:294`
   (`PURPOSES[-6:-3]`) (L1).
3. **The contract** (`wardrobe/ports.py`, ≤ 400): `PartName` += `tryon`, `seeme`; `TOOL_FAMILIES` both `()`;
   `ROUTE_PREFIX` `tryon` → `/v1/tryon`, `seeme` → `/v1/seeme`; `COLLECTIONS` (the data model);
   `JOB_OWNER`/`R13_JOB_NAMES` += `seeme_daily` (C, daily; `test_r13_seams.py:237`); `SERVICE_OWNER` +=
   `tryon_looks` (A), `seeme` (C); `PhotoVault` gains `get(uid, photo)`; `WardrobeContext.tryon:
   Callable[[], TryOnProvider | None]` (L12); the pins of fact 4 move.
4. **R13.1's own types** (`wardrobe/tryon/`): `model.py` (measurements, ranges, the template table, the
   palette, ids), `http.py` (every route's models), `ports.py` (the `seeme` service's `erase`), `kept.py`
   (the stand-in PrivacySources), stub parts `wardrobe/tryon/part.py` and `wardrobe/seeme/part.py` ("not
   built yet").
5. **The provider port** `llm/tryon.py` (D10: plural garments, `max_garments`, `location_words`, the
   billed-or-not errors, `TRYON_PRICES`) and `tests/r131_fake_tryon.py` (a scripted provider with
   `max_garments = 1`, which proves adapter-side chaining).
6. **Wiring** `api/r13_wiring.py` (≤ 400): `PART_MODULES` += the two; **`_with_kept` branches by part**:
   R13's four as today; `tryon` and `seeme` get `kept.py`'s PrivacySources in `privacy` and keep `data`
   empty; `check_part` refuses a `tryon` or `seeme` part that offers `data` (M4; test: both R13.1 parts
   failed → R13's five Wardrobe rows still read, the Try-on rows say "Couldn't check right now" and delete
   by path); `install_r13_routes` += `api/tryon.py`, `api/seeme.py` (stubs at I0) and
   `api/tryon_assets.py` (the mannequin route, D3); the provider built lazily into `ctx.tryon` (`AdcTokens`
   only when `tryon_pictures` is on; the project from `firestore_project`, else ADC's). `api/app.py` **0
   lines**.
7. **Settings** (`config.py`, one line each, ≤ 790): `tryon_enabled` (on), `tryon_pictures` (off; deploy
   sets it), `tryon_month_cap_inr` 300 (0–2,000), `tryon_tax_pct` 18 (0–28), `tryon_model`
   "gemini-3.1-flash-image" (a key of `TRYON_PRICES`), `tryon_location` "us" (`us`, `eu`, `global`),
   `tryon_model_retires` "2027-05-28", `tryon_keep_days` 30 (1–30; owner question 3), `tryon_photo_max_kb` 700
   (100–740); and (I0) `tryon_cache` off, which the deploy sets when Google refuses to switch its 24-hour cache
   off (seam 13), so the consent says so; `config.py` 790.
8. **Money** `billing/spend.py` (new, ≤ 100): `ensure_spend_allowed(billing, uid, inr)` (his limit, fail
   closed, BudgetReached's words) and `with_tax(inr, pct)`; `billing/service.py` `LABELS["tryon"] =
   "Try-on"` (+1).
9. **Console** (each file ≤ 800): `console-helpers-wardrobe.js` (the section, mounted once in `mount()`,
   and the plan buttons, ≤ 16 lines; ≤ 306); `console-r7-send.js` (`person`, `picture`, `myPhoto`; ≤ 165,
   its pin); `console-r111-files.js` (`shrink(file, {maxKb})`, ≤ 4 lines, M7); `console-privacy.js`
   (`JarvisPrivacy.remove(id)`, ≤ 8 lines, M10); `console-r7.js` (+ `console-tryon.css`); `api/console.py`
   `APP_ASSETS` (+ the new files, stubs at I0) and the manifest checker generalised as
   `_VisionFiles(lambda: _VISION)` so the five R7 tests that monkeypatch `console._VISION` stay as they
   are (L2); `tests/test_r51_console_assets_linked.py` `NOT_IN_PAGE`; `console.html` unchanged (782); the
   dock stays 22.
10. **The pixel and drawing rules** (`tests/test_r13_seams.py`): `PANELS` += `console-tryon-photo.js` (with
    the scan module's rules and `door.person` only); `DRAWING` += `console-tryon-3d.js`,
    `console-tryon-cloth.js` (their own canvases; a static test that neither calls `JarvisVision`,
    `JarvisCamera`, `getUserMedia` or the door's senders); D's modules use no pixel API (the share caption
    is drawn by B, M9); the door the only caller of `/v1/seeme/photo` and `/v1/seeme/pictures`.
11. **The engine contract** `static/console-tryon-3d.js` stub (throws "not built yet", so D's checklist path
    is real from day one): `window.JarvisTryOn3D = {supported(), mount(host, {release, onLost}) → Stage}`,
    `Stage = {show(figures, opts) → {drawn, approx, cards}, view(name), spin(on), zoom(step), closer(),
    snapshot({caption: string[]}) → Blob, stats(), dispose()}`; `figures[i] = {body: {weights, typed},
    look: {slots: [{slot, piece, template, variant, rgb, pattern, photo, private}]}}`, `opts = {tucked,
    open, layers, view}`; every field pinned in `tests/fixtures/r13_1/engine_contract.mjs` (L12).
12. **R13 joins and the R13 fix (D20, H2):** `_lock` and `reserve` refuse a piece that isn't eligible,
    test first; `lock` takes `pieces`, all or nothing in one `s.change`; `run_panel_tool` out of
    `api/wardrobe.py:284–309` for A's confirm; `outfit_suggest`'s `see_it` words (D17) and their pins; the
    eight pinned tick-job lists gain `seeme_daily` (fact 15).
13. **Deploy** `deploy/cloudrun.sh` (≈ +20, M6): switch on `aiplatform.googleapis.com` (a note when
    refused); create the custom role `jarvisTryOn` with only `aiplatform.endpoints.predict` and bind it to
    `jarvis-run` (falls back to `roles/aiplatform.user` with a note); set the project's `cacheConfig`
    `disableCache: true` (G6; a note when refused, and `JARVIS_TRYON_CACHE=on` so the consent says so);
    add a budget alert `jarvis-tryon` at the cap on the billing account beside `jarvis-any-charge`
    (`cloudrun.sh:385–389`; a note when refused); `JARVIS_TRYON_PICTURES=true` only when the API and a role
    worked (like `DRIVE_STATE`). Nothing is called and nothing is charged by that.
14. **Guide and book:** C72, C73 PLANNED (every collection and route), the edition line, the change log;
    `scripts/arch_coverage.json`; `buildbook/gen/libs.py` (the mannequin's licences). No `layers.py` row:
    it maps top-level packages and `wardrobe` (L5) and `llm` already cover the new subpackages (L3).
15. **Evals and fakes:** `evals/r13_1/run.py` (R14's shape, **staged gate**: unbuilt parts pass as
    `not_built_yet` until I1, which flips `STUBS_PASS = False`, pinned), gated in `evals/run_all_mock.py`
    after R13's line; stubs `figure`, `looks`, `seeme`, `console`, `e2e`, `needles`, and the built
    `contract`; `tests/r131_fakes.py` (a fixed IST clock, the pilot set: a shirt, trousers, a blazer, a pair
    of shoes, a belt, a watch, a kurta, two private basics), `tests/r131_fake_server.py`,
    `tests/test_r131_seams.py`, `tests/test_r131_wiring.py`.
16. `docs/plans/r13-1-integration/BRIEF-COMMON.md` (R13's rules plus: Fable 5.2 for B only; ₹ only in
    owner-facing words; no real Google call anywhere; every test takes a fixed clock; CI runs plain
    `pytest`, so never `from tests.x import`: fakes are imported bare and named uniquely (`r131_*`);
    browser tests carry `-m browser`) and `I0-NOTES.md`.

## Part split (four builders; worktrees; branches `r13-1-a` … `r13-1-d` from `r13-1-i0`; disjoint files)

Each Python part plugs in through `build(ctx: WardrobeContext) -> WardrobePart`; the wiring leaves out a
part that breaks the contract. B and D build against the engine contract and `tests/r131_fake_server.py`;
A and C against R13's real catalog and styling on I0's fakes.

- **A · Try-on data** (Opus; AVT-03, AVT-04, AVT-05's association, AVT-09's check, AVT-11's saved looks,
  AVT-14's views, OPS-05): `wardrobe/tryon/{part,store,versions,looks,options,assets,saved,confirm,
  privacy,erase}.py`, `api/tryon.py`, `tests/test_r131_a_*.py`, `tests/r131_fakes_a.py`,
  `evals/r13_1/looks.py`, INTEGRATION-A.md. `security-reviewer` required (OPS-05, the confirm path).
- **B · The 3D figure** (**Fable 5.2**, one builder; AVT-02, AVT-03's shape, AVT-05/06 drawing, AVT-07,
  AVT-08, AVT-10, AVT-11's two figures, AVT-14's covering): `scripts/mannequin/**`,
  `static/vendor/mannequin/m1/**`, `static/console-tryon-3d.js` (≤ 600), `console-tryon-glb.js` (≤ 200),
  `console-tryon-cloth.js` (≤ 300), `tests/test_r131_b_*.py`, `tests/fixtures/r13_1/b_*.mjs`,
  `tests/browser/test_r131_b_*.py` (a bare stage page from the fake server), `evals/r13_1/figure.py`,
  INTEGRATION-B.md. First steps, in order: port the script with tests on a synthetic mesh; the
  private-zone removal and its test; quantisation within the budget; then the templates (tee, kurta,
  shorts, wrap, jacket open/closed, sneaker, sandal) and v2's rough spots (vest neckline, high collar,
  shoulder pinch, 24-segment sleeves, a shaped shoe toe; straight fingers stay).
- **C · See it on me** (Opus; AVT-12, OPS-05's half): `llm/tryon_gemini.py`, `wardrobe/seeme/{part,vault,
  consent,cap,estimate,make,pictures,privacy,jobs,texts}.py`, `api/seeme.py`, `tests/test_r131_c_*.py`,
  `tests/r131_fake_gemini.py` (Google's documented GenerateContent answers through `httpx.MockTransport`:
  an image with `usageMetadata`, an answer with a text part carrying an instruction, a blocked prompt, a
  finish without an image, 400, 403, 404, 429, 500, 503, a cut body, a timeout), `evals/r13_1/seeme.py`,
  INTEGRATION-C.md. `security-reviewer` required (consent, money, his photo, the adapter, the deploy's
  role).
- **D · Console and phone** (Opus; AVT-15 and the UI of every row): `static/console-tryon.js` (the
  section, measurements form, controls, swaps, undo, compare, settings, OPS-05 button; ≤ 600),
  `console-tryon-list.js` (the checklist, image cards, the share caption; ≤ 300), `console-tryon-me.js`
  (photo, YES, estimate, confirm, progress, pictures; ≤ 400), `console-tryon-photo.js` (the pixel panel;
  ≤ 300), `console-tryon.css` (≤ 200), `tests/test_r131_d_*.py`, `tests/browser/test_r131_d_*.py`,
  `evals/r13_1/console.py`, the mockup screenshots, INTEGRATION-D.md. `security-reviewer` required (the
  pixel panel, the door).
- **All parts:** test first; functions ≤ 50 lines, Python modules ≤ 400, JS ≤ 800; only the planned
  collections, routes, services and job; never a wiring or shared file; ₹ only in owner-facing words.

## Tests and evals (mock only; each control must make its suite fail)

**Every acceptance check of the 14 is the named test in the first table**, in its part's files, and an
eval case of the same name. Real Google calls are never made by a test or an eval.

| Suite | Cases | Control that must fail it |
|---|---|---|
| `contract` (I0, built) | six parts build through the real wiring and own only their routes, services, collections and job; a broken R13.1 part is "setup failed" while R13's four still run and R13's Wardrobe rows still read; the Try-on Privacy section exists with stand-ins; a `tryon` part with `data` is refused | the contract check off: a stray route is accepted |
| `looks` (A) | AVT-03 versions and kept selections; AVT-04 views and the kurta; AVT-05 association; AVT-09 fresh check, drafts, no tool call for a draft, the race (a piece to the laundry between the check and the call → refused by `outfit_plan`, the plan unchanged), one card at most; AVT-11 saved comparisons re-checked; AVT-14 private slots covered (no id, colour, photo or label in any look, option or caption); OPS-05 erase order and the catalog's `rev` unchanged; D20's `lock`/`reserve` refusals | the private filter off: AVT-14 fails; the fresh check off: AVT-09's laundry jacket gets past the early refusal (and D20's control, `lock` without the eligibility check: the race case writes the jacket) |
| `figure` (B; Node and Python) | the manifest's sums, licences and the 3.5 MB budget; the measure table (12 slider ends and 4 mid points: each measurement changed alone within **0.5 cm**, measured 0.48 cm with the `waist_down` morph; every case's other measurements within **3.5 cm**, measured 3.33 cm; quantised within 0.2 cm of float); the private zone covered in every layer state × slot set × variant × view; AVT-07 geometry; tucked/untucked and open/closed where the table says; triangles ≤ 32,000 a figure; the GLB reader refuses an unknown accessor type | two morphs swapped: the measure table fails; `waist_down` dropped: waist 62 reads 63.9 and fails; the base shorts dropped in "All": the privacy walk fails; the blazer sleeve lengthened 2 cm: AVT-07 fails |
| `seeme` (C, through the port) | zero provider calls without a current YES; "yes", "Yes", "YES!" refused; a moved rate (95.24 → 96.10) keeps consent, a model or location change asks again; the cap: with each picture settled at ₹8.52 and a hold of ₹11.22, the 34th fits and the 35th is refused; 10 presses at once → exactly one reserves, nine `busy`; released on every non-200 and on "never sent", kept on a timeout after sending, a cut 200 and a blocked 200; settled from `usageMetadata`, at the hold without it; a text part in the answer is read nowhere (logs, store, reply); a private piece and a piece without a front crop refused before any call; No-AI, bearer token, past the end date, `price_changed`, idempotent `request_id`; the one-garment fake (`max_garments = 1`) passes the same cases through the port | the atomic reserve replaced by read-then-write: the 10-at-once case lets two through; the consent check off: "zero calls without YES" fails; the private check moved to the console only: a private piece reaches the fake provider; the ₹ hashed into the consent: the moved-rate case asks again |
| `console` (D, browser) | each row's UI half, the checklist under `__glFail`, missing WebGL2, a lost context and an asset 404; the YES dialog; the ₹ confirm with Cancel sending nothing; the share caption passed to `snapshot`; 44 px targets; 360 × 800 and 1280 × 800, day and night; the existing tabs' screenshots with Try-on **off** unchanged against R13's | the engine stub that throws, with the checklist hook removed: AVT-15 fails |
| `e2e` (I1) | his workbook's end-to-end tests: "Meeting outfit update" (the avatar half: one piece to the laundry, the viewer reopened, the checklist and the figure use the same ids), "Layer and rotate" (shirt, blazer, belt, watch, shoes; open the blazer, swap the shoes, turn to the back; every approximation named), "Private items and photos" (the avatar half: a look with private layers, a shared look, then OPS-05; the catalog usable); plus See it on me's life (photo, YES, estimate, picture, 30 days, gone by `seeme_daily`) | the look built from a stale view: "Meeting outfit update" fails |
| `needles` (I1) | his photo's bytes (raw, base64, hex), a picture's bytes, his measurements (numbers and words), the consent text, a private piece's label and colour, the fake token, the fake answer's text part — searched in every log record, the audit, approvals, activity, session turns, alerts, Telegram, Web Push, every tool result for the AI, every non-sealed document (`tryon_spend` included), the R13 backup file, the Privacy export; the fake provider receives only his photo and the chosen crops; a positive control per sink | the adapter logging its request body: the photo needle is found |

**A control for every row's own case (M8)**, run by the I1 sweep:

| Case | Control (must turn it red) |
|---|---|
| AVT-02 | Side returns Front's yaw |
| AVT-03 | a new version rewrites a saved comparison's piece ids |
| AVT-04 | the look drops the `back` view of the kurta |
| AVT-05 | the template choice is kept in page memory, not `tryon/{uid}.assets` |
| AVT-06 | the slot's thumbnail stays W1's after the swap |
| AVT-07 | the blazer sleeve lengthened 2 cm |
| AVT-08 | Back resets the tuck state |
| AVT-09 | `lock` without D20's eligibility check |
| AVT-10 | the closed variant is the open variant |
| AVT-11 | the second figure's readiness words are dropped |
| AVT-12 | the piece list is taken from the plan, not from what was sent |
| AVT-14 | the private filter off |
| AVT-15 | the checklist hook removed |
| OPS-05 | erase also deletes the wardrobe's photos (the catalog's `rev` changes) |

**Browser (Playwright, `-m browser`).** Against `tests/r131_fake_server.py` while building, the wired app at
I1. The 3D tests run only in a Chromium with WebGL2 (the Book's `_need_3d` rule: skip only for
"no-webgl2"); the fallback tests force `__glFail`. The photo panel uses a drawn full-length figure fixture
and the R13 test hook that can only add refusals; whether a drawn figure fires SSD and UltraFace is
checked first (as R13 did), else the panel's decision logic is tested on recorded task outputs and the
real check moves to the pilot.

**Static tests:** `console.html` byte-identical; the pixel and drawing lists (seam 10); the CSS rule for
`console-tryon*.css`; no `$` in owner-facing strings of R13.1's JS and Python texts; no real clock under
`wardrobe/` and `llm/tryon*.py`; the engine imports three only from the vendored URL; B's modules fetch
only `/static/vendor/mannequin/` (crops come from the door's `thumb` as `data:` URLs, decoded with an
`Image`, since `connect-src 'self'` refuses `fetch` of a `data:` URL, L8).

## Size guards

`api/app.py` 732 (no edit, ≤ 735), `tools/gateway.py` 760 (no edit), `core/brain.py` 713 (no edit),
`console.html` 782 (no edit), `config.py` ≤ 790 (< 800), `console-helpers.js` 238 (no edit),
`console-helpers-wardrobe.js` ≤ 306, `console-r7-send.js` ≤ 165 (pin moves from 145),
`console-r111-files.js` ≤ 335, `console-privacy.js` ≤ 268, every `console*.js` ≤ 800 (the new ones as in
the part split), `console-tryon*.css` ≤ 200 in all, every module under `wardrobe/` ≤ 400,
`api/r13_wiring.py` ≤ 400, `api/console.py` ≤ 475, `styling/actions.py` ≤ 400, new Python modules ≤ 400,
`static/vendor/mannequin/m1/` ≤ 3.5 MB. `tests/test_r131_seams.py` pins each.

## Risks and known limits

- **A general image model, not a try-on model.** Gemini 3.1 Flash Image lists virtual try-on, but how well
  it keeps his face and body and the clothes' true colours is unproven: the pilot's picture judges it
  (owner question 11). If it is poor, owner question 12's alternatives stand: Nano Banana 2.1 by setting,
  or the dedicated try-on model as a second adapter while Google serves it (D19).
- **The model's end.** Supported until "May 28, 2027 or later"; JARVIS warns 30 days before and stops on
  the date unless a newer model is set with his new YES (D18).
- **Data leaves India.** No Indian location serves these models; `us` keeps the processing inside the US
  boundary (`global` would not say where). Google may log for abuse checks; its 24-hour caching is switched
  off at deploy when Google allows it, else the consent says so.
- **Price varies a little.** Billing is per token: thinking tokens, if any, add up to about ₹0.4 a picture;
  his bill uses Google's INR price, not the dollar price × the day's rate. The cap holds the worst case and
  settles what Google reports; the pilot compares one picture with his bill.
- **GST.** Counted in every ₹ shown and in the cap (18 %); with a GSTIN and Google Asia Pacific as the
  seller it may be lower (then the cap is on the safe side).
- **Safety blocks.** Google may block a photo or a garment; a blocked 200 is billed; the words say so and
  suggest a better photo.
- **Likeness and children.** The device check counts people, not ages; Google's own rules on pictures of
  people apply. His photo is his own by his word.
- **The server could spend outside JARVIS's cap** with a broad role: the custom role allows only prompt
  requests, and a Cloud Billing budget alert at the cap watches the bill (M6).
- **Phone GPUs.** WebGL2 is needed; 24–32k triangles a figure, 7 morphs, one 1024 shadow map; render on
  demand; DPR ≤ 1.5; the governor steps down and the checklist takes over. Two figures in compare double
  the load.
- **The laptop's 4 GB graphics card does not matter here:** the figure runs in any WebGL2 browser and the
  paid picture in Google's cloud; only row 386 (later) would need a big GPU.
- **The figure is approximate.** One male base, six measurements (each within 0.5 cm alone, others up to
  about 3.3 cm off when several change), templates not his garments' cuts; every shape says
  "Approximate" and his photos stay visible.
- **The asset budget is tight** (≈ 3.2–3.7 MB before drops against 3.5 MB): D3's drop order decides, and
  INTEGRATION-B says what was dropped.
- **Textures from 512 px crops** are coarse; a `detail` view helps; the scale is assumed.
- **Asset licences:** CC0 data and Apache-2.0 indices are clean; the `smplx` topology is never read; the
  repository stays free of anything non-commercial.
- **Pins churn:** 7 version, 8 keyring, 3 contract, 8 tick-list, the door's and R13 C's result pins move at
  I0.
- **2 CPUs here:** targeted tests while building; whole suites queued.
- **Date bombs:** a fixed clock in every test; the 30-day keep and the end date tested at 23:30 and 00:30
  IST and across 28 May 2027.

## Needs the owner (safe defaults; none blocks the build)

1. **What a picture shows:** every garment of the look that can be sent (top, trousers, jacket) in ONE
   picture, about ₹9 with GST (default); untick any before you press (the price hardly changes).
2. **Pictures a press:** 1 (default); another try is another press, each with its ₹ shown.
3. **How long pictures stay:** **answered 17 Nov 2026 (≈ 14:25 IST): 30 days unless you press Keep**
   (the default was 7 days).
4. **Where Google makes the picture:** the United States (default, with question 12); or Europe (same
   price).
5. **The cap:** ₹300 a month (your decision), GST included (about 33 pictures); lowering is instant,
   raising asks with the new figure.
6. **Measurements:** in cm (default); inches later.
7. **From the chat:** JARVIS only tells you where the button is; it can't make a paid picture by itself
   (default, so no message or web page can make it spend).
8. **"Save a picture of this look":** fixed words like "Navy shirt", not your own labels, unless you tick
   them (default).
9. **When Google retires the model:** a warning 30 days before; "See it on me" stops on that day until you
   approve the next model with a new YES (default).
10. **Tax:** every ₹ shown and the ₹300 cap include 18 % GST (default; about 33 pictures); or count Google's
    price without GST (about 40 pictures, but your bill can then pass ₹300).
11. **Your trial (after release):** one shirt, trousers, a blazer, a pair of shoes, a belt and a watch,
    compared in two looks, as your workbook's "Build and Test" says; and ONE "See it on me" picture (about
    ₹9) after your YES, checked against your Google bill (default); or no paid trial.
12. **Which Google model makes your picture:** **answered 17 Nov 2026 (≈ 14:25 IST): Gemini 3.1 Flash
    Image, made in the United States** (the default: about ₹9 with GST for the whole outfit, supported
    until at least 28 May 2027). Not taken: Nano Banana 2.1, about
    ₹4.4, but Google may process your photo in any country; or Google's dedicated try-on model, one garment
    a picture (about ₹6.7 each), in Singapore, switched off by Google by 20 Jan 2027 (not built unless you
    ask).

## Exit check (before the PR)

1. **His workbook's Try-on exit condition:** "Each visual piece resolves to its inventory ID, estimates are
   clear and swaps update the avatar and checklist together", on the pilot set (owner question 11), on his
   phone and laptop; results in `docs/plans/r13-1-integration/I1-NOTES.md`.
2. The 14 named tests and the e2e suite pass; every built part's control and every row's own control
   (M8) fails its suite; `STUBS_PASS` flipped.
3. The full browser suite once on the joined branch (queued, never beside another whole suite).
4. **Screenshots** of the Try it on section (figure, compare, checklist, the See it on me card, the YES
   dialog, the ₹ confirm) at 360 × 800 and 1280 × 800, day and night, and the existing tabs with Try-on off,
   sent to the orchestrator.
5. The clock sweep (as R13: two days after the PR's date 09:00 IST, 20 Dec 2026, 1 Jan 2027 00:30 IST,
   1 Mar 2027, 28 May 2027, 29 Feb 2028).
6. `ruff check`, `ruff format --check`, `mypy src` (the baseline), `evals/run_all_mock.py` ALL PASS,
   `scripts/check_doc_versions.py`, `scripts/arch_coverage.py`, the coverage floor (95),
   `python -m jarvis.buildbook.gen --check`, the PR title check.
7. **One live picture only after his YES** (about ₹9, owner question 11): the adapter's real answer, its
   `usageMetadata`, latency and the ₹ settled, compared with his Google bill (Google's INR price and GST);
   otherwise "not called" is written in I1-NOTES.

## What can't be verified from this workspace

The real Gemini call (the shell can't reach Google; no paid call without his YES): its answer in this
project, latency from `us`, how many thinking tokens it bills, the exact names `responseModalities` and
`maxOutputTokens` take in the Agent Platform's GenerateContent (C checks the reference), the default
picture size, how well it keeps his likeness; whether the custom role with `aiplatform.endpoints.predict`
is enough for GenerateContent in his project, and whether the deploy may set `cacheConfig`; Google's INR
price and the GST on his invoice; the figure's speed and look on his phone's GPU; WebGL2 in the CI
Chromium; SSD and UltraFace on a real full-length photo; how close the figure looks to him.

## Plan review 1 — how each finding was handled

Review: `docs/plans/r13-1-integration/PLAN-REVIEW-1.md` (17 Nov 2026, 14:00 IST, on `281510d`): APPROVE
WITH CHANGES, 0 critical, 3 high, 10 medium, 12 low. The Workshop decided H1–H3, M1 and M2. Nothing is
declined in whole; the two partial declines are named in their rows.

| Finding | Grade | What changed | Where |
|---|---|---|---|
| H1 · a deprecated model as the provider; one garment a call baked in | HIGH | The port takes several garments in one request (`max_garments`; a one-garment adapter chains inside itself). The default is `gemini-3.1-flash-image` at the `us` multi-region (re-checked on Google's pages: GA, "May 28, 2027 or later", 14 images, `global`/`us`/`eu`; the `us` endpoint is `aiplatform.us.rep.googleapis.com`, corrected from the review's host). `virtual-try-on-001` is **not built** (deprecated, gone by 20 Jan 2027, one garment a call; the port keeps room for it). Consent bound to provider, model and location (M3). Owner question 12. Every owner ₹: ≈ ₹9 a picture with GST for the whole outfit, ≈ 33 a month | Summary 6, 7, 10; Google table; D10, D11, D13, D15, D18, D19; Cost; Risks; questions 1, 12 |
| H2 · R13's `outfit_plan` `lock` takes a piece that isn't ready; "Use this look" checks then acts over several writes | HIGH | D20: I0 fixes `_lock` and `reserve` test first (a piece that isn't eligible is refused, nothing written), `lock` takes `pieces` all or nothing in one `s.change`, the confirm makes ONE call through a shared `run_panel_tool` (at most one card); AVT-09's test adds the race. Listed as an R13 fix shipped in R13.1 | D7, D20; seam 12; HTTP `confirm`; AVT-09's test; `looks` suite |
| H3 · the measure table claim was wrong; the fix competes with the budget | HIGH | Corrected from the rebuilt table (waist 62 → 63.9; height 150 → chest 99.3; tall-and-heavy chest −1.8). Fix: ONE `waist_down` morph (≈ +0.26 MB), measured here: each measurement alone within 0.48 cm, others within 3.33 cm; the alternatives measured and not taken; the 3.5 MB budget kept with a named drop order; the eval's tolerances 0.5 / 3.5 cm and two controls | The 3D section; D3; `figure` suite |
| M1 · GST | MEDIUM | Every ₹ shown and the cap include 18 % (`tryon_tax_pct`); "about, with GST"; the INR-price note; question 10's default flipped | D13, D15; seam 7; Cost; question 10 |
| M2 · backups are kept 7 days | MEDIUM | "gone within 7 days", read from `backup/status.py:51` | Summary 9; D16; fact 17 |
| M3 · the consent hash held the day's ₹ | MEDIUM | A fixed template's version + provider, model, location; the ₹ on every estimate; tests both ways | D11; `seeme` suite |
| M4 · Try-on's Privacy rows must ride `privacy`, not `data` | MEDIUM | `_with_kept` branches by part; `check_part` refuses `data` from the two; the test with both failed | D16; seam 6; `contract` suite |
| M5 · enum spellings the API may reject | MEDIUM | Send only what Google's sample sends (now `responseModalities` and `maxOutputTokens`, names checked by C); a recorded 400 | D10; C's fake |
| M6 · `roles/aiplatform.user` can spend outside the cap | MEDIUM | A custom role `jarvisTryOn` with `aiplatform.endpoints.predict` only (fallback with a note) and a budget alert at the cap beside `jarvis-any-charge` | seam 13; Risks |
| M7 · the door can't meet 700 KB | MEDIUM | `shrink(file, {maxKb})` (I0, in R11.1's drawing module, so the door stays free of pixel APIs) and the "too detailed" words | D12; seam 9 |
| M8 · most cases had no control | MEDIUM | A control for every row's case | Tests (the table of controls) |
| M9 · the share caption broke the pixel rule | MEDIUM | `snapshot({caption})` draws it in B | D9; seams 10, 11 |
| M10 · OPS-05's passkey unspecified | MEDIUM | OPS-05 is the Privacy delete of `tryon_all` (its passkey, audit and words); no erase route; `JarvisPrivacy.remove(id)` | D16; HTTP; seam 9 |
| L1 · pins I0 will trip over | LOW | The seven version pins and the keyring's positional pins and `R13_JOB_NAMES`'s listed | seams 1–3; fact 1 |
| L2 · `_VisionFiles(folder)` read at call time | LOW | `_VisionFiles(lambda: _VISION)` | seam 9 |
| L3 · paths and layers | LOW | No `layers.py` row (top-level packages already map) | seam 14 |
| L4 · Google facts to tidy | LOW | Released on every non-200 (Google bills only 200s); kept on a timeout after sending, a cut or blocked 200; the child sentence softened; Content Credentials (C2PA) named; the appspot mirror dropped from the sources. (c) is moot: the default speaks GenerateContent | D10, D12, D13; Sources |
| L5 · sanitising removes Content Credentials | LOW | Google's picture kept as returned (structure checked, never decoded) | D10 |
| L6 · error shape | LOW | `{"error", "detail"}` on the new routes | HTTP |
| L7 · the section's life | LOW | Mounted once, disposed on hide and `pagehide`, one context, still under Motion Off | D1 |
| L8 · CSP traps | LOW | Crops decoded with an `Image`; the snapshot previewed from a canvas or `data:`; Full screen hidden where missing | D1, D5; static tests |
| L9 · the press's own state | LOW | `busy` inside the reserve's transaction; `done` (≤ 50); 6 presses a minute | D13, D15; HTTP |
| L10 · owner-facing consistency | LOW | Summary 11; screenshots with Try-on off; question 11 = exit check 7 (one picture); `see_it` without a ₹ figure; the device row "nothing is kept"; "Wearing it" after a swap confirms first | Summary; D13, D16, D17; Tests; Exit |
| L11 · small wording and inputs | LOW | AVT-03's and AVT-04's titles with ’ as in his workbook; no `capture`; the photo and picture GETs console-only with CORP. **Declined here:** the requirements workbook's row 363 "Subscription" is paperwork, not this plan (passed to the paperwork round) | First table; D12; HTTP |
| L12 · contracts I0 should pin | LOW | `WardrobeContext.tryon`, the project id, the engine's field list, the Apache header and NOTICE on `scripts/mannequin/measure.py` | seams 3, 6, 11; D3 |

## Sources (read 17 Nov 2026)

| # | Source |
|---|---|
| S1 | The owner's wardrobe workbook `AI_Wardrobe_Assistant_Use_Cases.xlsx`: "Use Cases" (rows AVT-01 … AVT-15, OPS-05), "Wardrobe Rules", "Build and Test" (the Try-on build row; end-to-end tests "Meeting outfit update", "Layer and rotate", "Private items and photos") — not in the repository |
| S2 | The owner's decisions of 17 Nov 2026 (≈ 12:50 IST) and the requirements workbook v13.0.7, rows 350–366 and 386 — not in the repository |
| S3 | The proposal "3D maps and try it on for your wardrobe" v1.0 (17 Nov 2026, 09:40 IST), section 2 — not in the repository |
| S4 | Preview v2 (`mannequin-preview-v2/`: `index.html`, `build_assets.py`, `mq_core.py`, `measure-table.txt`) and the earlier `mannequin-preview/index.html` — not in the repository |
| S5 | NAVER Anny, commit `8f35dc2df1c4062fd2fae86734f9705de50c0c2b`: `LICENSE` (Apache-2.0), `src/anny/data/mpfb2/LICENSE.md` (CC0 1.0), README §License — https://github.com/naver/anny |
| S6 | R13's plan `docs/plans/r13-wardrobe.md` (v13.0.3) and `docs/plans/r13-integration/I1-NOTES.md`; R6.2's `docs/plans/r6-2-integration/INTEGRATION-A.md` (the atomic hold, `confirm_cost`); plan review 1 `docs/plans/r13-1-integration/PLAN-REVIEW-1.md` |
| G1 | Virtual Try-On 001, legacy Vertex AI page — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/imagen/virtual-try-on-001 |
| G2 | Virtual Try-On, Gemini Enterprise Agent Platform (updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/vto/virtual-try-on-001 |
| G3a | `VirtualTryOnModelParams` — https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/VirtualTryOnModelParams |
| G3b | `VirtualTryOnModelInstance` ("A single product image to try on the person") — https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/VirtualTryOnModelInstance |
| G4 | Generative AI pricing (Gemini 3.1 Flash Image non-global $0.55 / $3.30 / $66 per million tokens and its footnote; Nano Banana 2.1; Imagen "Virtual Try-On … $0.06"; "charged only for requests that return a 200"; currency) — https://cloud.google.com/vertex-ai/generative-ai/pricing |
| G5 | Generate Virtual Try-On images (supported models; `:predict` sample; updated 11 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/generate-virtual-try-on-images |
| G6 | Data governance (training, abuse logging, caching and `disableCache`, the global endpoint) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance |
| G7 | Access control (`roles/aiplatform.user`, `aiplatform.endpoints.predict`, custom roles) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/access-control |
| G8 | Model versions and lifecycle (as read by plan review 1) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions |
| G9 | Gemini 3.1 Flash Image (GA 28 May 2026; "May 28, 2027 or later"; 14 images; virtual try-on, person generation, C2PA; `global`, `us`, `eu`; updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-image |
| G10 | Gemini Nano Banana 2.1 (as read by plan review 1) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/nano-banana-2-1 |
| G11 | Cloud Billing, taxes in your country (India GST; as read by plan review 1) — https://docs.cloud.google.com/billing/docs/resources/vat-overview |
| G12 | Deployments and endpoints (the `us`/`eu` multi-region host `aiplatform.{loc}.rep.googleapis.com`; the global endpoint; where ML processing happens) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 13:20 IST | R13.1 | First edition, from the code at `3f265cb`: the owner's summary in ₹; the 14 rows with his workbook's own titles and acceptance checks as the named tests, and where his wording goes beyond the approval; code facts with file:line; preview v2 built and measured here (sums, sizes, licences CC0 and Apache-2.0 checked in the anny clone); Google's try-on verified on Google's pages (one garment a call, $0.06 a picture, no Indian region, deprecated 14 Sep 2026 and retiring 20 Jan or 15 Mar 2027); D0–D19; the data model, the HTTP contract, no new tool; the I0 seam list; parts A–D with B on Fable 5.2; suites with controls; size guards; risks; 11 owner questions with defaults; the exit check | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 14:20 IST | R13.1 | Plan review 1 written in (H1–H3, M1–M10, L1–L12; one partial decline, L11's workbook paperwork), with the Workshop's decisions; Status Ready. The default provider is `gemini-3.1-flash-image` at `us` with several garments in one request (≈ ₹9 a picture with GST, ≈ 33 a month), `virtual-try-on-001` not built, consent bound to provider, model and location (H1, M3); R13's `outfit_plan` refuses a piece that isn't ready and locks every slot in one call, an R13 fix shipped here (H2); the measure table corrected and one `waist_down` morph (each measurement within 0.48 cm alone, measured here) inside the 3.5 MB budget (H3); GST in the cap and every ₹ (M1), backups 7 days (M2), Try-on's Privacy rows on `privacy` (M4), Google's defaults only (M5), a custom role and a budget alert (M6), the door's size (M7), a control for every row (M8), the caption in the engine (M9), OPS-05 as a Privacy delete (M10); the LOW items; owner question 12; a "Plan review 1" table | 🛠 Mark XXIII |
| v13.1.3 | 17 Nov 2026, 16:45 IST | R13.1 | The owner's answers of 17 Nov 2026 (≈ 14:25 IST) written in: the model is Gemini 3.1 Flash Image in the United States (question 12, the default confirmed); a See it on me picture is kept 30 days unless he presses Keep (question 3; was 7 days): summary 9, D14, the data model, seam 7 (`tryon_keep_days` 30, and I0's `tryon_cache`), the cost table (≈ 13–40 MB of pictures, backups ≤ ₹3), the `e2e` suite, the date-bomb line; every other question keeps its safe default | 🛠 Mark XXIII |
