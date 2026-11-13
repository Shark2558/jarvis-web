Version v7.0.2 · 13 Nov 2026, 23:30 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — Part C · Phone link and security (what I1 needs to know)

Written by Part C's builder on branch `r7-c` (from `r7-i0` @ `9d96320`). The plan is
`docs/plans/r7-mobile.md` v7.0.4 (D4, D5, D6, D16 server side, D21, D25, D26); the contract is
`phone-contract.md` and the shared vectors `tests/fixtures/r7/phone_vectors.json`. Part C plugs in
through `phone/part.py` `build(ctx)` and its own route file `api/phone.py`; no wiring file was edited.

## 1. What Part C built

| Deliverable | Where | State |
|---|---|---|
| The link code (D5): 8 Crockford characters, 10 minutes, once, void after 5 wrong tries, stored as an HMAC-SHA-256 under the session-signing secret; shown only after a `phone_link` passkey check bound to its offer `pl_<12 hex>`, or (no passkey in force) a Google sign-in under 5 minutes old | `phone/store.py`, `phone/service.py`, `POST /v1/phone/link-code` | built |
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
| Eval part `phone` (20 cases, 15 controls) | `evals/r7/phone.py` (`BUILT = True`) | built |

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
| `tests/test_r7_c_link.py`, `_door.py`, `_lock.py`, `_static.py`, `_review.py` | 132 passed |
| Guard tests (`test_r7_seams.py`, `test_r7_telegram_hook.py`, `test_r11_1_seams.py`, `test_arch_coverage.py`, `test_telegram_tool_guard.py`) and the existing tests of `buildbook/lock.py` and Privacy | all pass except the two I0 pins in "Needs I1" 1 and 2 |
| Coverage of `jarvis.phone` + `api/phone.py` (coverage.py, Part C's tests) | 93 % |
| `evals/r7/run.py --mock --part phone` | 20/20; each of the 15 controls fails EVERY case it names |
| Browser: `tests/browser/test_r7_c_phone.py`, `test_r7_c_lock.py` (incl. the visual gate at 1440×900 and 390×844, Night and Day, and the dialog-above-the-cover test) | 27 passed |
| Browser: `-k "r7 or ui_audit or dock_fit"` (Part C's two files, I0's sheet, the UI audit, the dock fit) | 182 passed |
| `ruff check` / `ruff format --check` on `src tests evals scripts` | clean |
| `mypy src` | the 9 old errors only (none in Part C's files) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |
| Sizes | `console-r7-phone.js` 248, `console-r7-lock.js` 196, `console-r7-phone.css` 37 (≤ 150), `api/phone.py` 491, `phone/*.py` ≤ 310 each; `app.py` 735 and `console.html` 782 untouched |

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

- **The lock follows the device (security review H1, the Workshop's decision).** The first time a
  session is marked as the app's, a signed `r7_dev` cookie is set (HttpOnly, Secure where the session
  cookie is, SameSite=Lax, path `/`, 400 days; `<owner id>.<HMAC-SHA256>` under the session-signing
  secret, no new secret). Signing out, "Sign out everywhere" and session expiry do not clear it. A
  later session of that owner carrying a valid one is marked as the app's and, with the lock armed,
  starts LOCKED (a mark never starts the idle clock of an armed lock). This includes a plain Chrome tab
  on the same phone (one cookie jar): intended. A forged cookie or another owner's is ignored. **Accepted
  limit: deliberately clearing all of Chrome's site data for the server removes the cookie and escapes
  the lock;** nothing final happens without the passkey anyway. The owner is never locked out: unlock
  stays the passkey made in the app; from any other signed-in device he can switch the lock off (laptop
  passkey) or unlink the phone (a fresh sign-in is enough; the last phone unlinked disarms the lock, and
  it arms again when a passkey is next added from the app).
- *Unverified on a phone:* that `sessionStorage` survives the Google sign-in round trip inside the
  Trusted Web Activity (it does in a Chrome tab), so the app's session is marked after sign-in;
  owner step C12 (a passkey added from the phone) and that the lock then says "On" in Privacy.
- *Unverified:* Android Keystore's real signatures against the door (E's `core` is tested against the
  same vectors in CI; Part C's door verifies every vector here); Chrome's asset-link verifier reading
  `/.well-known/assetlinks.json`.
- **Live checks and security dependencies** (cannot be proven here):
  1. The door's flood limit (60 a minute per client) keys on `client_key`, the last `X-Forwarded-For`
     hop. Check on the deployed service that this is the caller and not a shared Google front-end
     address (else every client shares one bucket and a stranger can starve the real phone).
  2. `--max-instances 1` is a SECURITY dependency: the nonce store, the rate tables and the lock's
     "last seen" table are in process. With two instances a captured request could be replayed on the
     other one inside the skew. Keep it pinned (`deploy/cloudrun.sh`).
  3. A stranger can send wrong link codes (30 a minute in all) and void the owner's live code (five
     wrong tries void it) or use the link budget up for a minute. He can never link a phone or lock
     the owner out of the console or of a linked phone: the owner just makes a new code.
  4. `/phone/v1/hello/` (a trailing slash) must answer a bare refusal, not a redirect: check live.

## 6. Part E's three expectations (Workshop message, 13 Nov 2026)

1. Asset links in the Digital Asset Links form from the app's 64 lower-case hex: built and tested
   (also from upper-case input).
2. The hello's `sos.label`, `sos.contacts[].label`, `sos.contacts[].phone`: built; the data comes
   through the named seam `services["sos_contacts"]` that Part D offers (Needs I1 item 4).
3. Codes of A–Z and 0–9 that the app upper-cases and strips of spaces and hyphens, a 200
   `{"device_id": …}`, `model` "phone": built and tested.

## 7. Review follow-ups (v7.0.2)

Each finding of the three reviews (security, code, python) and what became of it. `S` = 2ba1ba9
(server, tests, eval), `J` = 17a1f3a (console pages and their browser test).

| Finding | Result |
|---|---|
| Security H1 (lock bypassed by signing out and in) | fixed in S: `r7_dev` device cookie, a mark never starts an armed lock's clock, a new session carrying a valid cookie is the app's and starts locked; scenario A and B tests, eval case `device_lock` with three controls |
| Security M1 (door reads up to 10 MB before any check) | fixed in S: `DoorGate.precheck` (header, flood, device, time) runs before the body is read under the cap, then `finish` (nonce, signature, rate); tests count the chunks pulled |
| Security M2 / code M1 (end-all strips the app marks) | fixed in S: `r7_app`, `r7_ss`, `r7_seen` kept across `restamp`; the device cookie is never touched |
| Security L1 / python L6 (wrong tries or the link budget block linking) | declined: it is the plan's literal rule and the fail-safe side; written under "Live checks" in section 5 |
| Security L2 / code L5 (a laptop passkey taken as the app's) | declined: telling whose passkey it is needs the response of the register request (a wiring file). The harm is bounded now: the owner can switch the lock off with that laptop passkey or unlink the phone (both tested), and two passkeys at once still arm nothing |
| Security L3 (in-process nonce store) | kept as the plan says; `--max-instances 1` written as a security dependency (section 5) |
| Security L4 / code L4 (flood limit keyed on the last X-Forwarded-For hop; starves SOS) | declined to change; the check is written as a live check (section 5). Exempting signed requests would let junk from one address still cost a store read each |
| Security L5 / Needs I1 item 9 (`SessionMiddleware` on `/phone/`) | not Part C's file: stays in Needs I1 (item 9); the door sets no cookie of its own |
| Code M2 / python M2 (last-seen write can fail an SOS) | fixed in S: `seen()` in its own try, logs and goes on; `_touched` set only after the write succeeds; test with a failing write on `sos` |
| Code M3 (modal dialogs above the cover) | fixed in J: `showCover` closes every open dialog; the phone dialog's `close` stops its poll; browser test |
| Code L1 / python L7 (`del s`, dead code) | fixed in S; the unlock limit counting both calls of the two-step flow is kept (5 a minute is enough for one retry) |
| Code L2 / python L1 / L7 (`put_phone`, retry closures, asserts) | fixed in S: closures reset at the start of each attempt, explicit errors instead of `assert`, `put_phone` refuses past the cap (kept for the tests and evals) |
| Code L3 (two tabs; a link counted by length) | fixed in J: the dialog sees any NEW phone id. Declined: the second tab voiding the first's code (the plan: one pending code) |
| Code L6 (epoch in a test, `show_locked` vs `device_locked`, test seam) | fixed in S: `T_START` used, `show_locked` outranks `device_locked` tested, the clock seam commented |
| Python M1 (`PasskeyDataUnreadable` on the lock switch) | fixed in S: 503 `passkeys_unreadable`, tested |
| Python M3 (thin controls) | fixed in S: every named case must fail under its control; 11 new controls (skew, link body cap, 3-phone cap, code reuse, wrong tries, off-curve point, unlock binding, per-phone rate, three for the device cookie) |
| Python M4 (missing security tests) | fixed in S: concurrent link (`asyncio.gather`: one code, five phones; the cap under a crowd), raw r and s and high-S signatures, skew boundary, chunked and bad Content-Length, lock-table eviction, a non-owner session through the mark, `PasskeyDataUnreadable` on the lock routes. The two-passkeys-at-once case already existed |
| Python M5 (nonce TTL vs skew) | fixed in S: TTL = 2 x skew + 60 s; test at the largest skew (300 s) |
| Python L2 (link body read before its cap) | fixed in S: `_body` reads through `_capped` |
| Python L3 (`isdigit`) | fixed in S: ASCII digits only |
| Python L4 (`RecursionError`) | fixed in S: a deeply nested body is just refused |
| Python L5 (a store read per unsigned request) | declined: the price of "unlink closes the door at once", a stated choice; the per-client flood limit bounds it |
| Python L7 (clock seam, typing, eviction order) | fixed in S: the lock's and asset links' caches use the injected clock; `_body` is generic. Declined as cosmetic: `alert(kind: Any)` and `_touched` evicting by insertion (3 phones at most) |
| Python L8 (unsalted hash of the link code) | fixed in S: HMAC-SHA-256 under the session-signing secret |

The app-wide 2.1 MB body limit answers 413 (not a bare 401) to a door request whose Content-Length is
larger; it runs before the door and is not Part C's file.


## 8. Needs I1

1. `test_r7_seams.py::test_the_app_starts_with_four_stub_parts_and_their_status_routes` pins
   `door_handlers(app) == {}`; Part C now offers `hello` and `inbox`. Move the pin.
2. `test_r7_seams.py::test_the_r7_runner_passes_with_its_contract_built_and_the_rest_stubs` expects
   `phone:not_built_yet`; Part C's eval is BUILT. Move the pin.
3. Part A's `console-r7-links.js` must leave `source=app` in the address (`console-r7-lock.js` reads
   it at module load; the two load side by side).
4. Part D: offer `services["sos_contacts"]`, an `async (uid) -> {label, contacts: [{label, phone}]}`;
   without it the hello's SOS part is empty (Part E's item 2).
5. `phone-contract.md`: add section 2's answers (link, hello, inbox, bare door failures).
6. The guide: card C62 to built; `phone_devices/{uid}` gains `lock {on, keys}`.
7. Any other console POST sent on a timer or on viewing joins `applock.BACKGROUND_WRITES`.
8. `OWNER-STEPS.md` step C12: the lock turns on by itself once the passkey is added from the app.
9. Optional: keep `/phone/` out of `SessionMiddleware` (it re-sends a cookie a door request brought).
10. The guide: the `r7_dev` cookie (HttpOnly, 400 days, the app lock's device) belongs in the cookie list; "Sign out everywhere" does not clear it.
11. Live checks of section 5 (the flood limit's client address, `--max-instances 1`, the trailing slash).
12. The whole unit and browser suites.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 20:07 IST | R7 | First edition: what Part C built, the answers other parts build against (with the hello's SOS label for Part E), the checks, ten deviations with reasons, the known limits and what could not be verified, Part E's three expectations, and ten points for I1 | 🛠 Mark XVII |
| v7.0.2 | 13 Nov 2026, 23:30 IST | R7 | The three fresh-context reviews fixed: the app lock follows the device (`r7_dev`), a mark never starts an armed lock's clock, the door reads no body before its cheap checks, "last seen" best-effort, "Sign out everywhere" keeps the app marks, the unlock cover closes open dialogs, the nonce store follows the skew, keyed link-code hash, 20 eval cases with 15 controls; section 7 "Review follow-ups" | 🛠 Mark XVII |
