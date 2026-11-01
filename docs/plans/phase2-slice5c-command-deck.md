# Phase 2 · Slice 5c — Command Deck (dark 3D HUD), deploy-on-merge, owner identity

Status: IN PROGRESS · 2026-11-01

## Owner ask
Shared a reference screenshot of a dark sci-fi HUD (floating panels, central rotating ring,
radar, globe, 3D figure, bottom dock): "make the design something like this with all 3D
elements and motions … then proceed with the next set of development … make the deployment
process smoother."

## Decisions
| Question | Decision | Why |
|---|---|---|
| Dark (new reference) vs white (slice 5b ask) | Add a **Surface** switch: **Night** (dark HUD, new default) / **Day** (the 5b white look). All five themes and the custom colour work on both. | Newest ask wins as default; nothing the owner liked earlier is thrown away. |
| Layout | **Command Deck**: centre 3D Core, left/right instrument rails, floating draggable panels toggled from a bottom dock; positions remembered per device. Phones (< 900 px): one panel at a time, dock = tab bar, no dragging. | Matches the reference; floating windows don't work on phones. |
| 3D | three.js r0.187 (MIT), vendored and self-hosted (CSP stays `script-src 'self'`). Three scenes: **Core** (reactor-style rings + faceted core + particles, reacts to idle / thinking / needs-you), **Globe** (wireframe sphere + orbit), **Construct** (original rotating wireframe hologram). No WebGL → the existing 2D Core. | Real 3D was asked for; self-hosting keeps privacy + CSP. |
| The figure in the reference is a film character's armour | Not reproduced. The Construct panel is an original abstract hologram. | IP — same rule as 5b. |
| Fake readouts in the reference (CPU 90 %, "threat critical", satellite lock, weather) | **Only real data.** Vitals = reply latency (last / average + sparkline), turns, brain, approvals waiting, audit-chain verified, connection online/offline. Radar blips = real recent activity events. Globe label = the device's time zone. Weather comes later as a real tool (slice 6+). | "Never guess"; a dashboard that lies trains the owner to ignore it. |
| Type | Design repo (ui-ux-pro-max, style "HUD / Sci-Fi FUI") recommends Share Tech Mono + Fira Code. Use **Share Tech Mono** for HUD labels/readouts (self-hosted, OFL), keep Orbitron for the wordmark; body text stays the system UI font for reading comfort (repo's Fira Code body discarded: long chat replies in monospace read worse). | Accessibility priority over style. |
| Motion | Repo dials motion 7/10, density 8/10. Every motion keeps a job (5b motion map) + new: panel open = scale .96→1 + fade 220 ms; 3D scenes ≤ 30 fps, paused when hidden/off-screen or Motion = Off; reduced-motion → Calm. | Repo accessibility: reduced-motion + non-3D fallback required for this style. |

## Deployment, smoother
Today: Cloud Shell → `git pull` (private-repo trouble) → `bash deploy/cloudrun.sh` → 7 prompts.
After this slice:
1. **Deploy on merge.** `.github/workflows/deploy.yml`: on push to `main` (after the test jobs
   pass) GitHub signs in to Google **keylessly** (Workload Identity Federation, restricted to
   `Shark2558/jarvis-web` on `refs/heads/main`), builds the image, pushes to Artifact Registry
   and rolls out a new Cloud Run revision with the existing settings. No key or password is
   stored anywhere. Gated by the repo variable `AUTODEPLOY=on`, so it is a no-op until set up.
2. **One-time setup** folded into `deploy/cloudrun.sh` (step 7/7): creates the identity pool,
   provider and a `jarvis-deployer` account with only: deploy Cloud Run revisions, push images,
   act as `jarvis-run`.
3. **Re-runs ask nothing**: the script reads the saved answers from the live service and Secret
   Manager and only asks for what is missing (`--reconfigure` to change answers).

Owner's future update = click **Merge** on GitHub. Ever.

## Owner identity (slice 6 prerequisite)
- `user_id` is derived on the server, never taken from the client: signed-in email →
  `u_` + sha256(email)[:16]; API bearer token → the first owner email's id; dev without auth →
  `owner`. ChatRequest/Decision `user_id` fields are overwritten/ignored.
- Existing conversations are stored under `owner`; at start-up they are re-tagged to the first
  owner's id once (idempotent; `SessionStore.reassign_user`).

## Tests first
- console: three.js + new fonts served from allow-list with long cache; CSP unchanged; page
  references deck script; unknown names 404.
- identity: user_id from session email; client-supplied user_id ignored on chat, list, get,
  delete, approve; bearer → primary owner; legacy re-tag idempotent (memory + doc stores).
- deploy: shellcheck-clean; workflow YAML parses; deploy job depends on test jobs and the
  AUTODEPLOY gate.
- Playwright: Night + Day × desktop 1440 / phone 390, every theme, panels drag + persist,
  Motion Off, no WebGL fallback, zero JS errors; contrast of text tokens ≥ 4.5 : 1 on both surfaces.

## Status notes — Command Deck UI (branch `slice5c-ui`, 2026-11-01)
**Built.** Surface switch (Night default / Day) in Appearance; Command Deck on ≥ 900 px (top bar with
status pill + clock + date, 24-hour ruler with a live "now" mark and today's events, left/right rails,
centre 3D Core, six floating panels, dock); phones get one panel at a time and a tab bar.
Files: `console.html` (markup only), `console.css` (tokens + components, both surfaces),
`console-deck.css` (layout), `console-fx.js` (surfaces, per-surface contrast engine, events),
`console-deck.js` (panels, dock, rails, radar, vitals), `console.js` (API flows, unchanged behaviour),
`console-3d.js` + `console-3d-scenes.js` (ES modules), `vendor/three.module.min.js` + licence,
Share Tech Mono woff2 + OFL. All source files < 600 lines.

**Decisions made while building.**
- three r187 on npm ships no `.min.js`. Vendored file = esbuild 0.25.0 `--bundle --minify --format=esm`
  of the official `build/three.module.js` (core inlined; same 443 exports; no eval). Banner records it.
- The release is part of the URL (`/static/vendor/three-0.187.0/…`), so the year-long immutable cache
  can never serve a stale library after an upgrade. Static assets use one literal route each (no
  `/static/{name}` catch-all, which would turn `/static/fonts/` into a slash redirect).
- One WebGL renderer for all three scenes; each renders into a corner of the offscreen renderer and is
  copied into its own canvas, so panels stack above or below any scene. three is fetched only when
  WebGL2 works (no-WebGL devices never download it).
- Frame-budget governor: if the page sustains < ~22 fps while the scenes animate, step down (20 fps at
  DPR 1, then 12 fps), then retire 3D and let the CSS-animated 2D emblems take over. Found because
  software GL (SwiftShader) delayed reply animations by > 1 s. Never steps back up within a page load.
- Only the Conversation is open by default; the Core centres itself in the free span beside it.
  Approvals auto-open on desktop; on phones they badge the tab and turn the pill amber instead of
  pulling the owner away from the reply they are reading.
- Night labels/readouts use Share Tech Mono; Day keeps Rajdhani for component labels (the 5b look).
- Contrast engine: Night lightens accent-ink until AA on the panel, its tint, the page and a 90 % card
  with a white glow behind it; Day darkens it until AA on the page edge, a 12 % accent glow and a 90 %
  white card over a dark stroke. Day `--ink-3` darkened #5A687B → #536176 to pass over dark-accent glows.

**Verified.** pytest 217 passed / 27 skipped (31 new asset tests). Playwright (mock brain, Chromium):
53/53 flow checks (approve + decline, history restore/delete with confirm, drag + reload persistence,
clamping, keyboard dock/Esc/arrow-move, Reset layout, surface + theme via menu, brain banner, token gate,
Core animates, Motion Off still, WebGL context loss → 2D → restore, no-WebGL fallback), phone checks
(no horizontal scroll at 390, one panel at a time), reduced-motion → Calm; 0 JS errors, 0 CSP violations.
Contrast: 22 surface × theme/colour combinations (incl. #FFFF00, #FFFFFF, #000080, black, grey, lime),
every text token ≥ 4.5 : 1, minimum 4.56.

**Not verified here.** Real-GPU frame rate (CI has software GL only: ~5 fps before the governor
retires 3D); Google sign-in mode (`/auth/me` path is unchanged code); Safari / Firefox rendering.
