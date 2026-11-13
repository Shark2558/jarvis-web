Version v7.0.1 · 13 Nov 2026, 16:05 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVI

# R7 — the phone contract (server ⇄ app)

What the server (Parts A, C, D) and the Android app (Part E) must agree on, byte for byte. The code
side is `src/jarvis/mobile/contract.py` and `src/jarvis/mobile/ports.py`; the shared vectors are
`tests/fixtures/r7/phone_vectors.json` (a public key, exact strings, good and bad signatures; the
private keys that made them were never written down). Part E's `core` tests read the same file.
This is a contract file: it changes only with a line in the INTEGRATION file of the part that needs
the change, and in I1's notes.

## 1. The package and the signing key

- The one package the server accepts: `io.github.shark2558.jarvis` (D5, owner question 15).
- The signing fingerprint is the SHA-256 of the app's signing certificate, exactly 32 bytes (hex
  in the link request). The laptop's debug key signs `personal`; CI's debug key is a throwaway.

## 2. Linking (D5)

`POST /phone/link` with the JSON body `{"v":1,"code":"<8 characters>","public_key":"<hex of the
X9.62 uncompressed P-256 point, 65 bytes>","package":"io.github.shark2558.jarvis",
"fingerprint":"<64 hex>","model":"phone","app_version":"7.0.0"}` (no header, no cookie). The answer
is `{"device_id":"ph_<12 hex>"}` or a plain refusal. The key pair is made inside Android Keystore
and its private half never leaves it.

## 3. A signed request (D6)

```
X-Jarvis-Phone: v1;d=<device id>;t=<unix seconds>;n=<32 hex: 16 random bytes>;s=<signature>
```

- The signature: ECDSA P-256 with SHA-256 (Android Keystore's `SHA256withECDSA`), DER-encoded,
  written base64url without padding.
- Over these exact ASCII bytes, joined by `\n`:
  `jarvis-phone-v1`, the device id, `t` in decimal, `n` as in the header, the method (`POST`),
  the path, and the lowercase hex SHA-256 of the body's exact bytes.
- The path is exactly one of `/phone/v1/hello`, `/phone/v1/health`, `/phone/v1/inbox`,
  `/phone/v1/sos`. **No query string, ever**: the signature covers only the path, so a request
  whose address carries a `?` is a bare 401.
- The server checks, in this order, before parsing anything: the route (else 404) → no query
  (401) → the body cap (`DOOR_CAPS`: hello 16 KB, health 256 KB, inbox 10 MB + 64 KB, sos 16 KB) →
  the header's shape → the device is linked → `|now − t| ≤ phone_clock_skew_s` (120) → the nonce
  unseen for 10 minutes → the signature → 30 requests a minute per phone. Every failure is a bare
  401 (or 404 for an unknown route), logged by the check's name, never audited.
- The door never sets or reads a cookie and reaches no `/v1` route.

## 4. Payloads: one JSON form

Every JSON body is written in ONE form, so the signed bytes are the same on both sides
(`contract.canonical_json`; the app's tiny writer in `core` equals it):

- keys in the order given below, no spaces, UTF-8, no byte-order mark;
- strings: `"` → `\"`, `\` → `\\`, `\b \f \n \r \t` as those escapes, any other character below
  U+0020 as `\u00XX` (lowercase hex), every other character as itself (UTF-8; `/` is not escaped);
- numbers are integers only (a coordinate is an integer of micro-degrees: `lat_e6`, `lon_e6`);
  `true`, `false`, `null` as JSON writes them.

| Route | Body (key order as written) | Owner |
|---|---|---|
| `hello` | `{"v":1,"app_version","version_code","model","android","can":{"notifications","health_read","health_background","location","folder","tile"}}`; the reply carries the app's settings and, for the SMS screen, the SOS contacts' labels and numbers | C |
| `health` | `{"v":1,"days":[{"date","steps":{"count","writer"}\|null,"heart":{"min","avg","max","writer"}\|null,"sleep":[{"start","end","writer","stages":{"awake","light","deep","rem"}\|null}]}]}`: at most 35 days; `writer` is the writing app's package name; steps and heart rate come from Health Connect's `aggregate`; sleep holds ONE writer per night (the watch before the phone) | D |
| `inbox` | the first line is `{"v":1,"name","mime","sha256","bytes"}` in this form, then one `\n`, then the file's bytes (PDF, JPEG or PNG, at most 10 MB) | C |
| `sos` | `{"v":1,"kind":"real"\|"test"\|"safe","at","location":{"lat_e6","lon_e6","accuracy_m","age_s"}\|null}`: coordinates only in this body, never in an address | D |

The vectors hold one case per route plus `sos_no_location`, and the bad cases `changed_body`,
`other_key`, `changed_path` (all fail the signature) and `stale_time_shape` (a good signature whose
time is past the skew: the door refuses it on time).

## 5. Launch words (D8)

The app's tile and shortcuts (and only its second, non-exported launcher) open
`/?source=app&do=<word>` with one of exactly four words: `do=talk` (the mic button ready: "Tap to
talk"; it never starts the microphone), `do=look` (the Camera panel; the camera never starts without
a tap), `do=sos` (the SOS sheet; it still needs the hold), `do=shared` (the share tray). `open=<panel>`
opens a panel from an allow-list. The exported launcher (the icon) always opens `/?source=app` and
ignores any address an intent carries. The server drops `do` and `open` when the visit is marked
`Sec-Fetch-Site: cross-site` (and keeps every other word, such as Google's `reauth`).

## 6. Notifications (D10)

The push service worker sets each notification's `tag: kind` (the alert's kind, e.g. `sos_sent`).
The app's notification service reads that tag and picks a channel: **Urgent** for `home_intruder`,
`home_hazard`, `disaster_alert`, `sos_sent`, `phone_linked`; **Nudges** for every `nudge_*` kind;
**Alerts** for everything else and for a tag it cannot read. The click opens `/?open=<panel>` in the
JARVIS window that is already open.

## 7. Share target (D15)

The web manifest's `share_target` and the app's own share entry post `multipart/form-data` to
`/app/share/in` (fields `title`, `text`, `url`, `files`: JPEG, PNG, WebP, PDF; at most 5 items of
at most 10 MB). The share worker (scope `/app/share/` only) keeps them in the browser and answers
303 to `/?do=shared`; nothing reaches the server before a press.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 16:05 IST | R7 | First edition, written at I0 with the shared vectors: the package and key, linking, the signed request and its checks in order, the one JSON form and each route's body, the launch words, the notification tag and channels, the share target | 🛠 Mark XVI |
