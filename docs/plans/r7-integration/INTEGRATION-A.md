Version v7.0.2 · 13 Nov 2026, 20:50 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

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
| Part A unit tests `tests/test_r7_a_*.py` | 95 passed (v7.0.2 added four: reload route off, deep copy, read-only table, help line; 163 with the webpush tests) |
| `tests/test_webpush_service.py`, `test_webpush_ece.py` | passed (the payload pins moved to `/?open=…`) |
| Related unit tests (console assets, assets linked, R2/R3/R5 seams, console integrations, media console, wake-word assets) | 928 passed together with the above |
| Guard set (`test_r7_seams`, `test_r7_telegram_hook`, `test_r11_1_seams`, `test_arch_coverage`, `test_telegram_tool_guard`) | 229 passed, 1 failed by design: Needs I1 item 1 |
| Coverage (`coverage` in a private folder, not the shared venv) | `api/app_shell.py` 100 %, `webpush/service.py` 93 % (the misses are R3 lines) |
| `evals/r7/run.py --mock --part shell` | 8/8; the control fails each targeted case on its own |
| `evals/r7/run.py --mock` (all parts) | 22/22; control failed the suite |
| Browser: `test_r7_a_share.py` 16, `test_r7_a_share_review.py` 25, `test_r7_a_links.py` 24, `test_r7_a_manifest.py` 2, `test_alerts.py` 12 | all passed (v7.0.2) |
| Browser: Part A's files, `test_alerts.py`, `test_ui_audit.py`, `test_dock_fit.py` (v7.0.2) | 232 run: 229 passed, 3 failed (2 were new tests' own races, 1 the CSP-eval poll above, all fixed); re-run of the review and links files: 49 passed |
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
5. **The tray opens by itself after sign-in for something new**, not only on `do=shared`: Google's
   sign-in round trip drops the address's words, and a fresh share must not wait unseen. (v7.0.2:
   only for an item or a refusal notice newer than the last time the tray was shown, and never over
   a launch; see the review follow-ups.) Launch words read while signed out wait in sessionStorage
   for 10 minutes for the same reason.
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
8. LIVE CHECK (v7.0.2): a real Android share still lands in the tray. The origin rule accepts
   `Sec-Fetch-Site: none` (and a missing header), which is what a browser-initiated launch from
   the share sheet should send; this could not be checked without a device. If a real share is
   refused with "That did not come from your phone's share sheet", the TWA/WebAPK launch sends
   `same-site` or an Origin: loosen `foreign()` in `app-share-sw.js` for that one case only.
9. The whole unit and browser suites: Part A ran only its own files, the related tests and the
   `r7 or ui_audit or dock_fit` subset.

## 5a. Review follow-ups (v7.0.2)

Three fresh-context reviews of `ec370a2` (security WARN, code APPROVE, python APPROVE). Each fix was
test-first (`tests/browser/test_r7_a_share_review.py`, 25 tests, 20 of them red on the old JS), in
commit `d712869` (worker, tray, eval note, browser tests) or `3621bdb` (Python side).

| Finding | Outcome |
|---|---|
| Security MEDIUM-1 (cross-site posts to `/app/share/in`) | Fixed in d712869. The worker refuses (nothing stored, the plain-words notice "That did not come from your phone's share sheet, so JARVIS kept nothing.", 303 to `/`) when `Sec-Fetch-Site` is `cross-site` or `same-site`, or `Origin` is present and is neither this origin nor `null`; `none`, `same-origin` and no header pass. Browser tests: a form on a second site (`evil.example`) plants nothing; the header table; the same-origin console post still lands. |
| Security LOW-1 (24 h lazy, sign-out) | Fixed in d712869. The sweep runs on every tray read, when the console loads (signed out too: a local cache job, asks no server) and when a new worker activates; the Sign out button clears the tray and the "last shown" mark. |
| Security LOW-2 (unbounded body) | Fixed in d712869. Over 60 MB by `Content-Length` is refused before `formData()`; with no length the body is counted from a clone and stopped at the cap; at most 10 files are looked at ("Too many files at once" for the rest). |
| Security LOW-3 (type is a claim) | Fixed in d712869. The first bytes must match JPEG, PNG, WebP or PDF; otherwise "The file is not what its name says it is." (GIF is not allowed, so not sniffed.) |
| Security LOW-4 (eval controls are greps) | Fixed in d712869 in the way the reviewer suggested: a header note in `evals/r7/shell.py` calling those cases tripwires, plus the behavioural cross-site browser test. The eval also pins `foreign(req)`, `MAX_BODY` and `SNIFF`. The "share worker uploads at once" control now targets the worker's origin-check line; each control still fails exactly its own case. |
| Code M1 (Cache Storage errors) | Fixed in d712869. Every Cache Storage call is in try/catch; a failed put is "No room left on this phone for that item, Sir."; a failed `caches.open` refuses everything the same way; the answer is always the notice (when it can be put) and the redirect. Tests stub a full put and a broken `caches.open`. |
| Code M2 (tray auto-opens on every load) | Fixed in d712869. It opens by itself only for `do=shared` (through the launch reader) or when the worker left a notice, or an item newer than the "last shown" mark (localStorage, this browser) exists, and never when the address asked for any screen (`links.asked()`). Tests: an old item with `?do=talk` keeps the mic button focused and no modal; an old item on a plain load stays closed; a new item opens it once and not again. |
| Code L1 (second `show()` wipes the note) | Fixed in d712869 (the note is left alone when the sheet is open and nothing was refused). |
| Code L2 (two windows, double Ask) | Fixed in d712869 with a Web Lock per item (`jarvis-share-<id>`, `ifAvailable`): the second window's press says "Another window is already on that item." and sends nothing. Where Web Locks are missing the press runs as before. |
| Code L3 (`look()` closes first) | Fixed in d712869: the sheet comes back with the reason if `panel.look` fails. |
| Code L4 (two shares at once pass the cap) | Partly fixed in d712869: the held count is taken again before each put. Declined: a true cross-share lock, because a worker would need Web Locks across two simultaneous share-sheet launches, which one phone cannot produce; the worst case is a sixth item for 24 h. |
| Code L5 (dead `SHARE_EXTENSIONS`, wrong test comment) | Fixed in 3621bdb. |
| Code L6 (raw error text in the tray) | Fixed in d712869: only a plain `Error` (ours or the picture door's own words) is shown; a `TypeError` such as "Failed to fetch" gets "It wasn't sent. Try again in a moment." |
| Python LOW-1 (`GET /app/share/in` ignores `mobile_enabled`) | Fixed in 3621bdb (404 when off, in the test). |
| Python LOW-2 (manifest shallow copy) | Fixed in 3621bdb (`deepcopy`, with a test). |
| Python LOW-3 (`TARGETS` mutable) | Fixed in 3621bdb (`MappingProxyType`, with a test; it had also exposed that the mutation test polluted the next one). |
| Python LOW-4 (icon script help line) | Fixed in 3621bdb (`splitlines()[0]`, with a test of `--help`). |
| Python LOW-5 (mypy on `Settings(_env_file=None)`, redundant f-string) | Fixed in d712869 (`# type: ignore[call-arg]`, f-string removed). |
| Security informational (label the tray "Shared from another app or site") | Declined: it would change the tray's words and look; the lead line stays. The tray no longer opens over a launch and a foreign post is refused, which removes the scenario. |

Also: `test_do_sos_asks_the_sos_part_to_open_its_sheet_and_nothing_else` used `wait_for_function`,
which the console's CSP can refuse (it evaluates a string) when the first check finds the condition
false; it now polls with `evaluate` (flaky under load, found in the full run).

## 6. Not verified here

- A real Android share sheet into the installed app (Trusted Web Activity or Chrome's WebAPK; and which `Sec-Fetch-Site` it sends, Needs I1 item 8), the
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
| v7.0.2 | 13 Nov 2026, 20:50 IST | R7 | Review follow-ups: foreign posts refused, body cap, byte sniff, Cache Storage errors, the tray opens only for something new, 24 h sweep and sign-out clear, Web Lock per item, the Python lows; one new live check (a real Android share) | 🛠 Mark XVII |
