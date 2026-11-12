Version v11.1.0 · 12 Nov 2026 · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 Part B · Voice and files — integration note for I1

Branch `r11-1-b` (from `r11-1-i0` @ `9250be1`). Observations O3 and O4 of
`docs/plans/r11-1-observations.md` (D0, D8, D9, D10, D11, D12, D21-B). Everything is in Part B's own
files; no wiring file was edited. This note says what was built, how to check it, what I1 must do, where
the build differs from the plan, and what could not be verified here.

## 1. What was built

| # | Item | Where | State |
|---|---|---|---|
| O3 | "Heard / Understood as" (D8, D21-B) | `src/jarvis/understand/` (`words.py`, `rules.py`, `near.py`, `guard.py`, `model.py`, `service.py`), `api/fix_files.py` | Built. `POST /v1/input/understand {heard, alternatives?, files?, session_id?, confidence?}` → `{understood, changed, sure, question, via}`. Fixed rules first and free (a table of 60 real mishearings and near-matches against the hints); the fast tier only when unsure and only with the AI on, admitted (`Billing.ensure_allowed`) and metered (`Billing.record`) on a brain that does not learn; otherwise one short question. A number, an amount, a date, a time, a person's name, a phone number or an e-mail address is never rewritten, by a rule or by the model: plain code checks the model's answer (`guard.acceptable`) and asks instead. |
| O3 | The heard words in the chat | `console.js`, `console-r111-files.js`, `ChatRequest.heard` / `Turn.heard` (I0) | Built. Two fine lines under the spoken message ("Heard: …" / "Understood as: …") whenever something changed, also on a reopened conversation. Stored for display only; a test proves they never reach a model's window. |
| O3 | Per-turn hints and three alternatives (D9) | `understand/hints.py`, `voice/google_cloud.py`, `voice/service.py`, `api/voice.py`, `console-voice-loop-browser.js`, `console-voice-mic.js`, `console-voice-phrases.js` | Built. Hints = the names of the owner's waiting and attached files as they are said ("study plan", "CSV") and his own turns' nouns, at most `voice_hint_words`; to Google as speech contexts between the base list and his own words; to the browser recogniser where it takes hints. Both recognisers are asked for three alternatives. The language is untouched (`en-IN` already); no setting was added. |
| O4 | Excel `.xlsx` / `.xlsm` | `documents/sheets.py` | Built. openpyxl, read-only, values never formulas; each sheet as rows of text; more than 50 sheets refused whole; 5,000 rows a sheet (the rest counted and said). |
| O4 | Excel `.xls` | `documents/sheets.py` | Built. xlrd, its warnings sent nowhere; same shape and caps. |
| O4 | PowerPoint `.pptx` | `documents/slides.py` | Built. Slide words and each slide's own notes, in the deck's own order; lxml with entities, DTDs and the network off. |
| O4 | Pictures `.png` / `.jpg` / `.jpeg` (D10) | `documents/imagecheck.py`, `documents/pictures.py`, `documents/store.py` | Built. Structure checked and camera / location data removed without decoding a pixel (JPEG: the existing `photos.imaging.sanitise_jpeg`; PNG: a chunk filter with checksums); over 2,048 px a side or over `attach_picture_max_kb` refused in plain words; kept beside the file as bytes, never in a turn. `with_pictures` shows them to a seeing, non-training brain only, only with the turn they came with; every other brain gets the fixed line. |
| O4 | `.zip` | `documents/archive.py` | Built. Members one by one, each as its own kind (a picture inside is taken too, at most 4). A password, a bomb, a path that points outside, an archive inside and more readable files than `attach_zip_max_files` are refused from the directory alone, before anything is unpacked. |
| O4 | A folder | `documents/archive.py`, `console-r111-files.js`, `console-attach.js`, `api/documents.py` | Built. The folder button packs the folder's readable files into ONE stored zip in the browser and uploads it with `X-Jarvis-Folder: 1`; the server reads it with the zip reader and `attach_folder_max_files`. |
| O4 | Limits (D11) | `documents/limits.py` (`AttachPolicy`), `documents/service.py` | Built. 10 files a message (was 3), 10 MB a file, 40 MB together, 4 pictures: the owner's settings. |
| O4 | The rupee estimate (D12) | `understand/estimate.py`, `api/fix_files.py`, `console-r111-files.js` | Built. `POST /v1/input/estimate` → "About ₹N on the balanced tier; about ₹M on the stronger tier." above Send, with the tier it suggests; the owner chooses, then it is sent with that tier. From ₹5, never below; never for a free brain, in No-AI mode, or for small files. It never calls a model. |
| — | Console (D0) | `console-r111-files.js` / `.css`, `console-attach.js` / `.css`, `console.js`, three voice scripts | Built. The accept list and the tooltip are set from the script's own list (and from `GET /v1/input`); the page itself is unchanged. Existing classes only (`.bfine`, `.bnote`, `.btn`, `.clip`). |
| — | Eval | `evals/r11_1/files.py` | Built, `BUILT = True`: 11 cases, three negative controls, each of which fails its case. |

`build(ctx)` (`understand/part.py`) returns `FixPart("files")` with no tool, no job and no privacy row,
`ready = "ready"`, and two services for its own routes: `understand` and `estimate`.

## 2. How to check it

```
pytest -q -p no:cacheprovider tests/test_r11_1_*.py tests/test_documents_*.py \
    tests/test_voice_*.py tests/test_console_attach.py tests/test_console_assets.py
PYTHONPATH=src python evals/r11_1/run.py --mock --part files
JARVIS_BROWSER_TESTS=1 PYTHONPATH=src \
    python -m pytest -q tests/browser -m browser -k "r11_1 or ui_audit"
```

| What the plan asks of B | The test that proves it |
|---|---|
| A fixture set of real mishearings is corrected by the rules with no model call | `test_r11_1_b_rules.py::test_a_real_mishearing_is_corrected_by_the_rules_alone` (24 cases from `tests/fixtures/r11_1/b_mishearings.json`), `test_r11_1_b_understand.py::test_a_known_mishearing_is_understood_with_no_model_call` |
| An unsure case makes exactly one fast-tier call with the AI on, none in No-AI mode | `…::test_an_unsure_case_makes_exactly_one_fast_tier_call_admitted_and_metered`, `…::test_no_ai_mode_makes_no_call_and_asks_one_question`, `…::test_past_the_monthly_limit_makes_no_call_and_asks`, `…::test_a_brain_that_learns_is_never_asked` |
| An unresolvable case asks one question | `…::test_the_one_question_says_what_was_nearly_understood`, `…::test_a_near_miss_on_a_file_name_asks_about_that_file` |
| D21-B: nothing that matters is rewritten | `test_r11_1_b_rules.py::test_protected_words_survive_every_correction_around_them`, `test_r11_1_b_understand.py::test_a_model_answer_that_touches_a_protected_word_is_thrown_away` (9 cases), `…::test_a_number_is_never_rewritten_it_is_asked_about` |
| `heard` is stored and never reaches a model's window | `…::test_the_heard_words_are_kept_for_display_and_never_reach_a_model` |
| Each new kind is read inside its caps | `test_r11_1_b_kinds.py` (34 tests), `test_r11_1_b_archive.py::test_a_zip_is_read_file_by_file_each_as_its_own_kind`, `test_r11_1_b_service.py` |
| A zip bomb, a nested zip, a path-escaping member, a 300-sheet workbook and an oversized picture are refused in plain words and the child is killed on time | `test_r11_1_b_archive.py::test_each_hostile_file_is_refused_by_the_child_in_plain_words` (5 cases), `…::test_a_zip_bomb_is_refused_from_its_directory_alone`, `…::test_a_child_that_reads_too_long_is_killed_on_time`, `…::test_a_child_over_its_cpu_seconds_is_stopped_too` |
| A picture reaches only a seeing, non-training brain and is never stored in a turn | `test_r11_1_b_pictures.py` (17 tests), in particular `…::test_a_brain_that_may_learn_is_never_shown_one_even_if_it_can_see` and `…::test_the_brain_shows_the_picture_once_and_never_stores_it` |
| The estimate appears above ₹5 and never below | `test_r11_1_b_estimate.py::test_a_large_file_shows_both_tiers_in_rupees_with_about`, `…::test_nothing_is_shown_below_five_rupees` |
| The console pieces, with the look unchanged | `tests/browser/test_r11_1_b_files.py` (14 tests: the picker, Excel / deck / zip read by the real server, the picture shrink, the folder bundle opened as a real zip, heard / understood as, the question, the cost line, and the visual gate at 1440×900 and 390×844 in Night and Day) |

## 3. Needs I1

### 3.1 Dependencies (cloud image: `pyproject.toml`, `requirements.lock`, `requirements.licences.json`)

| Package | Version tried | Licence | Why |
|---|---|---|---|
| `openpyxl` | 3.1.5 | MIT | Reads `.xlsx` / `.xlsm` in the extraction child (read-only, values only) |
| `et-xmlfile` | 2.0.0 | MIT | openpyxl's own dependency |
| `xlrd` | 2.0.2 | BSD | Reads `.xls` in the extraction child (owner question 5: default "add it") |
| `lxml` | 6.1.3 (already locked through python-docx) | BSD-3-Clause | Now imported directly by `documents/slides.py`: list it as a direct dependency |

Nothing else: pictures need no library (structure checks only), a zip is the standard library, and
`opencv-python-headless` / `numpy` are Part C's for the home bridge, not the cloud image. `defusedxml`
is deliberately not added: an Office file with a DTD or a non-UTF-8 XML part is refused before any
parser sees it (`extract.office_guard`), inside the child's CPU, memory and time caps.

### 3.2 One line in `api/feature_wiring.py` (recommended)

```diff
-    app.state.documents = DocumentService(AttachmentStore(docs, prefix=s.firestore_prefix))
+    app.state.documents = DocumentService(
+        AttachmentStore(docs, prefix=s.firestore_prefix), policy=policy_from(s)
+    )
```
(`from jarvis.documents.service import DocumentService, policy_from`.) Until then the upload routes
and `/v1/input` set the owner's limits on the service on every request (`api/documents._svc`), so they
apply; the only gap is a message sent after a restart before any upload request, which uses the
defaults (the same numbers unless `JARVIS_ATTACH_*` was changed).

### 3.3 `core/models.py` (I0's seam)

`ChatRequest.attachments` has `max_length=10` and still says "at most 3". `attach_max_files` may be set
up to 20, but a message with more than 10 ids is refused by that field first. Either raise it to 20 or
lower the setting's upper bound to 10; and correct the description.

### 3.4 The guide and the docs (`docs/architecture/*`, README, go-live)

- Card C61: Part B as built (this note's table). Card C07 "Data it keeps": add
  `attachments/{id}/pictures/{01..04}` (a cleaned picture's bytes, at most 900 KB each, deleted with the
  attachment). No new collection: `COLLECTIONS["files"]` stays empty.
- Voice cards (C05 / C21): three alternatives; per-turn hints from file names and the owner's own turns;
  optional header `X-Jarvis-Session` on `POST /v1/voice/transcribe`; `alternatives` in its answer.
- `evals/r11_1/run.py` into `evals/run_all_mock.py` (the plan already lists this).

### 3.5 Nothing else

No new setting, alert kind, permission row, keyring purpose, secret or `console.html` line. No persona
sentence is needed for B (the turn note already tells the model what each file is).

## 4. What Part D may rely on from `turn_pictures`

```python
from jarvis.documents.pictures import turn_pictures
blocks = await turn_pictures(docs, user_id, session_id)            # list[ImageBlock]
blocks = await turn_pictures(docs, user_id, session_id, spec=spec)  # [] unless spec.sees_pictures
```

- It returns the pictures attached to the conversation's LATEST owner turn, newest first, at most 4,
  as `jarvis.llm.base.ImageBlock` (`image/jpeg` or `image/png`, already cleaned: no EXIF, no text
  chunks, at most 2,048 px a side and `attach_picture_max_kb`). Pictures found inside a zip or a folder
  sent with that turn count too.
- It returns `[]`, and never raises: when `docs` is None; for anyone but the owner of that conversation;
  when the latest owner turn came without a picture (an earlier turn's pictures are never returned);
  when the turn was sent before a restart (the "latest turn" record is in this process only:
  `DocumentService.note_turn`, written by `save_owner_turn` for every owner turn, AI on or off); when
  storage cannot be read; and, with `spec` given, for a brain that may not see pictures.
- It does not check the brain unless `spec` is passed. A caller that makes its own vision call must use
  a brain whose `BrainSpec.sees_pictures` is true (pass `spec`, or use `without_pictures`): a picture
  must never reach a blind or a training brain.
- A round that carries a picture is already tainted (the turn note holds a fenced line), so any write
  after it is an approval card; the picture's own words are data, never instructions.

## 5. Where the build differs from the plan

1. **Hints cap (D9).** `voice_hint_words` caps the per-turn additions (file names and nouns). The owner's
   own "Words to recognise" keep their own limit of 50 and are never crowded out; the plan's sentence
   could be read as capping all three together.
2. **Conversation nouns (D9)** come from the owner's own turns only, never from a reply (a reply may carry
   a mail's or a web page's words, and hints go to Google's recogniser).
3. **Low confidence alone (D8)** asks the fast tier when the AI is on, but never becomes a question by
   itself: with no model to check it the words go through as heard, or every quiet sentence would be a
   dead end in No-AI mode.
4. **A protected word (D21-B)** makes the rules ask at once; the model is not asked to do what the rules
   may not ("add it 2 the calendar" → "Did you mean “add it to the calendar”, Sir?", no call).
5. **A folder (D11)** goes up as one bundle (one attachment, at most 10 MB), not as separate files: a
   message carries 10 attachments and a folder may hold 50 files, so only one bundle fits both numbers.
   The folder button is hidden under 520 px (the composer has no room); on a phone, attach the files
   or a zip.
6. **A zip (D11)** with more readable files than the cap is refused whole (never half-read); members
   JARVIS does not read are named under "Not read:", not refused.
7. **Pictures (D10).** The browser shrinks a picture only when it must (over 1,568 px or over the weight
   cap); a small PNG stays a PNG and the server removes its extra chunks. The server's size cap is 2,048
   px a side (the existing sanitiser's). A picture inside a zip or folder is taken too.
8. **The estimate (D12).** "The output cap's typical use" is a quarter of `work_output_tokens`; a picture
   counts about 1,500 tokens only for a brain that will see it; the ₹5 threshold is on the tier the reply
   would use; the stronger tier is suggested only for complex files (many sheets, rows or pictures). On a
   spoken turn the line is shown and JARVIS says "The cost is on the screen, Sir. Choose how to send it."
9. **The limits reach the document service through its routes**, not at build time (the contract forbids
   reading app state while `build` runs): see 3.2.
10. **`.xlsm`** is read as `.xlsx` (macros are never run); hidden sheets are read like any other.
11. **A question** shows as the heard words marked "Spoken · Not sent" and JARVIS's question marked
    "Asked first"; nothing reaches the Brain.

## 6. Existing tests changed (behaviour the plan changes on purpose; none weakened)

| Test | Change |
|---|---|
| `tests/test_documents_extract.py::test_other_extensions_are_unsupported_with_a_plain_message` | `sheet.xlsx`, `pic.png` are read now: the cases use `sheet.ods`, `pic.gif` |
| `tests/test_documents_api.py::test_upload_returns_201_and_the_ref` | the answer gains `sheets`, `rows`, `slides`, `files`, `skipped`, `pictures` |
| `tests/test_documents_api.py::test_more_than_three_files…` | now `test_more_files_than_the_owners_limit…` (with `attach_max_files=3`) plus `test_four_files_now_go_with_one_message` |
| `tests/test_documents_service.py::test_attach_refusals_are_plain` | "3 files" comes from the owner's policy |
| `tests/test_voice_google.py::test_recognize_sends_the_documented_request` | `maxAlternatives` 1 → 3 |
| `tests/test_voice_api.py::test_transcribe_returns_the_contract` | the answer gains `alternatives` |
| `tests/test_console_attach.py::test_attach_script_writes_text_only…` | the limits line: 10 files, 40 MB together, 4 pictures |
| `tests/test_console_assets.py::test_voice_contract_paths_headers_and_channel` | the mic's `Chat.send` call carries `alternatives` and `confidence` |
| `tests/browser/test_voice_pace.py::test_the_helper_cleans_like_the_server_and_offers_the_list_only_where_supported` | this turn's hints now join his own words in the recogniser's list (D9); the test answers `GET /v1/input/hints` with none, so its count of one word still holds |

`tests/test_r5_seams.py` pins `JarvisVoicePhrases` to `{clean, list, apply}`; it was left alone, and the
per-turn hints reach `apply` through `JarvisFixes.parts.files.hints()` instead of a new export.

`tests/test_r11_1_seams.py::test_the_eval_runner_passes_with_every_part_still_a_stub` (not ours to edit)
looks for each part's name and for "not built yet" in the runner's output. A built part prints no stub
line, so `evals/r11_1/files.py::cases` writes one line of its own ("files: built, 11/11 cases passed")
and the test stays green on this branch. **For I1:** once all four parts are built nothing prints
"not built yet" and that assertion must go; the test's name already says it is for the stub stage.

## 7. Not verified live (the sandbox reaches no Google, no Claude, no Firestore)

- Google Speech-to-Text with `maxAlternatives: 3` and per-turn speech contexts (what it accepts, what it
  returns for Indian English); a refused request is retried once with the base list alone.
- Chrome's own recogniser: three alternatives and phrase biasing in the owner's Chrome.
- Claude reading the cleaned JPEG / PNG (the provider's encoding is I0's; the bytes are standard).
- Firestore keeping a 900 KB picture as a bytes field in one document, and one commit of a file's
  chunks with up to four pictures (tests use the in-memory store).
- Real files from Excel and PowerPoint: tests use workbooks written by openpyxl, one 5 KB `.xls` made
  with xlwt (`tests/fixtures/r11_1/b_made_up.xls`, made-up rows) and decks built by hand. Chrome's own
  JPEG from the canvas does pass the server's check (browser test).
- A 10 MB workbook inside the child's 200 MB address-space cap on Cloud Run: a very large one may be
  refused as "too large or unusual" rather than read.
- The mishearing table: built from the owner's two examples and common Indian-English patterns, not from
  recordings. It is data (`understand/rules.py::RULES`); new rows are one line each.
- The fast tier's real answers to the understood-as prompt, and its real price (the mock meters about
  ₹0.004 a call; the plan says about ₹0.01).
- Folder picking (`webkitdirectory`) in the owner's browsers; there is no folder button on a phone.

## 8. Owner checks (after deploy)

1. Say "add D csb file Tu D calender" with `study-plan.csv` attached: the message shows "Heard: … /
   Understood as: Add the CSV file to the calendar".
2. Say "add it 2 the calendar": JARVIS asks "Did you mean “add it to the calendar”, Sir?" and does nothing.
3. Attach an `.xlsx`, an `.xls`, a `.pptx`, a photo, a zip and a folder: each chip says what it holds; ask
   about each. A photo's chip says "picture"; Claude answers about it, another brain says it was not shown.
4. Attach a large workbook and press Send: the cost line appears with two tiers; choose one.
5. Vitals: the understood-as calls appear under the brain's rupees (about a paisa each).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.0 | 12 Nov 2026, 08:15 IST | R11.1 | First edition: Part B built (O3, O4), how to check it, Needs I1 (three libraries, one wiring line, the attachments field, the guide), what Part D may rely on from `turn_pictures`, eleven differences from the plan, nine existing tests changed, the eval-runner seam test to retire at I1, what is not verified live, owner checks | 🛠 Mark XV |
