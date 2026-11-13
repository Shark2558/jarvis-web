Version v7.0.5 · 13 Nov 2026, 23:20 IST · Release R7 · Status: Ready · Owner: 🛠 Mark XVII

# Release R7 — Mobile, watch & phone camera (`v7.0.0`)

**Phase:** 6 (mobile app and wearable), reusing Phase 1 (voice) and laying Phase 5 groundwork (vision); Phase 7
evals. **Type:** free: ₹0 a month, no new paid service, no new secret, no new Cloud Scheduler job, no Firebase.
**Branches:** I0 `r7-i0` (G0 met: `main` @ `5519e2d`, R11.1 live as v11.1.1, merged into `r7-i0` by a merge
commit) → parts `r7-a` … `r7-e` → integration `r7-i1` → one PR `v7.0.0 · R7 Mobile, watch & phone camera · Mark XVI`.
Every commit carries `JARVIS-Version: v7.0.0` and `JARVIS-Mark: XVI`. The code facts were re-read on `main` @
`5519e2d` for v7.0.4 (I0's notes: `docs/plans/r7-integration/I0-NOTES.md`), after the fresh-context review
`docs/plans/r7-integration/PLAN-REVIEW-1.md`. This document is the plan; I0's seams are built on `r7-i0`.

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
3. The watch's sleep and heart rate are not proven yet. NoiseFit DOES write steps and calories into Health
   Connect on your phone (your check, 13 Nov 2026, 15:19 IST). There is no sleep entry from it yet, because
   the watch was not worn overnight. Until a NoiseFit sleep or heart-rate entry appears, those two stay
   marked "Needs you first" (they wait for your check). The watch's steps and the phone's own steps and sleep
   arrive now.

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
| 8 | On-device vision groundwork | One vision engine with five tasks and a contract for later use cases; no use case itself: the 24 that need only your phone in your hand come in R9 and R10 (D13, D14; Appendix A) | B |

Not in this plan:

- An iPhone app.
- A native camera screen, and Google's ML Kit (D14).
- "Hey Jarvis" while the app is closed or the screen is dark (D9).
- Any fitness, kitchen or care use case itself: those are R8, R9 and R10; R7 builds what they stand on.
- Cameras that reach JARVIS through the home laptop.
- A Play Store listing, and sending the SOS text message without your tap (owner questions 5 and 8).
- Reading other apps' notifications or messages, ever.

## Gate G0 · R11.1 first

**Met.** R11.1 is merged and live: `main` @ `5519e2d` (v11.1.1: R11.1, its integrated fixer's last fifteen
commits and hotfix 1). On 13 Nov 2026 I0 merged `main` into `r7-i0` (which held this plan's own commits, cut
from `r11-1-i1` @ `bbe056d`) by a merge commit. Nothing was rebased or force-pushed.

R7 builds on R11.1's picture path (`documents/pictures.py`, `documents/imagecheck.py`, `console-r111-files.js`)
and touches files R11.1 changed (`console.js`, `console-attach.js`, every `console-voice*.js`, `core/prompts.py`).
Every file:line below was re-checked on `main` @ `5519e2d` for v7.0.4; the lines R11.1's fixer and hotfix 1
moved are corrected, and I0-NOTES.md lists each one.

## What exists today (`main` @ `5519e2d`, before I0)

1. **Sign-in.** Google only, owners only: `api/auth.py:185–190` sends the browser to Google and `:194–226`
   checks the verified e-mail against the owner list. The session is the signed cookie `jarvis_session`,
   `SameSite=Lax`, Secure, 12 hours sliding (`config.py:90`, `api/app.py:558–569`) and 24 hours at most
   (`api/auth.py:41`). A cookie write needs the header `X-Requested-With: JARVIS` (`api/auth.py:36–37`, `:111`);
   no CORS headers are served (`:9–10`). The page signs in with `location.href = '/auth/login'`
   (`console.js:124`).
2. **Passkeys.** The relying party is the server's own host and ONE expected origin
   (`permissions/ceremony.py:65–81`, `:154–155`, `:188–189`); the page uses the browser's own
   `navigator.credentials` (`console-permissions.js:63–64`, `:91`). Final actions, the vault, disarming and the
   build book all hang on it (`console-permissions.js:126–133`).
3. **Content security policy.** `api/console.py:194–199`: `default-src 'none'`; scripts and connections from
   the server itself only (plus `'wasm-unsafe-eval'`); `img-src 'self' data:`; `worker-src 'self'`; no
   `manifest-src`, no `media-src`. The exact string is pinned by four tests (`test_console_assets.py:22–27`,
   `test_media_console.py:36–40`, `test_r3_seams.py:1058–1060`, `test_wakeword_assets.py:189–192`; I0 seam 11).
4. **Not installable.** Nothing under `src/jarvis/api/` serves a web app manifest or an icon; `console.html:5–8`
   has only the viewport and the theme colour `#04070D`.
5. **Alerts.** Web Push is built (`webpush/service.py`; at most 5 devices, `notify/ports.py:39`; the allowed
   push hosts include `fcm.googleapis.com`, `webpush/endpoints.py:15–18`). The service worker `console-sw.js`
   has a push and a click handler, scope `/static/push/` and no fetch handler (`console-sw.js:1–5`). The payload
   is `{kind, text, url}` (`webpush/service.py:68–74`) with `url` `/#home` or `/`, but **no console script reads
   `location.hash`**: a tapped alert opens the console, not a panel. The click handler cannot carry a target
   either: the address check (`console-sw.js:13`) refuses a `?`, so `?open=home` falls back to `/`; and
   `navigate()` (`:31`) fails on a window this worker does not control (every console window, since its scope
   is `/static/push/`), so a tap opens a second JARVIS window. There are 38 alert kinds (`alerts.py:21–74`),
   R11.1's two among them: `series_checkin` (important; it rings by day) and `faces_to_name` (info). Telegram
   is the second channel, to the paired owner only (`telegram/alerts.py:44–57`). Two lists decide what has no
   off switch and what is never capped: `NO_SWITCH` (`notify/models.py:20`) and `NO_CAP_KINDS`
   (`notify/telegram_out.py:45`, today only `home_hazard`).
6. **Voice.** The microphone has one door, `console-voice-capture.js` (`getUserMedia` at `:154`), with the hard
   "mic off" lock that only a real tap opens (`:88`, `:118–123`). A turn starts in `press()`
   (`console-voice-mic.js:426`); `window.JarvisVoiceLoop` (`:663–670`) offers `state, inConversation, say,
   ask, offer, end` and **no way to start a turn**. On a phone the conversation ends when the page is hidden
   (`:633–634`). "Hey Jarvis" runs inside the page (its model files: `api/console.py:180–184`). R5's plan (D14)
   already lists Android's limits: no output switching, a chiming recogniser.
7. **Camera.** None. No console file opens a camera: `getUserMedia(` exists only in the voice capture file
   and `tests/test_r5_seams.py:118` pins that. The package `jarvis.camera` is the home burglar alarm.
8. **Pictures to the brain** (built by R11.1). An attached picture is cleaned and **kept as cleaned bytes
   beside its file until the conversation is deleted** (`documents/service.py:19–21`, `:374–381`;
   `documents/pictures.py:4–11`). It is never written into a turn and never sent with a later one. JPEG and PNG
   only, at most 2,048 px a side (`documents/imagecheck.py:13–14`; the console shrinks to 1,568 px first),
   at most 900 KB after cleaning (`config.py:478`), at most 4 a turn (`documents/pictures.py:50`). Only a
   brain with `BrainSpec.sees_pictures` gets them (it reads pictures and never learns); any other brain gets
   one fixed line instead. The console's brain detail does not say which brain sees (`{id, label, trains,
   tools}`, `console.js:53`). A picture turn's guard (`picture/turnguard.py`) refuses `research_person` and
   `web_search` with a face's name. A new permission row "Pictures" (R1, `picture_*`) holds the tool
   `picture_research`. `photos/imaging.py:20`, `:67` strips a JPEG's camera and location data.
   In the console the send path is `JarvisAttach` (`console-attach.js:13`, `:244`; it has no `add(files)`
   today) and R11.1's `JarvisFixes.parts.files` with `shrink` and `cost` (`console-r111-files.js:184`, `:310`).
9. **Files and the vault.** Attach in the composer (`console.html:165–168`); vault upload `POST /v1/vault/upload`
   (`api/vault.py:202`); DigiLocker comes through a Drive folder read by a tick job
   (`vault_inbox/service.py:1–24`) into `VaultIntake.intake` (`vault/ports.py:16–36`): PDF, JPEG, PNG, ≤ 10 MB.
10. **Telegram's front door.** Only the paired owner reaches the brain; a stranger may only pair with
    `/start <code>` and is otherwise turned away and audited (`handle()`, `telegram/service.py:144–167`, turns
    any non-owner away at `:155–158` unless `_is_pairing_attempt` (`:178–188`) is true; `_stranger()`,
    `:310–325`, then sends the word to `finish_pairing` at `:317`). JARVIS has never written to anyone but you.
11. **Cutting sessions off.** R6 keeps a "sessions valid after" mark per owner that ends every older cookie
    on every route within 3 seconds (`api/book_lock.py:188–202`; `buildbook/lock.py:42`, `:112`). Only the
    build book's Resume sets it today.
12. **Health words already taken.** `jarvis.health` is JARVIS's own systems check and `jarvis.vitals` its keys
    and limits. Nothing reads a watch; R11's `wellbeing/{uid}_{date}` holds water and stand-ups.
13. **Line budgets.** `console.html` 795 lines, pinned at **≤ 795** (`test_r11_1_seams.py:244`), so every
    added line fails until seam 10 frees lines and moves the pin; `console.js` 753 (every console file ≤ 800);
    `core/brain.py` 704 (pinned ≤ 770); `api/app.py` 732, pinned ≤ 735 (`:243`; the older guards 750); the dock
    has 21 tabs; `tools/gateway.py` is frozen at 760. After I0: `console.html` 782 (pinned ≤ 782), `console.js`
    761, `api/app.py` 735, the dock 22 tabs.
14. **Release naming.** The build book names the release from the highest-numbered plan file
    (`buildbook/gen/plans.py:76–78`, and the fallback's `_label`, `buildbook/gen/fallback.py:81–84`), and reads
    the plans in that order (`plan_paths`, `plans.py:61–73`). That would stay "R11.1" after R7 ships (I0
    seam 2).
15. **This workspace** (measured again 13 Nov 2026 at I0, one request each). JDK 21, Gradle 8.14.3 and Node 22
    are installed; there is no Android SDK. Reached: npm (200), PyPI (206), raw.githubusercontent.com (206,
    which is where I0 took the Gradle wrapper from Gradle's own tag `v9.6.0`) and `git ls-remote` to GitHub.
    **Refused:** dl.google.com, maven.google.com, services.gradle.org, plugins.gradle.org,
    repo.maven.apache.org, repo1.maven.org, cdn.jsdelivr.net and developer.android.com (no connection), and
    storage.googleapis.com (where MediaPipe keeps its model files) and github.com's release pages (403). So no
    Android build, no Gradle distribution checksum and no model download can happen here.

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
| Watch data through Health Connect | L6 Integration, L7 sealed · Health & Wellbeing | 6 | Build now; NoiseFit's steps (and calories) and the phone's own steps and sleep arrive now; the watch's sleep and heart rate are "Needs you first" until a NoiseFit entry is seen |
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
Android build exists. Two side effects are known. The web app Chrome installs (a WebAPK) catches JARVIS
addresses tapped in other apps and opens them in its own window. And once the real app is installed (step C)
there would be two JARVIS icons. So the Chrome-installed one is removed after linking (step C13).

**D4 · The site and the app vouch for each other; nothing else is trusted.** `GET /.well-known/assetlinks.json`
(public, `application/json`, no redirect, cached 60 s) lists, for each LINKED phone (D5), the app's package name
`io.github.shark2558.jarvis` and the SHA-256 fingerprint of the key that signed it, with the single relation
`delegate_permission/common.handle_all_urls` [S7]. No login-sharing or message-channel relation is granted.
The app's own half is built from the same address at build time. The app opens the console **only after it is
linked**, so the first check ever made finds the entry. R7 declares **no App Links**: JARVIS addresses tapped
in other apps keep opening in the browser, the app accepts no web link from another app, and Android runs no
early check that could cache a "no". (The WebAPK of D3 is Chrome's, not this app's, and does catch such links
until it is removed: D8 is written so that this can only open a screen.) If the check fails, Chrome shows its
bar and everything else still works.

**D5 · Linking a phone: a one-time code and a key that cannot leave the phone.** Integrations → Phone app →
**Link a phone** asks for your passkey (or, with no passkey yet, a Google sign-in under 5 minutes old) and
shows an 8-character code: 40 bits, 10 minutes, single use, stored as a hash, void after 5 wrong tries (the
R1 and R3 pairing rules). The app makes a P-256 key pair inside the phone's secure hardware (Android Keystore:
"the key material remaining non-exportable" [S40]) and sends `POST /phone/link {code, public key, package,
signing fingerprint, model word, app version}`. The server accepts only the one package name,
`io.github.shark2558.jarvis` (owner question 15, adopted by default on 12 Nov 2026; it follows GitHub's
reverse-domain form; you may still object before the first install, after which a change means a reinstall and
a new link), a fingerprint of exactly 32 bytes and a valid P-256 public key; it stores only public things and returns
a device id `ph_<12 hex>`. At most 3 phones (`phone_link_max`). Every link sends the alert `phone_linked` to every channel
("A phone was linked to JARVIS at 14:05. If this wasn't you, unlink it in Integrations."). **Unlink** stops
the phone at once.

**D6 · The phone's door: four signed routes and nothing else.** Each request carries `X-Jarvis-Phone:
v1;d=<device id>;t=<unix seconds>;n=<16 random bytes>;s=<ECDSA P-256 / SHA-256 signature>` over
`"jarvis-phone-v1\n" + device id + "\n" + t + "\n" + n + "\n" + METHOD + "\n" + path + "\n" + hex(sha256(body))`
(R3 D5's scheme with a public key instead of a shared secret, so the server holds nothing worth stealing).
Checked in this order before any parsing: the route is one of the four (else 404) → the address carries no
query string at all, else 401 (the signature covers only the path, so anything in a query would be unsigned
input) → the body is under its cap → the header's shape → the device is known and not unlinked →
`|now − t| ≤ 120 s` → the nonce is unseen for 10 minutes (in process; one instance) → the signature → 30 requests a minute per phone. Any failure is a bare
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
from the address. Anything else is ignored. **`do=talk` never starts the microphone by itself, anywhere.** It
opens JARVIS with the mic button ready ("Tap to talk", focus on the composer's mic button), and your tap
starts the turn through R5's own `press()`. It never unlocks "mic off". `do=look` opens the Camera panel;
**the camera itself never starts without a tap on that screen**. `do=sos` opens the SOS sheet, which still
needs your hold (D19). The server drops `do` and `open` when the browser says the visit came from another
site (`Sec-Fetch-Site: cross-site`). Push alerts get a real target per kind (`?open=home`, `?open=approvals`,
…), replacing the unread `/#home`. The push worker's address check learns to accept that `?`, and a tap
focuses the JARVIS window already open and hands it the target over a `BroadcastChannel`, instead of
`navigate()`, which fails on a window the worker does not control and so opened a second window (item 5
under "What exists today").

Why the mic needs your tap even inside the app: any app on the phone can open a JARVIS address. The web app
Chrome installs (D3) catches JARVIS links tapped in, say, WhatsApp and opens them in its own window. And an
exported `LauncherActivity` launches, by default, the address an incoming intent carries. Either way Chrome
reports `Sec-Fetch-Site: none` and the page reports its own window, exactly as for the tile, so no check in
the page or on the server can tell them apart. So: (1) the exported launcher (the icon) overrides
`getLaunchingUrl()` and always opens `/?source=app`, ignoring any address in the intent; (2) the tile and the
shortcuts use a second launcher that other apps cannot start, and only it adds a `do=` word from the
allow-list; (3) whatever arrives, the worst a launch can do is open a screen.

**D9 · Push-to-talk: three doors into the existing voice loop, and no always-listening service.**

| Piece | Native or web | What it does |
|---|---|---|
| The voice loop (listen, think, speak, barge-in, mic off) | Web, unchanged | Everything R5 built; it gains nothing: the tap on the mic button is R5's own `press()` |
| "Talk to JARVIS" Quick Settings tile | Native | Pull down, tap the tile: JARVIS opens with the mic button ready; one more tap and it listens (two taps in all). Android 13+ offers to add the tile for you [S32]; older phones: drag it in once. On Android 14+ the tile opens JARVIS with `startActivityAndCollapse(PendingIntent)` (Android 14 refuses the older form for an app that targets it) |
| App icon shortcuts: Talk, Camera, SOS, Set-up | Native (and in the web manifest) | Long-press the icon |
| "Talk" button on an alert | Web (the push service worker) | Opens JARVIS with the mic button ready |
| A widget, a Talk button kept in the notification shade | Not built | The tile and shortcuts cover it; a kept notification is clutter |
| A microphone service for "Hey Jarvis" with the app closed | Not built | Battery; a microphone that is always on; Android forbids starting such a service from the background [S33]; the wake-word model is for personal use only |

Honest limits: the phone must be unlocked; the first time each day you may have to sign in with Google (two
taps: the session lasts at most 24 hours, unchanged); listening always takes your tap on the mic button (D8),
and that same tap lets Chrome play JARVIS's voice; if Chrome still will not play sound, the first reply shows
its words and a "Tap to hear" chip.

**D10 · Alerts: the same Web Push, shown by the app with three channels.** The server keeps sending as today.
With the app installed and vouched for, Chrome hands each notification to the app's own service
(`DelegationService`, subclassed [S11, S12]), so alerts carry JARVIS's icon and obey JARVIS's notification
settings. That service sorts them into three Android channels by the alert's kind: **Urgent** (burglar,
hazard, disaster, SOS, a phone linked), **Alerts**, **Nudges**; an alert it cannot sort goes to Alerts. It
sorts by the notification's tag, which the push service worker sets to the alert's kind (`tag: kind`,
`console-sw.js:17`); that format is written into `phone-contract.md`, because Part A writes it and Part E
reads it. You set each channel's sound once in Android. Telegram stays the second channel. Android 13+ asks "Allow JARVIS
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
conversation or to the server while you look. Looking at a photo or the live picture produces a **result**
(numbers, short labels from fixed lists, text that was read). A picture reaches the server only when you
press one of:

- **Ask the AI about this photo (about ₹0.30)**: R11.1's picture path. On the phone the picture is shrunk to
  1,568 px and saved as a JPEG; on the server its camera and location data are stripped, and only a brain
  that sees pictures and does not learn gets it. It is **kept with that conversation**, as cleaned bytes,
  until you delete the conversation (item 8 under "What exists today"). The button is offered only when the
  brain answering now sees pictures; otherwise it reads "The brain answering now can't see pictures" and
  sends nothing (I0 adds `sees` to the brain detail, `console.js:53`).
- **Add to my vault** (documents; the usual proposal for you to confirm).
- **Attach to my message** (the paperclip's own path).

All three go through one door that I0 builds, `console-r7-send.js`, over `JarvisAttach.add(files)` (which I0
adds to `console-attach.js`) and R11.1's `shrink` and `cost`. So Part A's share tray and Part B's camera panel
send the same way and count in the same line: "Pictures sent from this device today: 0". A result is kept
only when you press **Keep**; kept results are sealed (`vision_results`, 90 days). Read text is other people's
words: it reaches the brain fenced as data, and a turn that carries it makes every change a card.

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
only. Its module may not use any way to read pixels or send bytes (a static test): `drawImage`,
`getImageData`, `toBlob`, `createImageBitmap`, `captureStream`, `fetch`, `XMLHttpRequest`, `sendBeacon`,
`WebSocket`, `JarvisConsole.api`, `JarvisChat`, a dynamic `import(`, or the storage APIs (`localStorage`,
`sessionStorage`, `indexedDB`, `caches`). So "frames are thrown away" is a property of the code's shape, not
a promise. R7 ships five tasks: `text` (read printed
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
| `text` | tesseract.js 7.0.0 with core 6.1.2, English data from npm `@tesseract.js-data/eng` or GitHub's `tessdata` (both reachable here; jsdelivr is not) [S5] | Apache-2.0 | about 4 MB + 3 MB |
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
discards the body unread and says "Open JARVIS once, then share again." The three send buttons use D12's one
door. A WebP or a full-size photo is never sent as it is, because R11.1 takes JPEG and PNG of at most 2,048 px:
the door first redraws it on the phone as a JPEG of at most 1,568 px (R11.1's `shrink` reads only `.png` and
`.jpg` names today, `console-r111-files.js:23`; I0 lets it take `.webp`). A picture the browser cannot read is
refused in plain words. Signed out, the tray asks the server nothing and keeps `do=shared` items until you
have signed in (the "ask nothing before sign-in" rule of `BRIEF-COMMON.md`).

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
[S18]) and sends per day: steps; heart rate lowest, average and highest; each night's sleep with minutes per
stage; and the name of the app that wrote each. No raw heart samples. "Resting" heart rate is not read: it is
a separate record type (`RestingHeartRateRecord`) behind its own permission (`READ_RESTING_HEART_RATE`), and
"lowest" says enough. The server checks ranges, seals the day with the new key purpose `watch`
(`watch_days/{uid}_{date}`, kept 400 days) and never logs a value. With no background permission, sync
happens when the app is opened and the tab says "Last synced: …".

*Three apps can write the same steps.* Health Connect on your phone lists NoiseFit, Google Fit and one other
app as connected. NoiseFit writes steps and calories (seen 13 Nov 2026, 15:19 IST), and the phone itself
writes steps and sleep (its only sleep entry so far is named "OnePlus 12R"). Adding up raw records would count your steps two or three times,
and "the longest sleep" could pick the phone's guess over the watch. So:

- steps, and heart rate lowest, average and highest, are read with Health Connect's own `aggregate`, which
  removes duplicates by your **App priority** list (owner step A2: NoiseFit first). That the priority list
  also governs heart-rate figures, not only steps, is *unverified*; the JVM tests and your first sync check it;
- sleep is read as sessions, and `core`'s day builder keeps **one writer per night**: NoiseFit before the
  phone, any other app after both (JVM tests, D24);
- the brief and the Watch tab name the writer that was kept ("· from your watch" or "· from your phone").

*The permission screens* are Health Connect's own: one switch per kind of data, then a second screen for "in
the background". Behind its "privacy policy" link the app shows four plain lines (what is read, that only
daily sums leave the phone, where they are kept, how to delete them). Health Connect requires that page [S17]
and opens it itself, so two entries must be reachable from outside the app:

- an activity for `androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE` (Android 13 and older);
- on Android 14 and newer, an activity-alias for `android.intent.action.VIEW_PERMISSION_USAGE` in the category
  `android.intent.category.HEALTH_PERMISSIONS`, guarded by `android.permission.START_VIEW_PERMISSION_USAGE`.

Without them either `apk_check.py` fails the build or Health Connect never asks; D22 lists both.

*Which apps write.* It works with any app that writes to Health Connect. On your phone NoiseFit writes into
Health Connect directly: it was listed as connected on 12 Nov 2026 (08:17–08:25 IST), and on 13 Nov 2026
(15:19 IST) you saw its **steps and calories** there. So the earlier research that the route is only through
Google Fit (Noise's help page [S22], a third-party page [S44]) is superseded. Whether NoiseFit writes the
watch's **sleep and heart rate** is still to be seen: there is no sleep entry yet because the watch was not
worn overnight. Until a NoiseFit sleep or heart-rate entry appears, they stay "Needs you first" (owner
question 3). Calories are not read: R7 reads steps, heart rate and sleep only (D22).
If the app were ever published on Google Play, each kind of data would have to be declared and reviewed, and a
public privacy policy added [S20].

**D18 · Sleep is plain code with fixed sentences, and never advice.** "Last night" is the longest session
ending between 00:00 and 14:00 your time, among the sessions of the one writer the day builder kept (D17); the
week is the average and the spread of bedtimes. Stages are shown only when the watch wrote them [S19]. Tools
`sleep_last_night`, `sleep_week`, `watch_today` are R1 reads under a new row "Watch and sleep"; they answer by
voice and chat, on the No-AI phrases too ("how did I sleep", "steps today"), are private on Telegram
(`watch_*` and `sleep_*` join `PRIVATE_PATTERNS`, I0 seam 21) and are never given to a brain that learns. The
brief gains one line in the console ("Sleep: 6 h 40 min, 23:50 to 06:30 · from your watch", or "· from your
phone"). It is left out of the brief's e-mailed inbox copy and out of Telegram (owner question 19; default
no). A typed "I slept 11:30 to 6" is accepted and marked "typed by you", so the feature is not dead without a
watch. Every sentence is a template; nothing diagnoses or advises treatment; the persona says the numbers are
the watch's or the phone's own estimates.

**D19 · SOS: a held button, a cancel window, a fixed message, and no way for the brain to send it.**
*Who:* up to 5 emergency contacts you add. *Channels, all free:* (1) a Telegram message and a map pin from
your JARVIS bot to each contact who joined (D20), sent by the server; (2) the phone's own SMS app opened with
every number and the message filled in, for you to press Send (no SMS permission; your plan's SMS charge, if
any; works without internet); (3) a notice to you on every channel ("SOS was sent at 14:05 to 3 people"),
which is also how a mis-sent SOS shows; (4) two buttons that open the dialler: your first contact, and 112.
*Message* (code, never a model): "SOS from {your label}: I need help. My location at 14:05:
{maps link} (within about 20 m). Sent by my JARVIS assistant." *Location:* asked for when the screen opens,
10 seconds at most; the message says how accurate and how old the fix is, or "location not available".
The app asks for precise and approximate location in one request, as Android requires. Android's precise
location is "usually within about 50 meters … sometimes as accurate as within a
few meters" [S31]; indoors it can be worse. Coordinates are used once to write the messages and are **never
stored, logged or audited**; the SOS record keeps the time, how many were reached and "location: yes / no".
Coordinates travel **only in a POST body, never in an address**: Cloud Run's request log keeps every address,
so a coordinate in one would be logged (the needles scan reads that log too).
So that the SMS screen works with no internet, the phone keeps your contacts' numbers itself, encrypted with
a key held in its secure hardware.
*No accidents:* inside JARVIS and by voice, a 2-second hold and then a 5-second countdown; from the tile or
the shortcut, a 10-second countdown with sound, vibration and a full-width Cancel. The native SOS screen draws
edge to edge (Android enforces it for an app that targets 36), so the Cancel button is placed inside the
system bars' insets and a test checks it is fully on screen. A cancelled countdown sends nothing at all.
Afterwards **"I'm safe"** tells the same people.

*Limits in code.* A real SOS: 3 an hour, 10 a day. Tests and "I'm safe" have their own budget (`sos_test_per_hour`
3, `sos_test_per_day` 10), so three tests never block a real SOS. A refused or failed send still opens the SMS
screen and the 112 button. *Delivery:* `sos_sent` and `phone_linked` join `NO_SWITCH` (`notify/models.py:20`;
no off switch), and `sos_sent` joins `NO_CAP_KINDS` (`notify/telegram_out.py:45`), like `home_hazard`, so no
Telegram cap can drop your SOS notice.

*Who can trigger:* you, by the web sheet (cookie, CSRF header) or the phone's door. No tool sends an SOS; the
brain's only SOS tool is the read `sos_status`; "Jarvis, SOS" only opens the screen. The native screen works
from the lock screen (it shows a countdown and nothing else; owner question 6). The card, the screen and the
persona all say: this is not an emergency service; call 112; set up Android's own Emergency SOS too (power
button five times, Android 12+ [S42]).

*A deliberate exception to the confirm rule.* An SOS is a send, and JARVIS's rule is that R3 (send, pay,
delete) needs an owner confirmation token. **SOS is not a tool and never passes the gateway.** The hold plus
the countdown is your confirmation (from the tile or the shortcut, the longer 10-second countdown takes the
hold's place). This is a deliberate exception, because asking for a passkey in an
emergency defeats the purpose. It stays narrow: there is no "don't ask again", the brain cannot reach it, and
every SOS is audited without coordinates.

**D20 · SOS contacts join by their own Start; the bot never chats with them.** A Telegram bot's link takes a
start word of up to 64 letters, digits, `_` or `-` [S43]. You add a contact (a label, optionally a phone number
for the SMS screen); JARVIS shows a join link carrying a one-time word (24 hours); you send that link yourself.
When they press Start the bot answers once: "You are now an emergency contact for {label}. This bot writes to
you only when {label} presses SOS or sends a test. Send /stop to leave." `/stop` removes them and tells you
(`sos_contact_left`). Anything else they write gets no reply and never reaches the brain. Contacts are sealed
with the new key purpose `sos`.

The Telegram front door changes in one place only, and it has to be the right place. Today `handle()` turns
any non-owner away (`telegram/service.py:155–158`) unless the message looks like pairing (`/start …`,
`:178–188`), and `_stranger()` then sends the word to `finish_pairing` (`:317`). Left as it is, a contact's
join word would count as a wrong pairing code and could start the owner's pairing cooldown, and a contact's
`/stop` would be turned away before any hook ran. So:

- a join word carries a fixed prefix (`sos-`) and is checked **before** `finish_pairing`, with its own counter
  of wrong words that never touches the pairing cooldown;
- a `/stop` from a known contact is handled **before** the turn-away at `:155–158`;
- the word holds at least 128 random bits and is stored only as `keyring.mac("sos", word)`;
- the code behind the hook lives in `jarvis.sos` (Part D); `telegram/service.py` gains only the hook (I0).

The "paired owner only" rule for everything else is untouched.

**D21 · Sessions, the app lock, and a lost phone.**
- *Where a session lives:* in Chrome's cookie store on the phone (HttpOnly, Secure, signed; 12 hours idle,
  24 hours at most), exactly as when you use JARVIS in the phone's browser today. The app holds no session.
- *The phone key* lives in the phone's secure hardware and opens only the door of D6.
- *App lock:* a switch in Privacy, "Lock JARVIS on this device after 5 minutes away". **Default: ON in the
  installed app once a passkey has been registered from this phone** (the registration ran in a session that
  opened at `/?source=app`, and the server records that). Until then it is OFF, so a passkey that lives only
  on the laptop (Windows Hello) can never lock you out of the phone. OFF in ordinary browsers. (Owner
  questions 10 and 18; owner step C12.) It is enforced by the server, not drawn on top of the page: once the
  session has been idle that long, every route answers 423 `device_locked` until a passkey check bound to that
  session (`device_unlock`). The installed app is known by its start address (`/?source=app`); opening that
  address can only switch the lock ON for the session, never off.
  - *What "idle" means:* no request **you** made. A write (with the CSRF header) counts, and so does a small
    "I'm here" call the page sends at most once a minute after a real tap or key press
    (`navigator.userActivation`). Background requests never count: R6's `/auth/me` recheck on every return to
    the screen (`console.js:692–701`) and panel polls such as the Home panel's (`console-home-panel.js:240`).
    A test holds this: with the Home panel polling and nothing touched, the lock still comes after 5 minutes.
  - *Never locked:* `GET /`, `/static/*`, `/console/config`, `/auth/*`, `POST /v1/passkeys/challenge`, the
    unlock route `POST /v1/session/unlock`, `/manifest.webmanifest`, `/.well-known/assetlinks.json`,
    `/app/share/*`, and the SOS routes.
  - *Order:* the app-lock middleware sits inside R6's show lock, and both sit inside the session middleware.
  - *Two kinds of 423.* Five places in the console treat any 423 as "a guest show is running" and send the
    page to `/book/show`: `console.js:78`, `:101`, `:699` (the `/auth/me` recheck), `:745` (boot), and
    `console-book-talk.js:147`. All five read the `error` code instead: `show_locked` goes to the show,
    `device_locked` to the unlock cover (I0 seam 14). Otherwise a locked app would jump to the show at boot
    and on every return to the screen.
  - *New passkey purposes* `phone_link` and `device_unlock` join `Purpose` and `TARGETED_PURPOSES`
    (`permissions/models.py:79`, `:88`), the exact targets (`permissions/service.py:145–148`) and the page's
    allow-list (`console-permissions.js:131`) (I0 seam 27).
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
location (while in use, for SOS; precise and approximate are requested together, as Android requires), Health
Connect read of steps, heart rate and sleep (plus background read; not resting heart rate, D17), vibrate.
The libraries add a few of their own when the app is built [S47]: the background-work library adds network
state, wake lock, start after reboot and foreground service, and AndroidX core adds one private
permission of the app's own. Each is on the list with its reason, except foreground service, which the app's
manifest removes because JARVIS starts no such service (D9). **Never declared:** read or receive SMS,
notification access, accessibility (the four that make Play Protect block a sideloaded app in India
[S28, S29]), send SMS, camera or microphone (Chrome holds those), contacts, any storage permission, "all
files", draw over other apps, query all packages. No cleartext traffic; system certificates only; backups
off, with `dataExtractionRules` beside it that exclude everything (Android 12 and newer read those rules for
cloud backup and device-to-device transfer). The app never asks for expedited background work: on Android 9
to 11 that runs as a foreground service, which needs the permission the manifest removes.

Reachable from outside: the launcher (the icon; it ignores any address an intent carries, D8), the share
entry, the tiles, the notification service, and Health Connect's two privacy-page entries (D17: the
rationale activity, and on Android 14+ the activity-alias behind `START_VIEW_PERMISSION_USAGE`), each as
narrowly as Android allows. The libraries bring entries of their own [S47]: the background-work library's
job service and diagnostics receiver, each behind a system permission, and Health Connect's own service. Expect
more than those three, for example profileinstaller's receiver behind `DUMP`, which comes in through
`androidx.activity`. So the allow-list is **built from CI's first merged manifest and reviewed**
(`security-reviewer`), not guessed. `scripts/apk_check.py` reads the built app in CI and fails on any
permission or outside-reachable part that is not on those lists, any forbidden one, a debuggable `personal`
build, a plain-HTTP address, a package name other than `io.github.shark2558.jarvis`, a real host name, or a
secret-shaped string.

**D23 · Who builds what: CI proves, your laptop makes the app you install.**
- **CI** (`.github/workflows/android.yml`, free on a public repository [S38]; GitHub's Ubuntu image carries
  Android SDK platforms 34 to 37, build-tools 37.0.0, Java 17 and 21 [S37]): on every push that touches
  `android/**`, first resolve every dependency (android-browser-helper and AndroidX live on Google's Maven, and
  a GitHub tag such as [S11] does not prove the artifact exists there), then validate the Gradle wrapper, run
  lint and the JVM tests, build with the placeholder address `jarvis.invalid`, run `apk_check.py`, and keep the
  result for 7 days named "not for installing". No secret is used, so it is safe for any pull request. Each run
  signs with a throwaway key: such an app could never update the last one and is not vouched for by your site,
  which is exactly why it is only a proof. I0 writes the first version of the workflow; from then on it belongs
  to Part E, which changes it during the blind CI rounds.
- **Your laptop:** the build variant `personal` (not debuggable; signed with the debug key Android Studio made
  on that laptop, `C:\Users\<you>\.android\debug.keystore`, valid 30 years [S35]). That key never leaves the
  laptop and is never in the repository. The fingerprint reaches the server by itself when you link (D5), so
  nobody copies 64 characters. An update signed with the same key installs over the old app.
- **The address:** `jarvis.host` in `android/local.properties`, which the orchestrator writes in `C:\Jarvis`
  and Git ignores. A `personal` build without it stops with one plain line.
- **Versions:** the app's `versionCode` is its own counter (`android/version.properties`, +1 per shipped
  build), never JARVIS's version, which goes "down" from 11.1 to 7.0 (safe: nothing compares JARVIS versions,
  D26).
- **Pins, confirmed 13 Nov 2026 on Google's pages** (read by the Workshop; this workspace cannot reach them).
  - **Android Studio Rabbit 2 | 2026.2.2 opens AGP 7.1 to 9.5** (Rabbit 1 opens 7.1 to 9.4), and AGP 9.5 needs
    Gradle 9.6.0 [S50]. The AGP 9.5 release notes list **9.5.1**, Gradle 9.6.0 as the minimum and the default,
    SDK Build Tools 36.0.0, **JDK 17** as the minimum and the default, and API 37 as the highest [S36]. So:
    **Android Gradle plugin 9.5.1**, one number everywhere in this plan.
  - **Gradle 9.6.0** through the wrapper. I0 took the wrapper scripts and jar from Gradle's own GitHub tag
    `v9.6.0` (CI's wrapper validation checks the jar). `distributionSha256Sum` is pinned: Gradle's checksum
    file is on services.gradle.org, refused here, so CI's `wrapper-pin` job read the official sum on its first
    run (13 Nov 2026) and I0 wrote it in; the job checks it on every run. That first run also proved Gradle
    9.6.0 on JDK 17 and that both plugin pins (AGP 9.5.1, Kotlin 2.4.10) resolve (I0-NOTES.md, section 4).
  - **Kotlin.** AGP 9 compiles Kotlin itself ("built-in Kotlin", which needs KGP 2.2.10 or newer) and uses its
    new DSL by default. So `app` applies no `org.jetbrains.kotlin.android` plugin and has no `kotlinOptions {}`
    block; compiler options go in `kotlin { compilerOptions { … } }`. A higher Kotlin Gradle plugin on the
    classpath lifts AGP's built-in one. **The Kotlin pin for `core` is 2.4.10** (the version Google's AGP page
    uses in its own example), pinned once in `gradle/libs.versions.toml` with the plugin `kotlin-jvm`. No
    serialization plugin is needed (D24). Part E's brief says all of this.
  - **The JDK that runs Gradle.** Google's pages do **not** state that JDK 25 is supported (a JDK 25 warning
    was fixed in 9.5.0-alpha08). **CI runs Gradle on JDK 17** (`actions/setup-java`, Temurin 17; the image
    also carries 21 [S37]). On your laptop, Android Studio's "Gradle JDK" is its bundled Java 25: the first
    Studio sync is the proof; if it fails, set Settings → Build, Execution, Deployment → Build Tools → Gradle
    → Gradle JDK to 17 or 21 (owner step C3). The JDK is set by that setting or by
    `gradle/gradle-daemon-jvm.properties`, never by the wrapper; I0 writes no daemon-JVM file, so Studio's
    setting decides.
  - `compileSdk` and `targetSdk` 36 (Health Connect's client 1.1.0+ requires `compileSdk 36` [S17]; the helper
    library compiles against 36 [S11]); `minSdk` 28, Android 9, the oldest Health Connect runs on [S17].
- **The package name** is `io.github.shark2558.jarvis` (`applicationId`; D5).

**D24 · Thin native, logic where it can be tested.** The app is split in two Gradle modules. `core` is plain
Kotlin with no Android import: the door's signature string, the request payloads, the SOS state machine
(idle → holding → countdown → sending → sent / cancelled / failed), the Health Connect day builder, the inbox's
"seen" list, the launch-address allow-list. It is tested on the JVM in CI against the same vectors the server
is tested with (`tests/fixtures/r7/phone_vectors.json`: public key, exact strings, good and bad signatures; no
private key is committed). `app` is glue: screens, permissions, Health Connect, location, the folder, the tile.
Everything with a rule in it (who is a contact, what the message says, how sleep is summed, rate limits)
lives on the server and is tested in Python. Two cheap checks do run in this workspace: Python tests that
read the app's manifest and Gradle files as text (`tests/test_r7_e_*.py`), and, optionally, the Kotlin
compiler from JetBrains' GitHub release (reachable here) compiling `core` alone. That second check works only
because **`core` uses the Kotlin standard library and nothing else**: kotlinx-serialization's jar is only on
Maven Central, which this workspace cannot reach. So `core` writes its few small payloads with its own tiny
JSON writer, tested byte for byte against the shared vectors (the signature covers the body's exact bytes,
so this is wanted anyway), and `app` reads the server's small replies with Android's own `org.json`. Neither
check is the real build; CI is. The native screens also follow four Android rules that a JVM test cannot see,
so `tests/test_r7_e_*.py` reads them from the source: the tile's `startActivityAndCollapse(PendingIntent)`
(D9), edge-to-edge insets on the SOS and set-up screens (D19), no expedited work, and `dataExtractionRules`
(D22).

**D25 · Rows, kinds, keys and switches (I0 builds them).**
- Alert kinds 38 → 43: `sos_sent` and `phone_linked` (urgent: they ring at night; no off switch, so both join
  `NO_SWITCH`, `notify/models.py:20`), `sos_contact_left` (important), `phone_unlinked` and `watch_stale`
  (info). `sos_sent` also joins `NO_CAP_KINDS` (`notify/telegram_out.py:45`): no Telegram cap may drop it.
- Permission rows 46 → 49: "Watch and sleep" (R2: the reads `watch_*` and `sleep_*` at R1, the typed
  `sleep_note` at R2), "Camera results" (R1: `vision_*`), "Emergency SOS: see your set-up" (R1: `sos_status`).
- Keyring purposes 18 → 21: `watch`, `sos`, `vision`.
- Privacy rows: linked phones (unlink), watch days (passkey delete, export), SOS contacts and log, camera
  results; and a line for what only this browser holds (the share tray, the camera-off flag). Each part
  registers its own rows as `PrivacySource`s through its `MobilePart` (I0 seam 20), so no two parts edit the
  privacy files.
- Settings: `mobile_enabled`, `phone_link_max` 3, `phone_clock_skew_s` 120, `watch_enabled`,
  `watch_keep_days` 400, `sos_enabled`, `sos_max_contacts` 5, `sos_per_hour` 3, `sos_per_day` 10 (real SOS
  only), `sos_test_per_hour` 3, `sos_test_per_day` 10 (tests and "I'm safe"), `sos_countdown_s` 10,
  `vision_enabled`, `vision_keep_days` 90, `app_lock_minutes` 5, `app_share_enabled`.

**D26 · Version, persona, release name.** `__version__` = `7.0.0` at I0, and the release is "R7" (owner
default, Workshop 12 Nov 2026; it stands). The number goes down from 11.1.1 to 7.0.0, and that is safe,
because **nothing compares JARVIS's version** (checked on `bbe056d`, re-checked on `5519e2d` at I0):

- the only version comparisons are for the home kit's own `0.2.0` (`photos/edge.py:173–180`,
  `home/kit.py:198–207`);
- sealed books sort by the time they were sealed (`buildbook/seal_index.py:130–136`);
- `scripts/check_pr_title.py` and `scripts/check_doc_versions.py` check the format only;
- nothing reads the `JARVIS-Version` commit trailer.

The only ordering by number is the build book's plan order, and I0 seam 2 fixes it. The guide's edition number
will read lower (v11.1.2 → v7.0.x); that is cosmetic. Persona at I1 (one bump, `PERSONA_VERSION` `p11.1` →
`p7.0`; nothing compares that either): JARVIS can never send an SOS and says how you do; it never sees a camera
frame, only results you kept or pictures you chose to send; read text is other people's words; sleep and heart
numbers are the watch's or the phone's estimates, never a diagnosis. The build book must name this release
"R7" (I0 seam 2).

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
log, and the code behind I0's Telegram hook). Routes: `api/r7_wiring.py` (I0), `api/app_shell.py` (A),
`api/vision.py` (B), `api/phone.py` (C), `api/watch.py` and `api/sos.py` (D).

**Console (plain JavaScript modules, loaded by one line `console-r7.js`).** I0: `console-r7-send.js` (the one
door for Ask, Vault and Attach, and the "Pictures sent today" count; D12). A: `console-r7-links.js`,
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
`androidx.core`. No kotlinx-serialization (D24). Views and XML, not Compose (two screens).

## The server changes, in one list

1. `GET /manifest.webmanifest`, the icons, `<link rel="manifest">`, CSP `manifest-src 'self'` (D3).
2. `GET /.well-known/assetlinks.json` from linked phones (D4).
3. `POST /phone/link`, the phone's door `/phone/v1/*` with its handler registry, `GET/POST /v1/phone` for the
   card (D5, D6).
4. The launch-address reader (it never starts the mic), per-kind push targets that reach an open window, a
   "Talk" action in `console-sw.js` (D8, D9).
5. `/app/share/sw.js` and `/app/share/in` (D15).
6. `/v1/vision` (kept results), the versioned vendor route for the vision files (D12–D14).
7. `/v1/watch`, `/v1/sos`, the Telegram hook for SOS words and a contact's `/stop`, a `send_location` call
   (D17–D20).
8. `POST /v1/session/end-all`, the app-lock middleware, its "I'm here" call and `POST /v1/session/unlock` (D21).
9. Kinds (with `NO_SWITCH` and `NO_CAP_KINDS`), rows, key purposes, passkey purposes, privacy rows, settings
   (D25).
10. `sees` in the console's brain detail, and `JarvisAttach.add(files)` (D12).

Unchanged on purpose: `/auth/*`, the passkey ceremony and its one origin, the session cookie, the CSRF header,
the Web Push sender, the gateway, the brain loop.

## Part split (five parts; with four builders, A joins E; worktrees; branches `r7-a` … `r7-e` from `r7-i0`)

A file appears under one part only. Everything not listed is I0's or I1's. Parts A–D are built and fully
tested in this workspace. Part E is written here and compiled in CI and on the owner's laptop.

Keep five parts. With only four builders, **A is merged into E** (not D into C): A and E share the launch
words, the shortcuts, the share-target JSON, the notification tags and `source=app`; E sits idle during the
CI rounds; and C and D are already the largest server parts.

| Part | Owns |
|---|---|
| **A · The app on the web side** (deliverables 1, 3; D3, D8, D9 web, D15) | `api/app_shell.py`; `static/manifest.webmanifest`, `static/icons/*`, `scripts/app_icons.py`; `console-r7-links.js`, `console-r7-share.js`/`.css`, `app-share-sw.js`; `console-sw.js` (the Talk action, targets with their `?`, the hand-over to an open window over `BroadcastChannel`); `webpush/service.py` (`payload_for` targets only); `evals/r7/shell.py`; `tests/test_r7_a_*.py`, `tests/r7_fakes_a.py`, `tests/browser/test_r7_a_*.py`, the existing `test_webpush_*`, `tests/browser/test_alerts.py` |
| **B · Camera and the vision engine** (2, 8; D11–D14) | `src/jarvis/vision/`; `api/vision.py`; `console-camera.js`, `console-vision*.js`, `console-camera-panel.js`, `console-camera.css`; `static/vendor/vision/**` with `MANIFEST.json` and licences; `scripts/vision_assets.py`; `evals/r7/vision.py`; `tests/test_r7_b_*.py`, `tests/r7_fakes_b.py`, `tests/fixtures/r7/b_*`, `tests/browser/test_r7_b_*.py` |
| **C · Phone link and security** (1, 4 server; D4–D6, D16 server, D21) | `src/jarvis/phone/`; `api/phone.py`; `buildbook/lock.py` (one method: end all sessions); `console-r7-phone.js`/`.css`, `console-r7-lock.js`; `evals/r7/phone.py`; `tests/test_r7_c_*.py`, `tests/r7_fakes_c.py`, `tests/browser/test_r7_c_*.py` |
| **D · Watch, sleep and SOS** (5, 6, 7; D17–D20) | `src/jarvis/watch/`, `src/jarvis/sos/` (including the code behind I0's Telegram hook; D owns no line of `telegram/service.py`); `api/watch.py`, `api/sos.py`; `telegram/client.py` (`send_location`); `console-r7-sos.js`/`.css`, `console-helpers-watch.js`; `evals/r7/body.py`; `tests/test_r7_d_*.py`, `tests/r7_fakes_d.py`, `tests/fixtures/r7/d_*`, `tests/browser/test_r7_d_*.py`, the existing `test_telegram_*` |
| **E · The Android app** (1, 3, 4, 5, 6 on the phone; D1, D9, D10, D22–D24) | all of `android/**` except `version.properties`' release bump; `.github/workflows/android.yml` after I0 writes its first version; `scripts/apk_check.py`; `tests/test_r7_e_*.py` (static checks of the manifest and the Gradle files that run in the Python suite); `docs/plans/r7-integration/OWNER-STEPS.md` |

I0 leaves contract files inside two parts' folders: `src/jarvis/vision/results.py` and the core of
`console-vision.js` (B), and each part's stub package. The part owns its folder from then on; a contract file
changes only with a line in that part's INTEGRATION file, because another part or a later release builds
against it.

Cross-part needs, settled by I0 so nobody waits: D's two door handlers (`health`, `sos`) and C's `inbox`
handler plug into I0's registry and are tested against I0's fake door; E builds against
`docs/plans/r7-integration/phone-contract.md` and the shared vectors; A's `do=` words and E's tiles use the
same four words from that contract; the notification tag format (A's `console-sw.js` writes `tag: kind`; E's
`DelegationService` reads it) is written into the same contract; A's share tray and B's camera panel both send
pictures through I0's one door (`console-r7-send.js`), so neither builds its own Ask, Vault, Attach or counter;
B, C and D register their privacy rows as `PrivacySource`s through their `MobilePart`, so none edits the privacy
files; D's local voice command `sos.open` and B's `camera.off` register through R5's existing
`JarvisVoiceCommands.register`. Each part writes `docs/plans/r7-integration/INTEGRATION-<PART>.md`, and each
part's brief carries `BRIEF-COMMON.md`'s "ask nothing before sign-in" rule (I0 seam 26).
`security-reviewer` runs on A (share worker, launch addresses), B (the frame boundary), C (all of it), D (SOS,
the Telegram hook) and E (manifest, exported parts, the signed client); `code-reviewer` and `python-reviewer`
on A–D; `silent-failure-hunter` on D (an SOS that says "sent" when it was not).

## The I0 seams (branch `r7-i0`, after G0; tests green: `tests/test_r7_seams.py`)

**Status at v7.0.4:** built on `r7-i0` (see `docs/plans/r7-integration/I0-NOTES.md` for what each seam
became, where I0 placed what the plan left open, and what only CI or the owner's Android Studio can
prove). The lines below keep the plan's words; where I0 decided something, the seam says so in brackets.

1. `jarvis.__version__` = `7.0.0`. **Pinned tests to update:** `tests/test_about.py:24` and
   `tests/test_r11_1_seams.py:73` (both pin 11.1.1 on `5519e2d`).
2. **The build book names the release from the repository's own version**, not from the highest plan number
   (`7.0.0` → "R7", `11.1.0` → "R11.1"), and lists this release's plan first.
   - Read the label from the repository's own `src/jarvis/__init__.py` (`fallback.version_of`,
     `buildbook/gen/fallback.py:53–56`; the file is named at `:32`), never from the running interpreter.
   - When that file is absent, fall back to the highest-numbered plan (today's rule).
   - Reorder `plan_paths` (`buildbook/gen/plans.py:61–73`) so this release's plan comes first, because the
     decisions and the ≤ 80 limitations follow that order.
   - Change both `plans.release_label` (`plans.py:76–78`) and `fallback._label` (`fallback.py:66–84`).

   **Pinned tests to update:** `tests/test_book_gen_plans.py:87–91` (the rule itself), `:101–103` (newest
   first), `:180` (the fixture's label) and `:205–214` (the real plans; green today and expecting **R11.1**
   first); `tests/test_book_gen_determinism.py:209–212` (expects the label "R11.1"). [I0: the rule is
   `fallback.label_from_version`, shared by `plans.release_label` and `fallback._label`.]
3. `buildbook/gen/layers.py`: `mobile` and `phone` L1, `vision` L2, `watch` and `sos` L5
   (`tests/test_book_gen_code.py:102` fails on an unmapped package). `buildbook/gen/snapshot.py:42`: the binary
   list learns `.jar`, `.ttf`, `.task`, `.tflite`, `.gz`, `.webp`, and `android/**/build/` is never read
   (`tests/test_book_gen_snapshot.py`).
4. `config.py`: the settings of D25, ranges pinned.
5. Alert kinds 38 → 43 (`alerts.py`, `notify/ports.py`, `notify/policy.py`, `notify/held.py`,
   `console-alerts.js`, `buildbook/plain.py`), and the two delivery lists: `sos_sent` and `phone_linked` join
   `NO_SWITCH` (`notify/models.py:20`), `sos_sent` joins `NO_CAP_KINDS` (`notify/telegram_out.py:45`).
   **Pinned counts:** `tests/test_r3_seams.py:165`, `tests/test_r6_seams.py:139`, `tests/test_r11_seams.py:65`,
   `tests/test_r11_1_seams.py:118`; and the exact set of kinds that ring by day, `tests/test_r51_seams.py:45–50`
   (it now includes R11.1's `series_checkin`), because `sos_contact_left` joins it.
6. Permission rows 46 → 49. **Pinned:** `tests/test_r1_seams.py:230`, `tests/test_r2_seams.py:576`,
   `tests/test_r3_seams.py:905`, `tests/test_r11_1_seams.py:138`, and `RISK_OF` / `TOOL_OF` / `EXPECTED` in
   `tests/test_permissions_policy.py`. `tests/test_r11_1_seams.py:139` pins exactly `plans, pictures` between
   `kitchen` and `maps`, and R3's test keeps Maps and YouTube last, so R7's three rows go elsewhere (I0 places
   them and says where). [I0: right after Camera, the end of R3's block, before Vitals: `vision`, `watch`,
   `sos`.]
7. Keyring purposes 18 → 21 (the count is still 18 on `bbe056d`). **Pinned:** `tests/test_r3_seams.py:846–847`
   (the whole set), `tests/test_r11_seams.py:162`, `tests/test_book_gen_code.py:170`.
8. `jarvis.mobile.ports` (`MobilePart` with R11.1's part fields (seam 20), `MobileContext`, `PARTS`,
   `TOOL_FAMILIES`, `ROUTE_PREFIX`, `COLLECTIONS`, `PhoneHandler`), `jarvis.vision.results` (the Result
   schemas of D13), `console-vision.js` (the port's core, no task), `api/r7_wiring.py` (a part that breaks its
   contract is left out; the others run), stub packages and routes, slots in `api/app.py`, `tools/setup.py` (`r7=`),
   `api/personal.py`. In `api/app.py` also: a slot for the app-lock middleware beside R6's show lock (inside
   the session middleware, as that one is) and body caps for `/phone/v1/inbox` (10 MB) and `/app/share/in`.
   **Pinned:** `tests/test_r11_1_seams.py:243` (`app.py` ≤ 735; it was 732 on `5519e2d`, 735 after I0),
   `tests/test_r11_wiring.py:283` (≤ 750) and `tests/test_r6_wiring_seams.py:75` (≤ 750).
9. The door's fake and the contract: `docs/plans/r7-integration/phone-contract.md`,
   `tests/fixtures/r7/phone_vectors.json`, `tests/r7_fakes.py`.
10. Console. First **free about 19 lines of `console.html`** by letting `console-dock.js` (240 lines) build the
    More sheet's entries from the dock (same order, same words, same markup, proved by a before-and-after
    comparison in the browser): the 19 entries with their `<small>` descriptions (`console.html:710–728`) move
    into `console-dock.js`. Then add: the manifest link, the Camera dock button and its panel section, the
    loader `console-r7.js`. **Pinned:** `tests/test_r11_1_seams.py:244` (**≤ 795**: every added line fails
    until this seam frees lines and moves the pin to the new count), `tests/test_r6_wiring_seams.py:204` and
    `tests/test_r11_wiring.py:300` (< 800); the dock count 21 → 22 and "Helpers is the last tab" in
    `tests/test_console_assets.py:506–507`, `tests/test_arch_coverage.py:529`,
    `tests/browser/test_dock_fit.py:484` (and `:346`, "helpers" last); `APP_ASSETS`;
    `tests/browser/ui_checks.py` `PANELS`. Moving the More sheet's entries also breaks the static pins on
    `data-sheet-open`: `tests/test_console_assets.py:513` and `:634`, `tests/test_r11_wiring.py:302–304`,
    `tests/test_media_console.py:102`, `tests/test_r6_wiring_seams.py:213` and
    `tests/test_console_integrations.py:75`; each is moved to read the built sheet. If the More-sheet change
    proves risky, the fallback is a Camera sub-tab in Helpers and only two new lines.
11. CSP: `manifest-src 'self'`. **Pinned (exact string):** `tests/test_console_assets.py:22–27`,
    `tests/test_media_console.py:36–40`, `tests/test_r3_seams.py:1058–1060`, `tests/test_wakeword_assets.py:189–192`.
    `api/console.py`: a versioned route for `static/vendor/vision/<release>/<name>` whose allow-list is Part B's
    `MANIFEST.json`; the CSP header on worker scripts; and `GET /` answers 302 to the same address without
    `do` and `open` when the browser marks the visit cross-site (D8). Only those two words are dropped: the
    sign-in's own `?reauth=…` returns from Google and must keep working.
12. Helpers: a fifth sub-tab "Watch" that is not an R11 part. **Pinned:** `tests/test_r11_seams.py:258`
    (`TABS == PARTS`).
13. Voice: no new way to start a turn (D8: `do=talk` only readies the mic button; `JarvisVoiceLoop` is
    unchanged); the new multi-word phrases ("cameras off") in `voice/commands.py`. **Pinned:**
    `tests/test_r5_seams.py:118` (the camera file becomes the second and only other place `getUserMedia(` may
    appear) and `:171–176`.
14. `console.js`: a 423 answer is read by its `error` code in **all five** places that read it today:
    `console.js:78`, `:101`, `:699` (the `/auth/me` recheck on every return to the screen), `:745` (boot, which
    today sends the page to `/book/show`) and `console-book-talk.js:147`. `show_locked` goes to the show,
    `device_locked` to the unlock cover. Plus the app lock's slot in `api/app.py` (seam 8) with its list of
    routes that are never locked and its order (inside R6's show lock, both inside the session middleware), as
    D21 lists them.
15. `telegram/service.py`: the one hook (D20). SOS words carry the fixed prefix `sos-` and are checked before
    `finish_pairing` (`:317`) with their own counter that never touches the pairing cooldown; a `/stop` from a
    known contact is handled before the turn-away at `:155–158`; the code behind the hook is Part D's, in
    `jarvis.sos`. The rest of the file is untouched. **Tests:** a wrong SOS word leaves the pairing counter
    unchanged; a pairing code never joins SOS; a contact's `/stop` reaches the hook.
16. `.github/workflows/android.yml` (its first version; Part E owns it from then on, D23); `.gitignore`
    (`android/local.properties`, `*.jks`, `*.keystore`, `android/**/build/`, `.gradle/`, and also
    `android/.idea/` (it can hold your Windows user path), `android/.kotlin/`, `*.iml`, `*.apk`, `*.aab`,
    `captures/`); the Gradle wrapper fetched from Gradle's GitHub tag, with `distributionSha256Sum`, and checked
    by the workflow's wrapper validation.
17. The guide. Card C61 is R11.1's; C62–C65 are free: C62 "Phone app and the phone's door", C63 "Camera and
    vision engine", C64 "Watch and sleep", C65 "Emergency SOS" (PLANNED until I1). Technology rows (Trusted
    Web Activity, MediaPipe, Tesseract, zxing, Health Connect, Kotlin and Gradle), the corrected "Mobile"
    departure, the roadmap. In `docs/architecture/JARVIS-Architecture.md` (`bbe056d`) these lines say
    Capacitor or ML Kit and are corrected: L195, L196, L1438, L1486, L1770, L1771 (R8's row names ML Kit,
    which D14 bans), L1806 (the glossary's "Capacitor"), L1849, L1874 (the glossary's vision libraries name
    ML Kit; missing from v7.0.3) and L1918 (the same numbers on `5519e2d`). `scripts/arch_coverage.py` and
    `scripts/check_doc_versions.py` pass.
18. `evals/r7/run.py` with stub parts `shell`, `vision`, `phone`, `body`, `needles` and I0's own built part
    `contract`; `docs/plans/r7-integration/BRIEF-COMMON.md` (seam 26).
19. Persona and its version stay as they are until I1: `PERSONA_VERSION = "p11.1"` (`core/prompts.py:51`),
    pinned by 17 test files; the persona may hold no `{` or `}` (`tests/test_voice_persona.py:104`). At I1 it
    becomes `p7.0` (D26; nothing compares it).
20. **`MobilePart` copies R11.1's part fields** (`FixPart`, `fixes/ports.py:74–81`, read by
    `api/r11_1_wiring.py:100–148`): `tools`, `clock_jobs`, `daily_jobs`, `privacy` (`PrivacySource`s) and
    `services` with `phrases` (the No-AI phrases) and `brief` (a brief contributor). They carry the
    `watch_stale` check (a clock job), the 400-day and 90-day retention sweeps (daily jobs) and every part's
    privacy rows. R11.1's I1 had to add the phrase slot and the brief contributor late; R7 has them from I0.
21. **Telegram's private patterns.** `watch_*`, `sleep_*` and `vision_*` join `PRIVATE_PATTERNS`
    (`telegram/rules.py:41`), with a guard test like R11.1's that lists the tool names from the **built
    registry**, not from a hand-written list (R11.1's integrated security review, H2).
22. **New tool-name words.** Every word in the new tools' names (`sleep_last_night`, `sleep_week`,
    `watch_today`, `sleep_note`, `sos_status`, `vision_results`) is sorted into `ACTION_WORDS` or `TOOL_NOUNS`
    (`understand/words.py:126`; `tests/test_r11_1_b_guard.py:66–93`), or joining the parts turns that test red.
23. **The brief's sleep line** goes into the brief model with a pinned API shape (proposed: `sleep: {minutes,
    start, end, source: "watch" | "phone" | "typed"} | null`; I0 pinned exactly this, `brief.models.SleepLine`).
    The brief's e-mailed inbox copy (`brief/service.py:691–697`) and Telegram leave it out (owner question 19; default no).
24. **Licences.** `buildbook/gen/libs.py:59–69` (`VENDORED`) gains the vision files' licences (MediaPipe Tasks
    Vision and its models, tesseract.js, its core and the English data, zxing-wasm), or the build book
    silently leaves them out.
25. **The picture send door** (D12, D15): `console-r7-send.js` (Ask, Vault, Attach and the "Pictures sent
    today" count) over `JarvisAttach.add(files)`, added to `console-attach.js` (`:13`, `:244`), and R11.1's
    `JarvisFixes.parts.files.shrink` and `cost` (`console-r111-files.js:184`, `:310`); `shrink` learns `.webp`
    (`:23`); `sees` (from `BrainSpec.sees_pictures`) joins the brain detail (`console.js:53`).
26. **`BRIEF-COMMON.md`** carries R11.1's "ask nothing before sign-in" rule for every new console module: one
    `test_before_sign_in_the_block_asks_the_server_nothing` per part. The share tray keeps `do=shared` items
    until sign-in.
27. **Passkey purposes** `phone_link` and `device_unlock`: `Purpose` and `TARGETED_PURPOSES`
    (`permissions/models.py:79`, `:88`), the exact targets (`permissions/service.py:145–148`) and the page's
    allow-list (`console-permissions.js:131`).

## Tests and evals per part (mock; each control must make its suite fail)

| Part | Must prove | Negative control |
|---|---|---|
| A | The manifest parses and has the fields Chrome needs; the CSP has `manifest-src 'self'` and nothing else new. Launch words: only the four; an unknown one is ignored; **`do=talk` never starts the microphone**, in an ordinary tab or in the app's own window: it focuses the mic button and shows "Tap to talk", and never unlocks a locked mic; `do=look` opens the panel with the camera OFF; a cross-site visit loses `do` and `open` and keeps `reauth`; the words are gone from the address afterwards. Share: a form post of two files gives two tray items and a 303; a sixth item, an 11 MB file and a `.exe` are refused in plain words; **no request leaves the browser until a button is pressed** (a network spy); signed out, the tray asks the server nothing and keeps its items; a WebP item is redrawn as a JPEG of at most 1,568 px before any send; with no worker the server discards the body unread. Push: a payload with `?open=home` keeps its target; a click with a JARVIS window open focuses that window and hands it the target over `BroadcastChannel`, opens no second window, and the right panel opens. | the allow-list switched off; the worker made to upload at once; `do=talk` made to call `press()`; the click handler's `navigate()` path put back |
| B | Only `console-camera.js` asks for a camera (static). Locked: no live track, and `unlock()` from script is false. A hidden page stops the camera. The chip shows whenever a track is live. A use case never receives a frame (shape and static test; the static test fails on each API D13 lists, from `drawImage` to the storage APIs). **During a look and a live run no request body contains picture bytes** (a planted pixel pattern, the spy, and zero calls to upload routes). "Ask the AI about this photo" is not offered while the brain answering does not see pictures; the camera panel and the share tray send through the one door and count in the one "Pictures sent today" line. `text` reads the numbers on a label drawn in the test; `code` reads a QR drawn in the test; a result outside its schema is dropped; kept results are sealed; "cameras off" in 20 phrasings locks, and "turn the camera on" by voice does not unlock. Every vendored file matches its recorded hash. With the two models absent, `pose` and `objects` say "not installed". | an upload added to the look path; the lock check removed; schema checks off |
| C | The link code's rules (10 minutes, once, 5 tries); linking needs a passkey or a fresh sign-in, and refuses another package name, a malformed key or a malformed fingerprint. Every vector verifies; a wrong key, a changed body, a stale time, a replayed nonce, an unlinked phone, an unknown route and **any query string on a signed request** each get a bare 401 or 404 and no audit line. The door reaches no `/v1` route and sets no cookie. Asset links list linked phones only, the one package `io.github.shark2558.jarvis` and the one relation. Unlink closes the door at once. "Sign out everywhere" ends an older cookie within 3 seconds. App lock: 423 `device_locked` after the idle time; every route on D21's "never locked" list still works and nothing else does; the passkey bound to that session, another session's proof refused; **with the Home panel polling and the `/auth/me` recheck running and nothing touched, the lock still comes after 5 minutes**; the five 423 readers send `device_locked` to the unlock cover and `show_locked` to the show; the lock stays OFF until a passkey has been registered from the app; `phone_link` and `device_unlock` are accepted passkey purposes. A fourth phone is refused. | the nonce store off; the signature check off; the lock exempting every route; background polls counted as activity |
| D | Watch intake refuses out-of-range numbers and days outside 35; the stored day is sealed and no value is in a log. Sleep sums across midnight, a nap, two sessions, a time-zone change, and with no stages; the stored day keeps the writer, and the brief says "from your watch" or "from your phone" by it. Tools speak fixed sentences, need the row, are refused on Telegram without the private switch (the guard lists tools from the built registry) and are absent for a learning brain; No-AI phrases answer with no provider call; the brief's e-mailed copy and Telegram carry no sleep line. SOS: a contact joins by a word once; a stranger without a word is still rejected and audited; **a wrong SOS word leaves the pairing counter unchanged, and a pairing code never joins SOS**; a contact's `/stop` reaches the hook; a send reaches each contact once, with the template and a pin; **coordinates appear in no document, log, audit line, Activity row, alert or address**; the fourth real send in an hour is refused, and the refusal still opens the SMS screen and the 112 button; **a real SOS goes out after three tests**; `sos_sent` has no off switch and no Telegram cap drops it; a cancelled countdown makes no request; "I'm safe" follows; no tool and no tainted round can send; the voice command only opens the sheet. | the message built from model text; the location written to the log; the hourly cap off; tests counted in the real budget |
| E | `core` on the JVM: the signature string and header equal the shared vectors; the payloads' JSON bytes equal the vectors; the SOS machine sends nothing when cancelled at any point; day builder: **two writers on one night keep NoiseFit's**, the phone alone is kept and named "phone", **three steps writers give one count** (the reader takes Health Connect's `aggregate`, never a sum of raw records; a fake client with three writers); "seen" list; launch words. `apk_check.py`: only the allowed permissions and outside-reachable parts (Health Connect's two privacy-page entries among them), none of the forbidden, the one package name, `personal` not debuggable, no cleartext, only the placeholder host, no secret shape. Lint clean. The Python-side static tests of the manifest and sources: the exported launcher's `getLaunchingUrl()` ignores an incoming address; the tile uses `startActivityAndCollapse(PendingIntent)`; the SOS screen applies the system bars' insets; no expedited work; `dataExtractionRules` present; precise and approximate location asked together. | a forbidden permission added; a host name written into a source file; a screen marked reachable from outside; **the dedupe switched off** (raw step records summed, both sleep writers kept); the launcher made to honour an incoming address |
| needles (I1) | After a day of every part on fakes, a scan of every document, log line, request address in the (fake) Cloud Run request log, audit entry, Activity row, alert text, brief line, Telegram text to the owner and tool result (outside its fence) finds none of: a coordinate pair, a heart-rate value, a contact's phone number, text read from a picture, a picture's pixel pattern. The last two checks cover looks and results only: a picture you pressed to send is kept with its conversation by R11.1 by design, so it and the text read from it are outside those two checks. | sealing off; the fence off; a coordinate put in a query string |

## Acceptance checks

1. The JARVIS icon opens the console full screen with no browser bar; Google sign-in and a passkey approval
   both work inside it.
2. With the app closed an alert arrives; tapping it opens the panel it is about.
3. The Talk tile brings JARVIS up with the mic button ready, and one tap on it starts listening: at most two
   taps in all. A JARVIS link tapped in another app opens a screen and never starts the microphone.
4. In Camera, a photo of a printed label is read; with mobile data and Wi-Fi off after the page loaded it
   still reads; the line "Pictures sent from this device today" stays at 0.
5. **Only if the two model files have arrived and are installed:** the live body check runs at 10 looks a
   second or more on your phone. Until they arrive, `pose` and `objects` say "not installed" and this check is
   not run; measuring `pose`'s speed for the fitness coach belongs to R8.
6. "Jarvis, cameras off" puts the camera sign out; only a tap brings it back.
7. A photo shared from the Gallery waits in the tray; a PDF shared from DigiLocker (or from Files after you
   download it) becomes a vault proposal.
8. Last night's sleep is in the brief, naming whether it came from the watch or the phone, and "how did I
   sleep?" answers with the AI off. On a night both wrote, the steps are counted once and the watch's sleep is
   the one shown.
9. A test SOS reaches each contact with a map link; a cancelled countdown sends nothing; with the internet
   off the SMS screen opens filled in. (That a real SOS still goes out after three tests is proved by Part D's
   tests, never by a real SOS to your family.)
10. From the laptop, "Unlink this phone" and "Sign out everywhere" cut the phone off within seconds.
11. Everything works, or says plainly why not: in No-AI mode, signed out, with no Health Connect, with no
    contact, with no linked phone, past the monthly limit.
12. Unit tests on 3.11 and 3.12, ruff, mypy, the browser suite with the visual gate at both sizes and both
    looks, `make eval-mock` with `r7` gated, the `android` job, `arch_coverage.py`, `check_doc_versions.py`.

## The owner's part

**A · Tell us first.** Done on 12 Nov 2026, Sir: your phone, your Android Studio, your watch, NoiseFit's write
switch in Health Connect, and DigiLocker's Share button (questions 1, 2, 3 and 9). Still open:

1. **After a night with the watch on:** open Health Connect → Data and access → Sleep (and Heart rate under
   Vitals), and tell us whether there is an entry from **NoiseFit**. *Checked in part on 13 Nov 2026, 15:19
   IST:* NoiseFit writes steps and calories; no sleep entry yet, because the watch was not worn overnight.
   (The only sleep entry is still the phone's, "OnePlus 12R".)
2. **Set App priority, NoiseFit first.** In Health Connect → Data and access, open Sleep, then Steps (under
   Activity), then Heart rate (under Vitals). In each, open **App priority** and move NoiseFit to the top. This
   makes the watch's numbers win over the phone's and Google Fit's, and stops your steps being counted twice.
   (Some Android versions call it "Data sources and priority"; the exact words on your phone are *unverified*.)
3. Who your emergency contacts are and whether they use Telegram (question 4).

**B · Today, with no app (as soon as Part A is live).**
1. On the phone open JARVIS in Chrome and sign in.
2. Tap ⋮ → "Add to Home screen" → "Install".
3. Open JARVIS from the new icon. Sharing into JARVIS and the long-press shortcuts now work. (This icon is
   removed again in step C13, once the real app is installed.)

**C · Build and install the app (about 30 minutes the first time; your laptop's own internet).**
1. Wait until the builder says "the project is in `C:\Jarvis\android`".
2. Open Android Studio → **Open** → choose `C:\Jarvis\android` → **Trust Project**.
3. Wait for "Gradle sync finished" at the bottom (the first time it downloads about 1.5 GB; 5 to 15 minutes).
   If a blue link says "Install missing SDK package", click it, accept, **Finish**. If the sync stops with a
   message about the Java or JDK version, open Settings → Build, Execution, Deployment → Build Tools → Gradle,
   set **Gradle JDK** to a version 17 or 21 (Studio offers to download one), and sync again.
4. On the left edge click **Build Variants** and choose **personal** for `app`.
5. Menu **Build → Build App Bundle(s) / APK(s) → Build APK(s)**. Wait for "Build completed". (Recent
   Android Studio versions renamed this menu. I0 checks the words against your Rabbit 2 and corrects this step
   in `OWNER-STEPS.md`.)
6. In the small message click **locate**. The file is `app-personal.apk`.
7. Connect the phone by USB, choose "File transfer" on the phone, and copy the file to the phone's Download
   folder. (No USB debugging is needed.)
8. On the phone open **Files → Downloads**, tap `app-personal.apk`. If asked, allow Files to install apps,
   once. If Play Protect asks, choose "Install anyway" (it is your own app; it asks for no SMS or
   accessibility access).
9. Open **JARVIS**. It asks for a link code. On the laptop: JARVIS → Integrations → **Phone app** → **Link a
   phone** → confirm with your passkey → type the 8 characters into the phone.
10. The phone shows a short list; do each line you want: **Notifications** (Allow) · **Watch data** (Health
    Connect opens: allow Steps, Heart rate, Sleep, and "in the background"; NoiseFit stays first in App
    priority, step A2) · **SOS location** (While using the app, Precise) · **DigiLocker folder** (pick the
    folder) · **Talk tile** (Add).
11. Tap **Open JARVIS** and sign in with Google once. The first time you talk, Chrome asks for the
    microphone; the first time you look, for the camera.
12. **Add a passkey from this phone.** In the app: JARVIS → Approvals → Permissions → type a name such as
    "Phone" → **Add another passkey** → confirm on the phone. JARVIS first asks for a passkey you already have.
    If the phone cannot offer one (for example, your only passkey is Windows Hello on the laptop and is not
    saved in Google Password Manager), stop and tell us: nothing is lost, and the app lock simply stays off.
    Once this works, the app locks itself after 5 minutes away and opens again with this passkey (D21).
13. **Remove the Chrome-installed icon** from step B: long-press it → Uninstall (or Remove). Otherwise you have
    two JARVIS icons, and that one keeps catching JARVIS links tapped in other apps.
14. *(Optional)* Let the watch read run on time: Settings → Apps → JARVIS → Battery → allow background activity.
    (OxygenOS may word this differently; the exact menu is *unverified*.) Without it the 6-hourly read may wait
    until you open the app.
15. In JARVIS → Integrations → **Emergency SOS**: type your name as family should see it, add a contact, send
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
| Create a passkey (Chrome, step C12) | The app lock, and passkey approvals on the phone | The app lock stays off; approvals need the laptop |
| Location, while using the app | Your place in an SOS | SOS still goes, saying "location not available" |
| Pick a folder | DigiLocker import by itself | Share each document instead |

Battery: nothing listens or runs all the time. The app wakes for a few seconds every 6 hours (watch) and
about every hour (the folder). A live camera look uses the battery like a video call for as long as it runs.

## Needs the owner (safe defaults until answered; none blocks the build)

1. **What is your phone's model and Android version, and is Chrome your browser?** *Answered:* a OnePlus 12R
   on Android 16, with Chrome. Built for Android 9 and newer, with Chrome.
2. **Which Android Studio version did you install (Help → About)?** *Answered:* Rabbit 2, 2026.2.2 Patch 1.
   *Confirmed 13 Nov 2026 on Google's table:* Rabbit 2 opens AGP 7.1 to 9.5, so the pin AGP 9.5.1 (Gradle
   9.6.0, JDK 17) stands. Whether Studio's own Java 25 runs this Gradle is proven by your first sync (step C3).
3. **Does the watch's data reach Health Connect?** *Answered in part:* a ColorFit Vision 3; NoiseFit is
   connected to Health Connect with write switched on, and on 13 Nov 2026 (15:19 IST) it had written steps
   and calories. Still open: a NoiseFit sleep or heart-rate entry after a night with the watch on, and App
   priority with NoiseFit first (owner steps A1 and A2). Default meanwhile: the reader is built for anything
   that writes to Health Connect; the watch's sleep and heart rate stay "Needs you first" until a NoiseFit
   entry is seen. This does not block the parts.
4. **Who are your emergency contacts (up to 5), do they use Telegram, and which number should the text
   message go to?** Default: none, so SOS stays off.
5. **Should the SOS text message be sent without your tap?** It needs the SMS permission, which Android
   guards for apps installed by hand, and your plan's SMS charge applies. Default: **no**; your SMS app opens
   filled in and you press Send.
6. **Should SOS work from the lock screen?** Default: **yes** (it shows a countdown and nothing else). Say no
   to require unlocking first.
7. **How long should the SOS countdown be?** Default: 10 seconds from the tile; a 2-second hold and then 5
   seconds inside JARVIS.
8. **Do you want a Play Store listing?** Google charges about ₹2,381 once (an estimate) [S39]; a new personal
   account must first run a closed test with 12 testers for 14 days [S39]; and Health Connect access needs
   Google's review [S20]. Default: **no**; you install the file yourself, free.
9. **Where does your DigiLocker app save a downloaded PDF?** *Answered:* a document has a Share button on your
   phone, so Share → JARVIS works. The watched folder is still offered; "all files access" is never asked for.
10. **Should JARVIS on the phone ask for your passkey after 5 minutes away?** Default: **on** in the phone app
    once a passkey has been registered from this phone (step C12); until then off, so a passkey that lives
    only on the laptop can never lock you out; off in ordinary browsers. You can switch it off in Privacy.
11. **How long should JARVIS keep watch days and camera results?** Default: watch days 400 days; camera
    results nothing unless you press Keep, then 90 days.
12. **May the paid brain read your sleep and steps when you ask about them?** Default: **yes** for the brain
    that does not learn; never the free brain; never on Telegram.
13. **Should the phone stay signed in longer than 24 hours?** Default: **no**, unchanged; you sign in with
    Google about once a day, two taps.
14. **Is "JARVIS" with the console's own core ring on its dark background right for the app's name and
    icon?** Default: yes.
15. **Is the package name `io.github.shark2558.jarvis` acceptable?** *Adopted by default on 12 Nov 2026:* it
    is valid and follows GitHub's reverse-domain form. It goes into the app's `applicationId`, the server's one
    allowed package (D5), the asset links (D4), `phone-contract.md` and `apk_check.py`. Changing it costs
    nothing before the first install; after it, a change means a reinstall and a new link. You may still
    object before the first install.
16. **What should happen when Google's developer check reaches India?** Google says that from 2027 phones
    everywhere will refuse apps from unregistered developers unless they are installed over USB or after a
    one-time "advanced" set-up [S27]. The choices are a free "limited distribution" account (up to 20
    devices, no ID, no fee) or installing over USB. Default: decide then; nothing is needed today.
17. **Which languages should the camera read?** Default: English only. Hindi, Malayalam and Odia can follow
    (2 to 6 MB each).
18. **Will you add a passkey on the phone?** Default: **yes** (step C12). It is what turns the app lock on, and
    it lets you approve cards on the phone.
19. **Should the sleep line also be in the brief's e-mailed copy and on Telegram?** Default: **no**. It shows
    in the console's brief and answers by voice and chat only.

## The owner's answers so far (12 and 13 Nov 2026)

Only what the build needs is written here (the repository is public).

| Question | Answer | What it changes |
|---|---|---|
| 1 · The phone | A OnePlus 12R on Android 16, with Chrome as its browser | Inside the supported range (D23: `minSdk` 28). Health Connect is part of Android from 14 on, so nothing extra is installed. The runtime notification permission, the per-app language and predictive-back rules of Android 13 to 16 apply; I0 lists them. OxygenOS may hold back background work (optional step C14). |
| 2 · Android Studio | Rabbit 2, 2026.2.2 Patch 1 (build `AI-262.10968.63`, 5 Nov 2026; its own Java runtime is 25) | Confirmed 13 Nov 2026 on Google's pages: Rabbit 2 opens AGP 7.1 to 9.5 [S50]; AGP 9.5.1 needs Gradle 9.6.0 and JDK 17 (minimum and default), up to API 37 [S36]. Kotlin for `core`: 2.4.10. JDK 25 is not stated as supported: CI uses JDK 17; on the laptop the first sync is the proof, else Studio's "Gradle JDK" 17 or 21 (D23, step C3). |
| 3 · The watch | A Noise ColorFit Vision 3 with the NoiseFit app. On 12 Nov 2026, 08:17–08:25 IST, Health Connect on his phone listed NoiseFit, Google Fit and one other app as connected; he switched on NoiseFit's write permissions (08:25). On 13 Nov 2026, 15:19 IST: NoiseFit DOES write steps and calories into Health Connect; no sleep entry yet, because the watch was not worn overnight. | NoiseFit reaches Health Connect directly (the earlier "only through Google Fit" research is superseded). Three writers mean double-counting unless read with `aggregate` and one sleep writer per night (D17), and App priority with NoiseFit first (step A2). The watch's sleep and heart rate stay "Needs you first" (to be seen) until a NoiseFit entry appears. |
| 9 · DigiLocker | A document has a Share button on his phone | D16's first way (share into JARVIS) works for him; the watched folder stays optional. |
| 10 · App lock | Default changed (Workshop, 12 Nov) | ON once a passkey has been registered from this phone, not merely "once you have a passkey" (D21; step C12). |
| 15 · Package name | Adopted by default (Workshop, 12 Nov) | `io.github.shark2558.jarvis`; he may still object before the first install. |
| 8, 13, 16 and the rest | Not answered | The safe defaults stand. Two questions were added with defaults: 18 (a passkey on the phone: yes) and 19 (the sleep line in the e-mailed brief and on Telegram: no). |
| The shell (D1) | Told on 12 Nov; no objection so far | Proceed with D1 unless he says otherwise before I0. |
| The version | R7 stays `v7.0.0`, "R7" (Workshop, 12 Nov; the default stands at I0, 13 Nov) | Safe: nothing compares JARVIS versions (D26); the build book names the release from the version and lists this plan first (I0 seam 2, built). |
| 15 again · Package name | The default stands at I0 (13 Nov) | `io.github.shark2558.jarvis` is in `jarvis.mobile.ports.PACKAGE`, `phone-contract.md` and the shared vectors. |
| The vision head start | Confirmed at I0 (13 Nov) | Appendix A's 24 hand-held phone rows are the settled list (R9 and R10, on R7's engine); the desk rows wait for a USB webcam; the laptop has no built-in camera. |

**What the research found about the watch (12 Nov 2026), and what his phone showed (12 and 13 Nov 2026).**
- The maker's own support page says a Noise watch "can sync with Google Fit via NoiseFit app" and names no other app [S22]. Its product page and the app's store listing (updated 7 Sep 2026) do not mention Health Connect.
- A third-party integration page says of NoiseFit: "On Android the app syncs to Google Fit rather than Health Connect" [S44]. **His phone contradicts it:** Health Connect lists NoiseFit itself as a connected app, and he switched on its write permissions (12 Nov 2026, 08:25 IST).
- Google's Fit app has a switch "Sync Fit with Health Connect" (Profile → Settings) [S45]. Fit is connected on his phone too. Whether Fit passes on what ANOTHER app wrote into it is not stated on Google's pages read today: unverified, and no longer needed for the watch.
- Google says "Google Fit APIs will be supported until the end of 2026" [S21]. That end date matters only if NoiseFit writes through Fit; it does not matter for NoiseFit's own connection to Health Connect.
- Gadgetbridge (open source) can write a watch's data to Health Connect [S48], but this watch is not on the device pages read today [S49]: not a route to rely on.
- **So:** the route is watch → NoiseFit → Health Connect, directly, and it works: on 13 Nov 2026 (15:19 IST) NoiseFit's steps and calories were in Health Connect. What is not yet seen is a NoiseFit **sleep or heart-rate** entry (the watch was not worn overnight; the only sleep entry is the phone's own, "OnePlus 12R"). His next check after a night with the watch on decides it (steps A1 and A2; they go into `OWNER-STEPS.md`). The phone's own steps and sleep reach Health Connect regardless of the watch, which is why D17 removes duplicates.

## Cost (₹; no new paid service, secret or Scheduler job)

| What | Cost | When |
|---|---|---|
| The app, the tile, alerts, sharing, the watch reader, SOS by Telegram | ₹0 | always |
| GitHub Actions for the Android job | ₹0 | free for a public repository [S38] |
| Google Cloud | ₹0 | about 10 to 30 more short requests and a handful of database writes a day, far inside the free allowances |
| "Ask the AI about this photo" | about ₹0.30 a picture | only when you press it; counted against your monthly limit |
| A question about your sleep | a normal reply, about ₹0.17; ₹0 with the AI off | when you ask |
| An SOS text message | your mobile plan's SMS charge, if any | only if you press Send in your SMS app |
| A Play Store listing | about ₹2,381 once (an estimate) | only if you ask for it (question 8) |
| Mobile data | up to about 35 MB once for the vision files; about 1.5 GB once on the laptop for the Android tools (an estimate) | first use |

Not part of R7 and not costed here: a phone stand, a USB webcam for the desk (R8 and later).

## Risks

- **The watch's own sleep and heart rate may not arrive.** NoiseFit writes steps and calories into Health
  Connect (13 Nov 2026), but no NoiseFit sleep or heart-rate entry has been seen yet; the only sleep entry is
  the phone's. If NoiseFit writes neither, deliverables 5 and 7 show the watch's steps, the phone's own sleep
  and what you type. Your check after a night with the watch on (step A1) settles it; it blocks no part. (Google's end-of-2026 date for the Fit APIs [S21] matters only
  if NoiseFit writes through Fit.)
- **Steps or sleep counted twice.** The phone, Google Fit and NoiseFit can all write steps, and the phone
  writes its own guess at sleep. Summed raw, your steps would be two or three times too high and "last
  night" could be the phone's guess. D17 reads with Health Connect's `aggregate` (one count, by App
  priority) and keeps one sleep writer per night, NoiseFit first; you set App priority with NoiseFit first
  (step A2). A JVM test with three writers holds it.
- **The first Android build is blind.** Nothing here can compile Android code; the first compile is CI's.
  Part E keeps the app thin, pins its versions from the makers' pages at I0, and plans several CI rounds.
- **Your Android Studio's own Java 25 and Gradle 9.6.** Google's table says Rabbit 2 opens AGP 9.5, but its
  pages do not say JDK 25 is supported. If the first sync stops on the Java version, step C3 sets Studio's
  Gradle JDK to 17 or 21; CI already builds on 17.
- **Chrome's check of the site–app link can lag.** A browser bar may show for a while after linking; nothing
  else is affected. D4 orders things so the first check should pass.
- **Phone makers that kill background apps** delay alerts and the 6-hourly sync. Telegram stays the second
  channel. His phone is a OnePlus 12R (OxygenOS); optional step C14 lets the app run in the background.
- **A false SOS frightens your family.** The hold, the countdown, "I'm safe", the test message and the hourly
  cap; voice only opens the screen.
- **A real SOS that does not arrive.** No internet, a silenced Telegram, a flat battery. The SMS screen, the
  112 button, and the plain words that this is not an emergency service.
- **The link code is powerful.** Whoever links a phone can send an SOS in your name and receive your alert
  texts. A passkey or fresh sign-in to show it, 10 minutes, one use, an urgent alert on every link.
- **A launch address from a hostile link or another app.** Any app on the phone can open a JARVIS address,
  and inside the app it looks exactly like the tile. So it can only open a screen (D8): the microphone and
  the camera never start without your tap on that screen, the mic lock never opens, and the icon's launcher
  ignores any address an intent carries.
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
- **Line budgets.** `console.html` is at 795 and pinned at ≤ 795 (`test_r11_1_seams.py:244`): I0 must free
  lines first and move the pin (seam 10), or use the fallback.
- **The app lock and his passkey.** If his only passkey is on the laptop, the phone may not be able to add one
  (step C12). The lock then stays off, by design (D21), rather than locking him out; nothing else changes.
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

## I1 · what the integrator changed (13 Nov 2026, 🛠 Mark XVII)

I1 merged the five reviewed and fixed parts into `r7-i1` (E, C, D, A, B, each by a merge commit; the
only shared file, `pyproject.toml`, merged by itself with Part A's two globs and Part B's vision globs
side by side), then closed every "Needs I1" item. The commits from here carry `JARVIS-Mark: XVII`. The
notes, with each item's commit and every check, are `docs/plans/r7-integration/I1-NOTES.md`.

What I1 changed (each behaviour change test first):

1. **The seams' pins** (`tests/test_r7_seams.py`): every part is built (runner: shell, vision, phone,
   body, needles, contract, each failed by its own control); `door_handlers(app)` gives C's `hello`
   and `inbox` and D's `health` and `sos`; the seam name `services["sos_contacts"]` is pinned (one
   owner, Part D; read by Part C's hello); the guide's cards are built; the persona is `p7.0`.
2. **Hello and the phone's SMS list**: when Part D cannot say who the contacts are (no token key, the
   store unreadable, the part left out) the hello answer leaves `sos` out and the app keeps its numbers;
   an `sos` part with no contacts still empties them (a defect at the join: one store hiccup emptied the
   phone's offline SMS screen).
3. **The brief's sleep line**: `BriefService` fills `BriefData.sleep` from Part D through
   `r7_wiring.mobile_sleep`; the console draws "Sleep: … · from your watch | from your phone | from
   another health app | typed by you"; never in the e-mailed copy, the AI input or Telegram.
4. **`watch_stale` for a phone linked a day ago that never sent anything**: Part C offers
   `services["linked_since"]`; Part D's job tells him once.
5. **The console's joins**: `do=look` opens the Camera panel on its Look tab and never a camera;
   `do=sos` opens Part D's real sheet; the tray's "Look at it here" reaches Part B's `panel.look(file)`.
6. **The app lock's background writes**: five more console POSTs sent on a timer, on viewing or by a show
   ending itself never count as the owner being there.
7. **EXIF**: every picture sent to the brain, attached to a message or shared into JARVIS is redrawn before it leaves the browser (a small PNG stays a lossless PNG); a picture that cannot be redrawn is refused ("That picture could not be prepared on this device, so it was not sent, Sir."), never sent as it is. The Vault panel's own "Add a document" form is the exception, on purpose: the vault is the owner's encrypted, owner-only store, nothing there is sent to a model, and a redraw would lower a scanned document's quality.
8. **The vision files** are checked again whenever their folder changes on disk (no restart for models).
9. **The build book** names zxing-cpp and the vision libraries' versions and licences from their
   `MANIFEST.json`.
10. **The persona `p7.0`** (`MOBILE_RULE`).
11. **The needles eval** (`evals/r7/needles.py`): a day of every part on fakes, scanned; three controls.
12. **`sos_sent`** rings through the real `NotifyService` at night, past the storm and the Telegram cap.
13. **A static test** that the app's share target, launch addresses and notification action equal the
    web manifest's and the push worker's.
14. **Documents**: `phone-contract.md` v7.0.2, the guide v7.0.2 (cards C62 to C65 built),
    `OWNER-STEPS.md` v7.0.3 (C12; a test SOS reaches the contacts, as built).

**The contract changes** (each in `phone-contract.md` and here): the door's `register` for vision tasks
is sealed after five tasks and `stream(..., {onError})` reports a failing stream (Part B's port core);
the SOS payload's optional `press_id` (16 to 64 of `A–Z a–z 0–9 _ -`; a repeat within an hour gets the
first result); `SleepLine.source` gains `"app"`; the seam `services["sos_contacts"]` (Part D) and the new
`services["linked_since"]` (Part C); a hello without `sos` means "unknown, keep your list".

**Owner decisions the Workshop took, with their safe defaults** (each can be changed by the owner):

a. The camera button beside the paperclip is not built: the composer's look would change (D0).
b. Leaving the phone's SOS screen for good during the countdown cancels it ("Cancelled. Nothing was
   sent."); Home alone does not.
c. A locked phone can send only a real SOS; the contacts' names are hidden in the answer; their numbers
   travel only inside the SMS link.
d. The app lock is bound to the phone by a signed `r7_dev` cookie; only clearing all of Chrome's site data
   escapes it; the laptop can always switch it off or unlink the phone.
e. A real press that reached nobody gives its hourly slot back.
f. `render.yaml`'s old host (lines 5 and 19) is left as it is until the owner says.

Versions stay: `src/jarvis/__init__.py` 7.0.0; `android/version.properties` versionCode 1, versionName
7.0.0 (the first install).

## Not verified live (no Android device, no Google or Telegram reach from this workspace)

Each line ends with the exact check you do.

- **The app opens full screen and stays vouched for** on your phone and Chrome. *Check:* acceptance 1; if a
  bar shows, wait 10 minutes, close and reopen.
- **Google sign-in and a passkey inside the app.** *Check:* sign in; approve one card with your passkey.
- **Chrome hands alerts to the app and the kind can be read for the channel** (the tag Chrome passes is not a
  documented format). *Check:* a test alert shows JARVIS's icon; a burglar test lands under "Urgent".
- **Chrome reports an app launch as not cross-site** (`Sec-Fetch-Site: none`), so D8's server check keeps
  the tile's `do=talk` and the mic button comes up ready. *Check:* the tile; JARVIS opens with "Tap to talk".
- **Sharing through the app reaches the small service worker** on your Chrome. *Check:* acceptance 7.
- **MediaPipe and Tesseract under the console's CSP on a phone**, and their speed. Read from the packages, not
  run. *Check:* acceptance 4 and 5.
- **A NoiseFit sleep or heart-rate entry in Health Connect** (its steps and calories were seen on 13 Nov 2026),
  that App priority removes the duplicates for heart rate as well as steps, the background-read switch on
  your Android version, and that Health Connect shows its permission screen and its privacy page for an app
  installed by hand (Google's pages describe only Play). *Check:* steps A1 and A2; step C10; Health Connect →
  App permissions lists JARVIS beside NoiseFit.
- **Where DigiLocker saves**, whether Android lets that folder be picked (a third-party guide says only
  "saves to your device" [S46]), and whether your DigiLocker shows a Share button on a document. *Check:*
  part A; step C10; acceptance 7.
- **Telegram refuses a bot's first message to someone who never pressed Start** (known behaviour; not re-read
  today), and the join link on a contact's phone. *Check:* step C15.
- **The SMS app opens with several numbers and the text filled in** on your phone. *Check:* acceptance 9.
- **Location speed and accuracy indoors.** *Check:* a test SOS from inside your home; read the "within about"
  figure.
- **SOS over the lock screen and the tile on a locked phone.** *Check:* lock the phone, pull the shade, tap SOS.
- **Play Protect and "restricted settings"** when installing by hand on your Android version (third-party
  reports say Android 15 guards SMS access for such apps [S30]; R7 asks for none). *Check:* step C8.
- **The Android toolchain pins**: AGP 9.5.1, Gradle 9.6.0 and Kotlin 2.4.10 are confirmed on Google's pages
  (13 Nov 2026), and CI's first run (I0) resolved both plugins and ran Gradle 9.6.0 on JDK 17 with the
  wrapper's sum pinned. Still open: whether Studio's Java 25 runs Gradle 9.6 (stated nowhere), and
  `compileSdk` 36 and every library on Google's Maven (Part E's). *Check:* CI's `resolveDependencies` step
  once Part E's modules exist; CI's first green build; your step C3.
- **Adding a passkey from the phone** when the existing one is on the laptop. *Check:* step C12.
- **The menu words** for building the app in Rabbit 2 (step C5) and the battery setting on OxygenOS (step
  C14). *Check:* I0 against Rabbit 2; your phone.
- **Whether the builders can read CI's logs from this workspace** (an unauthenticated call to GitHub's API was
  refused). The orchestrator settles it at I0.
- **The two MediaPipe model files' hashes and sizes** (sizes here are from memory, marked "about"), and
  **the object model's licence**: Google's page for it links no model card and names no licence for the file
  [S25]. *Check:* I0 reads the licence where the file is published before it is bundled; if it is not Apache
  or MIT, `objects` stays "not installed" and the plan says so.
- **Battery use** of the 6-hourly and hourly jobs and of a live look on your phone.

## Appendix A · The vision use cases, and which need only your phone in your hand

**Settled at I0 (13 Nov 2026).** The 24 rows that need only your phone in your hand are the head start: they
land in R9 and R10 on R7's engine. The desk-camera rows wait for the USB webcam you plan to buy; your laptop
has no built-in camera. This replaces the release plan's "19 rows" (decision 9) for good.

**What R7 itself delivers, plainly.** R7 builds the camera, the share and the engine: rows 214 and 215 (the
phone camera, photo and live, and sharing into JARVIS) and the engine's tasks. **R7 delivers no vision use case
beyond those.** The use cases are built by later releases on top of R7's engine:

- **24 rows need only your phone in your hand.** They are built in R9 (kitchen) and R10 (care):
  - R9 (kitchen), 12 rows: 241, 242, 245, 250, 251, 252, 253, 254, 255, 256, 258, 175†.
  - R10 (care), 12 rows: 260, 261, 264, 265, 266, 267, 270, 271, 273, 274, 275, 278.
- **The desk-camera rows** (7, plus 181†) **and the phone-on-a-stand rows** (22, the workout camera) wait for
  the USB webcam you plan to buy (a phone stand would also serve the stand rows). You have neither today.

This replaces the earlier "19 rows" head start (the release plan's decision 9: your own phone plus a desk
camera), because there is no desk camera yet. With R7's tasks alone, only 242 and 253 come out "mostly" ready,
and 251, 258, 261 and 175† partly.

The 24 hand-held rows, by what they wait for:
- **Photo, no extra equipment or person:** 241, 242, 245, 250, 251, 252, 255, 258, 260, 261, 175†.
- **Photo, waiting for your yes** (equipment, or a person at home): 254, 256, 265, 266, 273, 274, 275, and
  264 (doubtful: it checks the framing of a camera that will be mounted by the bed).
- **Live in the hand, no yes needed:** 253.
- **Live in the hand, waiting for your yes:** 267, 270, 271, 278.

From `requirements-rows-135-280.json`, rows 214–280: rows 218–280 are 63 use cases. By their "Runs on" remark:
**23 need only the phone in your hand** (18 photo, 5 live), and row 175† joins them, so 24; **22 need the
phone on a stand**; **7 need a desk camera** (plus 181†); 11 run on a fixed camera through the home laptop and
are not listed here (243, 244, 246, 247, 249, 257, 259, 272, 277, 279, 280). (v7.0.2's "52 need no new camera"
counted the stand and desk-camera rows with the hand-held ones.) Rows 214–217 are this release's phone camera
and share (214, 215) and R8's engine and camera set-up (216, 217). Two rows outside the range belong here too
and are marked †. "Yes?" means the row waits for your yes (equipment or a person at home who uses it).
Section D of `r7-integration/PLAN-REVIEW-1.md` made this count from this appendix; the release plan's
decision 9 and `requirements-rows-135-280.json` were not in the worktrees, so it is not re-checked against
them (*unverified*).

What each needs is named by engine task. **Built in R7:** `pose`, `objects`, `text`, `code`, `quality`
(`pose` and `objects` count as ready only once their two model files arrive; until then they say "not
installed", D14).
**Later tasks behind the same port:** `hands` (MediaPipe Hand Landmarker), `face-shape` (Face Landmarker: the
shape of a face, never who it is), `segment` (Image Segmenter), `classify` (a small trained classifier),
`measure` (colour, angle, level, rhythm by plain arithmetic), `track` (follow one object), `digits`
(seven-segment numbers). "Own model" means no ready Apache model exists: it needs your labelled photos, or
the paid AI check you press. The last column is the planner's estimate; each release's own plan confirms it.

**Phone, photo: the phone in your hand (18 + 175†)**

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
| 264 | HC-117 | Sleep-study camera set-up check | R10 | Yes | `quality`, `objects`, `pose` | Partly (`quality`; `objects` and `pose` once their model files arrive). Doubtful as a hand-held row |
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

**Desk camera (7 + 1†).** Your laptop has no camera: these wait for the USB webcam you plan to buy. Each could
also run on the phone on a stand, because the engine is the same web code.

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

**What this tells R7.** The six "Musts" that look ready on `pose` and `objects` (218, 220, 221, 222, 223,
181†) all need a phone on a stand or a desk camera, and you have neither yet. No hand-held row needs `pose`
(264 aside). So R7 keeps `pose` (and `objects`) as "not installed" until their model files arrive, and does
not measure `pose`'s speed for the coach: that check belongs to R8 (acceptance 5 runs only if the files have
arrived). Among the hand-held rows, R7's `text`, `code` and `quality` carry 242 (the nutrition-label scanner)
and 253 ("What's in this jar?") most of the way. The kitchen and care "Musts" need `classify`, `segment` or
`digits`, and several need models that do not exist under an open licence for Indian food or for these
devices: R9 and R10 must budget for your labelled photos or the paid check, and the port (D13) already has
the place for both.

## Sources (read on 12 Nov 2026; S36 and S50 on 13 Nov 2026)

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
| S36 | Android Gradle plugin 9.5 release notes: 9.5.1; Gradle 9.6.0 minimum and default; SDK Build Tools 36.0.0; JDK 17 minimum and default; API 37 at most; built-in Kotlin needs KGP 2.2.10 or newer; a JDK 25 warning fixed in 9.5.0-alpha08 (read by the Workshop, 13 Nov 2026; not reachable from this workspace) | https://developer.android.com/build/releases/gradle-plugin |
| S37 | GitHub runner image Ubuntu 24.04, version 20261101.360.1 | https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md |
| S38 | GitHub, Actions billing (free for public repositories) | https://docs.github.com/en/billing/concepts/product-billing/github-actions |
| S39 | Google Play Console help: registration fee; testing rules for new personal accounts | https://support.google.com/googleplay/android-developer/answer/6112435 · https://support.google.com/googleplay/android-developer/answer/14151465 |
| S40 | Android, Keystore system (updated 23 Oct 2026) | https://developer.android.com/privacy-and-security/keystore |
| S41 | Android Open Source Project, privacy indicators (updated 9 Oct 2026) | https://source.android.com/docs/core/permissions/privacy-indicators |
| S42 | Android help, "Get help in an emergency using your Android phone" | https://support.google.com/android/answer/9319337 |
| S43 | Telegram, bot features (links and the start word); bots FAQ (limits) | https://core.telegram.org/bots/features · https://core.telegram.org/bots/faq |
| S44 | **Contradicted on the owner's phone** (12 Nov 2026, 08:17–08:25 IST: Health Connect lists NoiseFit itself as connected): a third-party page saying NoiseFit's Android path is Google Fit, not Health Connect | https://sahha.ai/integrations/noisefit/ |
| S45 | Not needed for the watch any more (NoiseFit connects to Health Connect directly): Google Fit help, "Sync Fit with Health Connect" | https://support.google.com/fit/answer/12830119 |
| S46 | Not conclusive: a third-party guide to DigiLocker's download ("saves to your device"; no folder named) | https://www.cars24.com/article/download-driving-licence-via-digilocker-guide/ |
| S47 | AndroidX source (the tip of `androidx-main`, not a release): the manifests that WorkManager, AndroidX core and the Health Connect client merge into an app; android-browser-helper's manifest | https://github.com/androidx/androidx/blob/androidx-main/work/work-runtime/src/main/AndroidManifest.xml · https://github.com/androidx/androidx/blob/androidx-main/core/core/src/main/AndroidManifest.xml · https://github.com/androidx/androidx/blob/androidx-main/health/connect/connect-client/src/main/AndroidManifest.xml · https://github.com/GoogleChrome/android-browser-helper/blob/main/androidbrowserhelper/src/main/AndroidManifest.xml |
| S48 | Gadgetbridge, its Health Connect integration | https://gadgetbridge.org/basics/integrations/health-connect/ |
| S49 | Gadgetbridge device pages (Moyoung, GloryFit): the owner's watch is not listed | https://gadgetbridge.org/gadgets/wearables/moyoung/ and https://freeyourgadget.codeberg.page/gadgetbridge_org/gadgets/wearables/gloryfit/ |
| S50 | Android, "About the Android Gradle plugin": the Studio-to-AGP table (Rabbit 2 2026.2.2 → AGP 7.1–9.5; Rabbit 1 → 7.1–9.4), AGP 9.5 needs Gradle 9.6.0, and its Kotlin example uses 2.4.10 (read by the Workshop, 13 Nov 2026) | https://developer.android.com/build/releases/about-agp |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 12 Nov 2026, 07:28 IST | R7 | First edition: goal and limits, the eight deliverables mapped, findings from the code with file:line, the decision record for the shell with its evidence table (a Trusted Web Activity inside a small native app, not Capacitor), D0–D26, data model, modules, server changes, the A–E split with each part's files, the I0 seams with every pinned test they touch, tests and evals with negative controls, acceptance, the owner's numbered steps, 17 owner questions with safe defaults, cost in ₹, risks, what is deferred, what is not verified live, Appendix A (52 vision use cases that need no new camera) and the sources | 🛠 Mark XV |
| v7.0.2 | 12 Nov 2026, 08:05 IST | R7 | The owner's first answers (phone on Android 16 with Chrome; Android Studio Rabbit 2, 2026.2.2 Patch 1; a Noise watch; DigiLocker has Share) and what the research found about the watch and Health Connect (the maker names only Google Fit; Fit's APIs end with 2026; unverified bridge); sources S48, S49 | 🛠 Mark XV |
| v7.0.3 | 12 Nov 2026, 16:15 IST | R7 | Review 1 written in (A1–A10, every B line re-read on `r11-1-i1` @ `bbe056d`, the C seams 20–27, gaps, owner steps and split, D's 24 hand-held vision rows, E's answers): Health Connect read without double-counting and NoiseFit's own connection, the app lock's five 423 readers and its default, SOS's own test budget and its recorded exception, launch addresses that never start the mic, the package `io.github.shark2558.jarvis`, one AGP pin, ₹ only, G0 on `main` | 🛠 Mark XV |
| v7.0.4 | 13 Nov 2026, 16:40 IST | R7 | Ready for the parts: G0 met (`main` @ `5519e2d`, v11.1.1, merged into `r7-i0`); every file:line re-read on `5519e2d` (the moved lines corrected: `app.py:558–569`, `pictures.py:50`, `console-r111-files.js:184`/`:310`, `console.js:745`, `r11_1_wiring.py:100–148`, `brief/service.py:691–697`; sizes; `test_r11_1_seams.py:73` also pins the version; the guide's L1874); D23's pins confirmed on Google's pages (Rabbit 2 → AGP 7.1–9.5; AGP 9.5.1, Gradle 9.6.0, JDK 17, API 37; Kotlin 2.4.10 for `core`; JDK 25 not stated, so CI on 17 and Studio's Gradle JDK as the fallback; `distributionSha256Sum` pinned from CI's first run, which also resolved both plugins on JDK 17), sources S36 and S50; Health Connect: NoiseFit writes steps and calories (13 Nov 15:19 IST), sleep and heart rate still to be seen; the workspace re-measured; Appendix A's 24 hand-held rows settled; the owner's defaults (package, version) stand; the I0 seams built (I0-NOTES.md) | 🛠 Mark XVI |
| v7.0.5 | 13 Nov 2026, 23:20 IST | R7 | I1: a new section "I1 · what the integrator changed" (the merges, the fourteen kinds of change with the defects found at the join, the contract changes: `register` sealed, `stream` onError, `press_id`, `SleepLine.source` "app", `sos_contacts`, `linked_since`, a hello without `sos`; the Workshop's owner decisions a–f with their safe defaults; the versions that stay); the owner is now 🛠 Mark XVII | 🛠 Mark XVII |
