Version v7.0.1 · 13 Nov 2026, 19:35 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 Part A — the app on the web side (integration notes for I1)

Part A of `docs/plans/r7-mobile.md` (v7.0.4): deliverables 1 and 3 on the web side, decisions D3,
D8, D9 (web), D10 (the tag), D15, with D0, D12, D21 and D25 where they touch these files. Built on
branch `r7-a` from `r7-i0` @ `9d96320`. Every file below is Part A's own; no wiring file was
edited (one shared file outside the row was, see "Deviations" 1).

## 1. What Part A built

| Piece | Files | What it does |
|---|---|---|
| The part's join and routes | `src/jarvis/api/app_shell.py` (replaces I0's stub) | `build(ctx)` gives `MobilePart("shell")`: no tool, no job, one privacy row, `ready` "ready" (or "off" without `mobile_enabled`). Routes: `GET /manifest.webmanifest` (public, no cookie, no share target without `app_share_enabled`), `GET /static/icons/<name>` (an exact allow-list), `GET /app/share/sw.js` (the share worker, the console's CSP, `Service-Worker-Allowed: /app/share/`), `POST /app/share/in` (only reached when no worker caught the share: the body is never read; the console's gate card says "Open JARVIS once, then share again."), `GET /app/share/in` (303 to `/`), `GET /app/status` (owner-only: `{part, ready, share}`). With `mobile_enabled` off every public route is a 404. |
| The manifest | `src/jarvis/api/static/manifest.webmanifest` | `id` `/`, name and short name "JARVIS", `start_url` `/?source=app`, `scope` `/`, `standalone`, `#04070D` both colours, icons 192, 512 and a maskable 512, the shortcuts Talk (`/?source=app&do=talk`), Camera (`do=look`), SOS (`do=sos`) with 96 px icons, and `share_target` (POST multipart to `/app/share/in`: `title`, `text`, `url`, `files` accepting JPEG, PNG, WebP, PDF). Chromium itself reads it with no error and reports no installability error (DevTools, in the browser test). |
| The icons | `src/jarvis/api/static/icons/*.png` (six), `scripts/app_icons.py` | The console's own core ring (`console-fx.js coreSVG`, the large size) in the Workshop accents on the Night background, plus mic, camera and warning glyphs for the shortcuts, drawn from distance fields with the standard library only; byte-identical on every run (`--check`). No third-party artwork, no brand logo. The maskable icon keeps inside the 40 % safe circle. |
| Launch words | `src/jarvis/api/static/console-r7-links.js` | Reads `?do=talk\|look\|sos\|shared` and `?open=<panel>` (the dock's 22 panels) from frozen allow-lists, each key at most once; `do` wins over `open`; both keys leave the address at once (`history.replaceState`), every other word stays (`source=app`, `reauth`). `do=talk` opens the Conversation panel, focuses `#micBtn` and shows "Tap to talk" through `JarvisVoiceLoop.say`; it never calls press, click, unlock or anything that opens a microphone. `do=look` opens the Camera panel; `do=sos` calls `JarvisMobile.parts.sos.open({via: 'launch'})`; `do=shared` calls `parts.share.open()`. Signed out, the launch waits in this tab's sessionStorage (10 minutes, so it survives Google's sign-in round trip) and runs after `jarvis:ready`. It also takes `{type: 'launch', open, do}` from the BroadcastChannel `jarvis-launch` (same allow-lists; a window not on screen keeps it 15 s). It never asks the server anything. |
| The share worker | `src/jarvis/api/static/app-share-sw.js` | Scope `/app/share/` (holds no page, so it controls no page). Takes the one POST to `/app/share/in`, keeps at most 5 items of at most 10 MB (JPEG, PNG, WebP, PDF, or one line of text up to 2,000 characters) in Cache Storage `jarvis-share-v1` for 24 hours, refuses the rest in plain words (a notice the tray shows once), answers 303 to `/?do=shared`. No fetch, no message, no upload. |
| The share tray | `src/jarvis/api/static/console-r7-share.js`, `.css` (24 lines, placement only) | The console's own bottom sheet with Integrations cards. Per photo: Look at it here, Ask the AI about it (about ₹0.30) (only when the brain answering sees pictures; otherwise a disabled line "The brain answering now can't see pictures."), Add to my vault, Attach to my message, Discard. Per PDF: vault, attach, discard. Per text: Put it in my message, Discard. Ask, Vault and Attach go only through I0's door `JarvisMobile.parts.send` (`ask`, `vault`, `attach`, `canAsk`, `line`); the sheet shows the door's "Pictures sent from this device today" line. Signed out it asks nothing and keeps every item; after `jarvis:ready` it asks `GET /app/status`, registers (or, with sharing off, unregisters) its worker, and opens by itself when items are waiting. |
| Alerts that open their panel | `src/jarvis/webpush/service.py` (`payload_for` and its `TARGETS` only), `src/jarvis/api/static/console-sw.js` | Every alert kind's payload `url` is `/?open=<panel>` (home kinds `home`; approvals and study check-ins `approvals`; helpers, nudges and `watch_stale` `helpers`; the brief, vault, vitals, book and faces their own; Offline, systems check, phone and SOS kinds `integrations`); `test` and an unknown kind `/`. The worker keeps a target only if it is `/`, `/?open=<word>` or `/?do=<launch word>`, sets `tag` to the kind (sanitised; `alert` otherwise), offers a "Talk" action (`/?do=talk`), and on a tap focuses the JARVIS console window already open (this origin, path `/`, the focused one first, never the show's page) and hands it the target over `BroadcastChannel('jarvis-launch')`; with none open it opens one at the target. No navigate call, no fetch handler. 62 lines. |
| The eval | `evals/r7/shell.py` (BUILT) | 8 cases (manifest, csp, launch_words, talk, share_worker, share_unread, share_door, push). The control applies the plan's four mutations each on its own (the allow-list off, the worker uploading at once, do=talk clicking the mic, `navigate()` put back); each fails exactly its case. |
| The privacy row | in `app_shell.py` (`ShareTrayPrivacy`) | Section "Phone app", "Shared items waiting on your phone": no count, nothing deletable from the server, 24 hours, "Your phone's browser only". |

## 2. How it plugs in

- **I0's contract**: only `build(ctx) -> MobilePart` and `app_shell.router` (included by
  `install_r7_routes`). `check_part("shell", ...)` holds. `SHARE_IN_PATH` equals
  `r7_wiring.SHARE_IN_PATH`, whose 50 MB body cap (I0) applies before the route.
- **D21 never-locked list**: every public route here is on it (`/manifest.webmanifest`,
  `/static/icons/*` under `/static/`, `/app/share/*`); `/app/status` is locked like any owner route.
- **The one picture door** (`console-r7-send.js`): the tray uses `canAsk`, `ask`, `vault`,
  `attach`, `line` and nothing else; it builds no Ask, Vault, Attach or counter (a static test and
  the eval's `share_door` hold it).
- **Part B**: "Look at it here" calls `JarvisMobile.parts.panel.look(file)` (a `File` held in memory)
  after opening the Camera panel. Until B exposes it the tray says "The Camera screen can't look at
  a shared picture yet." and keeps the item. `do=look` only opens the panel.
- **Part D**: `do=sos` (and the SOS shortcut) calls `JarvisMobile.parts.sos.open({via: 'launch'})`,
  waiting up to 5 s for D's module to publish it.
- **Part E** (phone-contract.md sections 5–7): the four words are the contract's; the manifest's
  shortcuts open `/?source=app&do=<word>`; the share target is `/app/share/in` with fields `title`,
  `text`, `url`, `files`; the notification tag is the alert kind, `alert` when the kind is not a
  plain lowercase word.
- **Part C**: `source=app` stays in the address after the launch reader runs (C reads it on the
  server); the share tray's privacy row sits in the section "Phone app".

## 3. Checks (13 Nov 2026, this worktree)

| Check | Result |
|---|---|
| Part A unit tests `tests/test_r7_a_*.py` | 92 passed (shell 23, push 48, static 11, icons 10) |
| `tests/test_webpush_service.py`, `test_webpush_ece.py` | passed (the payload pins moved to `/?open=…`) |
| Related unit tests (console assets, assets linked, R2/R3/R5 seams, console integrations, media console, wake-word assets) | 928 passed together with the above |
| Guard set (`test_r7_seams`, `test_r7_telegram_hook`, `test_r11_1_seams`, `test_arch_coverage`, `test_telegram_tool_guard`) | 229 passed, 1 failed by design: Needs I1 item 1 |
| Coverage (`coverage` in a private folder, not the shared venv) | `api/app_shell.py` 100 %, `webpush/service.py` 93 % (the misses are R3 lines) |
| `evals/r7/run.py --mock --part shell` | 8/8; the control fails each targeted case on its own |
| `evals/r7/run.py --mock` (all parts) | 22/22; control failed the suite |
| Browser: `test_r7_a_share.py` 16, `test_r7_a_links.py` 24, `test_r7_a_manifest.py` 2, `test_alerts.py` 12 | all passed |
| Browser: `-k "r7 or ui_audit or dock_fit"` | 194 passed |
| Browser controls, run by hand and reverted | the worker uploading at once fails 2 share tests; do=talk clicking the mic fails the talk test; the allow-list off fails the `constructor` and `__proto__` cases; `navigate()` put back fails both hand-over tests |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean |
| `mypy src` | the 9 old errors only; `scripts/app_icons.py` and `evals/r7/shell.py` clean |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |
| `python scripts/app_icons.py --check` | the six icons are the script's output |

## 4. Deviations from the plan (and why)

1. **`pyproject.toml` gained two package-data globs** (`static/*.webmanifest`,
   `static/icons/*.png`). The image installs with `pip install .`, so without them the manifest and
   icons would 404 in production. The file is not on the never-edit list and no lint, format or
   type setting was touched; a Part A test (`test_the_manifest_and_icons_ship_in_the_image`) holds it.
2. **Icons are served at `/static/icons/<name>`**, not under the shell's declared `/app` prefix:
   `/static/` is on D21's never-locked list, so a locked app can still install and update.
   `ROUTE_PREFIX` is not enforced by any test.
3. **The missed-share page is a 200 HTML page** (the console's own gate card, no script, the
   console's CSP), not a redirect: the server has to say the words itself.
4. **Text and PDF items get fewer buttons**: a PDF has no Ask (the door's `ask` is the picture path
   and is refused for a brain that can't see); text gets "Put it in my message" (into the composer,
   nothing sent until Send) instead of Ask, Vault and Attach. Ask sends the fixed question "What can
   you tell me about this picture?".
5. **The tray opens by itself after sign-in when items are waiting**, not only on `do=shared`:
   Google's sign-in round trip drops the address's words, and the items must not wait unseen.
   Launch words read while signed out wait in sessionStorage for 10 minutes for the same reason.
6. **`do` wins over `open`**, and a key given twice is ignored (one screen per launch).
7. **Every alert offers "Talk"** (D9 names the action, not which alerts carry it).
8. **`/app/status` answers `share`** beside `part` and `ready`, so the tray knows whether to
   register or remove its worker.
9. **`webpush/service.py` lost `HOME_KINDS_PREFIX`**, which only `payload_for` used.
10. The console's push worker sanitises the kind it puts in the tag (lowercase letters, digits and
    `_`, up to 40), `alert` otherwise; phone-contract.md section 6 already sends an unreadable tag
    to the Alerts channel.

## 5. Needs I1

1. `tests/test_r7_seams.py::test_the_r7_runner_passes_with_its_contract_built_and_the_rest_stubs`
   pins `shell:not_built_yet` and `shell` in `parts_not_built`. Part A's eval is built, so the test
   is red on this branch by design (I may not edit it). After the merge it should expect the `shell:`
   cases, `failed_cases["shell"]`, and `shell` out of `parts_not_built` (as for each built part).
2. `pyproject.toml` package-data: keep Part A's two globs when Part B adds its
   `static/vendor/vision/**` ones (adjacent lines, likely a textual conflict).
3. Part B: expose `JarvisMobile.parts.panel.look(file)` for the tray's "Look at it here" (on the
   device only), and keep `tests/browser/test_r7_a_links.py::test_do_look_opens_the_camera_panel_with_the_camera_off`
   green once the real panel is in (the spy counts every `getUserMedia` call: it must stay 0).
4. Part D: expose `JarvisMobile.parts.sos.open(opts)` (the launch reader calls it with
   `{via: 'launch'}`); `test_do_sos_asks_the_sos_part_to_open_its_sheet_and_nothing_else` uses a
   stand-in because D's module is a stub here: re-run it with D's sheet.
5. Part E: the app's own share-target JSON and shortcuts should equal the manifest's (`/app/share/in`,
   `title`/`text`/`url`/`files`; `/?source=app&do=talk|look|sos`); the `DelegationService` reads the
   tag as the kind and should keep the notification's "Talk" action (`/?do=talk`).
6. phone-contract.md section 6 (a contract file, so only through I1): add "each notification carries
   one action, `talk`, whose tap opens `/?do=talk`" and "an unreadable kind is tagged `alert`".
7. The guide's card C62 ("Phone app and the phone's door"): name `scripts/app_icons.py`,
   `static/app-share-sw.js`, the routes `/static/icons/<name>`, `/app/share/sw.js`, `/app/share/in`,
   and the browser-only store (Cache Storage `jarvis-share-v1`, 24 hours) under "Data it keeps".
8. The whole unit and browser suites: Part A ran only its own files, the related tests and the
   `r7 or ui_audit or dock_fit` subset.

## 6. Not verified here

- A real Android share sheet into the installed app (Trusted Web Activity or Chrome's WebAPK), the
  long-press shortcuts and the WebAPK minting itself: no Android device. Chromium's own manifest
  parser and installability check pass (desktop Chromium, headless).
- A real notification tap: Playwright cannot click a system notification; the worker's handlers
  run in the page with a stand-in `self` and the real BroadcastChannel, and a real console window
  opens the panel it is handed.
- Whether Chrome on Android passes a notification's actions through to the app's
  `DelegationService` (Part E's side).
- Google sign-in with a launch word kept across the round trip: the browser tests run in token mode
  (sessionStorage carries the word the same way; the Google redirect itself was not run).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 19:35 IST | R7 | First edition: what Part A built (the manifest and icons, the share routes, worker and tray, the launch reader, real push targets and the hand-over to an open window, the eval), how it plugs into I0 and Parts B–E, the checks, ten deviations, eight needs for I1 and what could not be verified here | 🛠 Mark XVII |
