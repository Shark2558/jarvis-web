Version v7.0.1 · 12 Nov 2026, 07:28 IST · Release R7 · Status: Draft · Owner: 🛠 Mark XV

# Release R7 — Mobile, watch & phone camera (`v7.0.0`)

**Phase:** 6 (mobile app and wearable), reusing Phase 1 (voice) and laying Phase 5 groundwork (vision); Phase 7
evals. **Type:** free: ₹0 a month, no new paid service, no new secret, no new Cloud Scheduler job, no Firebase.
**Branches:** I0 `r7-i0` (from `r11-1-i0` @ `9250be1`; Gate G0) → parts `r7-a` … `r7-e` → integration `r7-i1` →
one PR `v7.0.0 · R7 Mobile, watch & phone camera · Mark XV`. Every commit carries `JARVIS-Version: v7.0.0` and
`JARVIS-Mark: XV`. Read on `r11-1-i0` @ `9250be1`. This document is the plan only; it writes no application code.

## Goal (plain words)

JARVIS gets a place on your phone. An app icon opens the same JARVIS you already use, full screen, with the look
you approved. You can start talking from a tile in the pull-down shade, alerts arrive while the app is closed,
and you can share a photo or a document into JARVIS from any app. Its camera screen looks at a photo, or at the
live picture, **on the phone itself**: a picture leaves the phone only when you press a button that says so.
Your watch's steps, heart rate and sleep come in through Health Connect, and the morning brief says how you
slept. An SOS button tells your family where you are. And the camera work is built so that the next releases
(fitness coach, kitchen, care) plug into it without being rebuilt.

Three limits are said now, because they are limits and not faults:

1. The app is Chrome showing your JARVIS full screen, plus a few small native parts. It is not a second copy
   of JARVIS, so it needs the internet, and Android will not let it block screenshots.
2. SOS is a message to your family. It is not an emergency service and it never calls 112 for you.
3. We found no proof that the NoiseFit app writes your watch's data into Health Connect. Noise's own help page
   names Google Fit, and Google supports Fit's connection for apps only until the end of 2026. The watch part
   is built and stays empty until data arrives. You check this on your phone before we build (owner
   question 3).

## The eight things you asked for

| # | You asked for | R7 builds | Part |
|---|---|---|---|
| 1 | An Android app: push-to-talk and alerts | The JARVIS app (D1), a "Talk to JARVIS" tile and shortcuts (D9), alerts with the app closed (D10) | A, E |
| 2 | The phone camera in JARVIS, photo and live, looked at on the phone | The Camera panel and the camera's one door (D11, D12) | B |
| 3 | Share a photo into JARVIS from any app | JARVIS in Android's share sheet; the item waits on the phone (D15) | A, E |
| 4 | DigiLocker import from the phone into the vault | Share the PDF into JARVIS (always works) and a watched folder (when Android allows it) (D16) | A, C, E |
| 5 | Noise watch data through Health Connect | A Health Connect reader on the phone, daily summaries on the server (D17) | D, E |
| 6 | Emergency SOS with your location | Hold, countdown, Telegram to family, the SMS app pre-filled (D19, D20) | D, E |
| 7 | Sleep tracking | Last night and the week, in the brief and by voice, with the AI off too (D18) | D |
| 8 | On-device vision groundwork | One vision engine with five tasks and a contract for later use cases (D13, D14; Appendix A) | B |

Not in this plan:

- An iPhone app.
- A native camera screen, and Google's ML Kit (D14).
- "Hey Jarvis" while the app is closed or the screen is dark (D9).
- Any fitness, kitchen or care use case itself: those are R8, R9 and R10; R7 builds what they stand on.
- Cameras that reach JARVIS through the home laptop.
- A Play Store listing, and sending the SOS text message without your tap (owner questions 5 and 8).
- Reading other apps' notifications or messages, ever.

## Gate G0 · R11.1 first

R7's base is `r11-1-i0` @ `9250be1`, on which four builders are finishing R11.1. R7's I0 seams are built only
after R11.1's integration branch `r11-1-i1` exists, and `r7-i0` is brought up to it first. R7 depends on R11.1
for the picture path to the brain (`documents/pictures.py`, Part B of R11.1) and touches files R11.1's parts own
today (`console.js`, `console-attach.js`, every `console-voice*.js`, `core/prompts.py`). Every file:line below
is from `9250be1` and is re-checked at I0.

## What exists today (`r11-1-i0` @ `9250be1`)

1. **Sign-in.** Google only, owners only: `api/auth.py:185–190` sends the browser to Google and `:194–226`
   checks the verified e-mail against the owner list. The session is the signed cookie `jarvis_session`,
   `SameSite=Lax`, Secure, 12 hours sliding (`config.py:90`, `api/app.py:555–562`) and 24 hours at most
   (`api/auth.py:41`). A cookie write needs the header `X-Requested-With: JARVIS` (`api/auth.py:36–37`, `:111`);
   no CORS headers are served (`:9–10`). The page signs in with `location.href = '/auth/login'`
   (`console.js:124`).
2. **Passkeys.** The relying party is the server's own host and ONE expected origin
   (`permissions/ceremony.py:65–81`, `:154–155`, `:188–189`); the page uses the browser's own
   `navigator.credentials` (`console-permissions.js:63–64`, `:91`). Final actions, the vault, disarming and the
   build book all hang on it (`console-permissions.js:126–133`).
3. **Content security policy.** `api/console.py:194–199`: `default-src 'none'`; scripts and connections from
   the server itself only (plus `'wasm-unsafe-eval'`); `img-src 'self' data:`; `worker-src 'self'`; no
   `manifest-src`, no `media-src`. The exact string is pinned by four tests (I0 seam 11).
4. **Not installable.** Nothing under `src/jarvis/api/` serves a web app manifest or an icon; `console.html:5–8`
   has only the viewport and the theme colour `#04070D`.
5. **Alerts.** Web Push is built (`webpush/service.py`; at most 5 devices, `notify/ports.py:39`; the allowed
   push hosts include `fcm.googleapis.com`, `webpush/endpoints.py:15–18`). The service worker `console-sw.js`
   has a push and a click handler, scope `/static/push/` and no fetch handler (`console-sw.js:1–5`). The payload
   is `{kind, text, url}` (`webpush/service.py:68–74`) with `url` `/#home` or `/`, but **no console script reads
   `location.hash`**: a tapped alert opens the console, not a panel. There are 38 alert kinds
   (`alerts.py:21–72`). Telegram is the second channel, to the paired owner only (`telegram/alerts.py:44–57`).
6. **Voice.** The microphone has one door, `console-voice-capture.js` (`getUserMedia` at `:154`), with the hard
   "mic off" lock that only a real tap opens (`:88`, `:118–123`). A turn starts in `press()`
   (`console-voice-mic.js:423–437`); `window.JarvisVoiceLoop` (`:660–667`) offers `state, inConversation, say,
   ask, offer, end` and **no way to start a turn**. On a phone the conversation ends when the page is hidden
   (`:631`). "Hey Jarvis" runs inside the page (`api/console.py:172–183`). R5's plan (D14) already lists
   Android's limits: no output switching, a chiming recogniser.
7. **Camera.** None. No console file opens a camera: `getUserMedia(` exists only in the voice capture file
   and `tests/test_r5_seams.py:118` pins that. The package `jarvis.camera` is the home burglar alarm.
8. **Pictures to the brain.** R11.1's seam `documents/pictures.py:19–41`: at most 4 pictures a turn, only to a
   seeing brain that does not learn, never stored in a conversation (Part B of R11.1 fills it).
   `photos/imaging.py:20`, `:67` strips a JPEG's camera and location data and refuses anything over 2,048 px.
9. **Files and the vault.** Attach in the composer (`console.html:165–168`); vault upload `POST /v1/vault/upload`
   (`api/vault.py:202`); DigiLocker comes through a Drive folder read by a tick job
   (`vault_inbox/service.py:1–24`) into `VaultIntake.intake` (`vault/ports.py:16–36`): PDF, JPEG, PNG, ≤ 10 MB.
10. **Telegram's front door.** Only the paired owner reaches the brain; a stranger may only pair with
    `/start <code>` and is otherwise turned away and audited (`telegram/service.py:132–148`, `:298–313`).
    JARVIS has never written to anyone but you.
11. **Cutting sessions off.** R6 keeps a "sessions valid after" mark per owner that ends every older cookie
    on every route within 3 seconds (`api/book_lock.py:188–202`; `buildbook/lock.py:42`, `:112`). Only the
    build book's Resume sets it today.
12. **Health words already taken.** `jarvis.health` is JARVIS's own systems check and `jarvis.vitals` its keys
    and limits. Nothing reads a watch; R11's `wellbeing/{uid}_{date}` holds water and stand-ups.
13. **Line budgets.** `console.html` 795 lines (guard < 800); `api/app.py` 725 (guard 750); the dock has 21
    tabs; `tools/gateway.py` is frozen at 760.
14. **Release naming.** The build book names the release from the highest-numbered plan file
    (`buildbook/gen/plans.py:76–78`): that stays "R11.1" after R7 ships (I0 seam 2).
15. **This workspace** (measured 12 Nov 2026, 06:37 IST, one request each). JDK 21, Gradle 8.14.3 and Node 22
    are installed; there is no Android SDK. Reached: npm (200), PyPI (200), raw.githubusercontent.com (200),
    GitHub release downloads (206). **Refused by the workspace's proxy (403):** dl.google.com,
    maven.google.com, services.gradle.org, plugins.gradle.org, repo.maven.apache.org, repo1.maven.org,
    storage.googleapis.com (where MediaPipe keeps its model files) and cdn.jsdelivr.net. So no Android build
    and no model download can happen here.

## Decision record · which shell (question 1)

Four ways to put the console on the phone were weighed for THIS app. Sources [S…] are listed at the end; every
one was read on 12 Nov 2026.

| For this app | A · Capacitor loading the live console (`server.url`) | B · Capacitor with a copy of the console inside the app | C · Installed web app only (Chrome's "Install") | D · A small native app whose main screen is the console in Chrome, full screen (Trusted Web Activity) |
|---|---|---|---|---|
| Owner-only Google sign-in | **Blocked.** Google: a developer "must not direct a Google OAuth 2.0 authorization request to an embedded user-agent under the developer's control" [S1]; embedded webviews get `disallowed_useragent` since 30 Sep 2021 [S2]. Needs a second, new sign-in path on the server | Blocked the same way | Works, unchanged | **Works, unchanged**: Chrome draws the page; Google's page shows with its address |
| Passkeys (one host, one origin) | Only if our own native code switches WebAuthn on in the WebView (androidx.webkit 1.12.0+, plus Digital Asset Links) [S3]; we found no statement that Capacitor does it (*unverified*) | The page's origin becomes `https://localhost` [S4]: every passkey check fails until the server accepts an app origin | Unchanged | **Unchanged** |
| Strict CSP | The page's CSP stays; plugin file addresses need `img-src` / `connect-src` loosened | The server's CSP header no longer covers the page at all | + `manifest-src 'self'` | + `manifest-src 'self'` |
| Cookie and CSRF header | A second cookie jar, separate from Chrome | Every API call becomes cross-site: `SameSite=Lax` blocks the cookie and no CORS is served (`api/auth.py:9–10`): the sign-in model must be redesigned | Unchanged | **Unchanged**: Chrome's own jar; signed in in Chrome is signed in in the app [S10] |
| Alerts with the app closed | No Push API and no notifications in Android's WebView [S13]: needs Firebase Cloud Messaging, a Firebase file that may not sit in a public repository, and a new sender on the server | Same | Today's Web Push, unchanged | **Today's Web Push, unchanged**, shown by the app itself with its own channels [S12] |
| Microphone and the voice loop | Works with app permissions; no browser voice (`speechSynthesis` is absent in WebView [S13]) | Same | As Chrome today | **As Chrome today** |
| "Hey Jarvis" | Only while the page is on screen | Same | Same | Same (D9 says why nothing more is built) |
| Camera, file upload | Work; a native preview is possible | Same | Work | Work (web camera; D11) |
| Share from other apps | Native code, then a bridge into the page | Same | Web manifest `share_target` (Chrome 76+) [S13] | The same web feature through the app (Chrome 86+) [S9] |
| Native code talking to the page | A JavaScript bridge: the one real advantage | Same | None | One-way launch address only [S8]; native parts talk to the server (D7) |
| Health Connect, SOS, tile, folder watcher | Native code anyway; the Health Connect plugin we found is stale (0.7.0, Aug 2024, for Capacitor 5) [S5] | Same | Impossible | Native code, the same amount as A |
| Screenshots, fingerprint gate | Possible natively | Possible | Not possible | Not possible natively; a server-side app lock instead (D21) |
| Updates | Web by deploy; native by reinstall | **Every console change needs a new app**: two copies, "one codebase" lost | Web only | Web by deploy; native by reinstall (rare) |
| What the maker says | Capacitor's own docs on `server.url`: "This is not intended for use in production." [S4] | Supported, but see above | Supported | Chrome's documented way to open "your web-app content" from an app [S6] |
| New server work | A second sign-in path, an FCM sender, WebAuthn changes | The same plus CORS and token sign-in | A manifest | A manifest, one public file, the phone's door |
| Tested in this workspace | Little: needs a device | Little | All of it (Playwright) | All web and server parts; native in CI and on the laptop |

**Recommendation: D, the hybrid.** One small native Android app. Its main screen is your console drawn by
Chrome with no browser bar (a Trusted Web Activity, through Google's Apache-licensed `android-browser-helper`
2.7.4 [S11]). Beside it sit a few small native parts for what a web page cannot do: the Talk tile, Health
Connect, SOS, the DigiLocker folder and the notification channels. This is still "wrap the console, add
native parts only where needed, one codebase, the look you approved". It replaces the words "for example with
Capacitor" in the release plan and in the architecture guide (rows "Mobile (PLANNED, R7)", the roadmap,
decision log R6.1): R7's I0 updates those rows; nothing is changed silently.

The three strongest reasons:

1. **Sign-in, passkeys and alerts keep working exactly as they do today**, because the page runs in Chrome.
   In a Capacitor WebView Google refuses the sign-in, passkeys need custom native work and Web Push does not
   exist; each would need a new, security-sensitive path on the server.
2. **Capacitor's one advantage is not needed.** The native parts (watch data, SOS, folder, tile) never need to
   draw inside the console; they send to the server, and the console reads the server as always (D7). The
   camera and the vision engine are web code, so the same engine runs on the phone and in the laptop browser.
3. **Almost all of it can be built and tested here.** The web and server parts run under the existing Python
   and browser suites; the native app is thin enough to check with JVM tests in CI (D24).

What the server must change for D: a web app manifest and `manifest-src 'self'` (D3); one public file,
`/.well-known/assetlinks.json` (D4); the phone link and the phone's signed door (D5, D6); a reader for launch
addresses (D8); a "sign out everywhere" (D21). Sign-in, the passkey check, cookies, the CSRF header and the
Web Push sender do not change. The full list is under "The server changes, in one list".

What you lose with D, plainly:

- **Screenshots cannot be blocked**, and there is no fingerprint gate drawn by the app in front of the console.
  Instead JARVIS can lock itself after 5 minutes away and ask for your passkey (D21).
- **It needs Chrome** (or another browser that supports this, set as default). Otherwise a browser bar shows.
- **The native parts are separate small screens** (SOS, set-up), styled to match; they cannot appear inside
  the console.
- **"Hey Jarvis" works only while JARVIS is open on screen**, never from a closed app or a dark screen.
- **Vision runs in the browser's engine**, slower than a native camera screen. If R8 needs more speed, a
  native camera screen can be added to the same app later.
- **Nothing opens without the internet**, except the SOS text message.

## How it fits the architecture

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| The Android app (console full screen), tile, shortcuts | L1 User Interaction · Platform | 6 | Build now |
| Installable console, launch addresses, share-in | L1 User Interaction · Platform | 6 | Build now |
| Phone link and the phone's signed door | L1, cross-cutting security · Platform | 6 | Build now; OFF until a phone is linked |
| Alerts on the phone | L8 Response & Output · Communication | 6 (R3's Web Push) | Build now |
| Push-to-talk | L1 / L2 · Communication | 1 and 6 | Build now |
| Phone camera, photo and live | L1 device, L2 Input Processing · Research & Intel | 6 | Build now |
| On-device vision engine (one port, five tasks) | L2 Input Processing · Health & Wellbeing (the planned 11th skill) | 6, groundwork for 5 | Build now; pose and objects wait for two model files |
| DigiLocker import from the phone | L6 Integration to L7 vault · Task & Productivity | 6 | Build now; automatic only where Android lets the folder be picked |
| Watch data through Health Connect | L6 Integration, L7 sealed · Health & Wellbeing | 6 | Build now; empty until data arrives |
| Sleep tracking | L5 Skills, L8 brief · Health & Wellbeing | 6 | Build now |
| Emergency SOS | L5 Skills, L8 Response & Output · Security Advisor | 6 | Build now; OFF until a contact joins |
| App lock, sign out everywhere | Cross-cutting security | 6 and 7 | Build now |
| "Hey Jarvis" with the app closed | L2 Input Processing | 6 | Not built (D9) |
| Native camera screen, ML Kit | L2 Input Processing | 6 | Not built (D14) |

Two additions to the reference architecture are proposed, both already marked PLANNED in the guide: a **vision
engine in Layer 2** (here it becomes real, in the browser) and the **11th core skill "Health & Wellbeing"**
(watch and sleep are its first built parts). One departure is new and is recorded by I0: the phone app is a
Trusted Web Activity, not Capacitor and not React Native.

## What runs where

```
PHONE (Android 9 or newer)                                      CLOUD (Cloud Run, Mumbai, one instance)
+-----------------------------------------------+              +------------------------------------------+
| JARVIS app (built on the owner's laptop)       |              | the console page and /v1 API             |
|  Launcher -> Chrome, full screen               |    HTTPS     |   (Google sign-in, cookie + CSRF header) |
|    the SAME console: chat, voice, every panel, +------------->|  /manifest.webmanifest   /app/share/*    |
|    Camera + vision engine (on the device),     |    cookie    |  /v1/vision (results only)               |
|    share tray (its own small service worker)   |              |  /v1/watch  /v1/sos  /v1/phone           |
|  Tiles and shortcuts: Talk, Camera, SOS        |              |  Web Push sender (unchanged)             |
|  Notification service (channels by level) <----+-- Web Push --+                                          |
|  Phone key (secure hardware, P-256) -----------+--- signed -->|  /.well-known/assetlinks.json (public)   |
|  Health Connect reader (background job) -------+   requests   |  /phone/link (one-time code)             |
|  SOS screen: hold, countdown, location --------+              |  /phone/v1/{hello,health,inbox,sos}      |
|     and the SMS app opened with the message    |              |    -> watch, vault intake, sos           |
|  Folder watcher (one folder you picked) -------+              |  Telegram: your alerts + SOS contacts    |
| Chrome keeps: the session cookie, passkeys,    |              |  Firestore: phone_devices, watch_days*,  |
|  mic and camera permissions, push subscription |              |    sos*, vision_results*   (* sealed)    |
+-----------------------------------------------+              +------------------------------------------+
LAPTOP BROWSER: the same console and the same vision engine (a desk camera: a USB webcam, later)
HOME LAPTOP (bridge): the same RESULT contract for fixed cameras in R8-R10; nothing is built there in R7
```

## Decisions (binding)

**D0 · Never change the look.** R5.1's rule and R11.1's D0 stand. New web screens reuse the existing tokens
and components (`.btn`, `.pbtn`, `.integ`, `.sheet`, `.bdialog`, `.clip`, `.chip`, the Helpers builders); no new
colour, font, radius or shadow; text through `textContent` only; 44 px targets; Night and Day at 1440×900 and
390×844; contrast ≥ 4.5:1. The two native screens (set-up, SOS) copy the console's tokens (background `#04070D`,
the same accent, the same three open-licensed fonts) and nothing else. The app icon is the console's own core
ring on its own background (owner question 14). `tests/browser/test_ui_audit.py` keeps passing and every part
adds its own browser test with `tests/browser/ui_checks.py`.

**D1 · The shell is a Trusted Web Activity inside a small native app.** `android/` holds one Gradle project.
Its launcher (`android-browser-helper`'s `LauncherActivity`, subclassed) opens `https://<your JARVIS address>/`
in the phone's browser without a browser bar once the site and the app vouch for each other (D4). No WebView,
no Capacitor, no Bubblewrap, no React Native, no Firebase, no Google Play services library. The helper's
WebView fallback is left OFF (in a WebView Google sign-in would fail): without a suitable browser the app shows
one plain screen saying "Install or update Chrome". **Supported: Android 9 and newer.** What differs by
version: on Android 9 to 13 Health Connect is a free app from the Play Store, from 14 it is part of Android
[S17]; Android 13 and newer ask before notifications and can offer the tile [S32]; Android 12 and newer draw
the system's own camera and microphone dot [S41] and have Android's own Emergency SOS [S42].

**D2 · Sign-in, passkeys, cookies, CSP and Web Push stay as they are.** Nothing in `api/auth.py`,
`permissions/ceremony.py`, the session middleware or `webpush/` changes for the app. The CSP gains exactly
`manifest-src 'self'` and nothing is loosened. The native parts never hold a browser session and can never
make one (D6).

**D3 · The console becomes installable, and that is also the fallback with no app at all.** `GET
/manifest.webmanifest` (public, no cookies): name "JARVIS", `start_url` `/?source=app`, `display: standalone`,
`theme_color` and `background_color` `#04070D`, icons 192 and 512 px plus a maskable one, `shortcuts` (Talk,
Camera, SOS) and `share_target` (D15). `console.html` gains one `<link rel="manifest">`. With this alone
Chrome's "Install app" gives an icon, the share sheet entry and the long-press shortcuts [S13, S15] before any
Android build exists.

**D4 · The site and the app vouch for each other; nothing else is trusted.** `GET /.well-known/assetlinks.json`
(public, `application/json`, no redirect, cached 60 s) lists, for each LINKED phone (D5), the app's package name
and the SHA-256 fingerprint of the key that signed it, with the single relation
`delegate_permission/common.handle_all_urls` [S7]. No login-sharing or message-channel relation is granted.
The app's own half is built from the same address at build time. The app opens the console **only after it is
linked**, so the first check ever made finds the entry. R7 declares **no App Links**: JARVIS addresses tapped
in other apps keep opening in the browser, the app accepts no web link from another app, and Android runs no
early check that could cache a "no". If the check fails, Chrome shows its bar and everything else still works.

**D5 · Linking a phone: a one-time code and a key that cannot leave the phone.** Integrations → Phone app →
**Link a phone** asks for your passkey (or, with no passkey yet, a Google sign-in under 5 minutes old) and
shows an 8-character code: 40 bits, 10 minutes, single use, stored as a hash, void after 5 wrong tries (the
R1 and R3 pairing rules). The app makes a P-256 key pair inside the phone's secure hardware (Android Keystore:
"the key material remaining non-exportable" [S40]) and sends `POST /phone/link {code, public key, package,
signing fingerprint, model word, app version}`. The server accepts only the one package name (owner question
15), a fingerprint of exactly 32 bytes and a valid P-256 public key; it stores only public things and returns
a device id `ph_<12 hex>`. At most 3 phones (`phone_link_max`). Every link sends the alert `phone_linked` to every channel
("A phone was linked to JARVIS at 14:05. If this wasn't you, unlink it in Integrations."). **Unlink** stops
the phone at once.

**D6 · The phone's door: four signed routes and nothing else.** Each request carries `X-Jarvis-Phone:
v1;d=<device id>;t=<unix seconds>;n=<16 random bytes>;s=<ECDSA P-256 / SHA-256 signature>` over
`"jarvis-phone-v1\n" + device id + "\n" + t + "\n" + n + "\n" + METHOD + "\n" + path + "\n" + hex(sha256(body))`
(R3 D5's scheme with a public key instead of a shared secret, so the server holds nothing worth stealing).
Checked in this order before any parsing: the route is one of the four (else 404) → the body is under its cap
→ the header's shape → the device is known and not unlinked → `|now − t| ≤ 120 s` → the nonce is unseen for 10
minutes (in process; one instance) → the signature → 30 requests a minute per phone. Any failure is a bare
401, logged by check name, never audited (a flood cannot fill the audit). The routes:
`POST /phone/v1/hello` (what the app may do, permission states; the reply carries its settings and, for the
SMS screen, the SOS contacts), `/phone/v1/health` (D17), `/phone/v1/inbox` (D16, ≤ 10 MB), `/phone/v1/sos`
(D19). The door **cannot** read a conversation, the vault, mail or memory, cannot approve anything, cannot
call a tool and never sets or reads a cookie. A stolen phone key can add watch numbers, add a document for
you to confirm, and send an SOS; nothing more.

**D7 · Native parts talk to the server, never to the page.** Chrome gives the app no access to the page [S6]
and only a launch address goes the other way [S8]. So the tile, the watch reader, SOS and the folder watcher
send to the phone's door; the console shows what the server holds, as every panel does. No JavaScript bridge,
no message channel, no injected script.

**D8 · A launch address opens a screen; it never acts.** One reader (`console-r7-links.js`) takes
`?do=talk|look|sos|shared` and `?open=<panel>` from an allow-list, opens the screen, and removes those words
from the address. Anything else is ignored. `do=talk` starts listening only when the page runs as the installed
app (its own window), never unlocks "mic off", and in an ordinary browser tab only points at the mic button.
`do=look` opens the Camera panel; **the camera itself never starts without a tap on that screen**. `do=sos`
opens the SOS sheet, which still needs your hold (D19). The server drops `do` and `open` when the browser says
the visit came from another site (`Sec-Fetch-Site: cross-site`). Push alerts get a real target per kind
(`?open=home`, `?open=approvals`, …), replacing the unread `/#home`. Inside the app, tiles and shortcuts reach
the launcher through a screen other apps cannot start, so no other app can make JARVIS listen.

**D9 · Push-to-talk: three doors into the existing voice loop, and no always-listening service.**

| Piece | Native or web | What it does |
|---|---|---|
| The voice loop (listen, think, speak, barge-in, mic off) | Web, unchanged | Everything R5 built; it gains only `JarvisVoiceLoop.start()` |
| "Talk to JARVIS" Quick Settings tile | Native | Pull down, tap: JARVIS opens already listening. Android 13+ offers to add the tile for you [S32]; older phones: drag it in once |
| App icon shortcuts: Talk, Camera, SOS, Set-up | Native (and in the web manifest) | Long-press the icon |
| "Talk" button on an alert | Web (the push service worker) | Opens JARVIS listening |
| A widget, a Talk button kept in the notification shade | Not built | The tile and shortcuts cover it; a kept notification is clutter |
| A microphone service for "Hey Jarvis" with the app closed | Not built | Battery; a microphone that is always on; Android forbids starting such a service from the background [S33]; the wake-word model is for personal use only |

Honest limits: the phone must be unlocked; the first time each day you may have to sign in with Google (two
taps: the session lasts at most 24 hours, unchanged); if Chrome will not play sound before a tap, the first
reply shows its words and a "Tap to hear" chip.

**D10 · Alerts: the same Web Push, shown by the app with three channels.** The server keeps sending as today.
With the app installed and vouched for, Chrome hands each notification to the app's own service
(`DelegationService`, subclassed [S11, S12]), so alerts carry JARVIS's icon and obey JARVIS's notification
settings. That service sorts them into three Android channels by the alert's kind: **Urgent** (burglar,
hazard, disaster, SOS, a phone linked), **Alerts**, **Nudges**; an alert it cannot sort goes to Alerts. You
set each channel's sound once in Android. Telegram stays the second channel. Android 13+ asks "Allow JARVIS
to send notifications?" once.

**D11 · The camera has one door and a hard off switch.** `console-camera.js` is the only file that asks for a
camera (`getUserMedia({video})`; a static test pins it beside the microphone's file). It mirrors R5's mic lock:
`JarvisCamera.lock(by)` stops every track, persists `jarvis_cam_off_v1`, syncs across tabs, and only a real tap
(`navigator.userActivation`) unlocks; nothing else can. While any track is live a "Camera on" chip with Stop
stays on screen, in addition to the green dot that Android itself draws from version 12 [S41]. The camera
stops by itself when the page is hidden, the screen locks, or nothing has used a frame for 10 minutes.
**"Jarvis, cameras off"** (also "camera off", "stop the camera") is a local voice command (`camera.off`,
through R5's router, so it works with the AI off): it locks this device's camera and says "The camera on this
device is off, Sir." It never touches the home burglar camera: switching that off is disarming, which stays a
card with your passkey (R3 D8).

**D12 · Frames stay on the device; only results exist; three buttons can send a picture, each says so.** A
frame lives in memory, is handed to the engine and is thrown away. Nothing is written to disk, to the
conversation or to the server. Looking at a photo or the live picture produces a **result** (numbers, short
labels from fixed lists, text that was read). A picture reaches the server only when you press one of:
**Ask the AI about this photo (about ₹0.30)** (R11.1's picture path: shrunk, metadata stripped, a seeing brain
that does not learn, never stored); **Add to my vault** (documents); **Attach to my message**. A result is
kept only when you press **Keep**; kept results are sealed (`vision_results`, 90 days). Read text is other
people's words: it reaches the brain fenced as data, and a turn that carries it makes every change a card.
The panel shows a running line: "Pictures sent from this device today: 0".

**D13 · The vision engine: one port; tasks see pixels, use cases never do.**

```
// console-vision.js (I0 core; Part B fills the tasks)
JarvisVision.tasks()                       // [{id, v, input: 'photo'|'live'|'both', ready, why}]
JarvisVision.run(task, source, opts)       // -> Promise<Result>            one photo
JarvisVision.stream(task, opts, onResult)  // -> {stop()}                   live, at a capped rate
JarvisVision.register(task)                // a task = {id, v, load(), run(frame, opts) -> data, schema}
JarvisVision.use(usecase)                  // a use case = {id, tasks: [...], onResult(result, state), summary(state)}
// Result = {task, v, at, ms, device: 'phone'|'browser'|'home', ok, data, quality: {light, sharp}}
```

A **task** is the only code that touches a frame; it returns plain data checked against its schema (numbers in
ranges, labels from the task's own list, text ≤ 2,000 characters). A **use case** (R8–R10) receives results
only: its module may not call `drawImage`, `getImageData`, `toBlob` or `fetch` (a static test), so "frames are
thrown away" is a property of the code's shape, not a promise. R7 ships five tasks: `text` (read printed
words and numbers), `code` (barcodes and QR), `objects` (which of 80 everyday things, and where), `pose` (33
body points) and `quality` (light and sharpness, plain arithmetic, no model). The same Result contract is
written down for the server (`jarvis.vision.results`), so a camera on the home laptop can deliver the same
shapes later through the bridge's plug-ins; nothing is built on the bridge in R7. Live work runs at a capped
rate (pose ≤ 15 a second, objects ≤ 5, text and codes on demand) and slows itself when the phone is slow; the
screen is kept awake while a live look runs.

**D14 · Vision tools: Apache and MIT only, served by JARVIS itself, pinned by hash.**

| Task | Tool (version read 12 Nov 2026) | Licence | Size sent to the device once |
|---|---|---|---|
| `pose`, `objects` | MediaPipe Tasks Vision 1.2.3 [S5, S23, S25] | Apache-2.0; pose model card: Apache-2.0 [S24] | 14.7 MB engine + about 6 MB and 4 MB of models |
| `text` | tesseract.js 7.0.0 with core 6.1.2, English data [S5] | Apache-2.0 | about 4 MB + 3 MB |
| `code` | zxing-wasm 3.1.6 [S5] | MIT | about 1 MB |
| `quality` | plain canvas arithmetic | JARVIS's own | 0 |

Each task downloads only its own files, the first time it is used (about 35 MB if you use them all). Files
live under `static/vendor/vision/<release>/` with their licences and a manifest of SHA-256 sums, served with a
year-long cache as the wake-word files are; nothing is fetched from another site (`connect-src 'self'`
stays). Read from the packages themselves: MediaPipe's bundle contains no `eval` and no `new Function`, loads
its engine by a same-origin script tag and fetches its binary same-origin; tesseract.js needs
`workerBlobURL: false` and its worker, core and language paths pointed at JARVIS (its defaults are a blob
worker and a public CDN), and its two `Function(...)` fallbacks are reached only where `globalThis` is
missing. Worker scripts are served with the console's CSP header. The object model's page links no model
card: its licence is read before the file is bundled, as R11.1 did for the face models. **Not used:** ML Kit
(Google's terms, not open source: "ML Kit APIs also send metrics about the performance and utilization of the
APIs in your app to Google" [S26]); Ultralytics YOLO (AGPL); any cloud vision service. MediaPipe's two model
files sit on a Google storage host this workspace cannot reach: until the orchestrator supplies them (from CI
or the owner's laptop) and their hashes are recorded, `pose` and `objects` answer "not installed" (R11's
nutrition-data precedent) while `text`, `code` and `quality` work. The model card's own limits are carried
into the panel's words: one person, within about 4 metres, head visible, never for a decision a life depends
on, never to recognise who someone is [S24].

**D15 · Share into JARVIS: the item waits on the phone until you choose.** The manifest's `share_target`
(and the same JSON in the app [S9]) posts shared files to `/app/share/in`. A second, tiny service worker
(`/app/share/sw.js`, scope `/app/share/` only) takes that one POST, keeps at most 5 items of ≤ 10 MB (JPEG,
PNG, WebP, PDF, or a line of text) in the browser's own cache, and answers 303 to `/?do=shared` [S14]. It
controls no page, so R3's rule (no worker that could serve a stale console) holds. The console's tray then
offers, per item: **Look at it here** (the vision engine), **Ask the AI about it (₹)**, **Add to my vault**,
**Attach to my message**, **Discard**; items older than 24 hours are dropped. Nothing reaches the server
before one of those presses. If the worker is not yet installed, the server's own route for that address
discards the body unread and says "Open JARVIS once, then share again."

**D16 · DigiLocker from the phone: share always; a watched folder where Android allows; never "all files".**
(a) Share the PDF to JARVIS, from DigiLocker's own Share button if your version shows one, otherwise from the
Files app after you download it: the PDF arrives in the tray (D15) and "Add to my vault" makes the usual
proposal for you to confirm. (b) **Automatic:** in the app's set-up you may pick ONE folder; Android
grants that folder only (`ACTION_OPEN_DOCUMENT_TREE`, kept across restarts) [S34]. About once an hour, and
whenever the app opens, a background job lists it and sends new PDF, JPEG or PNG files (≤ 10 MB, at most 3 a
run, each once by its SHA-256) through `/phone/v1/inbox` to `VaultIntake.intake(source="digilocker")`: an item
in "Check details", exactly like the Drive path. It never changes or deletes a file on the phone. Android
refuses the top of `Download` itself [S34]; if DigiLocker saves there, the app says so and (a) remains.
(c) "All files access" is never requested. R2's Drive folder keeps working beside both.

**D17 · Watch data: the phone reads Health Connect; the server keeps one sealed summary a day.** The app asks
Health Connect for Steps, Heart rate and Sleep only, plus "read in the background" [S17, S18]; it reads the
last 3 days every 6 hours and when opened (the first time, up to 30 days back, Health Connect's own limit
[S18]) and sends per day: steps; heart rate lowest, average, highest and resting; each sleep session with
minutes per stage; and the name of the app that wrote it. No raw heart samples. The server checks ranges,
seals the day with the new key purpose `watch` (`watch_days/{uid}_{date}`, kept 400 days) and never logs a
value. With no background permission, sync happens when the app is opened and the tab says "Last synced: …".
The permission screen is Health Connect's own: one switch per kind of data, then a second screen for "in the
background". Behind its "privacy policy" link the app shows four plain lines (what is read, that only daily
sums leave the phone, where they are kept, how to delete them); Health Connect requires that page [S17].
Works with any app that writes to Health Connect. Whether NoiseFit does is not proven: Noise's help page names
Google Fit [S22], a third-party page says the same [S44], and Google Fit's own "sync with Health Connect"
switch may be a detour worth trying [S45] (owner question 3). If the app were ever published on Google Play,
each kind of data would have to be declared and reviewed, and a public privacy policy added [S20].

**D18 · Sleep is plain code with fixed sentences, and never advice.** "Last night" is the longest session
ending between 00:00 and 14:00 your time; the week is the average and the spread of bedtimes. Stages are shown
only when the watch wrote them [S19]. Tools `sleep_last_night`, `sleep_week`, `watch_today` are R1 reads under a
new row "Watch and sleep"; they answer by voice and chat, on the No-AI phrases too ("how did I sleep", "steps
today"), are private on Telegram and are never given to a brain that learns. The brief gains one line ("Sleep:
6 h 40 min, 23:50 to 06:30 · from your watch"). A typed "I slept 11:30 to 6" is accepted and marked "typed by
you", so the feature is not dead without a watch. Every sentence is a template; nothing diagnoses or advises
treatment; the persona says the numbers are the watch's own estimates.

**D19 · SOS: a held button, a cancel window, a fixed message, and no way for the brain to send it.**
*Who:* up to 5 emergency contacts you add. *Channels, all free:* (1) a Telegram message and a map pin from
your JARVIS bot to each contact who joined (D20), sent by the server; (2) the phone's own SMS app opened with
every number and the message filled in, for you to press Send (no SMS permission; your plan's SMS charge, if
any; works without internet); (3) a notice to you on every channel ("SOS was sent at 14:05 to 3 people"),
which is also how a mis-sent SOS shows; (4) two buttons that open the dialler: your first contact, and 112.
*Message* (code, never a model): "SOS from {your label}: I need help. My location at 14:05:
{maps link} (within about 20 m). Sent by my JARVIS assistant." *Location:* asked for when the screen opens,
10 seconds at most; the message says how accurate and how old the fix is, or "location not available".
Android's precise location is "usually within about 50 meters … sometimes as accurate as within a few
meters" [S31]; indoors it can be worse. Coordinates are used once to write the messages and are **never
stored, logged or audited**; the SOS record keeps the time, how many were reached and "location: yes / no".
So that the SMS screen works with no internet, the phone keeps your contacts' numbers itself, encrypted with
a key held in its secure hardware.
*No accidents:* inside JARVIS and by voice, a 2-second hold and then a 5-second countdown; from the tile or
the shortcut, a 10-second countdown with sound, vibration and a full-width Cancel. A cancelled countdown sends
nothing at all. Afterwards **"I'm safe"** tells the same people. *Limits in code:* 3 an hour, 10 a day. *Who
can trigger:* you, by the web sheet (cookie, CSRF header) or the phone's door. No tool sends an SOS; the
brain's only SOS tool is the read `sos_status`; "Jarvis, SOS" only opens the screen. The native screen works
from the lock screen (it shows a countdown and nothing else; owner question 6). The card, the screen and the
persona all say: this is not an emergency service; call 112; set up Android's own Emergency SOS too (power
button five times, Android 12+ [S42]).

**D20 · SOS contacts join by their own Start; the bot never chats with them.** A Telegram bot's link takes a
start word of up to 64 letters, digits, `_` or `-` [S43]. You add a contact (a label, optionally a phone number
for the SMS screen); JARVIS shows a join link carrying a one-time word (24 hours); you send that link yourself.
When they press Start the bot answers once: "You are now an emergency contact for {label}. This bot writes to
you only when {label} presses SOS or sends a test. Send /stop to leave." `/stop` removes them and tells you
(`sos_contact_left`). Anything else they write gets no reply and never reaches the brain. The Telegram front
door changes in one place only: a hook for a stranger's `/start <word>` and `/stop`, so the "paired owner
only" rule for everything else is untouched. Contacts are sealed with the new key purpose `sos`.

**D21 · Sessions, the app lock, and a lost phone.**
- *Where a session lives:* in Chrome's cookie store on the phone (HttpOnly, Secure, signed; 12 hours idle,
  24 hours at most), exactly as when you use JARVIS in the phone's browser today. The app holds no session.
- *The phone key* lives in the phone's secure hardware and opens only the door of D6.
- *App lock:* a switch in Privacy, "Lock JARVIS on this device after 5 minutes away" (ON by default in the
  installed app once you have a passkey; OFF elsewhere). It is enforced by the server, not drawn on top of the
  page: once the session has been idle that long, every route answers 423 `device_locked` until a passkey
  check bound to that session (`device_unlock`); the SOS routes and the unlock itself are never locked. The
  installed app is known by its start address (`/?source=app`); opening that address can only switch the
  lock ON for the session, never off.
- *Screenshots:* cannot be blocked in Chrome. The vault still needs its own passkey unlock, and "names in
  alerts" stays off by default. The native set-up screen blocks screenshots (`FLAG_SECURE`).
- *A lost or stolen phone:* locked, it shows only alert text. Unlocked, a thief gets what your phone's browser
  gives today until the session ends or the app lock engages; nothing final without your passkey. From any
  other device: Integrations → Phone app → **Unlink this phone** (the door closes at once) and **Sign out
  everywhere** (R6's "sessions valid after" mark: every cookie older than now dies within 3 seconds); then
  remove that phone's passkey in Approvals → Permissions, and remove the phone from your Google account.
- *Never in the repository or the app:* no keystore, password, server address, e-mail address, phone number
  or key. The address enters at build time from a file that is never committed (D23).

**D22 · The app asks for little, and a test holds it to that.** Allowed permissions: internet, notifications,
location (while in use, for SOS), Health Connect read of steps, heart rate and sleep (plus background read),
vibrate. The libraries add a few of their own when the app is built [S47]: the background-work library adds
network state, wake lock, start after reboot and foreground service, and AndroidX core adds one private
permission of the app's own. Each is on the list with its reason, except foreground service, which the app's
manifest removes because JARVIS starts no such service (D9). **Never declared:** read or receive SMS,
notification access, accessibility (the four that make Play Protect block a sideloaded app in India
[S28, S29]), send SMS, camera or microphone (Chrome holds those), contacts, any storage permission, "all
files", draw over other apps, query all packages. No cleartext traffic; system certificates only; backups
off. Reachable from outside: only the launcher, the share entry, the tiles and the notification service, each
as narrowly as Android allows, plus three entries the libraries bring (the background-work library's job
service and diagnostics receiver, each behind a system permission, and Health Connect's own service) [S47].
`scripts/apk_check.py` reads the built app in CI and fails on any permission or outside-reachable part that
is not on those lists, any forbidden one, a debuggable `personal` build, a plain-HTTP address, a real host
name, or a secret-shaped string.

**D23 · Who builds what: CI proves, your laptop makes the app you install.**
- **CI** (`.github/workflows/android.yml`, free on a public repository [S38]; GitHub's Ubuntu image carries
  Android SDK platforms 34 to 37, build-tools 37.0.0, Java 17 and 21 [S37]): on every push that touches
  `android/**`, validate the Gradle wrapper, run lint and the JVM tests, build with the placeholder address
  `jarvis.invalid`, run `apk_check.py`, and keep the result for 7 days named "not for installing". No secret is
  used, so it is safe for any pull request. Each run signs with a throwaway key: such an app could never update
  the last one and is not vouched for by your site, which is exactly why it is only a proof.
- **Your laptop:** the build variant `personal` (not debuggable; signed with the debug key Android Studio made
  on that laptop, `C:\Users\<you>\.android\debug.keystore`, valid 30 years [S35]). That key never leaves the
  laptop and is never in the repository. The fingerprint reaches the server by itself when you link (D5), so
  nobody copies 64 characters. An update signed with the same key installs over the old app.
- **The address:** `jarvis.host` in `android/local.properties`, which the orchestrator writes in `C:\Jarvis`
  and Git ignores. A `personal` build without it stops with one plain line.
- **Versions:** the app's `versionCode` is its own counter (`android/version.properties`, +1 per shipped
  build), never JARVIS's version, which goes "down" from 11.1 to 7.0.
- **Pins, to be confirmed at I0 from the makers' pages, not guessed:** Android Gradle plugin 9.5.0 (needs
  Gradle 9.6.0 and JDK 17; supports up to API 37) [S36]; `compileSdk` and `targetSdk` 36 (Health Connect's
  client 1.1.0+ requires `compileSdk 36` [S17]; the helper library compiles against 36 [S11]); `minSdk` 28,
  Android 9, the oldest Health Connect runs on [S17].

**D24 · Thin native, logic where it can be tested.** The app is split in two Gradle modules. `core` is plain
Kotlin with no Android import: the door's signature string, the request payloads, the SOS state machine
(idle → holding → countdown → sending → sent / cancelled / failed), the Health Connect day builder, the inbox's
"seen" list, the launch-address allow-list. It is tested on the JVM in CI against the same vectors the server
is tested with (`tests/fixtures/r7/phone_vectors.json`: public key, exact strings, good and bad signatures; no
private key is committed). `app` is glue: screens, permissions, Health Connect, location, the folder, the tile.
Everything with a rule in it (who is a contact, what the message says, how sleep is summed, rate limits)
lives on the server and is tested in Python. Two cheap checks do run in this workspace: Python tests that
read the app's manifest and Gradle files as text (`tests/test_r7_e_*.py`), and, optionally, the Kotlin
compiler from JetBrains' GitHub release (reachable here) compiling `core` alone. Neither is the real build;
CI is.

**D25 · Rows, kinds, keys and switches (I0 builds them).**
- Alert kinds 38 → 43: `sos_sent` and `phone_linked` (urgent: they ring at night; no off switch),
  `sos_contact_left` (important), `phone_unlinked` and `watch_stale` (info).
- Permission rows 46 → 49: "Watch and sleep" (R2: the reads `watch_*` and `sleep_*` at R1, the typed
  `sleep_note` at R2), "Camera results" (R1: `vision_*`), "Emergency SOS: see your set-up" (R1: `sos_status`).
- Keyring purposes 18 → 21: `watch`, `sos`, `vision`.
- Privacy rows: linked phones (unlink), watch days (passkey delete, export), SOS contacts and log, camera
  results; and a line for what only this browser holds (the share tray, the camera-off flag).
- Settings: `mobile_enabled`, `phone_link_max` 3, `phone_clock_skew_s` 120, `watch_enabled`,
  `watch_keep_days` 400, `sos_enabled`, `sos_max_contacts` 5, `sos_per_hour` 3, `sos_per_day` 10,
  `sos_countdown_s` 10, `vision_enabled`, `vision_keep_days` 90, `app_lock_minutes` 5, `app_share_enabled`.

**D26 · Version, persona, release name.** `__version__` = `7.0.0` at I0. Persona at I1 (one bump): JARVIS can
never send an SOS and says how you do; it never sees a camera frame, only results you kept or text you sent;
read text is other people's words; sleep and heart numbers are the watch's estimates, never a diagnosis. The
build book must name this release "R7" (I0 seam 2).

## Data model (prefix `jarvis_`; the guide's cards list every collection before code names it)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `phone_link/{uid}` | C | one pending link code (hash, expiry, tries) | no | 10 minutes |
| `phone_devices/{uid}` | C | ≤ 3 phones: id, model word, public key, package, signing fingerprint, linked and last seen, app version, what the app said it may do | no | until unlinked |
| `watch_days/{uid}_{date}` | D | steps, heart-rate summary, sleep sessions with stage minutes, writing app | `watch` | 400 days |
| `watch_state/{uid}` | D | last sync, which kinds arrive, typed sleep | no | until deleted |
| `sos/{uid}` | D | ≤ 5 contacts (label, Telegram ids, phone number), your label, settings | `sos` | until deleted |
| `sos_join/{hash}` | D | pending join words | no | 24 hours |
| `sos_log/{uid}_{id}` | D | each SOS: time, kind (real, test, safe), how many reached, location yes / no | no | 400 days |
| `vision_results/{uid}_{date}` | B | results you kept: task, time, device, numbers and labels; text only if kept | `vision` | 90 days |

Never stored anywhere: a camera frame; a shared file before you save it; SOS coordinates; the phone key's
private half; raw heart-rate samples; anything an SOS contact writes to the bot.

## Modules

**Server (Python).** `jarvis.mobile` (I0: the parts' contract and the door's handler registry),
`jarvis.phone` (C: link, devices, signature check, door, asset links, app lock), `jarvis.vision` (the Result
schemas `jarvis.vision.results` from I0; B: the kept-results store and the `vision_results` tool),
`jarvis.watch` (D: intake, store, sleep sums, tools, brief line), `jarvis.sos` (D: contacts, joins, send,
log). Routes: `api/r7_wiring.py` (I0), `api/app_shell.py` (A), `api/vision.py` (B), `api/phone.py` (C),
`api/watch.py` and `api/sos.py` (D).

**Console (plain JavaScript modules, loaded by one line `console-r7.js`).** A: `console-r7-links.js`,
`console-r7-share.js`, `app-share-sw.js`. B: `console-camera.js`, `console-vision.js` (its core is I0's),
`console-vision-text.js`, `console-vision-code.js`, `console-vision-mp.js`, `console-vision-quality.js`,
`console-camera-panel.js`. C: `console-r7-phone.js`, `console-r7-lock.js`. D: `console-r7-sos.js`,
`console-helpers-watch.js`. Each has a stylesheet of ≤ 150 lines that only places things. Where things appear: a
**Camera** dock tab (the 22nd, last, so it folds behind More first) with sub-tabs Look, Results and Cameras; a
camera button beside the paperclip; a **Watch** sub-tab in Helpers; two cards in Integrations, **Phone app** and
**Emergency SOS**; the app-lock switch in Privacy.

**Android (`android/`, Kotlin, written here, compiled in CI and on the laptop).** `core/` (D24).
`app/shell/` (launcher, the screen for tiles and shortcuts, notification service, two tiles, shortcuts),
`app/link/` (set-up screen, phone key, signed client), `app/health/` (reader, background job, the privacy
screen Health Connect requires [S17]), `app/sos/` (screen, one-shot location, SMS composer), `app/inbox/`
(folder picker, hourly job), `app/ui/` (theme). Libraries, all Apache-2.0: `android-browser-helper` 2.7.4,
`androidx.browser`, `androidx.health.connect:connect-client` (newest stable 1.1.x), `androidx.work`,
`androidx.core`, `kotlinx-serialization-json`. Views and XML, not Compose (two screens).

## The server changes, in one list

1. `GET /manifest.webmanifest`, the icons, `<link rel="manifest">`, CSP `manifest-src 'self'` (D3).
2. `GET /.well-known/assetlinks.json` from linked phones (D4).
3. `POST /phone/link`, the phone's door `/phone/v1/*` with its handler registry, `GET/POST /v1/phone` for the
   card (D5, D6).
4. The launch-address reader, per-kind push targets, a "Talk" action in `console-sw.js`,
   `JarvisVoiceLoop.start()` (D8, D9).
5. `/app/share/sw.js` and `/app/share/in` (D15).
6. `/v1/vision` (kept results), the versioned vendor route for the vision files (D12–D14).
7. `/v1/watch`, `/v1/sos`, the Telegram stranger hook, a `send_location` call (D17–D20).
8. `POST /v1/session/end-all`, the app-lock middleware and `POST /v1/session/unlock` (D21).
9. Kinds, rows, key purposes, privacy rows, settings (D25).

Unchanged on purpose: `/auth/*`, the passkey ceremony and its one origin, the session cookie, the CSRF header,
the Web Push sender, the gateway, the brain loop.

## Part split (five builders, or four with D folded into C; worktrees; branches `r7-a` … `r7-e` from `r7-i0`)

A file appears under one part only. Everything not listed is I0's or I1's. Parts A–D are built and fully
tested in this workspace. Part E is written here and compiled in CI and on the owner's laptop.

| Part | Owns |
|---|---|
| **A · The app on the web side** (deliverables 1, 3; D3, D8, D9 web, D15) | `api/app_shell.py`; `static/manifest.webmanifest`, `static/icons/*`, `scripts/app_icons.py`; `console-r7-links.js`, `console-r7-share.js`/`.css`, `app-share-sw.js`; `console-sw.js` (the Talk action, targets); `webpush/service.py` (`payload_for` targets only); `evals/r7/shell.py`; `tests/test_r7_a_*.py`, `tests/r7_fakes_a.py`, `tests/browser/test_r7_a_*.py`, the existing `test_webpush_*`, `tests/browser/test_alerts.py` |
| **B · Camera and the vision engine** (2, 8; D11–D14) | `src/jarvis/vision/`; `api/vision.py`; `console-camera.js`, `console-vision*.js`, `console-camera-panel.js`, `console-camera.css`; `static/vendor/vision/**` with `MANIFEST.json` and licences; `scripts/vision_assets.py`; `evals/r7/vision.py`; `tests/test_r7_b_*.py`, `tests/r7_fakes_b.py`, `tests/fixtures/r7/b_*`, `tests/browser/test_r7_b_*.py` |
| **C · Phone link and security** (1, 4 server; D4–D6, D16 server, D21) | `src/jarvis/phone/`; `api/phone.py`; `buildbook/lock.py` (one method: end all sessions); `console-r7-phone.js`/`.css`, `console-r7-lock.js`; `evals/r7/phone.py`; `tests/test_r7_c_*.py`, `tests/r7_fakes_c.py`, `tests/browser/test_r7_c_*.py` |
| **D · Watch, sleep and SOS** (5, 6, 7; D17–D20) | `src/jarvis/watch/`, `src/jarvis/sos/`; `api/watch.py`, `api/sos.py`; `telegram/client.py` (`send_location`), `telegram/service.py` (only the code behind I0's hook); `console-r7-sos.js`/`.css`, `console-helpers-watch.js`; `evals/r7/body.py`; `tests/test_r7_d_*.py`, `tests/r7_fakes_d.py`, `tests/fixtures/r7/d_*`, `tests/browser/test_r7_d_*.py`, the existing `test_telegram_*` |
| **E · The Android app** (1, 3, 4, 5, 6 on the phone; D1, D9, D10, D22–D24) | all of `android/**` except `version.properties`' release bump; `scripts/apk_check.py`; `tests/test_r7_e_*.py` (static checks of the manifest and the Gradle files that run in the Python suite); `docs/plans/r7-integration/OWNER-STEPS.md` |

I0 leaves contract files inside two parts' folders: `src/jarvis/vision/results.py` and the core of
`console-vision.js` (B), and each part's stub package. The part owns its folder from then on; a contract file
changes only with a line in that part's INTEGRATION file, because another part or a later release builds
against it.

Cross-part needs, settled by I0 so nobody waits: D's two door handlers (`health`, `sos`) and C's `inbox`
handler plug into I0's registry and are tested against I0's fake door; E builds against
`docs/plans/r7-integration/phone-contract.md` and the shared vectors; A's `do=` words and E's tiles use the
same four words from that contract; D's local voice command `sos.open` and B's `camera.off` register through
R5's existing `JarvisVoiceCommands.register`. Each part writes `docs/plans/r7-integration/INTEGRATION-<PART>.md`.
`security-reviewer` runs on A (share worker, launch addresses), B (the frame boundary), C (all of it), D (SOS,
the Telegram hook) and E (manifest, exported parts, the signed client); `code-reviewer` and `python-reviewer`
on A–D; `silent-failure-hunter` on D (an SOS that says "sent" when it was not).

## The I0 seams (branch `r7-i0`, after G0; tests green: `tests/test_r7_seams.py`)

1. `jarvis.__version__` = `7.0.0`. **Pinned test to update:** `tests/test_about.py:24`.
2. **The build book names the release from the running version**, not from the highest plan number
   (`7.0.0` → "R7", `11.1.0` → "R11.1"), and lists this release's plan first. Code: `buildbook/gen/plans.py:76–78`,
   `fallback.py`. **Pinned tests to update:** `tests/test_book_gen_plans.py:87–91` (the rule itself) and
   `:205–214` (already red on `9250be1`: it still expects R11's plan first), `tests/test_book_gen_determinism.py:209–213`
   (expects the label "R11"). This task changes none of them.
3. `buildbook/gen/layers.py`: `mobile` and `phone` L1, `vision` L2, `watch` and `sos` L5
   (`tests/test_book_gen_code.py:102` fails on an unmapped package). `buildbook/gen/snapshot.py:42`: the binary
   list learns `.jar`, `.ttf`, `.task`, `.tflite`, `.gz`, `.webp`, and `android/**/build/` is never read
   (`tests/test_book_gen_snapshot.py`).
4. `config.py`: the settings of D25, ranges pinned.
5. Alert kinds 38 → 43 (`alerts.py`, `notify/ports.py`, `notify/policy.py`, `notify/held.py`,
   `console-alerts.js`, `buildbook/plain.py`). **Pinned counts:** `tests/test_r3_seams.py:165`,
   `tests/test_r6_seams.py:139`, `tests/test_r11_seams.py:65`, `tests/test_r11_1_seams.py:117`; and the exact
   set of kinds that ring by day, `tests/test_r51_seams.py:43–48`, because `sos_contact_left` joins it.
6. Permission rows 46 → 49. **Pinned:** `tests/test_r1_seams.py:230`, `tests/test_r2_seams.py:576`,
   `tests/test_r3_seams.py:896`, `tests/test_r11_1_seams.py:137`, and `RISK_OF` / `TOOL_OF` / `EXPECTED` in
   `tests/test_permissions_policy.py`.
7. Keyring purposes 18 → 21. **Pinned:** `tests/test_r3_seams.py:838` (the whole set),
   `tests/test_r11_seams.py:162`, `tests/test_book_gen_code.py:170`.
8. `jarvis.mobile.ports` (`MobilePart`, `MobileContext`, `PARTS`, `TOOL_FAMILIES`, `ROUTE_PREFIX`,
   `COLLECTIONS`, `PhoneHandler`), `jarvis.vision.results` (the Result schemas of D13), `console-vision.js`
   (the port's core, no task), `api/r7_wiring.py` (a part that breaks its contract is
   left out; the others run), stub packages and routes, slots in `api/app.py`, `tools/setup.py` (`r7=`),
   `api/personal.py`. In `api/app.py` also: a slot for the app-lock middleware beside R6's show lock (inside
   the session middleware, as that one is) and body caps for `/phone/v1/inbox` (10 MB) and `/app/share/in`.
   **Pinned:** `tests/test_r11_1_seams.py:239` (`app.py` ≤ 730; it is 725 now) and `tests/test_r11_wiring.py:276`
   (≤ 750).
9. The door's fake and the contract: `docs/plans/r7-integration/phone-contract.md`,
   `tests/fixtures/r7/phone_vectors.json`, `tests/r7_fakes.py`.
10. Console. First **free about 19 lines of `console.html`** by letting `console-dock.js` build the More sheet's
    entries from the dock (same order, same words, same markup, proved by a before-and-after comparison in the
    browser). Then add: the manifest link, the Camera dock button and its panel section, the loader
    `console-r7.js`. **Pinned:** `tests/test_r11_1_seams.py:240` (≤ 796 lines), `tests/test_r6_wiring_seams.py:204`
    and `tests/test_r11_wiring.py:293` (< 800); the dock count 21 → 22 and "Helpers is the last tab" in
    `tests/test_console_assets.py:506–507`, `tests/test_arch_coverage.py:529`,
    `tests/browser/test_dock_fit.py:478`; `APP_ASSETS`;
    `tests/browser/ui_checks.py` `PANELS`. If the More-sheet change proves risky, the fallback is a Camera
    sub-tab in Helpers and only two new lines.
11. CSP: `manifest-src 'self'`. **Pinned (exact string):** `tests/test_console_assets.py:20–26`,
    `tests/test_media_console.py:37–38`, `tests/test_r3_seams.py:1050`, `tests/test_wakeword_assets.py:191`.
    `api/console.py`: a versioned route for `static/vendor/vision/<release>/<name>` whose allow-list is Part B's
    `MANIFEST.json`; the CSP header on worker scripts; and `GET /` answers 302 to the same address without
    `do` and `open` when the browser marks the visit cross-site (D8). Only those two words are dropped: the
    sign-in's own `?reauth=…` returns from Google and must keep working.
12. Helpers: a fifth sub-tab "Watch" that is not an R11 part. **Pinned:** `tests/test_r11_seams.py:258`
    (`TABS == PARTS`).
13. Voice: `JarvisVoiceLoop.start()` (refuses while the mic is locked; never unlocks); the new multi-word
    phrases ("cameras off") in `voice/commands.py`. **Pinned:** `tests/test_r5_seams.py:118` (the camera file
    becomes the second and only other place `getUserMedia(` may appear) and `:171–176`.
14. `console.js`: a 423 answer is read by its code (`show_locked` goes to the show, `device_locked` to the
    unlock cover); today every 423 goes to the show (`console.js:78`).
15. `telegram/service.py`: the stranger hook (`/start <word>`, `/stop`); the rest of the file is untouched.
16. `.github/workflows/android.yml`; `.gitignore` (`android/local.properties`, `*.jks`, `*.keystore`,
    `android/**/build/`, `.gradle/`); the Gradle wrapper fetched from Gradle's GitHub tag and checked by the
    workflow's wrapper validation.
17. The guide: cards C62 "Phone app and the phone's door", C63 "Camera and vision engine", C64 "Watch and
    sleep", C65 "Emergency SOS" (PLANNED until I1), technology rows (Trusted Web Activity, MediaPipe,
    Tesseract, zxing, Health Connect, Kotlin and Gradle), the corrected "Mobile" departure, the roadmap.
    `scripts/arch_coverage.py` and `scripts/check_doc_versions.py` pass.
18. `evals/r7/run.py` with stub parts `shell`, `vision`, `phone`, `body`, `needles` and I0's own built part
    `contract`; `docs/plans/r7-integration/BRIEF-COMMON.md`.
19. Persona and its version stay as they are until I1 (16 test files pin `p11.0` today).

## Tests and evals per part (mock; each control must make its suite fail)

| Part | Must prove | Negative control |
|---|---|---|
| A | The manifest parses and has the fields Chrome needs; the CSP has `manifest-src 'self'` and nothing else new. Launch words: only the four; an unknown one is ignored; `do=talk` never unlocks a locked mic and does not listen in an ordinary tab; `do=look` opens the panel with the camera OFF; a cross-site visit loses `do` and `open` and keeps `reauth`; the words are gone from the address afterwards. Share: a form post of two files gives two tray items and a 303; a sixth item, an 11 MB file and a `.exe` are refused in plain words; **no request leaves the browser until a button is pressed** (a network spy); with no worker the server discards the body unread. A push click opens the right panel. | the allow-list switched off; the worker made to upload at once |
| B | Only `console-camera.js` asks for a camera (static). Locked: no live track, and `unlock()` from script is false. A hidden page stops the camera. The chip shows whenever a track is live. A use case never receives a frame (shape and static test). **During a look and a live run no request body contains picture bytes** (a planted pixel pattern, the spy, and zero calls to upload routes). `text` reads the numbers on a label drawn in the test; `code` reads a QR drawn in the test; a result outside its schema is dropped; kept results are sealed; "cameras off" in 20 phrasings locks, and "turn the camera on" by voice does not unlock. Every vendored file matches its recorded hash. With the two models absent, `pose` and `objects` say "not installed". | an upload added to the look path; the lock check removed; schema checks off |
| C | The link code's rules (10 minutes, once, 5 tries); linking needs a passkey or a fresh sign-in, and refuses another package name, a malformed key or a malformed fingerprint. Every vector verifies; a wrong key, a changed body, a stale time, a replayed nonce, an unlinked phone and an unknown route each get a bare 401 or 404 and no audit line. The door reaches no `/v1` route and sets no cookie. Asset links list linked phones only and the one relation. Unlink closes the door at once. "Sign out everywhere" ends an older cookie within 3 seconds. App lock: 423 after the idle time, SOS and unlock exempt, the passkey bound to that session, another session's proof refused. A fourth phone is refused. | the nonce store off; the signature check off; the lock exempting every route |
| D | Watch intake refuses out-of-range numbers and days outside 35; the stored day is sealed and no value is in a log. Sleep sums across midnight, a nap, two sessions, a time-zone change, and with no stages. Tools speak fixed sentences, need the row, are refused on Telegram without the private switch and are absent for a learning brain; No-AI phrases answer with no provider call. SOS: a contact joins by a word once; a stranger without a word is still rejected and audited; a send reaches each contact once, with the template and a pin; **coordinates appear in no document, log, audit line, Activity row or alert**; the fourth send in an hour is refused; a cancelled countdown makes no request; "I'm safe" follows; no tool and no tainted round can send; the voice command only opens the sheet. | the message built from model text; the location written to the log; the hourly cap off |
| E | `core` on the JVM: the signature string and header equal the shared vectors; the SOS machine sends nothing when cancelled at any point; day builder; "seen" list; launch words. `apk_check.py`: only the allowed permissions and outside-reachable parts, none of the forbidden, `personal` not debuggable, no cleartext, only the placeholder host, no secret shape. Lint clean. The Python-side static tests of the manifest. | a forbidden permission added; a host name written into a source file; a screen marked reachable from outside |
| needles (I1) | After a day of every part on fakes, a scan of every document, log line, audit entry, Activity row, alert text, brief line, Telegram text to the owner and tool result (outside its fence) finds none of: a coordinate pair, a heart-rate value, a contact's phone number, text read from a picture, a picture's pixel pattern. | sealing off; the fence off |

## Acceptance checks

1. The JARVIS icon opens the console full screen with no browser bar; Google sign-in and a passkey approval
   both work inside it.
2. With the app closed an alert arrives; tapping it opens the panel it is about.
3. The Talk tile brings JARVIS up listening in at most two taps.
4. In Camera, a photo of a printed label is read; with mobile data and Wi-Fi off after the page loaded it
   still reads; the line "Pictures sent from this device today" stays at 0.
5. With the two models installed, the live body check runs at 10 looks a second or more on your phone.
6. "Jarvis, cameras off" puts the camera sign out; only a tap brings it back.
7. A photo shared from the Gallery waits in the tray; a PDF shared from DigiLocker (or from Files after you
   download it) becomes a vault proposal.
8. Last night's sleep is in the brief, and "how did I sleep?" answers with the AI off.
9. A test SOS reaches each contact with a map link; a cancelled countdown sends nothing; with the internet
   off the SMS screen opens filled in.
10. From the laptop, "Unlink this phone" and "Sign out everywhere" cut the phone off within seconds.
11. Everything works, or says plainly why not: in No-AI mode, signed out, with no Health Connect, with no
    contact, with no linked phone, past the monthly limit.
12. Unit tests on 3.11 and 3.12, ruff, mypy, the browser suite with the visual gate at both sizes and both
    looks, `make eval-mock` with `r7` gated, the `android` job, `arch_coverage.py`, `check_doc_versions.py`.

## The owner's part

**A · Tell us first (ten minutes; questions 1–4 and 9 below).** Your phone's model and Android version
(Settings → About phone). Your Android Studio version (Help → About). Your watch's model, and whether NoiseFit
shows a "Health Connect" switch. Who your emergency contacts are and whether they use Telegram. Where a PDF
lands when you press the download arrow on a document in DigiLocker (find it in the Files app).

**B · Today, with no app (as soon as Part A is live).**
1. On the phone open JARVIS in Chrome and sign in.
2. Tap ⋮ → "Add to Home screen" → "Install".
3. Open JARVIS from the new icon. Sharing into JARVIS and the long-press shortcuts now work.

**C · Build and install the app (about 30 minutes the first time; your laptop's own internet).**
1. Wait until the builder says "the project is in `C:\Jarvis\android`".
2. Open Android Studio → **Open** → choose `C:\Jarvis\android` → **Trust Project**.
3. Wait for "Gradle sync finished" at the bottom (the first time it downloads about 1.5 GB; 5 to 15 minutes).
   If a blue link says "Install missing SDK package", click it, accept, **Finish**.
4. On the left edge click **Build Variants** and choose **personal** for `app`.
5. Menu **Build → Build App Bundle(s) / APK(s) → Build APK(s)**. Wait for "Build completed".
6. In the small message click **locate**. The file is `app-personal.apk`.
7. Connect the phone by USB, choose "File transfer" on the phone, and copy the file to the phone's Download
   folder. (No USB debugging is needed.)
8. On the phone open **Files → Downloads**, tap `app-personal.apk`. If asked, allow Files to install apps,
   once. If Play Protect asks, choose "Install anyway" (it is your own app; it asks for no SMS or
   accessibility access).
9. Open **JARVIS**. It asks for a link code. On the laptop: JARVIS → Integrations → **Phone app** → **Link a
   phone** → confirm with your passkey → type the 8 characters into the phone.
10. The phone shows a short list; do each line you want: **Notifications** (Allow) · **Watch data** (Health
    Connect opens: allow Steps, Heart rate, Sleep, and "in the background") · **SOS location** (While using
    the app, Precise) · **DigiLocker folder** (pick the folder) · **Talk tile** (Add).
11. Tap **Open JARVIS** and sign in with Google once. The first time you talk, Chrome asks for the
    microphone; the first time you look, for the camera.
12. In JARVIS → Integrations → **Emergency SOS**: type your name as family should see it, add a contact, send
    them the join link yourself, then press **Send a test**.

**D · Updating later.** The builder says "a new project is in `C:\Jarvis\android`". Do steps C2 to C8 again.
The new app installs over the old one and nothing is lost. **Never uninstall JARVIS to update it**: that
throws away the phone's link and you would link again (step C9).

**E · What each prompt means.**

| Prompt | Why | If you say no |
|---|---|---|
| Allow JARVIS to send notifications | Alerts with the app closed | Alerts come on Telegram only |
| Allow (your JARVIS address) to use your microphone (Chrome) | Talking | Typing only |
| … to use your camera (Chrome) | The Camera panel | No camera; shared and picked photos still work |
| Health Connect: Steps, Heart rate, Sleep; background | Watch data and sleep | The Watch tab stays empty; you can type your sleep |
| Location, while using the app | Your place in an SOS | SOS still goes, saying "location not available" |
| Pick a folder | DigiLocker import by itself | Share each document instead |

Battery: nothing listens or runs all the time. The app wakes for a few seconds every 6 hours (watch) and
about every hour (the folder). A live camera look uses the battery like a video call for as long as it runs.

## Needs the owner (safe defaults until answered; none blocks the build)

1. **What is your phone's model and Android version, and is Chrome your browser?** Default built: Android 9
   and newer, with Chrome.
2. **Which Android Studio version did you install (Help → About)?** Default: the project is pinned to Android
   Gradle plugin 9.5.0; if your Studio says it is too old for that, we pin one step lower.
3. **Which Noise watch do you have, and does NoiseFit (Profile or Settings) offer a "Health Connect" switch?**
   Default: the reader is built for anything that writes to Health Connect and says "no watch data yet" until
   some arrives.
4. **Who are your emergency contacts (up to 5), do they use Telegram, and which number should the text
   message go to?** Default: none, so SOS stays off.
5. **Should the SOS text message be sent without your tap?** It needs the SMS permission, which Android
   guards for apps installed by hand, and your plan's SMS charge applies. Default: **no**; your SMS app opens
   filled in and you press Send.
6. **Should SOS work from the lock screen?** Default: **yes** (it shows a countdown and nothing else). Say no
   to require unlocking first.
7. **How long should the SOS countdown be?** Default: 10 seconds from the tile; a 2-second hold and then 5
   seconds inside JARVIS.
8. **Do you want a Play Store listing?** Google charges about ₹2,381 once (its price is 25 US dollars; ₹95.24
   to the dollar is JARVIS's stored rate, so this is an estimate) [S39]; a new personal account must first
   run a closed test with 12 testers for 14 days [S39]; and Health Connect access needs Google's review
   [S20]. Default: **no**; you install the file yourself, free.
9. **Where does your DigiLocker app save a downloaded PDF?** Default: Share → JARVIS always works; the watched
   folder is offered; "all files access" is never asked for.
10. **Should JARVIS on the phone ask for your passkey after 5 minutes away?** Default: **on** in the phone app
    once you have a passkey; off in ordinary browsers. You can switch it off in Privacy.
11. **How long should JARVIS keep watch days and camera results?** Default: watch days 400 days; camera
    results nothing unless you press Keep, then 90 days.
12. **May the paid brain read your sleep and steps when you ask about them?** Default: **yes** for the brain
    that does not learn; never the free brain; never on Telegram.
13. **Should the phone stay signed in longer than 24 hours?** Default: **no**, unchanged; you sign in with
    Google about once a day, two taps.
14. **Is "JARVIS" with the console's own core ring on its dark background right for the app's name and
    icon?** Default: yes.
15. **Is the package name `dev.jarvis.companion` acceptable?** It cannot change later without reinstalling.
    Default: yes.
16. **What should happen when Google's developer check reaches India?** Google says that from 2027 phones
    everywhere will refuse apps from unregistered developers unless they are installed over USB or after a
    one-time "advanced" set-up [S27]. The choices are a free "limited distribution" account (up to 20
    devices, no ID, no fee) or installing over USB. Default: decide then; nothing is needed today.
17. **Which languages should the camera read?** Default: English only. Hindi, Malayalam and Odia can follow
    (2 to 6 MB each).

## Cost (₹; no new paid service, secret or Scheduler job)

| What | Cost | When |
|---|---|---|
| The app, the tile, alerts, sharing, the watch reader, SOS by Telegram | ₹0 | always |
| GitHub Actions for the Android job | ₹0 | free for a public repository [S38] |
| Google Cloud | ₹0 | about 10 to 30 more short requests and a handful of database writes a day, far inside the free allowances |
| "Ask the AI about this photo" | about ₹0.30 a picture | only when you press it; counted against your monthly limit |
| A question about your sleep | a normal reply, about ₹0.17; ₹0 with the AI off | when you ask |
| An SOS text message | your mobile plan's SMS charge, if any | only if you press Send in your SMS app |
| A Play Store listing | about ₹2,381 once (25 US dollars; an estimate) | only if you ask for it (question 8) |
| Mobile data | up to about 35 MB once for the vision files; about 1.5 GB once on the laptop for the Android tools (an estimate) | first use |

Not part of R7 and not costed here: a phone stand, a USB webcam for the desk (R8 and later).

## Risks

- **The watch data may never arrive.** Noise's help page names Google Fit, not Health Connect [S22]; Google
  supports the Fit APIs only until the end of 2026 [S21]. If NoiseFit does not write to Health Connect,
  deliverables 5 and 7 show only what you type. Owner question 3 settles it before the Android work starts.
- **The first Android build is blind.** Nothing here can compile Android code; the first compile is CI's.
  Part E keeps the app thin, pins its versions from the makers' pages at I0, and plans several CI rounds.
- **Your Android Studio may be older than the pinned plugin.** The sync then stops with a plain message;
  question 2 and one lower pin.
- **Chrome's check of the site–app link can lag.** A browser bar may show for a while after linking; nothing
  else is affected. D4 orders things so the first check should pass.
- **Phone makers that kill background apps** delay alerts and the 6-hourly sync. Telegram stays the second
  channel; question 1 tells us the phone.
- **A false SOS frightens your family.** The hold, the countdown, "I'm safe", the test message and the hourly
  cap; voice only opens the screen.
- **A real SOS that does not arrive.** No internet, a silenced Telegram, a flat battery. The SMS screen, the
  112 button, and the plain words that this is not an emergency service.
- **The link code is powerful.** Whoever links a phone can send an SOS in your name and receive your alert
  texts. A passkey or fresh sign-in to show it, 10 minutes, one use, an urgent alert on every link.
- **A launch address from a hostile link.** It can only open a screen (D8); the camera never starts by itself;
  the mic lock never opens.
- **The vision files are heavy** (up to about 35 MB once on the phone) and the two model addresses are "latest"
  only [S23]: they are vendored and hash-pinned, not fetched at run time.
- **Vision is slower in the browser.** Google's own timings are for a native Pixel 6 [S25]; your phone in
  Chrome will be slower. Acceptance check 5 measures it; D13 slows itself rather than freezing the page.
- **Text read from pictures can carry instructions.** It is fenced, and a turn that carries it makes every
  change a card.
- **Google's developer check (2027).** Sideloaded apps from unregistered developers will be refused except
  over USB or after a one-day "advanced" set-up [S27]. A free limited account or USB installs; question 16.
- **The debug key is the app's identity.** If the laptop's `.android` folder is lost, the next build cannot
  update the old app: uninstall, install, link again (five minutes; nothing on the server is lost).
- **Line budgets.** `console.html` is at 795 of 799; I0 must free lines first (seam 10) or use the fallback.
- **Health data and children.** Only the owner's own watch; no other person's Health Connect data is read.

## Deferred (not in R7, and why)

- A native camera screen with MediaPipe's Android library: only if R8's coach needs more speed than Chrome
  gives.
- "Hey Jarvis" with the app closed: needs an always-on microphone service; not without your explicit ask.
- Long-press the power button to talk to JARVIS (Android's assistant slot): a later comfort.
- App Links (JARVIS addresses opening in the app): left out on purpose in D4.
- A signed-in session longer than 24 hours on the phone (question 13).
- Automatic SMS (question 5); a Play Store listing (question 8).
- Hands, face-shape, segmentation and classification tasks; Hindi, Malayalam and Odia reading; seven-segment
  digits for thermometers: R8–R10 add them as tasks behind the same port (Appendix A).
- The vision plug-in on the home laptop's bridge and every fixed-camera use case: R8–R10, after cameras exist.
- Starting the console with no internet at all: needs an offline copy, which R3 deliberately avoided.

## Not verified live (no Android device, no Google or Telegram reach from this workspace)

Each line ends with the exact check you do.

- **The app opens full screen and stays vouched for** on your phone and Chrome. *Check:* acceptance 1; if a
  bar shows, wait 10 minutes, close and reopen.
- **Google sign-in and a passkey inside the app.** *Check:* sign in; approve one card with your passkey.
- **Chrome hands alerts to the app and the kind can be read for the channel** (the tag Chrome passes is not a
  documented format). *Check:* a test alert shows JARVIS's icon; a burglar test lands under "Urgent".
- **`do=talk` starts listening without a tap, and sound plays** in the app's window (Chrome's rule names
  sites "added to the home screen" [S16], not this kind of app). *Check:* the tile; if you must tap once,
  tell us.
- **Chrome reports an app launch as not cross-site**, so D8's server check lets the tile's address through.
  *Check:* same as above.
- **Sharing through the app reaches the small service worker** on your Chrome. *Check:* acceptance 7.
- **MediaPipe and Tesseract under the console's CSP on a phone**, and their speed. Read from the packages, not
  run. *Check:* acceptance 4 and 5.
- **NoiseFit and Health Connect**, the background-read switch on your Android version, and that Health Connect
  shows its permission screen for an app installed by hand (Google's pages describe only Play). *Check:* step
  C10; Health Connect → App permissions lists JARVIS and NoiseFit.
- **Where DigiLocker saves**, whether Android lets that folder be picked (a third-party guide says only
  "saves to your device" [S46]), and whether your DigiLocker shows a Share button on a document. *Check:*
  part A; step C10; acceptance 7.
- **Telegram refuses a bot's first message to someone who never pressed Start** (known behaviour; not re-read
  today), and the join link on a contact's phone. *Check:* step C12.
- **The SMS app opens with several numbers and the text filled in** on your phone. *Check:* acceptance 9.
- **Location speed and accuracy indoors.** *Check:* a test SOS from inside your home; read the "within about"
  figure.
- **SOS over the lock screen and the tile on a locked phone.** *Check:* lock the phone, pull the shade, tap SOS.
- **Play Protect and "restricted settings"** when installing by hand on your Android version (third-party
  reports say Android 15 guards SMS access for such apps [S30]; R7 asks for none). *Check:* step C8.
- **The Android toolchain pins** (plugin 9.5.0, Gradle 9.6.0, `compileSdk` 36) against your Android Studio and
  GitHub's image. *Check:* CI's first green run; your step C3.
- **Whether the builders can read CI's logs from this workspace** (an unauthenticated call to GitHub's API was
  refused). The orchestrator settles it at I0.
- **The two MediaPipe model files' hashes and sizes** (sizes here are from memory, marked "about"), and
  **the object model's licence**: Google's page for it links no model card and names no licence for the file
  [S25]. *Check:* I0 reads the licence where the file is published before it is bundled; if it is not Apache
  or MIT, `objects` stays "not installed" and the plan says so.
- **Battery use** of the 6-hourly and hourly jobs and of a live look on your phone.

## Appendix A · The vision use cases that need no new camera

From `requirements-rows-135-280.json`, rows 214–280: rows 218–280 are 63 use cases. By their "Runs on" remark,
**52 need no new camera** (18 phone photo, 27 phone live, 7 desk camera); 11 run on a fixed camera through the
home laptop and are not listed here (243, 244, 246, 247, 249, 257, 259, 272, 277, 279, 280). Rows 214–217 are
this release's phone camera and share (214, 215) and R8's engine and camera set-up (216, 217). Two rows
outside the range belong here too and are marked †. "Yes?" means the row waits for your yes (equipment or a
person at home who uses it).

What each needs is named by engine task. **Built in R7:** `pose`, `objects`, `text`, `code`, `quality`.
**Later tasks behind the same port:** `hands` (MediaPipe Hand Landmarker), `face-shape` (Face Landmarker: the
shape of a face, never who it is), `segment` (Image Segmenter), `classify` (a small trained classifier),
`measure` (colour, angle, level, rhythm by plain arithmetic), `track` (follow one object), `digits`
(seven-segment numbers). "Own model" means no ready Apache model exists: it needs your labelled photos, or
the paid AI check you press. The last column is the planner's estimate; each release's own plan confirms it.

**Phone, photo (18)**

| Row | Sheet | Use case | Rel. | Yes? | Needs from the engine | Ready with R7's tasks? |
|---|---|---|---|---|---|---|
| 241 | DN-01 Must | Food recognition and meal logging | R9 | | `classify` (own model for Indian dishes), your correction, paid check | No |
| 242 | DN-07 Must | Nutrition-label scanner | R9 | | `text`, `code`, label rules | **Mostly**: reading; the table rules are R9's |
| 245 | DN-10 Must | Balanced-plate coach | R9 | | `segment`, `classify` | No |
| 250 | DN-23 | Known-container fill level | R9 | | `measure`, one calibration per container | No |
| 251 | DN-30 | Grocery basket food-group mix | R9 | | `objects`, `classify` | Partly (`objects`) |
| 252 | DN-09 | Ripeness and visible defects | R9 | | `classify` (own model), `measure` | No |
| 254 | DN-32 | Milk-froth check | R9 | Yes | `segment`, `measure` | No |
| 255 | DN-55 | Fridge door-gasket check | R9 | | `classify` (own model) or paid check | No |
| 256 | DN-87 | Leafy-vegetable trimming yield | R9 | Yes | `segment`, `measure` | No |
| 258 | DN-89 | Cut-fruit browning score | R9 | | `measure` (colour), `quality` | Partly (`quality`) |
| 260 | HC-94 Must | Thermometer screen reader | R10 | | `digits`, `quality` | No: printed-text reading is weak on such digits |
| 261 | HC-20 Must | Fall-hazard photo survey | R10 | | `objects` plus own model (rugs, cables), a checklist | Partly (`objects`) |
| 264 | HC-117 | Sleep-study camera set-up check | R10 | Yes | `quality`, `objects`, `pose` | **Yes** |
| 265 | HC-45 | Peristomal skin tracking | R10 | Yes | `segment`, `measure`; never leaves the phone | No |
| 266 | HC-106 | Hearing-aid placement check | R10 | Yes | `classify` (own model) | No |
| 273 | HC-110 | Head-of-bed angle check | R10 | Yes | `measure` (angle), the phone's tilt sensor | No |
| 274 | HC-115 | Walker brake-lever check | R10 | Yes | `classify` (own model per device) | No |
| 275 | HC-118 | Wheelchair cushion check | R10 | Yes | `classify` (own model) | No |
| 175† | DN-05 Must | Kitchen inventory from a fridge photo | R9 | | `objects`, `text`, `classify` | Partly |

**Phone, live (27): the phone in your hand (5) and the phone on a stand as the workout camera (22)**

| Row | Sheet | Use case | Rel. | Yes? | Needs from the engine | Ready with R7's tasks? |
|---|---|---|---|---|---|---|
| 253 | DN-24 | "What's in this jar?" spoken helper | R9 | | `text`, `objects`, the voice | **Mostly** |
| 267 | HC-82 | Auto-injector training steps | R10 | Yes | `hands`, `classify` (own model) | No |
| 270 | HC-103 | Inhaler spacer training guide | R10 | Yes | `hands`, `classify` (own model) | No |
| 271 | HC-104 | Incentive spirometer logger | R10 | Yes | `track`, `measure` | No |
| 278 | HC-80 | Nebuliser assembly and mask check | R10 | Yes | `objects` / `classify`, `face-shape` | No |
| 218 | HF-38 Must | Warm-up checklist | R8 | | `pose` | **Yes** |
| 219 | HF-24 Must | Resistance-band tracker | R8 | | `pose`, `track` (the anchor) | Partly (`pose`) |
| 220 | HF-01 Must | Personal trainer and form corrector | R8 | | `pose` | **Yes** |
| 221 | HF-04 Must | Yoga and mobility coach | R8 | | `pose` | **Yes** |
| 222 | HF-16 Must | Plank hold and alignment | R8 | | `pose` | **Yes** |
| 223 | HF-22 Must | Workout-space clearance | R8 | | `objects`, `pose` | **Yes** |
| 225 | HF-94 | Cycling cadence meter | R8 | Yes | `pose`, `measure` (rhythm) | Partly |
| 226 | HF-07 | Single-leg balance | R8 | | `pose` | **Yes** |
| 228 | HF-08 | Shadowboxing tracker | R8 | | `pose` at a high rate | **Yes**, if the phone is fast enough |
| 229 | HF-12 | Barbell path tracker | R8 | Yes | `track` | No |
| 230 | HF-13 | Agility cone timer | R8 | Yes | `track`, `pose` | Partly |
| 231 | HF-34 | Pilates sequence | R8 | | `pose` | **Yes** |
| 232 | HF-35 | Tai-chi sequence | R8 | | `pose` | **Yes** |
| 233 | HF-116 | Battle-rope symmetry | R8 | Yes | `pose`, `measure` (rhythm) | Partly |
| 234 | HF-117 | Medicine-ball hit counter | R8 | Yes | `objects` (ball), `pose` | **Mostly** |
| 235 | HF-06 | Jump height and landing | R8 | | `pose` at a high rate | **Yes**, if the phone is fast enough |
| 236 | HF-09 | Dance synchronisation | R8 | | `pose`, the music's beat | Partly |
| 237 | HF-113 | Handstand hold | R8 | | `pose` (upside down: to be tried) | To be tried |
| 239 | HF-99 | Kettlebell swing | R8 | Yes | `pose`, `track` | Partly |
| 240 | HF-70 | Assisted stretching with a partner | R8 | Yes | `pose` for two people (the model follows one [S24]) | No |
| 263 | HC-101 | Six-minute walk lap counter | R10 | | `pose`, `track` | Partly |
| 269 | HC-06 | Sit-to-stand test | R10 | | `pose` | **Yes** |

**Desk camera (7 + 1†).** Your laptop has no camera: each of these also runs on the phone on a stand until a
USB webcam exists, because the engine is the same web code.

| Row | Sheet | Use case | Rel. | Yes? | Needs from the engine | Ready with R7's tasks? |
|---|---|---|---|---|---|---|
| 224 | HF-25 | Gesture reaction game | R8 | | `hands` | No |
| 227 | HF-21 | Seated fitness coach | R8 | | `pose` (upper body) | **Yes** |
| 238 | HF-47 | Breath-pacing companion | R8 | | `pose` (shoulders), `measure` (rhythm) | Partly |
| 248 | DN-06 | Water-intake logger at the desk | R9 | | `hands`, `objects` (cup, bottle), `face-shape` | Partly |
| 262 | HC-86 | Blood-pressure posture coach | R10 | | `pose`, `objects` | **Yes** |
| 268 | HC-17 | Hand and finger exercise game | R10 | | `hands` | No |
| 276 | HC-19 | Reach-and-grasp scoring | R10 | | `hands`, `objects` | No |
| 181† | HF-02 Must | Posture checks at the desk | R8 | | `pose` | **Yes** |

**What this tells R7.** Of the 13 "Must" rows above, 6 are ready on `pose` and `objects` alone (218, 220, 221,
222, 223, 181†), which is why R7 ships `pose` live and measures its speed on your phone now. The kitchen and
care "Musts" need `classify`, `segment` or `digits`, and several need models that do not exist under an open
licence for Indian food or for these devices: R9 and R10 must budget for your labelled photos or the paid
check, and the port (D13) already has the place for both.

## Sources (every one read on 12 Nov 2026)

| # | What | Address |
|---|---|---|
| S1 | Google, OAuth 2.0 policies, "Use secure browsers" (updated 5 Aug 2026) | https://developers.google.com/identity/protocols/oauth2/policies |
| S2 | Google Developers Blog, embedded webviews blocked from 30 Sep 2021 | https://developers.googleblog.com/upcoming-security-changes-to-googles-oauth-20-authorization-endpoint-in-embedded-webviews/ |
| S3 | Android, "Authenticate users with WebView" (updated 26 Feb 2026) | https://developer.android.com/identity/sign-in/credential-manager-webview |
| S4 | Capacitor v8 configuration (`server.url`, `server.hostname`) | https://capacitorjs.com/docs/config |
| S5 | npm registry: Capacitor 8.6.0, tasks-vision 1.2.3, tesseract.js 7.0.0, tesseract.js-core 6.1.2, zxing-wasm 3.1.6, capacitor-health-connect 0.7.0; three packages downloaded and read | https://registry.npmjs.org/ |
| S6 | Chrome, Trusted Web Activity overview | https://developer.chrome.com/docs/android/trusted-web-activity |
| S7 | Chrome, Trusted Web Activity integration guide (asset links) | https://developer.chrome.com/docs/android/trusted-web-activity/integration-guide |
| S8 | Chrome, passing information with query parameters | https://developer.chrome.com/docs/android/trusted-web-activity/query-parameters |
| S9 | Chrome, Web Share Target in a Trusted Web Activity | https://developer.chrome.com/docs/android/trusted-web-activity/web-share-target |
| S10 | Chromium, "Android Web App Architectures (WebAPK and TWA)" | https://chromium.googlesource.com/chromium/src/+/main/components/webapps/docs/android_architecture.md |
| S11 | android-browser-helper 2.7.4: README, `LauncherActivity`, `DelegationService`, build file | https://github.com/GoogleChrome/android-browser-helper |
| S12 | AndroidX reference, `TrustedWebActivityService` | https://developer.android.com/reference/androidx/browser/trusted/TrustedWebActivityService |
| S13 | MDN browser-compat-data 8.1.8: PushManager, Notification, SpeechSynthesis, share_target, shortcuts, BarcodeDetector | https://github.com/mdn/browser-compat-data |
| S14 | Chrome, Web Share Target | https://developer.chrome.com/docs/capabilities/web-apis/web-share-target |
| S15 | MDN, "Making PWAs installable" (6 Oct 2026); MDN, CSP `manifest-src` | https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable · https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/manifest-src |
| S16 | Chrome, autoplay policy | https://developer.chrome.com/blog/autoplay |
| S17 | Android, Health Connect: get started (updated 21 Oct 2026) | https://developer.android.com/health-and-fitness/guides/health-connect/develop/get-started |
| S18 | Android, Health Connect: read data (updated 9 Oct 2026) | https://developer.android.com/health-and-fitness/guides/health-connect/develop/read-data |
| S19 | Android, Health Connect: sleep sessions (updated 21 Oct 2026) | https://developer.android.com/health-and-fitness/guides/health-connect/develop/sleep-sessions |
| S20 | Android, declare access to Health Connect data types (Play); Play policy FAQ | https://developer.android.com/health-and-fitness/guides/health-connect/publish/declare-access · https://support.google.com/googleplay/android-developer/answer/12991134 |
| S21 | Android, Google Fit migration guide: Fit APIs "supported until the end of 2026" (updated 10 Sep 2026) | https://developer.android.com/health-and-fitness/guides/health-connect/migrate/migration-guide |
| S22 | Noise support: the watch "can sync with Google Fit via NoiseFit app"; the NoiseFit Play listing (updated 9 Oct 2026) names no Health Connect | https://support.gonoise.com/support/solutions/articles/47001189233-does-the-watch-sync-with-any-other-app- · https://play.google.com/store/apps/details?id=com.noisefit |
| S23 | Google, MediaPipe Pose Landmarker and its web guide (updated 11 Nov 2026) | https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker · https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/web_js |
| S24 | Model card, BlazePose GHUM 3D (16 Apr 2021) | https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf |
| S25 | Google, MediaPipe Object Detector (updated 11 Nov 2026) | https://developers.google.com/edge/mediapipe/solutions/vision/object_detector |
| S26 | Google, ML Kit terms (updated 14 May 2025) | https://developers.google.com/ml-kit/terms |
| S27 | Android, developer verification FAQ (updated 30 Sep 2026); Android Developer Console help | https://developer.android.com/developer-verification/guides/faq · https://support.google.com/android-developer-console/answer/16561738 |
| S28 | Google Security Blog, Play Protect pilot and its four permissions | https://security.googleblog.com/2024/02/piloting-new-ways-to-protect-Android-users-from%20financial-fraud.html |
| S29 | TechCrunch, the pilot in India (3 Oct 2024) | https://techcrunch.com/2024/10/03/google-pilots-blocking-some-sideloaded-apps-in-india |
| S30 | textbee (third party), Android 15 and SMS access for apps installed by hand | https://textbee.dev/blog/android-15-send-sms-permission-guide |
| S31 | Android, location permissions (updated 28 Oct 2026) | https://developer.android.com/develop/sensors-and-location/location/permissions |
| S32 | Android, Quick Settings tiles (updated 28 Oct 2026) | https://developer.android.com/develop/ui/views/quicksettings-tiles |
| S33 | Android, restrictions on starting a foreground service from the background (updated 28 Oct 2026) | https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start |
| S34 | Android, access documents and other files (folder grants and their limits; updated 28 Oct 2026) | https://developer.android.com/training/data-storage/shared/documents-files |
| S35 | Android, sign your app (the debug certificate; updated 6 Mar 2026) | https://developer.android.com/studio/publish/app-signing |
| S36 | Android Gradle plugin 9.5.0 release notes (updated 5 Nov 2026) | https://developer.android.com/build/releases/gradle-plugin |
| S37 | GitHub runner image Ubuntu 24.04, version 20261101.360.1 | https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md |
| S38 | GitHub, Actions billing (free for public repositories) | https://docs.github.com/en/billing/concepts/product-billing/github-actions |
| S39 | Google Play Console help: registration fee; testing rules for new personal accounts | https://support.google.com/googleplay/android-developer/answer/6112435 · https://support.google.com/googleplay/android-developer/answer/14151465 |
| S40 | Android, Keystore system (updated 23 Oct 2026) | https://developer.android.com/privacy-and-security/keystore |
| S41 | Android Open Source Project, privacy indicators (updated 9 Oct 2026) | https://source.android.com/docs/core/permissions/privacy-indicators |
| S42 | Android help, "Get help in an emergency using your Android phone" | https://support.google.com/android/answer/9319337 |
| S43 | Telegram, bot features (links and the start word); bots FAQ (limits) | https://core.telegram.org/bots/features · https://core.telegram.org/bots/faq |
| S44 | Not conclusive: a third-party page saying NoiseFit's Android path is Google Fit, not Health Connect | https://sahha.ai/integrations/noisefit/ |
| S45 | Not conclusive: Google Fit help, "Sync Fit with Health Connect" (a possible detour for the watch's data) | https://support.google.com/fit/answer/12830119 |
| S46 | Not conclusive: a third-party guide to DigiLocker's download ("saves to your device"; no folder named) | https://www.cars24.com/article/download-driving-licence-via-digilocker-guide/ |
| S47 | AndroidX source (the tip of `androidx-main`, not a release): the manifests that WorkManager, AndroidX core and the Health Connect client merge into an app; android-browser-helper's manifest | https://github.com/androidx/androidx/blob/androidx-main/work/work-runtime/src/main/AndroidManifest.xml · https://github.com/androidx/androidx/blob/androidx-main/core/core/src/main/AndroidManifest.xml · https://github.com/androidx/androidx/blob/androidx-main/health/connect/connect-client/src/main/AndroidManifest.xml · https://github.com/GoogleChrome/android-browser-helper/blob/main/androidbrowserhelper/src/main/AndroidManifest.xml |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 12 Nov 2026, 07:28 IST | R7 | First edition: goal and limits, the eight deliverables mapped, findings from the code with file:line, the decision record for the shell with its evidence table (a Trusted Web Activity inside a small native app, not Capacitor), D0–D26, data model, modules, server changes, the A–E split with each part's files, the I0 seams with every pinned test they touch, tests and evals with negative controls, acceptance, the owner's numbered steps, 17 owner questions with safe defaults, cost in ₹, risks, what is deferred, what is not verified live, Appendix A (52 vision use cases that need no new camera) and the sources | 🛠 Mark XV |
