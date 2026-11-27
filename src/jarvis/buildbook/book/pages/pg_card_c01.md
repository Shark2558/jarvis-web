---
page: pg_card_c01
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/console.py": "5f89470424a0a10a"
  "src/jarvis/api/static/console-3d-scenes.js": "80d2691e8bb110de"
  "src/jarvis/api/static/console-3d.js": "b590fd5947ccb313"
  "src/jarvis/api/static/console-deck.js": "9068fb0d30f872de"
  "src/jarvis/api/static/console-dock.js": "7172e71a34e29998"
  "src/jarvis/api/static/console-fx.js": "bb9dd7f373411a5f"
  "src/jarvis/api/static/console-helpers.js": "38c9179fa5cd2d23"
  "src/jarvis/api/static/console-text.js": "be5a5239bbffae37"
  "src/jarvis/api/static/console.css": "6a8f96e9bcd21971"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
  "src/jarvis/api/static/console.js": "7f64b41a454a9ea7"
---
## In plain words
The web console is the screen you use JARVIS from, on a laptop or a phone: the chat, the dock of panels, the brain picker and the Night and Day looks. You install nothing: the JARVIS server sends the page, its fonts and its 3D library itself, so nothing is loaded from another website (`src/jarvis/api/console.py`). Whatever the server sends is shown as plain text, never run as part of the page (`src/jarvis/api/static/console.js`).

## Example (made up)
At 7:40 you open JARVIS on your phone. The dock shows Chat, Brief, Approvals and a few more buttons; the rest wait behind More, which lists them in the same order, Calls last. You tap More, choose Things and ask where Rohan left the spare car key. That evening your laptop's 1920-pixel screen shows every button but Calls, each where it always was, so you open Calls from the calls line in Vitals. You switch the look from Night to Day because the room is bright. Your layout and look are still there the next morning.

## How it works
`GET /` answers with the page through `console`, and `_page` adds the one console security policy, no caching, no framing and no referrer. Every script and stylesheet has its own fixed route made by `_asset_endpoint`, so a request can never name a file outside that list (`src/jarvis/api/console.py`). Fonts and the vendored three.js come from `console_font` and `console_vendor`; their release is part of the address, so `_immutable` lets the browser keep them for a year. On start the page asks `GET /console/config` which sign-in to show, which brain is set and whether to warn that a free brain may learn from what you type (`console_config`). `GET /auth/me` answers with the signed-in account, or with status 401, which brings back the sign-in gate (`src/jarvis/api/console.py:me`). `src/jarvis/api/static/console.js` runs the chat, the brain picker, approvals, the activity log and your conversations, and it only ever calls JARVIS's own paths. Under each reply it shows the model, the time and the rupees, or "price unknown" when JARVIS has no price for that model, never ₹0 (`src/jarvis/api/static/console.js`). `src/jarvis/api/static/console-deck.js` builds the floating panels and the dock in a fixed order and keeps your layout in the browser; its This conversation line adds "price unknown" once a reply had no known price. `src/jarvis/api/static/console-dock.js` measures the dock at every width: buttons that don't fit fold into the More sheet, last ones first. Chat, Brief and Approvals never fold for lack of room, though on a mid-size laptop Approvals folds when its name is wider than its button, and More then carries its waiting count (`src/jarvis/api/static/console-dock.js`). Calls never takes another button's place: the others are fitted as if it weren't there, it joins the bar only when none of them folds for lack of room and it still fits, it waits in the More sheet while More shows, and otherwise it opens from Vitals' calls line, a call card in the chat or its own link (`src/jarvis/api/static/console-dock.js`). `src/jarvis/api/static/console-fx.js` draws the Night and Day surfaces, the themes and the motion levels. `src/jarvis/api/static/console-3d.js` fetches three.js only when a 3D scene is on screen and the browser has WebGL2, and it steps down, then retires the scenes of `src/jarvis/api/static/console-3d-scenes.js` when the page runs slowly.

## What it costs
Nothing in rupees: the page, its fonts and its libraries come from JARVIS itself, with no outside service behind them (`src/jarvis/api/console.py`). The console keeps no data of its own on the server; the browser keeps only small conveniences such as your layout and look (`src/jarvis/api/static/console-deck.js`).

## When it fails
A panel whose data can't be fetched shows a plain line such as "Couldn't load approvals." with a Retry button, and the rest of the console keeps working (`src/jarvis/api/static/console.js`). If the browser can't draw 3D, `src/jarvis/api/static/console-3d.js` leaves the flat 2D emblems in place. A browser without pop-up sheets gets every dock button, wrapped onto more rows, and no More; if measuring the dock goes wrong, every button shows again (`src/jarvis/api/static/console-dock.js`). A sign-in that has ended brings back the gate, and a device lock brings up the unlock cover (`src/jarvis/api/static/console.js`). A vision file whose bytes don't match its recorded SHA-256 is never served (`_check_vision`).
