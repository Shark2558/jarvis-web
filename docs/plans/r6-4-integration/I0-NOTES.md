Version v6.4.0 · 25 Nov 2026, 13:20 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXIV

# R6.4 — I0 notes (the seams for "the Book's own look and the narrated chapters")

The R6.4 I0 builder wrote these notes in the Workshop (🛠 Mark XXIV) on `r6-4-i0`, from `r6-4-plan`
(the plan `docs/plans/r6-4-book-look.md` v6.4.1, approved at stop 4 on 25 Nov 2026, 12:13 IST, and
its mockups `docs/plans/r6-4-mockups/`). `main` was `f5cf529` (`v6.3.2`). Builders A (reader and
search UI), B (chapter player and effects), C (rows 392, 393) and the narration writers W1–W4
build on these seams; I1 joins them.

## 1. What I0 built

| Piece | Files |
|---|---|
| The chapters (D5) | `src/jarvis/buildbook/book/chapters.py` (`chapters()`, `HOMES`) |
| The narration format and checks (D6) | `src/jarvis/buildbook/book/narration.py`, `narration_check.py`, `files.py` (shared readers), the guide `AUTHORING-NARRATION.md`, the reference script `narration/module_vault.md` |
| The writers' tools | `src/jarvis/buildbook/gen/narration_cli.py`; `gen/pages_cli.py` (the flags, strict `--check` covers narration) |
| Compile and seal | `src/jarvis/buildbook/gen/compile_narration.py`, `gen/compile_pages.py`; `writer/model.py` (`Narration`, `BookChapter`, `ChapterLine`, `ChapterCue`, `ScriptMeta`; `PagesFile.narration`) |
| Routes (D4–D6) | `writer/http.py` (contract), `writer/texts.py` (refusals), `writer/chapters.py`, `writer/search.py`, `writer/serve.py`, `api/book_pages.py` |
| The page `/book/read` (D1–D3) | `api/book_read.py` (mounted by `install_book_pages`), `static/book-read.html`, `static/book-read.css`, the stubs `static/console-book-read.js`, `console-book-chapter.js`, `console-book-fx.js` |
| The panel (D1) | `static/console-book.js`: **Read the full book** and **Short tour** (was "Start the show") |
| Docs | the guide's C57 (v6.4.0); six pages refreshed (§8) |

Tests: `tests/test_r64_i0_chapters.py`, `_narration.py`, `_narration_cli.py`, `_compile.py`,
`_search.py`, `_routes.py`, `tests/browser/test_r64_i0_read.py`; touched: `test_r631_i0_cli.py`,
`test_r631_e_compile.py`, `test_r631_e_serve.py`, `browser/test_book_panel.py`, `browser/book_mocks.py`
(`FakeBook` answers `GET /v1/book/chapters` from `chapters_answer`).

## 2. The chapters (D5)

`book/chapters.chapters(pages)` reads any index in its order (`IndexedPage` at build time, a
compiled `Page` list for an old release): 8 **story** chapters (`story_<id>`, one `pg_chapter_*`
page each), then 18 **module** chapters (`module_<id>`: the `pg_module_*` page, its cards in the
module map's order, then the screens and services `HOMES` places there, in the index's order).
`HOMES` is the one table (page id → module); a page in no row stays readable, not narrated. On
this tree every one of the 153 pages is in exactly one chapter (a test says so).

| Chapter | Title | Pages | Chapter | Title | Pages |
|---|---|---|---|---|---|
| `story_what` | What JARVIS is | 1 | `module_people` | People and faces | 5 |
| `story_example` | The running example | 1 | `module_home` | Home bridge and cameras | 11 |
| `story_data` | Data, hosting, security and recovery | 1 | `module_alerts` | Alerts and notifications | 5 |
| `story_answers` | How answers are made | 1 | `module_integrations` | Google, Telegram and other integrations | 27 |
| `story_setup` | A local setup | 1 | `module_vitals` | Vitals, costs and the systems check | 8 |
| `story_technology` | The technology inventory | 1 | `module_privacy` | The privacy panel | 3 |
| `story_costs` | Costs | 1 | `module_activity` | Activity log and undo | 4 |
| `story_planned` | What's planned | 1 | `module_approvals` | Approvals and passkeys | 6 |
| `module_console` | Console and API | 9 | `module_android` | The Android app | 4 |
| `module_brain` | Chat and the brain router | 14 | `module_helpers` | Daily helpers (brief, helpers, family, groceries, parcels) | 12 |
| `module_voice` | Voice | 6 | `module_delivery` | Delivery, CI and backups | 8 |
| `module_memory` | Memory and knowledge | 7 | `module_book` | The Build Book | 4 |
| `module_vault` | Vault and documents | 5 | `module_wardrobe` | Wardrobe & Try-on | 7 |

## 3. The narration scripts (D6)

The format, the cues and the voice are in `src/jarvis/buildbook/book/AUTHORING-NARRATION.md`. Key
points for the writers and I1:

- A script's `pages:` stamps hash each page's **written sections and flowchart** (not its front
  matter), so restamping a page's `sources` never makes a script stale; a changed word or box does.
  Order at the end of R6.4: refresh stale pages first, then re-check and re-stamp the scripts.
- `pages --check` with no ids now checks all 26 scripts too: CI's `docs-check` fails until W1–W4
  have written them all. Until then use `--check --allow-missing`.
- The Vault script: **80 lines, about 9 minutes (1,333 words)**, cues: 30 `show` (every section),
  9 `edge`, 9 `count`, 8 `node`, 5 `page`.

## 4. Sealing: the finding and the choice

**The question:** how does a `v6.3.2` server (`main` @ `f5cf529`) react, after a rollback, to a
release sealed by `v6.4.0` with (a) an extra sealed file, or (b) an extra field in `pages.json.gz`?
Read: `seal_index.py`, `seal.py` (`DocsBookVault._decode`), `model.py` (`SealedRelease`,
`FileKind`, `Release`), `writer/model.py` (`PagesFile`), `writer/serve.py`. Then tried: `main`'s
own `writer/model.py` and `model.py` (from `git show f5cf529:...`) against the new bytes.

| Way | What `v6.3.2` does | Effect after a rollback |
|---|---|---|
| (a) a 5th file kind `narration` | `SealedRelease.files` is `FileKind` = book, source, pages, flows and at most 4: `literal_error` | The **whole index** fails `BookIndex` → `VaultTampered`: every kept release unreadable, the "sealed build books failed their integrity check" notice, and the sealer can't seal (an index that won't open is never overwritten) until roll-forward. `release.json` would also need a `narration_sha256`, refused too (`extra_forbidden`) |
| (b) a field `narration` in `pages.json.gz` | `PagesFile` refuses it (`extra_forbidden`) | Only **that release's full book** answers "can't be read right now" (`serve.py` turns the `ValueError` into 503 `unavailable`, logged by type, no notice). The index, every other kept release, the tour and v6.3.2's own release all keep working |

**Choice: (b).** `PagesFile.narration` is optional and left out of the bytes when absent (a model
serializer, the `ReleaseRef` pattern), so a pages file without it is byte-for-byte v6.3.2's. A
sealed release keeps its four files. The plan's risk line ("may show one false integrity check
failed") is better than feared: no notice at all, one release's full book unreadable until you
roll forward. `pages.json.gz` on this tree: 205 KB with the Vault narrated (cap 2 MiB).

## 5. The routes (owner only, the pages routes' gates)

Signed in, the primary owner (403 `not_primary`), an OWNER session's `X-Jarvis-Book` (a guest's is
403 `owner_only`, none 401), the console only (403 `console_only`), `no-store`. Chapters share the
pages' limit (60 a minute); search has its own (`LIMITS["search"]` 60, installed by
`install_book_pages`). `?release=` as the pages routes; 404 `no_page` for a release not kept.

**`GET /v1/book/chapters?release=`** (old releases: chapters worked out, `narrated: false`)

```json
{"release": "afe8b38", "chapters": [
  {"id": "story_what", "title": "What JARVIS is", "kind": "story", "pages": ["pg_chapter_what"], "minutes": 0, "narrated": false},
  {"id": "module_vault", "title": "Vault and documents", "kind": "module",
   "pages": ["pg_module_vault", "pg_card_c07", "pg_card_c42", "pg_card_c43", "pg_screen_vault"], "minutes": 9, "narrated": true}]}
```

**`GET /v1/book/chapters/{chapter_id}?release=`** (404 `no_chapter`; an unnarrated one: `lines: []`)

```json
{"release": "afe8b38", "id": "module_vault", "title": "Vault and documents", "kind": "module",
 "pages": [{"id": "pg_module_vault", "title": "Vault and documents"}, {"id": "pg_card_c07", "title": "Attached documents"},
           {"id": "pg_card_c42", "title": "Document vault"}, {"id": "pg_card_c43", "title": "DigiLocker import folder"},
           {"id": "pg_screen_vault", "title": "Vault"}],
 "lines": [
  {"n": 1, "page": "pg_module_vault", "text": "This chapter is about how your documents reach JARVIS, and how the important ones are kept safe.",
   "cues": [{"kind": "page", "target": "pg_module_vault"}, {"kind": "show", "target": "title"}]},
  {"n": 6, "page": "pg_module_vault", "text": "It starts with you, adding a file to a message or to the vault.", "cues": [{"kind": "node", "target": "file"}]},
  {"n": 9, "page": "pg_module_vault", "text": "A message carries at most 10 files, and 40 megabytes together.", "cues": [{"kind": "count", "target": "10"}]},
  {"n": 25, "page": "pg_card_c07", "text": "Now the first part: attached documents.",
   "cues": [{"kind": "page", "target": "pg_card_c07"}, {"kind": "show", "target": "title"}]}],
 "minutes": 9, "narrated": true, "written": {"written_by": "Workshop · Mark XXIV", "written_on": "2026-11-25"}}
```

(4 of the 80 lines shown.) Cue targets: `page` a page id; `show` one of `title`, `plain`,
`example`, `how`, `costs`, `fails`, `overview`; `node` a box id; `edge` `"<from>><to>"` (e.g.
`"kind>refused"`); `count` the filled amount as text, `"10"` or `"₹2.9"` (strip `₹`, parse).

**`GET /v1/book/pages/search?q=&release=`** (422 `bad_query` unless `q` is 2–60 characters once
trimmed; `{"results": [], "total": 0}` when nothing matches)

```json
{"release": "afe8b38", "q": "expiry", "total": 26, "results": [
  {"id": "pg_module_vault", "title": "Vault and documents", "kind": "module",
   "snippet": "…with its own key, JARVIS reminds you before something expires, and nothing opens until you prove it's you. The DigiLocker import folder brings documents you…",
   "marks": [[55, 62]]},
  {"id": "pg_card_c42", "title": "Document vault", "kind": "card",
   "snippet": "…JARVIS reminds you before a document expires, and the brain only ever sees a document's type, title and dates, never the file or a full number…",
   "marks": [[38, 45]]}]}
```

At most 20 results; `marks` are [start, end) in UTF-16 units (`snippet.slice(a, b)` in JS). Words
match at their start, case-blind, with a light stem ("expiry" finds "expires"); every word must be
on the page; ranked title > the flowchart's title and box labels > text hits > index order.

## 6. `/book/read` and the token

- Served by `api/book_read.py` with `console._page`: the same headers and CSP as `/book/show`
  (tested). Mounted from `install_book_pages`, not `console.py` (which 7 pages cite). Its assets
  are one literal route each in `READ_ASSETS`: **A and B add any new file there.**
- The guest lock (`book_lock.py`) is NOT changed: under a lock `/book/read` is 423 like any owner
  screen; only the show passes. A guest never holds an owner token, so never reads it.
- The token: the panel's **Read the full book** calls `toShow(token, session, '/book/read')` (the
  show's hand-off): `jarvis_book_token` and `jarvis_book_session` in THIS tab's sessionStorage,
  the panel forgets it, the page goes to `/book/read`. A guest open always goes to the show.
- `console-book-read.js` (I0's part, A keeps the contract): no token → asks nothing,
  `#bookRead[data-state=closed]`, `#brGate` says how to open the book; with one →
  `GET /v1/book/chapters` → `data-state=ready`, the release id in `#brRelease`, the event
  `jarvis:book-read` `{release}`; a 401/403/404/410 forgets the token. It posts
  `/v1/book/show/beat` every 60 s while visible. **Short tour** → `/book/show` (same token).
  **Close** → `POST /v1/book/close`, the token cleared, back to `/` (no confirm yet; the show's
  End asks first: A decides).

## 7. Interfaces for builders A and B

**Globals and modules** (`book-read.html` loads `console-fx.js` and `console-book-voice.js`
(classic, deferred), then `console-book-read.js` and `console-book-chapter.js` as ES modules):

| File | Owner | Gives |
|---|---|---|
| `console-book-read.js` | A (I0's hand-off inside) | `window.JarvisBook = {api, raw, failure, captionMs, token, mode}` (the show's transport shape); `window.JarvisBookRead = {state(), release(), chapters(), ready(), close()}`; exports `api, close, ready` |
| `console-book-chapter.js` | B | `window.JarvisBookChapter = {open(chapterId, {line}) → Promise<boolean>, stop(), state() → {open, chapter, line, playing}}`; draws only in `#brPlayer`, sets `#bookRead[data-mode="player"]` while open (CSS hides `.bk-body` then) |
| `console-book-fx.js` | B | `export createFx(stage, {motion: 'full'|'calm'|'off'}) → {cue(line, cue), page(fromId, toId), pause(), resume(), stop(), dispose()}`; imported by the player, never linked |

**DOM ids** (`book-read.html`): A owns `#brTop` (`#brMenu` phone contents button, `#brSearchBox`,
`#brSearch` (combobox, maxlength 60), `#brResults` (listbox, hidden), `#brRelease`, `#brTour`,
`#brClose`), `#brBody` (`#brRail` with `#brContinue` and `#brContents`, `#brMain` with
`#brPage`, `#brToc`), `#brSheet` (phone dialog), `#brScrim`, `#brMini` (phone Play bar), `#brNote`
(polite status); I0's boot owns `#bookRead[data-state]`, `#brGate`, `#brGateText`, `#brBack`; B owns
`#brPlayer`.

**CSS** (`book-read.css`, all under `html[data-book]`): `--bk-measure:68ch`, `--bk-body` 16/1.65,
`--bk-lead` 18, `--bk-h1` Orbitron, `--bk-h2`/`--bk-label` Share Tech Mono, `--bk-paper`,
`--bk-raise`, `--bk-now`, `--bk-mark`, `--bk-tap:44px`; the mockup's classes (`.bk-top`, `.bk-rail`,
`.bk-nav`, `.bk-page`, `.bk-h1`, `.bk-h2`, `.bk-p`, `.bk-ex`, `.bk-fig`, `.bk-results`, `.bk-res`,
`.bk-player`, the lit flowchart `.fl-told`/`.fl-now`/`.fl-done`). Toc at ≥ 1280 px; one column and the
44 px rule at ≤ 860 px or a coarse pointer. Add yours in your own section, with these tokens.

**Flowcharts** (`console-book-flow.js`, an ES module): `figure(raw)` → a `<figure class="bk-flow">`
or null (raw = the page JSON's `flow`); `renderFlow(spec, host)` for a checked spec. Boxes are
`g.fl-node[data-id]` (class `fl-k-<kind>`), connectors `g.fl-link[data-from][data-to]` inside
`g.fl-mains` / `g.fl-sides`, the chart `svg.fl-svg`. **The SVG is redrawn when its box's width
asks for another layout** (a ResizeObserver replaces the children): B must re-apply `fl-told`,
`fl-now`, `fl-done` after a redraw (watch `box.firstChild` or re-apply on every cue).

**The voice** (`console-book-voice.js`, `window.JarvisBookVoice`): call `start('browser')` from
the Play tap (a user gesture), then `await say(id, text)` per line (resolves when it ends; `pause`,
`resume`, `stop`, `mute`, `dispose` as in the show). Two things to know:
1. In `'cloud'` mode a line id that isn't a show id goes to the **captions timer**, not the browser
   voice (`console-book-voice.js:142` and `:154`): always `start('browser')` for chapters. The cloud
   voice can't speak chapter lines anyway: `POST /v1/book/show/speak` speaks only the show's own
   line ids (`api/book_show.py:191`). If the owner chose the cloud voice, say "browser voice" in
   the player (a gap for the Workshop, not wired in R6.4).
2. Word boundaries aren't exposed (`onboundary` only pulses the level, `:90`). For lit captions
   add an optional third argument, `say(id, text, {onWord(charIndex, charLength)})`, called from
   `u.onboundary` when `e.name === 'word'` (backward compatible; the show passes none), and time an
   estimate when no boundary comes (`captionMs`: 330 ms a word + 800 ms).

## 8. Pages refreshed, and notes for I1

- Refreshed and stamped because I0 changed their code or their refs gained I0's files:
  `pg_card_c57`, `pg_module_book`, `pg_chapter_what`, `pg_screen_book`, `pg_card_c02`,
  `pg_chapter_planned`. A and B will make some stale again (D10: refresh in the same PR).
- The fact pack's route scan refuses a route added in a loop over `ROUTES` on a router with no
  prefix (`gen/facts_routes.py:256`): keep one prefixed router per prefix (`book_pages.py` has two).
- `module_integrations` is the longest chapter (27 pages): its writer may keep a service to one
  line. The plan's "Not in R6.4" list stands (no guest-safe book, no print).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.0 | 25 Nov 2026, 13:20 IST | R6.4 | First edition: what I0 built, the chapters, the narration, the sealing finding and choice, the routes with real JSON, `/book/read` and its token, the interfaces for A and B, notes for I1 | 🛠 Mark XXIV |
