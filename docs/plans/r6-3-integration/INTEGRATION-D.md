Version v6.3.1 · 23 Nov 2026, 18:35 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part D: the short tour (integration notes)

Builder D (Opus) on `r6-3-d` from `origin/r6-3-i0` @ `d25dbcc`. Plan `docs/plans/r6-3-book-content.md`
v6.3.3 ("The short tour's first script", D9, D13, D14, the `tour` suite), `BRIEF-COMMON.md`,
`BRIEF-D.md`, `I0-NOTES.md`. Per the owner's instruction of 23 Nov (skip what isn't mandatory), no
self-review agents ran: the Workshop's combined review after the join covers this part.

## 1. Plan (written first) and what was built

Order, each step test first (run red, then the least code, then green):

1. **The script** `src/jarvis/buildbook/gen/tour.json`: the approved words copied VERBATIM from the
   plan's tables (17 scenes, 55 beats; `t13b03` owner, `t13b04` guest, the rest both), each scene
   pinned as `tour_model.TOUR_SCENES`, its chapter, its picture (`{"from_show": n}`, or T12-T14's
   own data written from their own words), the keys it uses. Test: `tests/test_r63_d_script.py`
   (the plan's tables are read by `tests/r63_fakes_d.approved()`; three lines typed by hand guard
   the reader itself).
2. **The filler** `src/jarvis/buildbook/gen/tour.py` (315 lines): `build(repo, facts, *, show=None,
   script=None) -> Tour | None`, `check_script`, `tour_values`, `picture_problems`. Test:
   `tests/test_r63_d_tour.py`.
3. **The serve** `src/jarvis/buildbook/tour_serve.py` (80 lines): `tour_lines`, `tour_line_text`
   (optional `words`), `render`. Test: `tests/test_r63_d_serve.py` (H1 through the real routes).
4. **The page** `src/jarvis/api/static/console-book-tour.js` (100 lines, ≤ 300): `label`, `seen`,
   `start`. Tests: `tests/test_r63_d_static.py`, `tests/browser/test_r63_d_tour.py`.
5. **The eval** `evals/r6_3/tour.py`, BUILT, with its five controls.

Fakes: `tests/r63_fakes_d.py` (`PLAN_VALUES`: the facts table's "on 47ee8fc" column in A's forms;
`TOUR_FACTS`; 47ee8fc's real show; `TourSource`).

## 2. The filled tour, measured (plan values, 47ee8fc's show and this branch's real show alike)

| Audience | Seconds | Words | Characters | Lines | Scenes | `tour.minutes` |
|---|---|---|---|---|---|---|
| Owner | 795.7 | 1,761 | 9,416 | 54 | 17 | 14 |
| Guest | 767.8 | 1,699 | 9,093 | 53 | 16 | 13 |

Both inside the aimed bands (780-870 s, 760-850 s) and the hard band (600-900 s). The plan measured
1,762 / 9,415 and 1,700 / 9,092: the one-word difference is the roadmap rows' wording (A's form is
not known yet; see "Needs I1" 5). The tour adds 89,710 bytes to 47ee8fc's `book.json` (2 MiB cap).
The filled tour passes today's scrubber (`default_scrubber().verify`).

## 3. Checks (behind `/tmp/jarvis-heavy.lock`)

| Check | Result |
|---|---|
| `tests/test_r63_d_*.py` | 51 passed, 1 xfailed (pinned for I1, §5.3) |
| `tests/test_r63_*.py tests/test_book_*.py` | 1,057 passed, 5 skipped, 9 xfailed, **1 failed: I0's stub pin `test_the_empty_tour_script_is_package_data`** (moves at I1, §5.1) |
| `tests/browser/test_r63_d_tour.py` (Chromium, WebGL2 present: 3D ran) | 10 passed, 2 xfailed (pinned for I1, §5.2) |
| `evals/r6_3/run.py --mock --part tour` | 10/10 cases; the control failed the suite (all five controls turned their own case red) |
| `ruff check` / `ruff format --check` (my files) | clean |
| `mypy src` | the one baseline error only (`memory/redis_store.py:67`) |
| `python -m jarvis.buildbook.gen --check` | two builds byte-identical (no tour yet: A's stub pack is empty) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |

Screenshots (not committed), `/tmp/r63-d-shots/`: `phone-NN-<id>.png` (390 × 844, 2D) and
`laptop-NN-<id>.png` (1280 × 800, 3D) for all 17 scenes as they draw today (I0's modules), and
`fixed-phone-…`, `fixed-laptop-…` with §5.2's diff routed in (every scene draws its own data).

## 4. Decisions and deviations (with reasons)

1. **`build` takes the show** (`show=` keyword): `{"from_show": n}` copies a show scene's facts
   "at CI", but the join `tour.build(repo, pack)` gives no show. Without one the generator refuses
   (`GenError`), loudly, rather than shipping empty pictures (§5.1).
2. **No tour facts, no tour**: a pack with none of `FACT_TOUR_KEYS` (I0's stub, a fixture
   repository) builds no tour (today's 11-scene show); a pack with some but not all is a `GenError`
   naming the missing keys.
3. **T14's picture is generated from the module map** (the `{{modules.others}}` marker in
   `tour.json`, `PICTURE_KEYS`): one fact a module of `gen/modules.others()`, its title and "N
   parts" from its cards, so a new module grows the screen, not the time (D9); its count must equal
   `modules.else_count` (what the tour says), else `GenError`.
4. **A guest's pictures drop facts naming Rs**: show scene 11's facts hold Rs (7 of 60 in 47ee8fc,
   9 of 60 on this branch); a guest's T17 copy drops them. A guest's LINE naming Rs is a `GenError`.
5. **`tour.minutes` rounds up** (`ceil(seconds / 60)`): the plan's 14 and 13 (rounding to the
   nearest gives 13 and 13).
6. **Continue is automatic at Begin**, for the owner, same release, from the remembered scene's
   first line: I0's hook contract (`start` returns an index) has no place for an explicit
   "Continue: <scene>" offer before Begin (§5.6). Nothing is remembered before Begin (the show
   presents beat 0 while loading); Questions or the closing forget the scene.
7. **The chapters menu's titles** come from a table in `console-book-tour.js`, kept equal to
   `facts_model.CHAPTERS` and `gen/modules.MODULES` by `test_r63_d_static.py`: the show's script
   reader (`normalScene`) passes a scene's chapter id, not its title.
8. **Focus** (what a beat lights, not spoken) is chosen per beat from today's picture data (a
   flow's step, a layer, a group); T12-T14's groups are their own words.
9. **The digit rule** also covers T12-T14's own picture data (labels and values; "3D" allowed).

## 5. Needs I1 (exact diffs)

**5.1 The generator passes the show to the tour** (decision 1), and I0's stub pins move.

```diff
--- a/src/jarvis/buildbook/gen/write.py
+++ b/src/jarvis/buildbook/gen/write.py
@@ def assemble(repo: Repo, opts: Options) -> tuple[Book, FactPack]:
         p = _parts(repo, opts, scrub)
         pack = fact_pack(repo, p.release, scrub)
+        show = build_show(p)
         book = Book(
@@
-            show=build_show(p),
+            show=show,
             digest=build_digest(p),
-            tour=tour.build(repo, pack),
+            tour=tour.build(repo, pack, show=show),
         )
--- a/tests/test_r63_gen_joins.py
+++ b/tests/test_r63_gen_joins.py
@@
-    def fake_tour(repo: Repo, pack: FactPack) -> None:
+    def fake_tour(repo: Repo, pack: FactPack, show: object = None) -> None:
@@
-def test_the_empty_tour_script_is_package_data() -> None:
-    assert TourScript.model_validate_json(tour.SCRIPT_FILE.read_bytes()).scenes == ()
-    assert tour.load_script().scenes == ()
+def test_the_tour_script_is_package_data() -> None:
+    script = TourScript.model_validate_json(tour.SCRIPT_FILE.read_bytes())
+    assert script == tour.load_script() and len(script.scenes) == 17
```

**5.2 A scene after one with the same picture redraws** (I0's 2D and 3D modules key a drawn scene
by today's picture number, so T13-T15, picture 9 after T12, keep T12's data; T09 → T10 share data
and look right by chance). Verified in Chromium (2D and 3D) with the diff routed in; then remove
the `xfail` mark of `test_a_scene_after_one_with_the_same_picture_draws_its_own_data`.

```diff
--- a/src/jarvis/api/static/console-book-2d.js
+++ b/src/jarvis/api/static/console-book-2d.js
@@ function show(scene, beatIndex, beat, ctx) {
-      if (!cur || cur.n !== scene.n) {
+      if (!cur || cur.n !== scene.n || cur.id !== scene.id) { // R6.3: a tour scene may borrow the picture before it
@@
-        cur = Object.assign({ n: scene.n, box }, built); // it enters by a CSS animation (none in Calm / Off)
+        cur = Object.assign({ n: scene.n, id: scene.id, box }, built); // it enters by a CSS animation (none in Calm / Off)
--- a/src/jarvis/api/static/console-book-3d.js
+++ b/src/jarvis/api/static/console-book-3d.js
@@ function enter(sc, ctx) {
     if (cur) cur.root.visible = false;
-    if (!built.has(sc.n)) {
+    const key = sc.n + ':' + (sc.id || ''); // R6.3: tour scenes share today's pictures, each with its own data
+    if (!built.has(key)) {
@@
-      const s = make(kit); scene.add(s.root); built.set(sc.n, s);
+      const s = make(kit); scene.add(s.root); built.set(key, s);
     }
-    cur = built.get(sc.n); curN = sc.n; cur.root.visible = true; stats.scene = sc.n;
+    cur = built.get(key); curN = key; cur.root.visible = true; stats.scene = sc.n;
@@ function show(sc, i, beat, ctx) {
-    if (sc.n !== curN && !enter(sc, ctx)) return;
+    if (sc.n + ':' + (sc.id || '') !== curN && !enter(sc, ctx)) return;
```

(2D 191 lines, 3D 345: both under 400.)

**5.3 The spoken T16 line gets his honorific**: `tour_line_text` has no words in I0's call, so with
the cloud voice the owner would hear `{h}` read out in t16b01 (the browser's voice, the default,
reads the script's filled text). Then remove the `xfail` mark of
`test_the_owners_spoken_t16_line_has_his_honorific` in `tests/test_r63_d_serve.py`.

```diff
--- a/src/jarvis/buildbook/show_script.py
+++ b/src/jarvis/buildbook/show_script.py
@@ async def line_text(self, uid: str, line_id: str, audience: Audience) -> str | None:
         if tour_serve.TOUR_LINE.fullmatch(line_id):
-            return tour_serve.tour_line_text(self.source.book(), line_id, audience)
+            book, words = self.source.book(), await self.words(uid)
+            return tour_serve.tour_line_text(book, line_id, audience, words)
```

**5.4 C and D share `jarvis_book_place_v1`**: D writes `{release, scene}` and keeps a valid `page`
of the same release; C (`{release, page}`) must likewise keep a valid `scene` (an integer 1-17) of
the same release when it writes, or the tour's place is lost each time the reader saves.
`test_reaching_questions_forgets_the_scene_but_keeps_the_readers_page` pins D's half.

**5.5 When A's fact pack joins**: run `tests/test_r63_d_*.py`, the browser file and `--part tour`
on A's real pack (they use `r63_fakes_d.PLAN_VALUES` today); A's value forms must make the approved
lines read right: `loc.python_code` without "about" (L1), `seeme.inr_a_picture` and
`seeme.month_cap_inr` as "₹9" / "₹300", `release.date` as "24 Nov 2026", the roadmap rows as short
phrases (they are spoken: a long row lengthens T17; every line stays ≤ 400 characters or the
generator refuses). Check that `book_gen_fakes.fixture_repo` still builds: a pack holding SOME tour
keys but not all is a `GenError` (decision 2). Then `--check` on the real repository with a tour.

**5.6 Optional**: an explicit "Continue: <scene title>" offer on the start card needs a show.js hook
before Begin (D14's wording); today continue is automatic for the owner (decision 6).

## 6. What the brief or plan got wrong

- **M6, picture 4 "at least one `purpose` group and one other"**: show scene 4 (which T06, T09 and
  T10 borrow) has only `purpose` facts (26 in 47ee8fc; `gen/show.py` writes no other), so the rule can't hold;
  `picture_problems` asks for a `purpose` group only.
- **M6, picture 10 "a number `n` on every fact (≤ 10)"**: enforced as a number on every fact; the
  3D picture draws the first 10, the 2D 12 (show scene 10 has 25).
- **The join gives no show** for `from_show` (§5.1), **the speak join no words** (§5.3), and **I0's
  pictures redraw by picture number** (§5.2): the brief's contracts assume all three work.
- **T14's "list written in `tour.json`"**: a static list would not grow with the map (D9's own
  rule), so it is the `{{modules.others}}` marker, expanded at CI (decision 3).
- **Rs in show scene 11**: copying it into a guest's T17 would break "no Rs in a guest's picture
  facts" (decision 4).

No spoken word was changed; no wording problem was found. Every approved line is under 400
characters filled; no doubled word; the only typed digits are the running example's ("5 pm") and
"3D".

## 7. What could not be verified here

- A's real values (the hand-made pack stands in); the stopwatch check of the timer (exit check 6);
  the cloud voice reading tour lines (no voice service here; the route's 503 `voice_unavailable`
  proves each line resolved).
- M8's four private PHRASES: A's phrase rule hasn't landed, so the filled tour is checked against
  the hashed names only.
- The self-review agents (skipped by the owner's instruction of 23 Nov).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 18:35 IST | R6.3 | First edition: part D built (the approved script verbatim, the filler per audience with its timer and bands, the serve bound to the audience, the page's hooks, the eval with five controls), the measured tour, the checks, the decisions, "Needs I1" with exact diffs (the show to the tour, same-picture redraw, the spoken honorific, the shared place key, A's join), the plan's errors, what could not be verified | 🛠 Mark XXIV |
