Version v7.0.1 · 13 Nov 2026, 20:07 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — Part C · Phone link and security (what I1 needs to know)

Written by Part C's builder on branch `r7-c` (from `r7-i0` @ `9d96320`). The plan is
`docs/plans/r7-mobile.md` v7.0.4 (D4, D5, D6, D16 server side, D21, D25, D26); the contract is
`phone-contract.md` and the shared vectors `tests/fixtures/r7/phone_vectors.json`. Part C plugs in
through `phone/part.py` `build(ctx)` and its own route file `api/phone.py`; no wiring file was edited.

## 1. What Part C built

| Deliverable | Where | State |
|---|---|---|
| The link code (D5): 8 Crockford characters, 10 minutes, once, void after 5 wrong tries, stored as SHA-256; shown only after a `phone_link` passkey check bound to its offer `pl_<12 hex>`, or (no passkey in force) a Google sign-in under 5 minutes old | `phone/store.py`, `phone/service.py`, `POST /v1/phone/link-code` | built |
| Linking (D5): `POST /phone/link`, exactly the app's keys, the one package `io.github.shark2558.jarvis`, an X9.62 point ON P-256, a 32-byte fingerprint; one transaction (code spent with the save); at most `phone_link_max` (3); `phone_linked` alert (urgent, every channel) and a content-free audit | same | built |
| The door (D6): `/phone/v1/{hello,health,inbox,sos}`, every check in the plan's order, bare 401/404, logged by check name only, never audited; bounded in-process nonce store (10 minutes) and per-phone rate (30 a minute) | `phone/door.py`, `api/phone.py` `phone_door` | built |
| The door's `hello` and `inbox` handlers; inbox → `VaultIntake.intake(source="digilocker")` (D16) | `phone/handlers.py` | built |
| Asset links (D4): linked phones only, one statement, the one package and relation, `public, max-age=60` (read at most once a minute) | `GET /.well-known/assetlinks.json` | built |
| Unlink (the door closes at once; `phone_unlinked`, info) | `POST /v1/phone/{device}/unlink` | built |
| Sign out everywhere (D21): R6's "sessions valid after" mark for the owner; every older cookie ends at once on this instance, within 3 s on another; this browser is stamped again | `buildbook/lock.py` `end_sessions` (the one method), `POST /v1/session/end-all` | built |
| The app lock's check for I0's slot (D21): app sessions only; armed once a passkey was registered from the app; 423 `device_locked` after `app_lock_minutes`; writes with the CSRF header and "I'm here" count, background polls and `/auth/me` never; `device_unlock` bound to the session (`ss_<24>`) | `phone/applock.py`, `/v1/session/{app,here,lock,unlock}` | built |
| The lock's switch in Privacy (on takes nothing; off takes a `device_unlock` check) | `PUT /v1/session/lock`, `console-r7-lock.js` | built |
| Integrations → Phone app (link, the phones and what each may do, unlink, sign out everywhere) | `console-r7-phone.js` | built |
| The unlock cover on `jarvis:device-locked` | `console-r7-lock.js`, `console-r7-phone.css` | built |
| Privacy row "Linked phones" (`PrivacySource` id `phones`: count, export without keys, delete = unlink all) | `phone/privacy.py` | built |
| Eval part `phone` (15 cases, four controls) | `evals/r7/phone.py` (`BUILT = True`) | built |

What the part offers the app (`MobilePart("phone")`): `services["phone"]` (the service its routes
read), `services["door"]` = `{"hello", "inbox"}`, `services["app_lock"]` (the check),
`privacy = (PhonePrivacy,)`, `ready = "ready"` (`"switched off"` with `mobile_enabled` off: then
every phone route answers 404 and the slot passes everything through). No tools.

## 2. The answers other parts build against

These are additions to `phone-contract.md` (a contract file: I1 writes them in; this is the line).

- `POST /phone/link` → 200 `{device_id}`; 403 `{error: bad_code}`; 409 `{error: too_many_phones |
  already_linked}`; 422 `{error: input_rejected | not_this_app | bad_key | bad_fingerprint}`; 413 over
  4 KB; 429 past 10 a minute from one client (30 from all). Every refusal has plain `detail` words.
  A code is 8 characters of the Crockford alphabet (A–Z and 0–9 without I, L, O, U); the server
  reads it upper-cased, without spaces or hyphens, with O read as 0 and I or L as 1.
- `GET /.well-known/assetlinks.json`: the app sends its signing fingerprint at linking as 64 hex
  (lower or upper case, no colons); the asset links give it the Digital Asset Links way, upper-case
  hex pairs joined by `:` (both input cases are tested).
- `POST /phone/v1/hello` → 200 `{v: 1, device_id, settings: {app_lock_minutes, watch_enabled,
  sos_countdown_s, health_every_h: 6, inbox_every_min: 60, inbox_per_run: 3, inbox_max_bytes},
  sos: {enabled, label, contacts: [{label, phone}]}}` (Part E reads `sos.label` and
  `sos.contacts[].label` / `.phone`; at most 5 contacts, labels ≤ 40 characters of plain text, a
  number kept as `+` and digits, a contact with no number left out); 422 when the body is not
  exactly the one JSON form.
- `POST /phone/v1/inbox` → 200 `{status: added | duplicate}` (mark the file seen); 503 `{error:
  vault_off}` or `{status: skipped, code: unavailable | vault_full | busy}` (try again later); 422
  `{status: skipped, code}` or `{error: input_rejected}` (mark seen; do not send it again).
- Door failures are bare (empty body): 401 for every check, 404 for a route that is not one of the
  four (or whose part is not built), 503 when the phone store can't be read.
- The console's first answer of a passkey-guarded step is a **200 that carries the target**,
  because `console.js` `api()` keeps only a refusal's code: `POST /v1/phone/link-code {}` →
  `{needs: "passkey", target: "pl_…"}`; `POST /v1/session/unlock {}` (locked) → `{unlocked: false,
  target: "ss_…"}`; `PUT /v1/session/lock {on: false}` → `{…state, needs: "passkey", target}`. A
  proof that fails is a 403 `passkey_rejected`.

## 3. Checks (this worktree, Python 3.12)

| Check | Result |
|---|---|
| `tests/test_r7_c_link.py`, `_door.py`, `_lock.py`, `_static.py` | 94 passed |
| Guard tests (`test_r7_seams.py`, `test_r7_telegram_hook.py`, `test_r11_1_seams.py`, `test_arch_coverage.py`, `test_telegram_tool_guard.py`) and the existing tests of `buildbook/lock.py` and Privacy | all pass except the two I0 pins in "Needs I1" 1 and 2 |
| Coverage of `jarvis.phone` + `api/phone.py` (coverage.py, Part C's tests) | 93 % |
| `evals/r7/run.py --mock --part phone` | 15/15; each of the four controls fails its cases |
| Browser: `tests/browser/test_r7_c_phone.py`, `test_r7_c_lock.py` (incl. the visual gate at 1440×900 and 390×844, Night and Day) | 26 passed |
| Browser: `-k "r7 or ui_audit or dock_fit"` (Part C's two files, I0's sheet, the UI audit, the dock fit) | 181 passed |
| `ruff check` / `ruff format --check` on `src tests evals scripts` | clean |
| `mypy src` | the 9 old errors only (none in Part C's files) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |
| Sizes | `console-r7-phone.js` 247, `console-r7-lock.js` 190, `console-r7-phone.css` 37 (≤ 150), `api/phone.py` 455, `phone/*.py` ≤ 310 each; `app.py` 735 and `console.html` 782 untouched |

## 4. Deviations from the plan, and why

1. **"A passkey registered from this phone"** is recorded without touching the permissions files
   (not Part C's): the check notes a `POST /v1/passkeys/register` made in an app session and, on that
   session's next request (within 2 minutes), the ONE passkey that appeared; its `passkey_ref` goes
   into `phone_devices/{uid}.lock.keys`. If two appear at once (another device registered one in
   the same moment), neither counts, so the lock can't arm on a laptop-only passkey. Removing that
   passkey disarms the lock.
2. **The app session is marked by the page**, not by the server seeing `GET /?source=app`: Google's
   sign-in returns to `/` (the callback), and `GET /` is on the never-locked list, so the slot never
   asks the check about it; `api/console.py` is not Part C's. `console-r7-lock.js` keeps a
   `sessionStorage` flag when the tab opened at `/?source=app` and, after sign-in, posts
   `/v1/session/app` once. A mark only ever switches the lock ON; no route turns it off.
3. **Switching the lock off takes a `device_unlock` passkey check** (bound to the session) when
   passkeys are in force. The plan says only "a switch in Privacy"; without this, a thief inside the
   5 minutes could switch it off.
4. **Two kinds of write do not count as being here**: `/v1/book/show/beat` and `/v1/brief/seen`
   (`applock.BACKGROUND_WRITES`), which the console sends on a timer or on viewing. Every other write
   with the CSRF header counts, as D21 says.
5. **Extra door checks**: a request carrying a `Cookie` header is a bare 401 (`cookie`: the door reads
   no cookie), and at most 60 requests a minute from one client before any store is read (`flood`),
   so junk headers cannot cost a Firestore read each. `/phone/link` has its own limits (10 a minute
   per client, 30 in all): the app's global limiter covers only `/v1`, `/auth`, `/connect`.
6. **An empty `?`** (`/phone/v1/hello?` with nothing after it) cannot be told apart from no `?` at the
   ASGI level (uvicorn gives an empty query string for both), so it passes the `query` check; any
   character after the `?` is a bare 401. It carries no input, and the signature covers the path.
7. **Where the lock lives**: the app mark, the session id `ss_<24>` and the last activity are in the
   signed session cookie (`r7_app`, `r7_ss`, `r7_seen`), with a bounded in-process table of the last
   activity per session (the later of the two counts, so a slow background answer carrying an older
   cookie can't undo an "I'm here"). The plan does not say where.
8. **Sign out everywhere keeps the pressing browser** (stamped again at the mark, as R6's Resume does)
   and covers that owner's sessions only.
9. **A wrong code counts a try on every live code** (5 void it): the plan's literal rule. R3's home
   link counts per client instead; with an unauthenticated route and a short code, a stranger's
   guesses voiding a code (the owner makes another) is the safer side.
10. `GET /v1/phone` answers more than I0's `{part, ready}`: also `enabled`, `max`, `phones`, `code`.

## 5. Known limits, and what could not be verified here

- **The lock is bound to the session (D21).** Signing out and in again with Google on the phone
  gives a new session with a fresh 5 minutes, and a new sign-in in an ordinary Chrome tab is never
  locked: the server cannot tell the phone's Chrome from the laptop's. Nothing final happens without
  the passkey anyway (the plan's own words). An option for the owner or I1: start a NEW app session
  locked while the lock is armed (one more passkey touch after each daily sign-in).
- *Unverified on a phone:* that `sessionStorage` survives the Google sign-in round trip inside the
  Trusted Web Activity (it does in a Chrome tab), so the app's session is marked after sign-in;
  owner step C12 (a passkey added from the phone) and that the lock then says "On" in Privacy.
- *Unverified:* Android Keystore's real signatures against the door (E's `core` is tested against the
  same vectors in CI; Part C's door verifies every vector here); Chrome's asset-link verifier reading
  `/.well-known/assetlinks.json`; Cloud Run's last `X-Forwarded-For` hop as the client for the flood
  limit.

## 6. Part E's three expectations (Workshop message, 13 Nov 2026)

1. Asset links in the Digital Asset Links form from the app's 64 lower-case hex: built and tested
   (also from upper-case input).
2. The hello's `sos.label`, `sos.contacts[].label`, `sos.contacts[].phone`: built; the data comes
   through the named seam `services["sos_contacts"]` that Part D offers (Needs I1 item 4).
3. Codes of A–Z and 0–9 that the app upper-cases and strips of spaces and hyphens, a 200
   `{"device_id": …}`, `model` "phone": built and tested.

## 7. Needs I1

1. `tests/test_r7_seams.py::test_the_app_starts_with_four_stub_parts_and_their_status_routes` pins
   `wiring.door_handlers(app) == {}` ("no part has built its handlers yet"): with Part C it is
   `{"hello", "inbox"}` (and D's two). Move the pin.
2. `tests/test_r7_seams.py::test_the_r7_runner_passes_with_its_contract_built_and_the_rest_stubs`
   expects `phone:not_built_yet` and `phone` in `parts_not_built`: Part C's eval is BUILT. Move it.
3. Part A's `console-r7-links.js` must leave `source=app` in the address (it drops only `do` and
   `open`), or read it first and hand it on: `console-r7-lock.js` reads it at module load, and the
   two modules load side by side.
4. Part D: for the app's SMS screen, offer `services["sos_contacts"]` on the body part, an
   `async (uid) -> {label: <the owner's name as family sees it>, contacts: [{label, phone}]}` (a bare
   list of contacts is read too). Without it the hello carries `label: ""` and `contacts: []`, and
   the app says no numbers are saved (Part E's Needs I1 item 2).
5. `phone-contract.md`: add the answers of section 2 (link, hello, inbox, the bare door failures);
   Part E's app reads them.
6. The guide: card C62 from PLANNED to built with Part C's facts; its data line gains
   `phone_devices/{uid}.lock {on, keys}` (the switch and the references of passkeys registered from
   the app).
7. If another console module sends a POST on a timer or on viewing, add its path to
   `applock.BACKGROUND_WRITES` (found: `/v1/book/show/beat`, `/v1/brief/seen`).
8. `OWNER-STEPS.md` (Part E's) step C12: say that the lock turns on by itself once the passkey is
   added from the app, and Privacy → This device then reads "On".
9. Starlette's `SessionMiddleware` re-sends a cookie a request brought: the door refuses such a
   request (401 `cookie`), but that 401 still carries the refreshed cookie. Optional: keep `/phone/`
   out of the session middleware.
10. The whole unit suite and the whole browser suite (not run here, by the Workshop's rule).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 20:07 IST | R7 | First edition: what Part C built, the answers other parts build against (with the hello's SOS label for Part E), the checks, ten deviations with reasons, the known limits and what could not be verified, Part E's three expectations, and ten points for I1 | 🛠 Mark XVII |
