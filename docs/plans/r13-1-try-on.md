Version v13.1.1 · 17 Nov 2026, 13:20 IST · Release R13.1 · Status: Draft — for plan review · Owner: 🛠 Mark XXIII

# Release R13.1 — Try-on: the 3D figure and "See it on me" (`v13.1.0`)

**Phase:** 3 (profile and personalisation) on R13's wardrobe skill, with one Phase 2 paid tool path and
Phase 7 evals. **Type:** free by default: ₹0 a month fixed, no new Scheduler job, no new secret; ONE paid
path ("See it on me", Google's try-on model) that is off until the owner's typed YES, shows its ₹ before
every picture and stops at a ₹300 monthly cap. **Scope (the owner's decisions of 17 Nov 2026, ≈ 12:50
IST):** 14 rows of his workbook (353–363, 365, 366 and 350: AVT-02 … AVT-12, AVT-14, AVT-15, OPS-05); the
free figure starts from the Fable 5.2 preview v2 ("Build on v2"); the 3D work is ONE part built by ONE
builder on Fable 5.2 (his rule of 15 Nov), every other agent on Opus. **Not in scope:** AVT-01 (declined),
AVT-13 and the extras (later), row 386 (a 3D model made from his own photo, cloud, ≈ ₹21 a look: later),
R13.2 maps. **Branches:** plan `r13-1-plan` (from `main` @ `3f265cb`, R13 live as `v13.0.0`) → I0
`r13-1-i0` → parts `r13-1-a` … `r13-1-d` → integration `r13-1-i1` → PR `v13.1.0 · R13.1 Try-on · Mark
XXIII`. Every commit carries `JARVIS-Version: v13.1.0` and `JARVIS-Mark: XXIII`. Read on `3f265cb`; every
file:line below is from that commit. The owner's wardrobe workbook (sheets "Use Cases", "Wardrobe Rules",
"Build and Test") was read on 17 Nov 2026, 13:05 IST: each row's title and acceptance check below are HIS
words.

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
   **See it on me**, JARVIS sends that photo and the top's photo to Google's try-on service, and shows a
   picture of you wearing it, marked **"Generated 2D style preview"**, with the exact pieces listed beside
   it. The first time, you type **YES** after reading what is sent and to whom.
7. **The money.** About **₹5.7 a picture** for one piece (the top). Adding the trousers is a second step,
   **about ₹5.7 more**, and you choose it each time. The ₹ is shown before every picture and nothing is
   sent until you confirm. JARVIS stops at **₹300 a month** (about 52 one-piece pictures); you can lower it
   any time, and raising it asks you first.
8. **Never sent to Google:** underwear, vests, thermals or anything you marked private; your measurements;
   anyone else's photo. JARVIS checks on your phone that your photo shows one person, but it can't tell an
   adult from a child, so use only your own photo.
9. **What is kept:** your measurements and your photo until you delete them; each try-on picture 7 days
   unless you press **Keep**. **Delete all my try-on data** (with your passkey) removes the figure, your
   measurements, your photo, your YES and the pictures; your wardrobe stays as it is. JARVIS's own backups
   keep a locked copy until they expire (at most 14 weeks), and the button says so.
10. **Cost otherwise: ₹0 a month.** The figure's files (about 2.5–3.5 MB) download once to each device.
    Google says it retires this try-on model in early 2027; JARVIS stops offering "See it on me" on
    20 Jan 2027 unless you approve its successor (a new YES).
11. **The same look.** Only one new section inside Helpers → Wardrobe; no new dock button; the existing
    screens don't change.

## What is built: the 14 rows (his workbook's words), and where each goes

Release group "Try-on" of his workbook has 15 rows; AVT-01 stays declined and its photo-based figure is
row 386 (later). The table gives each row's **use case** and **acceptance check** exactly as in his
workbook, the part that builds it, and the named test that proves it (the eval case of the same name
runs it through the wired app at I1).

| Row · ID | His use case | His acceptance check | Part | The test (what must hold) |
|---|---|---|---|---|
| 353 · AVT-02 | Create a rotatable personal avatar | The owner can rotate the model and inspect a distinct front, side and back view. | B (figure), D (controls), A (store) | `test_avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views`: with only typed measurements (his fallback "a configurable basic avatar … when the user chooses to skip photos"), the Front, Side and Back buttons give three different camera yaws (0°, 90°, 180° ± 1°), drag turns it, the figure is labelled "Estimated from your measurements" (his "Mark estimated geometry") |
| 354 · AVT-03 | Adjust the avatar's measurements and shape | Correcting height updates the avatar and its previews while retaining saved outfit selections. | A (versions), B (shape), D (form) | `test_avt03_correcting_height_reshapes_the_figure_and_keeps_every_saved_selection`: 172 → 178 cm changes the figure's height to 178 ± 0.5 cm and every open look and saved comparison redraws; their piece ids per slot are byte-identical before and after; the old version stays in use until "Use these measurements" (his "Keep the current version available until the replacement is approved"); an untyped measurement is shown "estimated" |
| 355 · AVT-04 | Capture visuals for a garment's preview | A kurta has recognisable front and back references and remains linked to its original inventory record. | A (views), D (cards) | `test_avt04_a_kurta_shows_its_front_and_back_references_under_its_own_id`: a kurta with R13's `front` and `back` crops lists both as reference cards in its look slot, under the same `wi_` id as in the catalog; a kurta with only a front asks for the back view only (a link to Camera → Wardrobe), and stays selectable |
| 356 · AVT-05 | Assign a 3D asset to a wardrobe item | A patterned shirt can use an approximate silhouette while its actual reference image stays visible. | A (association), B (template, texture), D (card) | `test_avt05_a_patterned_shirt_draws_on_an_approximate_shape_beside_its_real_photo`: a checked shirt gets template `shirt` (saved against its id), its texture from its own crop, the label "Approximate", and its front photo card visible beside the figure; a type with no template shows an image card only |
| 357 · AVT-06 | Preview shoes, belts and watches | Swapping a watch changes the correct wrist accessory or its linked thumbnail. | B (models), A (options), D (swap) | `test_avt06_swapping_the_watch_changes_the_left_wrist_and_its_thumbnail`: swapping watch W1 for W2 changes the strap colour on the left wrist and the slot's thumbnail to W2's photo; shoes and belt likewise in their own places |
| 358 · AVT-07 | Dress the avatar layer by layer | A blazer covers the shirt sleeves and torso where appropriate without hiding the shirt collar or watch by mistake. | B | `test_avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch` (geometric, Node): with shirt + blazer + watch, the blazer shell contains the shirt's torso and sleeve vertices from shoulder to 1 cm above the cuff; every shirt-collar vertex and every watch-case vertex lies outside the blazer shell |
| 359 · AVT-08 | Rotate and inspect an outfit | Changing the viewpoint from front to back preserves outfit and avatar identity. | B, D | `test_avt08_front_to_back_keeps_the_same_pieces_layers_and_figure`: after Front → Back the engine reports the same slot → piece ids, the same tuck/open/layers state and the same measurement weights; a photo-only piece stays as a labelled card beside the 3D view |
| 360 · AVT-09 | Swap, remove or undo a piece on the avatar | Swapping a ready jacket changes the avatar and checklist together. A jacket in laundry cannot be confirmed for the event. | A (fresh check), D (swap, undo), B (redraw) | `test_avt09_a_ready_jacket_swaps_figure_and_checklist_together_and_one_in_laundry_stays_a_draft`: the swap changes the drawn outer layer and the checklist row in one step; a jacket In laundry is offered as "Draft: in the laundry", "Use this look" is refused by the server's fresh check (no `outfit_plan` call is made); undo returns to the last still-eligible pick |
| 361 · AVT-10 | Try different styling options | Toggling jacket open to closed updates shirt visibility and leaves the same jacket selected. | B (variants), D (toggles) | `test_avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket`: open → closed hides the shirt placket region, keeps the jacket's piece id; tucked ↔ untucked likewise for a shirt (belt shown only when tucked); a kurta offers no tuck (said in words) |
| 362 · AVT-11 | Compare two looks side by side | A formal and festive look can be compared without losing either item list or its availability state. | B (two figures), D, A (saved, re-check) | `test_avt11_a_formal_and_a_festive_look_compare_with_both_lists_and_their_readiness`: two figures, one figure and light set, each with its own item list and each piece's readiness word; a saved comparison whose piece changed state opens marked "Draft" |
| 363 · AVT-12 | Generate a quick photo-style preview | A still preview is labelled as 2D and the checklist still identifies the exact clothes used in the plan. | C (provider, consent, cap), D (card) | `test_avt12_the_picture_is_labelled_a_generated_2d_preview_and_lists_the_exact_pieces`: a made picture shows "Generated 2D style preview — not a photo" and the list of the exact piece ids sent (top, and bottom if chosen) with their words; pieces not sent are listed as not in the picture; the 3D view stays |
| 365 · AVT-14 | Keep underwear and vests private in previews | Sharing a look displays the dressed avatar and only the approved item details. | B (covering), A (views), D (share) | `test_avt14_a_shared_look_shows_the_dressed_figure_and_only_approved_details`: "Save a picture of this look" makes a PNG of the dressed figure plus a caption with only fixed words of non-private pieces; a private piece's label, colour and id appear nowhere in it; in every layer state the private zone is covered |
| 366 · AVT-15 | Keep outfit planning usable when rendering fails | If a render fails, the user can still confirm a ready outfit or change a piece from its checklist. | D (checklist), B (failure signals) | `test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm`: with no WebGL (the `__glFail` hook), a lost context, an asset that fails its sum, or a 10 s render timeout, the checklist shows each piece with its image card and readiness; "Change" swaps a piece and "Wearing it" confirms the ready outfit through R13's tools |
| 350 · OPS-05 | Manage and delete avatar photos and models | Deleting an avatar removes it from the viewer and disables dependent previews while retaining the item catalog. | A (erase), C (its data), D (button) | `test_ops05_deleting_the_figure_empties_the_viewer_disables_previews_and_keeps_the_catalog`: after "Delete all my try-on data" the viewer says "No figure yet", saved comparisons and pictures are gone, "See it on me" asks for a photo again, and `GET /v1/wardrobe` returns the same pieces and `rev` as before |

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
| AVT-12: "Mark it as a generated style preview" | "See it on me" with Google's model | Labelled "Generated 2D style preview — not a photo; the fit is not exact"; Google also adds an invisible watermark (SynthID / Content Credentials); the exact pieces are listed beside it |
| AVT-14: "Sharing a look" | private layers always covered | "Save a picture of this look": a PNG made on his device, with only approved details; JARVIS itself sends it nowhere |
| OPS-05: "default to local processing where supported and require specific consent for external processing … honour backup retention" | delete all try-on data | The figure is drawn on his device; storage is sealed on his own JARVIS server; the one outside step needs his typed YES, bound to that provider, model and region; R14's backups keep sealed copies until they expire, and the panel says when |

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
   `tests/test_about.py:25`, `test_r14_seams.py:99` and two more). `api/app.py` **732** lines (guard ≤ 735:
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
    the set in `test_r3_seams.py:850–872`.
15. **The morning tick's job lists are pinned** in eight wiring tests (R13 I1-NOTES, fix F3): a new daily
    job moves them.

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
  Triangles: dressed and tucked 24,566; base layer only 26,134. Its measure table: every slider value comes
  back within 0.5 cm on its own measurement; the worst cross-effect is chest 99.3 cm at height 150
  (+3.3 cm), and 3.0 cm on tall-and-heavy.
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

## Google's try-on model, verified on Google's own pages (17 Nov 2026)

| Fact | What Google says | Source |
|---|---|---|
| Model id | `virtual-try-on-001` (GA); the earlier preview was `virtual-try-on-preview-08-04` | G1, G3 |
| Dates | Legacy Vertex AI page: released 20 Jan 2026, **discontinued 20 Jan 2027**. The current page (now "Gemini Enterprise Agent Platform", updated 13 Nov 2026): **deprecated 14 Sep 2026, retired 15 Mar 2027** ("may remain accessible through the Gemini API after"). No successor is named | G1, G2 |
| What one call takes | "Maximum images per prompt: 2" (one person, one product); the price row reads "Input: 1 image of a person and 1 image of clothing". **One garment per call**: a top and trousers are two calls | G2, G4 |
| Output | 1–4 images (`sampleCount` 1–4, default 1), same size as the input | G2, G3 |
| Inputs | `image/jpeg` or `image/png`, ≤ 7 MB a file (the legacy page said 10 MB) | G1, G2 |
| REST | `POST https://REGION-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/REGION/publishers/google/models/virtual-try-on-001:predict` with `instances[0].personImage.image.bytesBase64Encoded`, `instances[0].productImages[0].image.bytesBase64Encoded`, `parameters.sampleCount`; the answer is `predictions[]` of `{mimeType, bytesBase64Encoded}` | G3, G5 |
| Settings | `personGeneration` `dont_allow` / `allow_adult` (default) / `allow_all`; `safetySetting` `block_low_and_above` / `block_medium_and_above` (default) / `block_only_high` / `block_none`; `addWatermark` (default true; `seed` unavailable while it is on); `baseSteps` (default 32); `outputOptions` {`mimeType`, `compressionQuality`}; `storageUri` (not used) | G3 |
| Marking | Digital watermarking and verification, Content Credentials (C2PA); the legacy page lists the watermark as invisible (SynthID by name is not on the model page) | G1, G2, G3 |
| Regions | us-central1, us-east1, us-east4, us-east5, us-south1, us-west1, us-west4, northamerica-northeast1, europe-west1/4/8/9, europe-southwest1, europe-north1, asia-northeast1, **asia-southeast1**, me-central1. **No Indian region** | G2 |
| Quota | 50 online prediction requests a minute per base model per region | G1 |
| Price | **$0.06 an image** (Imagen section, "Virtual Try-On", per output image) = **₹5.71 at ₹95.24 a dollar** (the console's fallback rate; JARVIS uses the day's rate) | G4 |
| Data use | "Google won't use your data to train or fine-tune any AI/ML models without your prior permission or instruction"; Google "may log prompts to detect potential abuse"; the 24-hour caching rules name Gemini models only | G6 |
| Deploy needs | API `aiplatform.googleapis.com` on, billing on; the runtime account needs a role with `aiplatform.endpoints.predict` ("Agent Platform User", `roles/aiplatform.user`, the narrowest predefined role listed) | G5, G7 |
| Likely successors | The same Agent Platform page lists Gemini image models for try-on (`gemini-3.1-flash-image` and others); Gemini 3.1 Flash Image is about $0.067 (≈ ₹6.4) a 1K picture and takes several images in one call | G5, G4 |

## Decisions (binding)

**D0 · Scope, parts, order, and what does not change.** R13.1 builds the 14 rows in four parts after
I0: **A · Try-on data** (measurements and their versions, looks for the figure, each piece's figure
choice, saved comparisons, the fresh readiness check, the Try-on Privacy rows, OPS-05), **B · The 3D
figure** (the asset build, the figure engine, garment templates and textures; **Fable 5.2, one builder,
its own files only**), **C · See it on me** (the provider port's Vertex adapter, his photo, consent, the
cap, pictures), **D · Console and phone** (the Try it on section, every control, the checklist, the photo
panel, the See it on me card). No new model-callable tool, no new permission row, no new alert kind, no
persona change, no new Telegram pattern, no new Scheduler job, no new secret. The figure is free; the one
paid path is owner-only and console-only (D13). `api/app.py`, `tools/gateway.py`, `core/brain.py` and
`console.html` are not edited.

**D1 · Where it lives: one new section inside Helpers → Wardrobe.** A new Helpers tab would push
`console-helpers.js` past its pinned 238 lines; a dock button needs `console.html` (782, byte-identical) and
a 23rd button. So:
- `console-helpers-wardrobe.js` gains a seventh section, **Try it on**, between "Today and tomorrow" and
  "Laundry", which `console-tryon.js` (D) mounts; and each plan row in "Today and tomorrow" gains **Show in
  3D** (free) and, while "See it on me" is on, **See it on me · about ₹5.7**. Both open the section with
  that plan's look. I0 writes this hook (≤ 16 lines) and pins it.
- The stage sits in the section (56 % of the viewport's height on a phone, 480 px tall on a laptop) with a
  **Full screen** button (the Fullscreen API on the stage; Escape returns).
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
- **Size budget:** `m1` ≤ **3.5 MB** in all (a test), target ≤ 2.5 MB: positions and morph deltas as
  normalised int16 with a per-accessor scale, normals as int8, UVs float32 (v2's float32 build is 3.96 MB).
  Quantisation must keep the measure table within 0.2 cm of the float build. **Triangles:** a dressed
  figure ≤ 32,000; two figures (compare) ≤ 64,000.
- **Served** by `GET /static/vendor/mannequin/{release}/{name}` (I0): the vision route's manifest check
  generalised to a folder (`_VisionFiles(folder)`; R7's tests unchanged), JavaScript never, a year's
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
  fetched through the door's `thumb` (read-only); the centre 40 % square, mirror-tiled 2 × 2 into its own
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
  re-checks every piece from a fresh view and refuses a draft in words ("The navy jacket is in the
  laundry: it can't be confirmed for this event") **before** any tool call; when all are eligible it calls
  R13's `outfit_plan` (`lock`, one slot at a time) through `gateway.execute` (the panel's rule,
  `console-helpers-wardrobe.js`'s `tool()`), so the cards, rows and audit are R13's. I0 checks that `lock`
  refuses an ineligible piece itself; if it doesn't, I0 adds that check to `styling/actions.py` (a seam,
  with a test), so the AI's path is safe too.
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
again once a page.

**D9 · "Save a picture of this look" (AVT-14's sharing).** B's `snapshot()` draws the current figure(s)
to a PNG on the device (the engine's own canvas, `toBlob`); D adds a caption image beneath: the date or
event's time, and each non-private piece in fixed words (type and colour: "Navy shirt · Charcoal
trousers · Brown belt"), "Base layer (covered)" for any private slot, never his labels unless he ticks
"Use my own labels", never a piece id. It is saved to his Downloads like the label sheet; JARVIS sends it
nowhere. A "See it on me" picture is never part of it.

**D10 · The provider port and the Vertex adapter (AVT-12).**
- **The port** (I0, `src/jarvis/llm/tryon.py`): `TryOnProvider.make(ask) -> TryOnResult`;
  `TryOnAsk(person: bytes, garment: bytes, samples: int, safety: Literal["default"], timeout_s)`; one garment
  per call; `TryOnResult(pictures: tuple[bytes, ...], billed_images: int, filtered: int)`; `describe()` →
  `{provider, model, region, usd_per_image, retires_on}` (what the consent names). Errors say what was
  billed: `TryOnNotBilled` (refused before work: 400, 403, 404, 429, not configured, never sent),
  `TryOnMaybeBilled` (a timeout after sending, 5xx, a cut answer), and a result with `filtered > 0` (Google's
  safety check returned no picture) counts as billed, the safe side for his money. The wardrobe asks for "the
  try-on provider", never a model id.
- **The adapter** (C, `src/jarvis/llm/tryon_vertex.py`): plain REST with httpx (G3's request; `sampleCount`,
  `personGeneration: "allow_adult"`, `safetySetting: "block_medium_and_above"`, `addWatermark: true`,
  `outputOptions: {mimeType: "image/jpeg", compressionQuality: 80}`), a bearer token from an injected token
  source (the wiring passes `voice.adc.AdcTokens`, loaded only when pictures are on), redirects never
  followed, the answer capped at 16 MB and checked (`predictions[*].bytesBase64Encoded` JPEG or PNG, or a
  filtered entry), the token and the bodies never logged (class names and statuses only). **No SDK:** the
  `google-genai` client would be a new heavy dependency (its own retries and logging, a new licence entry)
  for one POST; google-auth is already a dependency, and REST is testable with `httpx.MockTransport` like
  Drive and voice.
- **Region:** `tryon_location` = `asia-southeast1` (Singapore), the nearest listed region; Google lists no
  Indian region for this model (G2). The consent says so.
- **Swappable:** a second provider is a new adapter file plus its name in settings; the suite in
  `evals/r13_1/seeme.py` runs against any provider through the port (I0's fake and C's adapter on recorded
  answers).

**D11 · Consent: his typed YES, specific and bound (AVT-12, OPS-05).**
- The first time, the card shows (fixed words): what is sent (his photo and one garment photo a step; never
  a private piece, his measurements or anything else), to whom (Google Cloud, `virtual-try-on-001`, the
  Singapore region), what Google says it keeps (no training without permission; may log for abuse checks),
  the price a step in ₹ and the cap, the watermark, the retire date, and how to withdraw. He types **YES**
  (exactly, letters only; trimmed): anything else changes nothing.
- The record (`tryon_consent/{uid}`, sealed `tryon`): when, the words' version (a SHA-256 of the shown
  text), provider, model, region. A different provider, model or region, or new words, asks again.
- Only from a signed-in browser (`console_only`'s rule, fact 12); never from chat, voice, Telegram, a tool,
  No-AI mode or a script with a bearer token. **Withdraw** = delete his photo (the consent goes with it).

**D12 · His photo (AVT-12): one, checked on his device, sealed on his server.**
- "Your photo for See it on me" in the section: **Take a photo** (`<input type=file accept="image/jpeg,image/png"
  capture="user">`) or **Choose a photo**; advice in words: standing, head to feet, plain background,
  fitted everyday clothes, good light.
- **The check runs on his device** in a third pixel panel, `console-tryon-photo.js` (D): R13's `person`
  (SSD ≥ 0.5) and `face` (UltraFace ≥ 0.7) tasks on one bitmap; exactly one person and at most one face
  pass; none or several → "This photo should show only you"; a person box under 60 % of the height →
  "Step back so your whole body is in the picture" (advice, not a refusal). The words say the check can't
  tell an adult from a child; Google's `allow_adult` refuses to make pictures of children. I0 adds the panel
  to R13's `PANELS` allow-list in the open with the scan module's rules (no `fetch`, XHR, storage, beacons;
  `JarvisConsole.api` only to `/v1/seeme…`; picture bytes only through `door.person`).
- **The door** (`console-r7-send.js`, I0): `person(blob)` (redrawn by R11.1's `shrink`, ≤ 1,568 px JPEG,
  counted in "Pictures sent from this device today", posted to `POST /v1/seeme/photo`) and `picture(id)` /
  `myPhoto()` (read back as `data:` URLs). The pin moves 145 → ≤ 165.
- **On the server** (C): JPEG only, the side ≤ 1,568 px from its SOF marker (R13's `frame_size`), ≤ 700 KB,
  cleaned by `photos.imaging.sanitise_jpeg` (EXIF and GPS dropped; never decoded), sealed `tryon_photos`
  (AAD `tryon/person/{uid}/v1`) in `tryon_person/{uid}`; a new photo replaces the old in one write. Shown
  back only to his console (`Cache-Control: no-store`, `Content-Security-Policy: default-src 'none'`,
  `nosniff`). Never in the Vault panel (a Vault item can be attached to a chat and listed to the AI), never
  in the R13 backup file or any export, never to the AI.

**D13 · "See it on me", press to picture (AVT-12).**
1. **Which pieces.** From the plan's look (or the swapped look on the figure): the top (`shirt`, `tee`,
   `kurta`) by default; the bottom (`trousers`, `shorts`, `wrap`) only when he ticks **Add the trousers
   (about ₹5.7 more)**; an outer layer is a third step he may tick. A private piece, a piece without a
   `front` crop, or a slot that isn't a garment (shoes, belt, watch) is never sent; the card lists them as
   "not in the picture" (his AVT-12 fallback: their thumbnails beside it).
2. **Estimate** (`GET /v1/seeme/estimate`): steps × samples × the price a step at the day's rate (FxRates;
   ₹95.24 when unknown), rounded up to 10 paise; the cap left; his monthly limit's room.
3. **Confirm** (D's `.bdialog`): "Make 1 picture of you in the navy shirt? About ₹5.7. ₹54.3 of ₹300 used
   this month." **Make the picture** sends `confirm_cost: true`, `inr_shown` and a fresh `request_id`;
   **Cancel** sends nothing.
4. **The server's gates**, in order, each refusing before any spend: console-only; pictures on in this
   deployment (`tryon_pictures`) and before `tryon_model_retires`; not No-AI mode (`BrainMode.load`);
   consent current (D11); his photo kept; every piece eligible to send (from the record); `confirm_cost`;
   the fresh estimate ≤ `inr_shown` + ₹0.01 else 409 `price_changed`; one picture at a time (409 `busy`);
   his overall monthly limit (`billing/spend.py` `ensure_spend_allowed`, fail closed); **the cap's atomic
   reserve** (D15).
5. **The calls:** step 1 puts the top on his photo; step 2 puts the bottom on step 1's picture. A step
   that comes back filtered stops the chain ("Google didn't make this picture (its safety check). About
   ₹5.7 may still be charged. Try another photo of you: standing, plain background, fitted clothes."). A
   120 s deadline for the whole press (Cloud Run allows 300 s).
6. **Settle:** billed images × the price into the cap and into his usage month under the label `tryon`
   (Vitals shows "Try-on"); the picture (the last step's) is kept if ≤ 700 KB, else shown once and not kept
   (said); a repeated `request_id` returns the same result.
7. **Shown** with **"Generated 2D style preview — not a photo; the fit is not exact"**, the made-at time,
   the ₹, the exact pieces sent (ids and words), the pieces not in it, and Google's watermark note; the 3D
   view stays where it was.

**D14 · What is kept, and for how long.**

| What | Kept | Gone when |
|---|---|---|
| His measurements, versions, figure choices, saved comparisons | sealed `tryon/{uid}` | he deletes them (Privacy, OPS-05) |
| His photo | sealed `tryon_person/{uid}` | he deletes or replaces it, or OPS-05 |
| His YES | sealed `tryon_consent/{uid}` | his photo is deleted, or OPS-05 |
| A try-on picture | sealed `tryon_picture/{uid}_{id}` | 7 days after it was made (`tryon_keep_days`), unless **Keep** (then until he deletes it; at most 24 kept); also when a piece in it is later made private or purged; OPS-05 |
| The month's try-on spend | `tryon_spend/{uid}_{YYYY-MM}`, numbers only | 13 months after its month (it is his cap's record) |

C's daily job `seeme_daily` (the morning tick) deletes pictures past their time and pictures of pieces now
private or gone, turns holds older than an hour into spend (a call that may have been billed), and from
30 days before the retire date writes the panel's notice. Nothing else in R13.1 runs on a clock.

**D15 · The ₹ cap: atomic, his month, fail closed.** `tryon_spend/{uid}_{YYYY-MM}` (his IST month,
`UsageMeter.month_of`): `{spent_inr, held_inr, holds {request_id: {inr, at}}, pictures, steps, filtered,
updated_at}`. `TryonCap.reserve(uid, request_id, inr)` reads and writes in ONE transaction: refused with
nothing written when `spent + held + inr > cap` ("This month's try-on limit of ₹300 is used: ₹297.1 spent.
It resets on 1 Dec, or raise it in Try-on settings."); a counter that isn't a finite number ≥ 0 is
unreadable and refuses (never "₹0 spent"); `settle(hold, billed_inr)` moves the hold into spend;
`release(hold)` gives it back (never below 0), with `released` set before the first await and a failed
release retryable (R6.2's `Hold`, fact 10). Released only on `TryOnNotBilled`; kept and settled as billed
on `TryOnMaybeBilled` and on a filtered result. The cap is `tryon_month_cap_inr` (₹300; his own setting
0–2,000; 0 = off; raising it needs `confirm_cost: true` and the new figure shown). The cap counts Google's
list price at the day's rate; tax on Google's invoice, if any, is not in it (Risks).

**D16 · Privacy rows and OPS-05.**
- **Section "Try-on"** (its own; R13's Wardrobe section is untouched, fact 5): `tryon_figure` "Your
  measurements and your 3D figure" (A; count, export, delete with a confirm); `tryon_photo` "Your photo for
  See it on me, and your YES" (C; export says when and how big, never the bytes; delete with the passkey);
  `tryon_pictures` "See it on me pictures" (C; export lists them, never the bytes; passkey); `tryon_spend`
  "Try-on spend" (C; numbers per month; not deletable: "kept 13 months for your monthly limit");
  `tryon_device` "Only on this device: the 3D view's undo steps and checklist ticks" (nothing to delete).
  A part that is off or failed still answers for what it left on disk: I0's
  `wardrobe/tryon/kept.py` stand-ins say "Couldn't check right now" and delete by path with no key
  (R13 I1's M1 rule), `owner` kept as a plain field on every R13.1 document.
- **OPS-05 "Delete all my try-on data"** (in Try-on settings; the passkey, like a Privacy passkey delete,
  `permissions/passkeys.py`): A's `POST /v1/tryon/erase` deletes, in this order, C's pictures, his photo
  and his YES (through C's `seeme` service, or C's stand-in paths), then `tryon/{uid}`; the spend counters
  stay. Afterwards the viewer says "No figure yet: type your measurements", saved comparisons and pictures
  are gone, "See it on me" asks for a photo again; the wardrobe catalog is untouched. The dialog says:
  "Copies inside JARVIS's own backups stay locked until those backups expire (at most 14 weeks)" (R14's
  retention); a figure is only ever rebuilt from measurements he keeps.

**D17 · Version, persona, the AI's words, guide.** `__version__ = "13.1.0"` at I0 (its four pins move).
The persona stays **p13.0** (no new tool). R13's `outfit_suggest` result gains one fixed field while
Try-on is on: `see_it: "In Helpers, Wardrobe you can see this look on your 3D figure, free, or press See it
on me (about ₹5.7 a picture)."` (I0; C's R13 result pins move). Guide cards **C72** Try-on figure (R13.1)
and **C73** See it on me (R13.1), PLANNED at I0 with every collection and route, built at I1; C63's pixel
sentence becomes "Three panels see pixels: Camera, Camera → Wardrobe and Try-on's own photo check …",
pinned by a test in the same I1 commit.

**D18 · The model's retirement.** `tryon_model_retires` = 2027-01-20, the earlier of Google's two dates
(G1, G2). From 30 days before, the Try-on section says "Google is retiring this try-on model on 20 Jan
2027"; from that day "See it on me" is off ("Google retired its try-on model; JARVIS will offer the next
one in an update, with your YES again") while everything else keeps working. A successor (likely a
Gemini image model, about ₹6.4 a picture with several garments in one call, G4, G5) is a later small
release: a new adapter, a new price, and his new YES (D11 binds consent to the model).

**D19 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| A figure from his photos (AVT-01, row 386) | Declined / later by the owner; photo-to-3D needs a large GPU or a cloud service |
| Fabric behaviour, garment measurements (AVT-13) | Extras, later |
| Ties, caps, scarves, jewellery, bags, eyewear on the figure | Image cards in R13.1; shapes later |
| A second figure base | Not needed for one owner (YAGNI) |
| "See it on me" from the chat or voice | Kept out on purpose (a typed or injected request can't spend); the AI says where the button is |
| Re-making pictures by themselves after a change | Each picture costs money: only by a press |
| Inches | cm only in R13.1 (owner question 6) |

## Data model (prefix `jarvis_`; flat ids; every document carries `updated_at` and a plain `owner`)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `tryon/{uid}` | A | measurements (`current`, `draft`, ≤ 5 `earlier`, each typed/estimated per field), `assets` {piece → template, texture view, card only}, `saved` ≤ 10 comparisons (slots → piece ids, tuck, open, layers), his figure preferences; ≤ 200 KB sealed | `tryon` | until deleted |
| `tryon_person/{uid}` | C | his one photo (cleaned JPEG ≤ 700 KB, ≤ 1,568 px), when, its size, the device's check (people, faces counts) | `tryon_photos` (AAD `tryon/person/{uid}/v1`) | until he deletes it |
| `tryon_consent/{uid}` | C | his YES: when, the words' version, provider, model, region | `tryon` | with his photo |
| `tryon_picture/{uid}_{id}` | C | one picture (JPEG ≤ 700 KB), made at, piece ids sent, plan id, steps, ₹, kept flag | `tryon_photos` (AAD `tryon/picture/{uid}/{id}/v1`) | 7 days, or until deleted if kept (≤ 24) |
| `tryon_spend/{uid}_{YYYY-MM}` | C | spent, held, holds, pictures, steps, filtered | no (numbers only) | 13 months |

Ids: a picture `tp_` + 12 hex; a request id `tq_` + 16 hex (the console's). Keyring purposes 24 → **26**
(`tryon`, `tryon_photos`). **Never stored:** a camera frame, his photo's check bitmap, a texture, a
snapshot of the figure, a picture Google filtered, a request body or a token in a log, his measurements
outside `tryon/{uid}`, anything about another person. Sizes: `tryon/{uid}` ≈ 5–20 KB; his photo ≈ 0.4–0.9
MB sealed; pictures ≈ 0.3–0.9 MB each sealed. R14's drill counts the new root collections (flat ids,
`updated_at`: no change there, R13's plan fact 22).

## The HTTP contract (I0's `wardrobe/tryon/http.py`; `tests/r131_fake_server.py` serves it for D)

Every route is the signed-in owner's, rate-limited like R13's (30 changes and 60 reads a minute), `no-store`,
and answers plain words (`{"detail": …}`). Routes marked **console** pass a signed-in browser only.

| Route | Part | What |
|---|---|---|
| `GET /v1/tryon` | A | the figure's release and files, his measurements (current, draft, earlier), which are typed, the ranges, his figure choices, saved comparisons (ids), the section's ready word |
| `PUT /v1/tryon/body` · `POST /v1/tryon/body/use` · `DELETE /v1/tryon/body/draft` | A | save a draft · make it current · drop it (each `record_change`) |
| `GET /v1/tryon/look?plan=` / `?day=today\|tomorrow&alt=0\|1\|2` | A | `TryonLook`: slots → {slot, piece, words, template, variants, rgb, pattern, texture view and photo id, views kept and missing, readiness, approximate flags, private → covered only}, ≤ 12 options a slot with readiness, the tuck and open defaults, gaps |
| `PUT /v1/tryon/assets/{piece}` | A | his template choice for a piece (or "image card only") |
| `POST /v1/tryon/confirm` | A | `{plan, slots}`: the fresh check, then R13's `outfit_plan` (`lock`) through the gateway; 409 with the draft's words |
| `GET/POST/DELETE /v1/tryon/saved[/{id}]` | A | saved comparisons (≤ 10), re-checked on GET |
| `POST /v1/tryon/erase` | A | **console**, passkey: OPS-05; the counts deleted |
| `GET /v1/seeme` | C | on or off and why, provider words, his photo (kept, when, size), consent (given, when, model, region, current), the month (spent, held, cap, pictures), the price a step in ₹, the retire date, pictures (≤ 50: id, when, pieces' words, ₹, kept, until) |
| `POST /v1/seeme/photo` · `GET` · `DELETE` | C | **console** (POST, DELETE); the door's JPEG · his photo for his console · delete (and the consent) |
| `POST /v1/seeme/consent` | C | **console**; `{typed, words_version}`; 422 unless exactly YES and the words are current |
| `GET /v1/seeme/estimate?plan=&pieces=&samples=` | C | steps, ₹, the pieces sent and not sent (with reasons), the cap left, the limit's room |
| `POST /v1/seeme/pictures` | C | **console**; `{pieces, plan?, samples, confirm_cost, inr_shown, request_id}` → the picture's view; 402 `cap_reached` / `budget_reached`, 409 `consent_needed` / `price_changed` / `busy`, 422 `private_piece` / `no_photo` / `not_a_garment`, 502 `filtered` (with the ₹ note), 503 `not_configured` / `retired` / `no_ai` / `provider_unavailable` |
| `GET /v1/seeme/pictures/{id}` · `POST …/{id}/keep` · `DELETE …/{id}` | C | the picture (image/jpeg, `default-src 'none'`, `nosniff`) · keep or not · delete |
| `PUT /v1/seeme/settings` | C | **console**; `{on, cap_inr, samples_default, keep_days}`; a higher cap needs `confirm_cost: true` |

## Tools: none new (every R13 tool is unchanged)

R13.1 adds no model-callable tool, so no permission row (52 stay), no Telegram pattern, no skill-register
group, no persona line. The panel's plan changes still go through `gateway.execute` (D7). The paid path is
an owner-only console route with `confirm_cost`, the pattern R6.2 set for spending (fact 10), so no
e-mail, web page or chat message can start a spend or send his photo (security-reviewer to confirm). The
AI learns where Try-on is from `outfit_suggest`'s `see_it` words (D17).

## Per part: failures, security, cost

| Part | Failure modes and handling | Security and privacy | ₹ a month |
|---|---|---|---|
| A · Try-on data | no key → Try-on is off (never in clear) and says so; an unreadable `tryon/{uid}` is never overwritten; a value out of range refused in words; a look for a plan that isn't there → "That plan isn't there any more"; the fresh check refuses a draft before any tool; R13's store down → the look says so and the checklist stays | measurements sealed, never to the AI, logs or Google; private slots covered in every view; confirm through R13's tools and the gateway; OPS-05 behind the passkey | 0 |
| B · The 3D figure | no WebGL2, an asset 404 or sum mismatch, a lost context, a 10 s first render, a slow device → the checklist (D8); a crop that can't be read → colour only | draws his crops on its own canvas only; no network but the vendored files and the door's `thumb`; nothing stored; private zone never drawn | 0 (≈ 2.5–3.5 MB to each device once) |
| C · See it on me | not configured / no role / API off → 503 in words; Google 429 → "busy, try in a minute" (released); 5xx or timeout → "may be charged" (kept); filtered → its words (kept); his photo missing or unreadable → asks again; the cap or limit unreadable → refused (fail closed); retire date → off | his photo and pictures sealed; consent typed and bound; console-only; private pieces refused from the record; only his photo and garment crops leave, to one named model and region; token, bodies and bytes never logged | ₹5.7 a step, capped at ₹300 |
| D · Console and phone | the engine missing or failing → the checklist; the photo check's models not installed → "The photo check isn't available on this device" (no photo is saved); offline → R13's words | textContent only; the third pixel panel's rules; the door is the only sender; no storage | 0 |

## Cost (₹; no new Scheduler job, no new secret)

| Item | ₹ |
|---|---|
| Firestore: measurements, his photo (≤ 0.9 MB), pictures for 7 days (≈ 10 a week ≈ 5 MB) and ≤ 24 kept (≤ 22 MB), inside the free 1 GiB | 0 |
| R14's daily backups, when he has them on (≈ ₹3.8 per 100 MB a month) | ≤ 1 |
| The figure's files to each phone and laptop, once a release (≈ 2.5–3.5 MB from asia-south1) | < 0.1 once |
| Cloud Run time for a press (≈ 10–60 s, inside the free vCPU-seconds) | 0 |
| **See it on me**: Google's price a step (G4) = ₹5.71 at ₹95.24 a dollar; a top only ₹5.7; top and trousers ₹11.4; with a jacket ₹17.1; 4 samples × each | 0 unless used |
| The cap: ₹300 a month = 52 one-step pictures or 26 two-step pictures | ≤ 300 |
| Tax on Google's invoice, if Google charges GST for his billing account (not verified) | outside the cap |

## The I0 seam list (branch `r13-1-i0`; the integrator owns these files)

1. **Version** `13.1.0` (`__init__.py`; `test_about.py:25`, `test_r14_seams.py:99` and the other pins).
2. **Keyring** +2 → **26** (`tryon`, `tryon_photos`; the six pins of fact 14, the last two purposes now
   `tryon`, `tryon_photos`).
3. **The contract** (`wardrobe/ports.py`, ≤ 400): `PartName` += `tryon`, `seeme`; `TOOL_FAMILIES` both `()`;
   `ROUTE_PREFIX` `tryon` → `/v1/tryon`, `seeme` → `/v1/seeme`; `COLLECTIONS` (the data model);
   `JOB_OWNER`/`R13_JOB_NAMES` += `seeme_daily` (C, daily); `SERVICE_OWNER` += `tryon_looks` (A), `seeme`
   (C); `PhotoVault` gains `get(uid, photo)`; the pins of fact 4 move (`test_r13_seams.py:230–236`,
   `test_r13_wiring.py:307`).
4. **R13.1's own types** (`wardrobe/tryon/`): `model.py` (measurements, ranges, the template table, the
   palette, ids), `http.py` (every route's models), `ports.py` (`TryonData`: count, export, delete, kept;
   the `seeme` service's `erase`), `kept.py` (the stand-ins), stub parts `wardrobe/tryon/part.py` and
   `wardrobe/seeme/part.py` ("not built yet").
5. **The provider port** `llm/tryon.py` (D10) and `tests/r131_fake_tryon.py` (a scripted provider:
   pictures, filtered, each error).
6. **Wiring** `api/r13_wiring.py` (≤ 400): `PART_MODULES` += the two; `_with_kept` gives the two parts their
   stand-in Privacy sources; `install_r13_routes` += `api/tryon.py`, `api/seeme.py` (stubs at I0) and
   `api/tryon_assets.py` (the mannequin route, D3); the provider built lazily (`AdcTokens` only when
   `tryon_pictures` is on). `api/app.py` **0 lines** (R13's wiring carries everything).
7. **Settings** (`config.py`, one line each, ≤ 790): `tryon_enabled` (on), `tryon_pictures` (off; deploy sets
   it), `tryon_month_cap_inr` 300 (0–2,000), `tryon_usd_per_image` 0.06, `tryon_model`
   "virtual-try-on-001", `tryon_location` "asia-southeast1" (one of G2's list), `tryon_model_retires`
   "2027-01-20", `tryon_keep_days` 7 (1–30), `tryon_photo_max_kb` 700 (100–740).
8. **Money** `billing/spend.py` (new, ≤ 100): `ensure_spend_allowed(billing, uid, inr)` (his limit, fail
   closed, BudgetReached's words); `billing/service.py` `LABELS["tryon"] = "Try-on"` (+1).
9. **Console** (each file ≤ 800): `console-helpers-wardrobe.js` (the section and the plan buttons, ≤ 16
   lines; ≤ 306), `console-r7-send.js` (`person`, `picture`, `myPhoto`; ≤ 165, its pin), `console-r7.js` (+
   `console-tryon.css`), `api/console.py` `APP_ASSETS` (+ the new files, stubs at I0), the manifest checker
   generalised (`_VisionFiles(folder)`, R7's tests unchanged), `tests/test_r51_console_assets_linked.py`
   `NOT_IN_PAGE`; `console.html` unchanged (782); the dock stays 22.
10. **The pixel and drawing rules** (`tests/test_r13_seams.py`): `PANELS` += `console-tryon-photo.js` (with
    the scan module's rules and `door.person` only); `DRAWING` += `console-tryon-3d.js`,
    `console-tryon-cloth.js` (their own canvases; a static test that neither calls `JarvisVision`,
    `JarvisCamera`, `getUserMedia` or the door's senders); the door the only caller of `/v1/seeme/photo`
    and `/v1/seeme/pictures`.
11. **The engine contract** `static/console-tryon-3d.js` stub (throws "not built yet", so D's checklist
    path is real from day one) with the API of D2/D7: `window.JarvisTryOn3D = {supported(), mount(host,
    {release, onLost}) → Stage}`, `Stage = {show(figures, opts) → {drawn, approx, cards}, view(name),
    spin(on), zoom(step), closer(), snapshot() → Blob, stats(), dispose()}`; its node contract test
    `tests/fixtures/r13_1/engine_contract.mjs`.
12. **R13 joins:** `outfit_suggest`'s `see_it` words (D17) and their pins; `outfit_plan` `lock` refuses an
    ineligible piece (D7; a test; a fix only if needed); the eight pinned tick-job lists gain `seeme_daily`
    (fact 15).
13. **Deploy** `deploy/cloudrun.sh` (≈ +12): switch on `aiplatform.googleapis.com` (a note when refused),
    `try_bind roles/aiplatform.user` to `jarvis-run`, `JARVIS_TRYON_PICTURES=true` only when both
    worked (like `DRIVE_STATE`); nothing is called and nothing is charged by that.
14. **Guide and book:** C72, C73 PLANNED (every collection and route), the L5 and L8 rows, the edition line,
    the change log; `scripts/arch_coverage.json`; `buildbook/gen/libs.py` (the mannequin's licences);
    `buildbook` `layers.py` (`tryon` → L5, `seeme` → L4).
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
- **C · See it on me** (Opus; AVT-12, OPS-05's half): `llm/tryon_vertex.py`, `wardrobe/seeme/{part,vault,
  consent,cap,estimate,make,pictures,privacy,jobs,texts}.py`, `api/seeme.py`, `tests/test_r131_c_*.py`,
  `tests/r131_fake_vertex.py` (Google's documented answers through `httpx.MockTransport`),
  `evals/r13_1/seeme.py`, INTEGRATION-C.md. `security-reviewer` required (consent, money, his photo, the
  adapter).
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
| `contract` (I0, built) | six parts build through the real wiring and own only their routes, services, collections and job; a broken R13.1 part is "setup failed" while R13's four still run; the Try-on Privacy section exists with stand-ins | the contract check off: a stray route is accepted |
| `looks` (A) | AVT-03 versions and kept selections; AVT-04 views and the kurta; AVT-05 association; AVT-09 fresh check, drafts, no tool call for a draft; AVT-11 saved comparisons re-checked; AVT-14 private slots covered (no id, colour, photo or label in any look, option or caption); OPS-05 erase order and the catalog's `rev` unchanged | the private filter off: AVT-14 fails; the fresh check off: AVT-09's laundry jacket is confirmed |
| `figure` (B; Node and Python) | the manifest's sums, licences and budget; the measure table (15 cases: each measurement within 0.5 cm on its own slider, every cross-effect within 3.5 cm, quantised within 0.2 cm of float); the private zone covered in every layer state × slot set × variant × view; AVT-07 geometry; tucked/untucked and open/closed exist where the table says; triangles ≤ 32,000 a figure; the GLB reader refuses an unknown accessor type | two morphs swapped: the measure table fails; the base shorts dropped in "All": the privacy walk fails; the blazer sleeve lengthened 2 cm: AVT-07 fails |
| `seeme` (C, through the port) | zero provider calls without a current YES; "yes", "Yes", "YES!" refused; the cap: 52 one-step pictures at ₹5.71 fit ₹300, the 53rd is refused; 10 presses at once at ₹5 left → exactly the fitting number pass; released on `TryOnNotBilled`, kept on `TryOnMaybeBilled` and filtered; a private piece and a piece without a front crop refused before any call; No-AI, bearer token, retired date, `price_changed`, `busy`, idempotent `request_id`; the second fake provider passes the same cases | the atomic reserve replaced by read-then-write: the 10-at-once case lets one past the cap; the consent check off: "zero calls without YES" fails; the private check moved to the console only: a private piece reaches the fake provider |
| `console` (D, browser) | each row's UI half, the checklist under `__glFail`, missing WebGL2, a lost context and an asset 404; the YES dialog; the ₹ confirm with Cancel sending nothing; the share PNG's caption; 44 px targets; 360 × 800 and 1280 × 800, day and night; the existing tabs' screenshots unchanged against R13's | the engine stub that throws, with the checklist hook removed: AVT-15 fails |
| `e2e` (I1) | his workbook's end-to-end tests: "Meeting outfit update" (the avatar half: one piece to the laundry, the viewer reopened, the checklist and the figure use the same ids), "Layer and rotate" (shirt, blazer, belt, watch, shoes; open the blazer, swap the shoes, turn to the back; every approximation named), "Private items and photos" (the avatar half: a look with private layers, a shared look, then OPS-05; the catalog usable); plus See it on me's life (photo, YES, estimate, picture, 7 days, gone by `seeme_daily`) | the look built from a stale view: "Meeting outfit update" fails |
| `needles` (I1) | his photo's bytes (raw, base64, hex), a picture's bytes, his measurements (numbers and words), the consent text, a private piece's label and colour, the fake token — searched in every log record, the audit, approvals, activity, session turns, alerts, Telegram, Web Push, every tool result for the AI, every non-sealed document (`tryon_spend` included), the R13 backup file, the Privacy export; the fake provider receives only his photo and the chosen crops; a positive control per sink | the adapter logging its request body: the photo needle is found |

**Browser (Playwright).** Against `tests/r131_fake_server.py` while building, the wired app at I1. The
3D tests run only in a Chromium with WebGL2 (the Book's `_need_3d` rule: skip only for "no-webgl2"); the
fallback tests force `__glFail`. The photo panel uses a drawn full-length figure fixture and the R13 test
hook that can only add refusals; whether a drawn figure fires SSD and UltraFace is checked first (as R13
did), else the panel's decision logic is tested on recorded task outputs and the real check moves to the
pilot.

**Static tests:** `console.html` byte-identical; the pixel and drawing lists (seam 10); the CSS rule for
`console-tryon*.css`; no `$` in owner-facing strings of R13.1's JS and Python texts; no real clock under
`wardrobe/` and `llm/tryon*.py`; the engine imports three only from the vendored URL; no `fetch(` of
anything but `/static/vendor/mannequin/` and the door in B's modules.

## Size guards

`api/app.py` 732 (no edit, ≤ 735), `tools/gateway.py` 760 (no edit), `core/brain.py` 713 (no edit),
`console.html` 782 (no edit), `config.py` ≤ 790 (< 800), `console-helpers.js` 238 (no edit),
`console-helpers-wardrobe.js` ≤ 306, `console-r7-send.js` ≤ 165 (pin moves from 145), every `console*.js`
≤ 800 (the new ones as in the part split), `console-tryon*.css` ≤ 200 in all, every module under
`wardrobe/` ≤ 400, `api/r13_wiring.py` ≤ 400, `api/console.py` ≤ 475, new Python modules ≤ 400,
`static/vendor/mannequin/m1/` ≤ 3.5 MB. `tests/test_r131_seams.py` pins each.

## Risks and known limits

- **Google retires the model soon.** Deprecated since 14 Sep 2026; retired 20 Jan 2027 (legacy page) or
  15 Mar 2027 (current page). JARVIS stops on the earlier date (D18); the port makes the successor a small
  release, with a new YES. Until then the owner gets about 2 months of use.
- **One garment per call.** A top-and-trousers picture costs two steps and is made by putting the trousers
  on the first result, which can drift from his look; the default is the top only (owner question 1).
- **Safety refusals.** Google may refuse a photo or a garment (its filter); a refused step may still be
  charged; the words say so and suggest a better photo.
- **Is a filtered step billed? Is GST added?** Not stated on Google's pages; the cap counts a filtered step
  as billed (the safe side) and the list price without tax.
- **Data leaves India.** No Indian region serves this model; Singapore does (said in the consent). Google
  may log for abuse checks.
- **Likeness and children.** The device check counts people, not ages; Google's `allow_adult` refuses
  children. His photo is his own by his word.
- **Phone GPUs.** WebGL2 is needed; 24–32k triangles a figure, 6 morphs, one 1024 shadow map; render on
  demand; DPR ≤ 1.5; the governor steps down and the checklist takes over. Two figures in compare double
  the load.
- **The laptop's 4 GB graphics card does not matter here:** the figure runs in any WebGL2 browser and the
  paid picture in Google's cloud; only row 386 (later) would need a big GPU.
- **The figure is approximate.** One male base, six measurements, templates not his garments' cuts; every
  shape says "Approximate" and his photos stay visible.
- **Textures from 512 px crops** are coarse; a `detail` view helps; the scale is assumed.
- **Asset licences:** CC0 data and Apache-2.0 indices are clean; the `smplx` topology is never read; the
  repository stays free of anything non-commercial.
- **Pins churn:** 4 version, 6 keyring, 3 contract, 8 tick-list and the door's pins move at I0.
- **2 CPUs here:** targeted tests while building; whole suites queued.
- **Date bombs:** a fixed clock in every test; the retire date and the 7-day keep tested at 23:30 and
  00:30 IST and across 20 Jan 2027.

## Needs the owner (safe defaults; none blocks the build)

1. **What a picture shows:** the top only, about ₹5.7 (default), with "Add the trousers (about ₹5.7
   more)" each time; or always the top and the trousers (about ₹11.4).
2. **Pictures a press:** 1 (default); up to 4, each priced.
3. **How long pictures stay:** 7 days unless you press Keep (default); or 30 days.
4. **Where Google makes the picture:** Singapore, the nearest offered (default); or a US region.
5. **The cap:** ₹300 a month (your decision); lowering is instant, raising asks with the new figure.
6. **Measurements:** in cm (default); inches later.
7. **From the chat:** JARVIS only tells you where the button is; it can't make a paid picture by itself
   (default, so no message or web page can make it spend).
8. **"Save a picture of this look":** fixed words like "Navy shirt", not your own labels, unless you tick
   them (default).
9. **When Google retires the model:** "See it on me" stops on 20 Jan 2027 until you approve the next one
   with a new YES (default).
10. **Tax:** the ₹ shown is Google's price at the day's rate; if Google adds GST on its bill, that is on top
    and not counted in the cap (default); or count 18 % in the cap (then about 44 pictures).
11. **Your trial (after release):** one shirt, trousers, a blazer, a pair of shoes, a belt and a watch, as
    your workbook's "Build and Test" says, compared in two looks; and 3 "See it on me" pictures (about
    ₹17) after your YES (default); or no paid trial.

## Exit check (before the PR)

1. **His workbook's Try-on exit condition:** "Each visual piece resolves to its inventory ID, estimates are
   clear and swaps update the avatar and checklist together", on the pilot set (owner question 11), on his
   phone and laptop; results in `docs/plans/r13-1-integration/I1-NOTES.md`.
2. The 14 named tests and the e2e suite pass; every built part's control fails its suite; `STUBS_PASS`
   flipped.
3. The full browser suite once on the joined branch (queued, never beside another whole suite).
4. **Screenshots** of the Try it on section (figure, compare, checklist, the See it on me card, the YES
   dialog, the ₹ confirm) at 360 × 800 and 1280 × 800, day and night, and the unchanged existing tabs,
   sent to the orchestrator.
5. The clock sweep (as R13: two days after the PR's date 09:00 IST, 20 Dec 2026, 1 Jan 2027 00:30 IST,
   20 Jan 2027, 1 Mar 2027, 29 Feb 2028).
6. `ruff check`, `ruff format --check`, `mypy src` (the baseline), `evals/run_all_mock.py` ALL PASS,
   `scripts/check_doc_versions.py`, `scripts/arch_coverage.py`, the coverage floor (95),
   `python -m jarvis.buildbook.gen --check`, the PR title check.
7. **One live picture only if he says YES** (about ₹5.7): the adapter's real answer shape, latency and the
   billed amount compared in his Google bill; otherwise "not called" is written in I1-NOTES.

## What can't be verified from this workspace

The real Vertex call (the shell can't reach Google; no paid call without his YES): its answer shape in
this project, latency from Singapore, whether a filtered step is billed, the GenerateContent-versus-predict
note on the current model page (its REST sample uses `:predict`; the adapter follows the sample);
`roles/aiplatform.user` being enough in his project; GST on his invoice; the figure's speed and look on his
phone's GPU; WebGL2 in the CI Chromium; SSD and UltraFace on a real full-length photo; how close the figure
looks to him; the watermark's presence (Google's statement only).

## Sources (read 17 Nov 2026)

| # | Source |
|---|---|
| S1 | The owner's wardrobe workbook `AI_Wardrobe_Assistant_Use_Cases.xlsx`: "Use Cases" (rows AVT-01 … AVT-15, OPS-05), "Wardrobe Rules", "Build and Test" (the Try-on build row; end-to-end tests "Meeting outfit update", "Layer and rotate", "Private items and photos") — not in the repository |
| S2 | The owner's decisions of 17 Nov 2026 (≈ 12:50 IST) and the requirements workbook v13.0.7, rows 350–366 and 386 — not in the repository |
| S3 | The proposal "3D maps and try it on for your wardrobe" v1.0 (17 Nov 2026, 09:40 IST), section 2 — not in the repository |
| S4 | Preview v2 (`mannequin-preview-v2/`: `index.html`, `build_assets.py`, `mq_core.py`, `measure-table.txt`) and the earlier `mannequin-preview/index.html` — not in the repository |
| S5 | NAVER Anny, commit `8f35dc2df1c4062fd2fae86734f9705de50c0c2b`: `LICENSE` (Apache-2.0), `src/anny/data/mpfb2/LICENSE.md` (CC0 1.0), README §License — https://github.com/naver/anny |
| G1 | Vertex AI, "Virtual Try-On 001" (legacy page; released 20 Jan 2026, discontinued 20 Jan 2027; inputs, outputs, quota) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/imagen/virtual-try-on-001 |
| G2 | Gemini Enterprise Agent Platform, "Virtual Try-On" (deprecated 14 Sep 2026, retired 15 Mar 2027; 2 images a prompt; locations; updated 13 Nov 2026) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/vto/virtual-try-on-001 |
| G3 | Virtual Try-On API reference (parameters, preview id) — https://cloud-dot-devsite-v2-prod.appspot.com/vertex-ai/generative-ai/docs/model-reference/virtual-try-on-api ; `VirtualTryOnModelInstance` — https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/VirtualTryOnModelInstance |
| G4 | Agent Platform (Vertex AI) generative AI pricing: Imagen "Virtual Try-On … $0.06"; Gemini image models — https://cloud.google.com/vertex-ai/generative-ai/pricing |
| G5 | "Generate Virtual Try-On Images" (REST sample, models, API enablement) — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/generate-virtual-try-on-images |
| G6 | "Gemini Enterprise Agent Platform and zero data retention" (training, caching, abuse logging) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance |
| G7 | Agent Platform access control (`roles/aiplatform.user`, `aiplatform.endpoints.predict`) — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/access-control |
| S6 | R13's plan `docs/plans/r13-wardrobe.md` (v13.0.3) and `docs/plans/r13-integration/I1-NOTES.md`; R6.2's `docs/plans/r6-2-integration/INTEGRATION-A.md` (the atomic hold, `confirm_cost`) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 13:20 IST | R13.1 | First edition, from the code at `3f265cb`: the owner's summary in ₹; the 14 rows with his workbook's own titles and acceptance checks as the named tests, and where his wording goes beyond the approval; code facts with file:line; preview v2 built and measured here (sums, sizes, licences CC0 and Apache-2.0 checked in the anny clone); Google's try-on verified on Google's pages (one garment a call, $0.06 a picture, no Indian region, deprecated 14 Sep 2026 and retiring 20 Jan or 15 Mar 2027); D0–D19; the data model, the HTTP contract, no new tool; the I0 seam list; parts A–D with B on Fable 5.2; suites with controls; size guards; risks; 11 owner questions with defaults; the exit check | 🛠 Mark XXIII |
