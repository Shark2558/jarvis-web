---
page: pg_card_c72
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r13_1/console.py": "118d00dbda65f49f"
  "evals/r13_1/contract.py": "d5b713abcb6fc781"
  "evals/r13_1/e2e.py": "dfbac05fd1cea26c"
  "evals/r13_1/figure.py": "5f5400127a75285d"
  "evals/r13_1/looks.py": "a53003503cbbb9bb"
  "evals/r13_1/needles.py": "bc334a54931d1ca1"
  "evals/r13_1/run.py": "4388e220c3f52608"
  "evals/r13_1/wired.py": "a1f33f60bef69258"
  "scripts/mannequin/__init__.py": "de67d8d68b9bc346"
  "scripts/mannequin/accessories.py": "d3ef5ec85ce00100"
  "scripts/mannequin/bottoms.py": "46bed7f0d256fd4f"
  "scripts/mannequin/build.py": "d59862be48618096"
  "scripts/mannequin/carry.py": "c2bd876742d942df"
  "scripts/mannequin/core.py": "f59ad7e75f0c1440"
  "scripts/mannequin/feet.py": "5160c21ad643eb23"
  "scripts/mannequin/figure.py": "4b84aa7ddc32ff22"
  "scripts/mannequin/glb.py": "1153e93dd878eba3"
  "scripts/mannequin/measure.py": "17fad12a48495acd"
  "scripts/mannequin/mesh.py": "02908b87f5cce65c"
  "scripts/mannequin/outer.py": "ad0e5ea5fa8ff013"
  "scripts/mannequin/pose.py": "5a9be1ee467b44dd"
  "scripts/mannequin/requirements-dev.txt": "49fbc2d02308aa8f"
  "scripts/mannequin/tops.py": "f9d1b7dab522b3d7"
  "src/jarvis/api/r13_wiring.py": "4228b2005530a17c"
  "src/jarvis/api/static/console-helpers-wardrobe.js": "acd25c1703c9f832"
  "src/jarvis/api/static/console-media.js": "9470b3411b87efe1"
  "src/jarvis/api/static/console-privacy.js": "7184a1fe77763ae0"
  "src/jarvis/api/static/console-r7.js": "914448d515edf369"
  "src/jarvis/api/static/console-tryon-3d.js": "c3c07a9cd8e4edf9"
  "src/jarvis/api/static/console-tryon-card.js": "7735889bded44c4b"
  "src/jarvis/api/static/console-tryon-cloth.js": "7a78ee65b5efce5f"
  "src/jarvis/api/static/console-tryon-form.js": "9d7d2182c13b6481"
  "src/jarvis/api/static/console-tryon-glb.js": "eaa1b775f5fc637d"
  "src/jarvis/api/static/console-tryon-list.js": "d4c5519202b33437"
  "src/jarvis/api/static/console-tryon.css": "b50a3fa6af3f4d51"
  "src/jarvis/api/static/console-tryon.js": "12ee85f81da27e64"
  "src/jarvis/api/static/vendor/mannequin/m1/MANIFEST.json": "476df5b093b1cb5b"
  "src/jarvis/api/tryon.py": "8316b6a14304293f"
  "src/jarvis/api/tryon_assets.py": "d75d02059ff1f16f"
  "src/jarvis/api/wardrobe.py": "dd3ee504e11c74fa"
  "src/jarvis/tools/reply_cards.py": "97b29df16f9aceb2"
  "src/jarvis/wardrobe/styling/actions.py": "4cd977b6364b3f89"
  "src/jarvis/wardrobe/styling/ready.py": "c2364da92205f632"
  "src/jarvis/wardrobe/styling/tryon_card.py": "b05959a7b3ba30a3"
  "src/jarvis/wardrobe/tryon/__init__.py": "2561702bd2ffc8c0"
  "src/jarvis/wardrobe/tryon/assets.py": "7a893e09b68971d8"
  "src/jarvis/wardrobe/tryon/confirm.py": "64f2602554e9c96c"
  "src/jarvis/wardrobe/tryon/erase.py": "9d8a836c1b6f5087"
  "src/jarvis/wardrobe/tryon/http.py": "d6a311e915dc0a38"
  "src/jarvis/wardrobe/tryon/http_figure.py": "51061c5e647762cd"
  "src/jarvis/wardrobe/tryon/http_seeme.py": "79c7276f36e3a4c2"
  "src/jarvis/wardrobe/tryon/kept.py": "6c647438ef60d967"
  "src/jarvis/wardrobe/tryon/looks.py": "e1ab3815f08449b6"
  "src/jarvis/wardrobe/tryon/model.py": "f858f3c4614e2440"
  "src/jarvis/wardrobe/tryon/options.py": "b2b8a9fcc15dd891"
  "src/jarvis/wardrobe/tryon/part.py": "f13bb75c65417960"
  "src/jarvis/wardrobe/tryon/ports.py": "208ae54f78d2bb2f"
  "src/jarvis/wardrobe/tryon/privacy.py": "ccc5d853b063f373"
  "src/jarvis/wardrobe/tryon/saved.py": "bb6fa60dcecf74b6"
  "src/jarvis/wardrobe/tryon/store.py": "645dcb493555bf10"
  "src/jarvis/wardrobe/tryon/versions.py": "d1bf73646eb648c3"
  "tests/fixtures/r13_1/engine_contract.mjs": "ab75228e62d3a38d"
---
## In plain words
"Try it on" shows a plain grey 3D figure shaped from the measurements you type: height, shoulders, chest, waist, hips and inseam. JARVIS dresses it in the outfit it suggests, each piece drawn as a ready-made shape in that piece's own colour, with its real photo beside it, so you can see the look before you put it on (`src/jarvis/api/static/console-tryon-3d.js`). Every shape is marked "Approximate". The figure is drawn on your own phone or laptop, and nothing about it is sent anywhere. When you ask what to wear, the reply opens the figure already dressed in that look (`src/jarvis/wardrobe/styling/tryon_card.py`).

## Example (made up)
Ananya types her height, 163 cm, and her waist, 70 cm, and leaves the rest; the figure fills the others in from her height and marks them "estimated". She asks "what should I wear tomorrow?" and the reply shows the figure in her green kurta, white trousers and tan sandals. She swaps the kurta for a blue one that is still in the laundry; it shows as a draft she can't confirm. She swaps back and presses "Use this look", and the plan is locked in one step.

## How it works
`src/jarvis/wardrobe/tryon/model.py` holds the measurement ranges, fills in any you didn't type from your height, and maps each clothing type to its ready-made shape and colour.
`src/jarvis/wardrobe/tryon/store.py` keeps your measurements sealed in `tryon`, with the current set, one draft and up to {{fact:src/jarvis/wardrobe/tryon/model.py:EARLIER_MAX}} earlier versions, and up to {{fact:src/jarvis/wardrobe/tryon/model.py:SAVED_MAX}} saved comparisons by piece id, never a picture.
`src/jarvis/wardrobe/tryon/looks.py` reads every look fresh from the outfit rules and your wardrobe, so the figure never shows a stale outfit.
When you ask what to wear, `show` puts one `TryOnCard` beside the reply with only piece ids; the AI never reads it, and a private piece is covered.
`src/jarvis/api/static/console-tryon-3d.js` draws the figure on your device with a bundled copy of three.js, from files that `mannequin` serves only when their SHA-256 matches the release's manifest (`src/jarvis/api/tryon_assets.py`).
A swap to a piece that isn't ready stays a draft; `check_and_lock` re-checks every piece on the server and makes one plan call that locks every slot at once, and `fits` is the one readiness rule both the figure and the plan read (`src/jarvis/wardrobe/styling/ready.py`).
Private pieces are never drawn: the figure wears a plain base layer instead (`src/jarvis/wardrobe/styling/tryon_card.py`).
`erase_all` deletes every piece of try-on data in a safe order when you ask in Privacy with your passkey.

## What it costs
Nothing. The figure is drawn by your own device from files JARVIS serves itself, with no outside service and no AI (`src/jarvis/api/tryon_assets.py`).

## When it fails
With no WebGL2, a file that fails its check, a lost graphics context or a device too slow for the first frame, the figure gives way to a checklist with each piece's photo, which still changes or confirms the outfit (`src/jarvis/api/static/console-tryon-3d.js`). A measurement out of range is refused in words (`src/jarvis/wardrobe/tryon/model.py`). Without the token key, Try-on is off rather than storing anything in clear, and a document that won't open is never overwritten (`src/jarvis/wardrobe/tryon/store.py`). A piece that isn't ready is refused by the server's check and again by the plan itself (`check_and_lock`).
