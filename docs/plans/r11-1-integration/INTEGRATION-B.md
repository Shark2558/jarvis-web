Version v11.1.1 · 12 Nov 2026, 10:00 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 Part B · Voice and files — integration note for I1

Branch `r11-1-b` (from `r11-1-i0` @ `9250be1`). Observations O3 and O4 of
`docs/plans/r11-1-observations.md` (D0, D8, D9, D10, D11, D12, D21-B). Everything is in Part B's own
files; no wiring file was edited. This note says what was built, how to check it, what I1 must do, where
the build differs from the plan, and what could not be verified here. v11.1.1 adds what the two
fresh-context reviews found and how each finding was fixed (section 9).

## 1. What was built

| # | Item | Where | State |
|---|---|---|---|
| O3 | "Heard / Understood as" (D8, D21-B) | `src/jarvis/understand/` (`words.py`, `rules.py`, `near.py`, `guard.py`, `model.py`, `service.py`), `api/fix_files.py` | Built. `POST /v1/input/understand {heard, alternatives?, files?, session_id?, confidence?}` → `{understood, changed, sure, question, via}`. Fixed rules first and free (a table of 60 real mishearings and near-matches against the hints); the fast tier only when unsure and only with the AI on, admitted (`Billing.ensure_allowed`) and metered (`Billing.record`) on a brain that does not learn; otherwise one short question. A number, an amount, a date, a time, a person's name, a phone number or an e-mail address is never rewritten, by a rule or by the model: plain code checks the model's answer (`guard.acceptable`) and asks instead. v11.1.1: no fixed rule turns one real word into another that changes the request (each rule's context is in `understand/context.py`; the audit is section 5a); the model can only respell misheard words: no action word (`words.ACTION_WORDS`, from the gateway's tool verbs) changed, added or dropped, and every changed word a near spelling of the one it replaces or what the recogniser offered in that place (a hint alone is never enough). |
| O3 | The heard words in the chat | `console.js`, `console-r111-files.js`, `ChatRequest.heard` / `Turn.heard` (I0) | Built. Two fine lines under the spoken message ("Heard: …" / "Understood as: …") whenever something changed, also on a reopened conversation. Stored for display only; a test proves they never reach a model's window. v11.1.1: a check that fails or is late says "Couldn't check the words; sent as heard." under the row. |
| O3 | Per-turn hints and three alternatives (D9) | `understand/hints.py`, `voice/google_cloud.py`, `voice/service.py`, `api/voice.py`, `console-voice-loop-browser.js`, `console-voice-mic.js`, `console-voice-phrases.js` | Built. Hints = the names of the owner's waiting and attached files as they are said ("study plan", "CSV") and his own turns' nouns, at most `voice_hint_words`; to Google as speech contexts between the base list and his own words; to the browser recogniser where it takes hints. Both recognisers are asked for three alternatives. The language is untouched (`en-IN` already); no setting was added. v11.1.1: no file name is a hint with Documents on "Never" (or unreadable); the owner's waiting files are read by one query on his own key; the "Words to recognise" privacy card says what goes to Google Speech as hints. |
| O4 | Excel `.xlsx` / `.xlsm` | `documents/sheets.py` | Built. openpyxl, read-only, values never formulas; each visible sheet as rows of text; hidden and very hidden sheets never read ("(2 hidden sheets not read)"); more than 50 sheets in all refused whole (one count, hidden ones too); 5,000 rows a sheet (the rest counted and said). Every member of the zip is scanned for a DTD by its content before any parser runs (`extract.office_guard`). |
| O4 | Excel `.xls` | `documents/sheets.py` | Built. xlrd, its warnings sent nowhere; same shape, caps and hidden-sheet rule. |
| O4 | PowerPoint `.pptx` | `documents/slides.py` | Built. Slide words and each slide's own notes, in the deck's own order; lxml with entities, DTDs and the network off; a slide or a notes page that cannot be read is said. |
| O4 | Pictures `.png` / `.jpg` / `.jpeg` (D10) | `documents/imagecheck.py`, `documents/pictures.py`, `documents/store.py` | Built. Structure checked and camera / location data removed without decoding a pixel (JPEG: the existing `photos.imaging.sanitise_jpeg`; PNG: a chunk filter with checksums); over 2,048 px a side or over `attach_picture_max_kb` refused in plain words; kept beside the file as bytes, never in a turn. `with_pictures` shows them to a seeing, non-training brain only, only with the turn they came with; every other brain gets the fixed line. v11.1.1: the latest turn comes from the STORED conversation, never from this process; `turn_pictures` says when it could not read (section 4); the parent cleans every picture the child returns again. |
| O4 | `.zip` | `documents/archive.py` | Built. Members one by one, each as its own kind (a picture inside is taken too, at most 4). A password, a bomb, a path that points outside, an archive inside and more readable files than `attach_zip_max_files` are refused from the directory alone, before anything is unpacked. |
| O4 | A folder | `documents/archive.py`, `console-r111-files.js`, `console-attach.js`, `api/documents.py` | Built. The folder button packs the folder's readable files into ONE stored zip in the browser and uploads it with `X-Jarvis-Folder: 1`; the server reads it with the zip reader and `attach_folder_max_files`. |
| O4 | Limits (D11) | `documents/limits.py` (`AttachPolicy`), `documents/service.py` | Built. 10 files a message (was 3), 10 MB a file, 40 MB together, 4 pictures: the owner's settings. |
| O4 | The rupee estimate (D12) | `understand/estimate.py`, `api/fix_files.py`, `console-r111-files.js` | Built. `POST /v1/input/estimate` → "About ₹N for one reply on the balanced tier; about ₹M on the stronger tier." above Send, with the tier it suggests; the owner chooses, then it is sent with that tier. From ₹5, never below; never for a free brain, in No-AI mode, or for small files. It never calls a model. v11.1.1: a fault answers `unavailable: true` (never "nothing to show"), and the console asks "Couldn't estimate the cost; send anyway?" (Send anyway / Cancel) before a large message goes, also when the request itself fails. What counts as large comes from `GET /v1/input` (`limits.large`). |
| — | Console (D0) | `console-r111-files.js` / `.css`, `console-attach.js` / `.css`, `console.js`, three voice scripts | Built. The accept list and the tooltip are set from the script's own list (and from `GET /v1/input`); the page itself is unchanged. Existing classes only (`.bfine`, `.bnote`, `.btn`, `.clip`). |
| — | Eval | `evals/r11_1/files.py` | Built, `BUILT = True`: 11 cases, six negative controls (v11.1.1 adds: the guard switched off, the ₹5 threshold removed, an estimate fault reported as nothing to show), each of which fails its case. |

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
| (review H1) No fixed rule turns a real word into another that changes the request | `test_r11_1_b_rules.py::test_remainder_becomes_reminder_only_with_a_real_reminder_cue`, `…::test_remainder_in_money_talk_is_left_as_heard`, `…::test_each_tightened_rule_fires_only_where_it_cannot_change_the_request` (31 cases, one or more per tightened rule), `…::test_a_near_match_never_touches_or_makes_an_action_word`, and the fixture's 17 new `untouched` and one new `asks` case (also run by the eval) |
| (review M1) The fast tier cannot change the action | `test_r11_1_b_guard.py` (all of it: the review's probe, action words never changed / added / dropped, near spelling or the recogniser's own word in that place, the rules' reading as baseline, every gateway tool verb is an action word), eval `protected` with the hostile file name, control "the guard switched off" |
| (review M2) An estimate fault is never "under ₹5" | `test_r11_1_b_estimate.py::test_an_estimate_that_cannot_be_worked_out_says_so` (3 faults), `…::test_nothing_to_estimate_is_not_a_fault`, browser `test_a_cost_that_could_not_be_estimated_waits_for_the_owner` (2), eval `estimate` and its two controls |
| (review M3) A turn's pictures come from the stored conversation; a fault is not "no picture" | `test_r11_1_b_pictures.py::test_turn_pictures_reads_the_stored_conversation_not_this_process`, `…::test_turn_pictures_never_raises_and_says_when_it_could_not_read`, `…::test_without_a_conversation_store_it_cannot_tell_and_says_so`, `…::test_a_picture_bound_to_another_turn_is_never_this_turns`, `…::test_when_some_pictures_load_the_turn_says_how_many_did_not` |
| (review M5) Hidden sheets are not read; one count | `test_r11_1_b_kinds.py::test_hidden_and_very_hidden_sheets_are_not_read_and_are_said`, `…::test_a_workbook_with_only_hidden_sheets_says_so`, `…::test_the_sheet_cap_counts_every_sheet_once_hidden_ones_too`, `…::test_a_hidden_xls_sheet_is_not_read_either` |
| (review M6) A failed meter keeps the answer; the console is never silent | `test_r11_1_b_understand.py::test_a_meter_that_fails_after_the_call_keeps_the_answer`, `…::test_a_limit_that_cannot_be_checked_means_no_call_and_one_question` (2), browser `test_a_failed_check_says_so_and_sends_the_words_as_heard` |
| (security M1) A DTD in any member of an Office zip is refused | `test_r11_1_b_kinds.py::test_a_dtd_in_a_part_with_any_name_is_refused` (6: the review's proof of concept), `…::test_the_child_refuses_the_renamed_dtd_part_too`, `…::test_a_part_in_another_encoding_is_refused_whatever_its_name`, `…::test_the_xml_cap_counts_a_part_by_its_content_not_its_name`, `…::test_a_pptx_slide_with_any_name_is_scanned_too`, `…::test_a_plain_renamed_part_and_a_picture_member_are_still_read` |
| (security L1, L3, L4) Pictures cleaned again; limits; one owner's rows; no file names with Documents off | `test_r11_1_b_archive.py::test_the_parent_cleans_each_picture_again_and_refuses_one_that_changes`, `test_r11_1_b_understand.py::test_the_hints_and_estimate_routes_are_rate_limited_per_owner_too` (2), `…::test_the_hints_read_only_this_owners_waiting_files_by_query`, `…::test_a_file_sent_with_a_message_is_no_longer_a_waiting_hint`, `…::test_no_file_name_is_a_hint_when_documents_are_switched_off` (2), `test_voice_privacy.py::test_the_card_says_file_names_and_own_words_go_to_google_speech_as_hints` |
| (code L1, L2, L3, L8) | `test_r11_1_b_archive.py::test_the_jpeg_side_cap_has_one_source_the_sanitiser`, `test_r11_1_b_kinds.py::test_a_notes_page_that_cannot_be_read_is_said`, `test_r11_1_b_estimate.py::test_the_console_takes_what_counts_as_large_from_the_server`, `test_r11_1_b_archive.py::test_a_child_that_reads_too_long_is_killed_on_time` (now on the kill) |
| The console pieces, with the look unchanged | `tests/browser/test_r11_1_b_files.py` (17 tests: the picker, Excel / deck / zip read by the real server, the picture shrink, the folder bundle opened as a real zip, heard / understood as, the unchecked line, the question, the cost line, the unknown cost, and the visual gate at 1440×900 and 390×844 in Night and Day) |

## 3. Needs I1

Each item below is a file Part B may not edit (brief, section 2). The diffs are exact.

### 3.1 Dependencies (cloud image: `pyproject.toml`, `requirements.lock`, `requirements.licences.json`)

| Package | Pin | Licence | Why |
|---|---|---|---|
| `openpyxl` | `==3.1.5` | MIT | Reads `.xlsx` / `.xlsm` in the extraction child (read-only, values only) |
| `et-xmlfile` | `==2.0.0` | MIT | openpyxl's own dependency |
| `xlrd` | `==2.0.2` | BSD | Reads `.xls` in the extraction child (unmaintained, final release; it runs only in the capped child). `documents/sheets.py::_xls_visible` reads its `_sheet_visibility` list (no public reader exists): keep the pin exact |
| `lxml` | `==6.1.3` (already in `requirements.lock` through python-docx) | BSD-3-Clause | Now imported directly by `documents/slides.py`: list it as a direct dependency at the version installed |

```diff
 # pyproject.toml, [project] dependencies
+    "openpyxl==3.1.5",
+    "et-xmlfile==2.0.0",
+    "xlrd==2.0.2",
+    "lxml==6.1.3",
```
then regenerate `requirements.lock` with hashes as the lock already does, and add the three new rows
to `requirements.licences.json`. Nothing else: pictures need no library (structure checks only), a zip
is the standard library, and `opencv-python-headless` / `numpy` are Part C's for the home bridge, not
the cloud image. `defusedxml` stays out: every member of an Office zip is now scanned for a DTD by its
content, and any part written as XML must be UTF-8, before any parser sees it (`extract.office_guard`,
security review M1), inside the child's CPU, memory and time caps.

### 3.2 `api/feature_wiring.py` (code review M4; and M3)

```diff
-from jarvis.documents.service import DocumentService
+from jarvis.documents.service import DocumentService, policy_from
@@ def wire_features(
-    app.state.documents = DocumentService(AttachmentStore(docs, prefix=s.firestore_prefix))
+    app.state.documents = DocumentService(
+        AttachmentStore(docs, prefix=s.firestore_prefix),
+        policy=policy_from(s),  # what one message may carry: the owner's own settings (M4)
+        sessions=app.state.store,  # a turn's pictures come from the stored conversation (M3)
+    )
```
(`app.state.store` is set by `app._wire_core`, which runs before `wire_features`.) Then, and only then,
drop the per-request assignment in `api/documents.py` (Part B's file; it must stay until the line above
lands, or the owner's limits would reach the service nowhere):
```diff
 def _svc(request: Request) -> DocumentService:
     svc: DocumentService | None = getattr(request.app.state, "documents", None)
     if svc is None:
         raise LookupError("Attached files are not available on this server.")
-    settings = getattr(request.app.state, "settings", None)
-    if settings is not None:  # R11.1: what one message may carry is the owner's own setting
-        svc.policy = policy_from(settings)
     return svc
```
Until 3.2 lands: the upload and `/v1/input` routes set the owner's limits on every request, so a message
sent after a restart before any upload uses the defaults (the same numbers unless `JARVIS_ATTACH_*` was
changed); and `turn_pictures` has no conversation store unless its caller passes `sessions=`, so it
answers "could not read" (`unreadable=True`), never another turn's pictures. `with_pictures` (the Brain's
path) is not affected: it is handed the conversation.

### 3.3 `core/models.py` and `config.py`: the two bounds must agree (code review M4)

`ChatRequest.attachments` allows 10 ids; `attach_max_files` may be set up to 20, so a message of 11–20
files is refused by the field before the owner's own limit is ever read. Both become 10:
```diff
 # src/jarvis/core/models.py, class ChatRequest
     attachments: list[str] = Field(
         default_factory=list,
         max_length=10,
-        description="Ids from POST /v1/attachments sent with this message (at most 3; slice 10)",
+        description="Ids from POST /v1/attachments sent with this message (at most 10; R11.1 D11)",
     )
```
```diff
 # src/jarvis/config.py, class Settings
     attach_max_files: int = Field(
-        default=10, ge=1, le=20, description="Files one message may carry (3 before R11.1)"
+        default=10,
+        ge=1,
+        le=10,
+        description="Files one message may carry (3 before R11.1; at most ChatRequest's 10)",
     )
```
and a test that keeps them together (any I1 test file):
```python
def test_the_attach_setting_never_allows_more_than_a_message_carries() -> None:
    from jarvis.config import Settings
    from jarvis.core.models import ChatRequest

    le = next(m.le for m in Settings.model_fields["attach_max_files"].metadata if hasattr(m, "le"))
    most = next(
        m.max_length
        for m in ChatRequest.model_fields["attachments"].metadata
        if hasattr(m, "max_length")
    )
    assert le == most == 10
```

### 3.4 The guide and the docs (`docs/architecture/*`, README, go-live)

- Card C61: Part B as built (this note's section 1, with the v11.1.1 fixes of section 9).
- Card C07 "Data it keeps": `attachments/{id}/pictures/{01..04}` (a cleaned picture's bytes, at most
  900 KB each, deleted with the attachment) and the header's new key `waiting_owner` (the owner while
  the file waits to be sent, "" once sent; used only to find one owner's waiting files). No new
  collection: `COLLECTIONS["files"]` stays empty.
- Voice cards (C05 / C21): three alternatives; per-turn hints from file names (never with Documents on
  "Never") and the owner's own turns, said on the "Words to recognise" privacy card; optional header
  `X-Jarvis-Session` on `POST /v1/voice/transcribe`; `alternatives` in its answer.
- The estimate's `unavailable` field and the console's "Couldn't estimate the cost; send anyway?"; the
  understand step's "Couldn't check the words; sent as heard."; `GET /v1/input` `limits.large`.
- `evals/r11_1/run.py` into `evals/run_all_mock.py` (the plan already lists this).

### 3.5 At the merge

- `tests/test_r11_1_b_guard.py::test_every_gateway_tool_verb_is_an_action_word` builds the app and
  checks that every word of every registered tool's name is an action word (`words.ACTION_VERBS`) or a
  known noun (the test's `TOOL_NOUNS`). The R11.1 tools of Parts A, C and D (as on their branches now)
  are already classified; any other new tool word fails it by name: add a verb to `ACTION_VERBS`, a noun
  to `TOOL_NOUNS`.
- `tests/test_r11_1_seams.py::test_the_eval_runner_passes_with_every_part_still_a_stub`: see section 6.

No new setting, alert kind, permission row, keyring purpose, secret or `console.html` line. No persona
sentence is needed for B (the turn note already tells the model what each file is).

## 4. For Part D / I1: the `turn_pictures` contract (changed in v11.1.1, compatible)

```python
from jarvis.documents.pictures import TurnPictures, turn_pictures
got = await turn_pictures(docs, user_id, session_id)                     # TurnPictures
got = await turn_pictures(docs, user_id, session_id, spec=spec)          # empty unless spec.sees_pictures
got = await turn_pictures(docs, user_id, session_id, sessions=store)     # optional: the conversations
if got.unreadable: ...  # the pictures could not be read: say so ("I couldn't look at the picture")
for block in got: ...   # jarvis.llm.base.ImageBlock, newest first
```

- The positional signature Part D calls today (`turn_pictures(ctx.state("documents"), uid,
  session_id)`) is unchanged, and the result is still a `list[ImageBlock]` (`TurnPictures` is a list
  subclass), so D's code works as it is. New: the keyword `sessions` (a `SessionStore`; default: the
  document service's own, which I1 passes in 3.2) and the attribute `unreadable: bool`.
- "Latest" is the STORED conversation's latest owner turn, read from the conversation store on every
  call; that turn names its files and each is read again through the document store (owner,
  conversation and turn checked). The in-process record of v11.1.0 is gone: another instance's newer
  turn and a restart are both seen (a turn sent before a restart now does give its pictures while it
  is still the latest). An earlier turn's pictures are never returned.
- Empty and `unreadable=False`: `docs` is None; anyone but the owner; a missing conversation; the latest
  owner turn came without a picture; with `spec`, a brain that may not see pictures.
- Empty or short and `unreadable=True`: the conversation or a picture could not be read (storage
  fault), a stored picture is unusable, fewer pictures loaded than the turn says it came with, or no
  conversation store is known (until 3.2 lands, unless `sessions=` is passed: D may pass
  `sessions=ctx.state("store")` read late, as it reads `documents`).
- It never raises. A caller that makes its own vision call must use a brain whose
  `BrainSpec.sees_pictures` is true (pass `spec`, or use `without_pictures`): a picture must never reach
  a blind or a training brain. A round that carries a picture is already tainted (the turn note holds a
  fenced line), so any write after it is an approval card; the picture's own words are data, never
  instructions.

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
   The line says "for one reply" (a reply that uses tools reads the files again). An estimate that cannot
   be worked out is said, and waits for the owner's click (section 9, M2).
9. **The limits reach the document service through its routes**, not at build time (the contract forbids
   reading app state while `build` runs): see 3.2.
10. **`.xlsm`** is read as `.xlsx` (macros are never run). v11.1.1: hidden and very hidden sheets are NOT
    read (v11.1.0 read them); the text says how many were left out.
11. **A question** shows as the heard words marked "Spoken · Not sent" and JARVIS's question marked
    "Asked first"; nothing reaches the Brain.
12. **Where a rule's context is weak, the word is left as heard** (D8 allows "or ask"): asking "Did you
    mean ..." for "put the pasta in the colander" would be worse than taking it as said. A protected word
    still makes the rules ask (item 4).
13. **The fast tier may change a word only into a respelling of it** (code review M1), so some real fixes
    the model would make ("clndr" to "calendar" with no alternative saying it) are now a question rather
    than an answer. That is the price of "a hint never decides what is done".

### 5a. The fixed rules, audited (code review H1)

Every rule in `understand/rules.py::RULES` was checked for one danger: turning one real word into
another real word that changes the meaning, an amount, a recipient or the action. Where it could, the
rule now fires only on a cue that makes the meant word certain (`understand/context.py`), and is left as
heard otherwise. Each tightened rule has its tests in `test_r11_1_b_rules.py`.

| Rule (heard → means) | Danger found | Now | Proof (fires / left alone) |
|---|---|---|---|
| `remainder` → reminder | "pay the remainder" became "pay the reminder" (an amount) | only on "set / add / create / new / another (a) remainder" always; "for / at / on / by a time", "remainder to call …" or "remind" only with no money talk in the sentence | `test_remainder_becomes_reminder_only_with_a_real_reminder_cue` (9) / `test_remainder_in_money_talk_is_left_as_heard` (11) and 7 fixture cases |
| `remainders` → reminders | "transfer all remainders to savings" (amounts) | the owner's own list ("show my remainders", "any remainders today"), never with money talk | "show my remainders", "any remainders today" / "transfer all remainders to savings", "show the remainders of the loan" |
| `c s b`, `csb` → CSV | a bank's initials ("pay the c s b bank"; with a CSV waiting, "pay the csb") | a file word after it, or a CSV waiting and no money talk; `c s v`, `cs v`, `see s v`, `sea s v` unchanged (no real word) | "open the c s b file", "summarise the csb" / "pay the csb", "transfer it to the csb", fixture `asks` "pay the c s b bank" |
| `power point` → PowerPoint | a wall socket: "switch off the power point" (home control) | never with a home word in the sentence (switch, plug, socket, light, fan, off, …) | "what is in the power point" / "switch off the power point", "turn on the power point in the hall" |
| `xl / axel / accel sheet(s)` → Excel sheet(s) | a bed sheet's size ("buy an xl sheet") | never with a shopping word (buy, order, size, bed, king, …); `xl`, `xxl`, `xs` are known short words | "open the XL sheet" / "buy an xl sheet for the bed", "order a king size xl sheet" |
| `fail` → file (after a file type) | the verb ("why did the csv fail") | never after an auxiliary / "why" / "if" in the sentence, nor before "to" | "read the csb fail" / "why did the csv fail", "will the pdf fail to upload" |
| `colander` → calendar | the kitchen ("put the pasta in the colander") | after "my" / "google", or "the / to / in / on" when the sentence is about the calendar (an event word or a time); never with a kitchen word | "check my google colander", "add it to the colander for 5 pm" / "put the pasta in the colander", "wash my colander", "rinse the colander" |
| `D` → the | a letter that labels a thing ("D drive", "D block", "vitamin D", "D column") | never before a label noun, never after "the / a / my …" | the owner's own cases / "save it in D drive", "book a room in the D block", "open D drive", "add D column to the sheet", "take vitamin D tablets" |
| `ad` → add | the noun in a list ("the poster and ad the client sent") | only where a request starts: sentence start, "please / jarvis / sir / also", "(and) then", "can / could / will / would you" | "ad this to my calander", "please ad it to the list" / "show me the poster and ad the client sent", "the banner and ad the client liked" |
| JARVIS variants (`jarviz`, `javis`, `charvis`, …) | a person the request is for ("send it to javis") | only when spoken to: sentence start, after "hey / hi / ok / thanks / please …", "thank you" | "hey jarviz …", "thank you javis" / "send it to javis", "forward it to jarvice" |
| `male(s)` → mail(s) | a word about someone ("send a male nurse", "the male ward") | only as the thing sent or read: the end of the sentence, punctuation, or a small word after it | "send a male to the office", "check my male" / "send a male nurse to the ward", "get a male doctor", "check the male ward" |
| `what's app`, `what sap` → WhatsApp | a question ("what's app is this") | only as the app: after "on / via / my / a / send …" or before "message / chat / group / call …"; `whats app`, `watsapp`, `whatsap` unchanged (no real word) | "send it on what's app", "draft a what sap message" / "what's app is this", "what sap is this" |
| `calender(s)`, `calander`, `calandar`, `calendor`, `kalender` → calendar(s) | "calender" is a real word (a pressing machine) but never an amount, a recipient or an action | unchanged | the fixture |
| `tu` → to, `too` → to | function words only; "tu" as a name is already HARD after "to / call" | unchanged | fixture `untouched` "Send it to Tu tomorrow", "call tu and ask …", "It is too late for that" |
| `2`, `two` → to | a number: never applied, only offered as the one question | unchanged | fixture `asks` |
| `csp`, `p d f`, `p p t`, `xl / axel / accel file(s)`, `g mail`, `e mail`, `e male`, `mourning brief` | no real word becomes another real word that changes the request | unchanged | the fixture |
| near-matches against the hints (`near.py`) | a file called "Delete list" could turn "deplete" into "delete" | never touch or make an action word | `test_a_near_match_never_touches_or_makes_an_action_word` (3) |

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
| `tests/test_r11_1_b_understand.py::test_a_careful_model_answer_is_taken` (Part B's own, v11.1.1) | "qzx" → "CSV" on a file hint alone is exactly what code review M1 forbids; the test now uses "csx" (a near spelling) for "a careful answer is taken", and the old input has its own test that it is asked about (`test_a_word_only_a_file_name_suggests_is_asked_about`) |
| `tests/test_r11_1_b_estimate.py` (v11.1.1) | the line says "for one reply" (code review L7); the route's answer gains `unavailable` |
| `tests/test_r11_1_b_pictures.py` (v11.1.1) | the "latest turn" comes from a stored conversation, so the helper stores one instead of calling the removed `note_turn`; the assertions are unchanged, and a fault now also checks `unreadable` |
| `tests/test_r11_1_b_archive.py::test_a_child_that_reads_too_long_is_killed_on_time` and the eval's `killed` (v11.1.1) | code review L8: they now prove the kill (ended by a signal, process gone) and bound the time by the contract (`timeout_s + KILL_WAIT_S`) instead of 3 s, which flaked on the shared two-CPU box |

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
- v11.1.1: the `waiting_owner` equality query on Firestore (a single-field index, which Firestore makes
  by itself); headers stored before this version lack the key and are not hints until they are swept
  (at most a day). Hidden sheets in workbooks saved by real Excel (tests use openpyxl's states and an
  edited `.xls` flag). The every-member DTD scan on large real decks and workbooks (it streams 1 MB
  pieces; tests use small files).

## 8. Owner checks (after deploy)

1. Say "add D csb file Tu D calender" with `study-plan.csv` attached: the message shows "Heard: … /
   Understood as: Add the CSV file to the calendar".
2. Say "add it 2 the calendar": JARVIS asks "Did you mean “add it to the calendar”, Sir?" and does nothing.
3. Attach an `.xlsx`, an `.xls`, a `.pptx`, a photo, a zip and a folder: each chip says what it holds; ask
   about each. A photo's chip says "picture"; Claude answers about it, another brain says it was not shown.
4. Attach a large workbook and press Send: the cost line appears with two tiers; choose one.
5. Vitals: the understood-as calls appear under the brain's rupees (about a paisa each).

## 9. Review findings and what was done (v11.1.1)

Two fresh-context reviews of `af5532b` (code and Python: BLOCK, 1 HIGH, 6 MEDIUM, 9 LOW; security:
APPROVE, 1 MEDIUM, 4 LOW, 2 INFO). Each fix was written test first; the tests are in section 2.

| Finding | Done | How |
|---|---|---|
| Code H1 "remainder" rewrites money talk | Fixed | Real reminder cue only; every other rule audited and tightened (5a) |
| Code M1 the model can swap a verb for a hint word | Fixed | Action words kept exactly; every change a near spelling or the recogniser's own word in that place; docstring states the real guarantee; probe test; eval control |
| Code M2 an estimate fault looks like "under ₹5" | Fixed | `unavailable`; the console asks before a large message goes; two eval controls |
| Code M3 `turn_pictures` trusts an in-process record | Fixed | Stored conversation; `TurnPictures.unreadable`; contract in section 4 |
| Code M4 the owner's limits reach the service only through the routes; two bounds disagree | Needs I1 | 3.2 and 3.3 (files Part B may not edit) |
| Code M5 hidden sheets read; the cap counted twice | Fixed | Visible only, said; one count |
| Code M6 a failed meter after the call; a silent console fallback | Fixed | Logged at ERROR as `Billing.record` does, answer kept; unreadable limit means no call; "Couldn't check the words; sent as heard." |
| Code L1 a duplicated JPEG check | Fixed | `sanitise_jpeg` alone decides; the walker only words the refusal (exporting a `jpeg_size` from `photos/imaging.py` is Part C's file) |
| Code L2 a bad notes page dropped silently | Fixed | "(notes could not be read)" |
| Code L3 a silent "as heard"; duplicated large-file thresholds | Fixed | The unchecked line (M6); `limits.large` from `GET /v1/input` |
| Code L4 `AttachPolicy` defaults duplicate the settings' | Already covered | `test_r11_1_b_service.py::test_the_policy_comes_from_the_settings_and_its_defaults_are_theirs` pins them |
| Code L5 `policy` and `_picture_turns` are mutable public state | Partly | `_picture_turns` is gone (M3). `policy` stays assignable until I1 applies 3.2: the routes must set it, because Part B may not edit the wiring; 3.2 then removes the assignment |
| Code L6 fewer pictures loaded, silently | Fixed | "[1 of the 2 attached pictures could not be loaded just now]"; `unreadable` for Part D |
| Code L7 the estimate understates tool loops | Fixed | "for one reply" in the line |
| Code L8 timing-based tests | Fixed | They assert the kill; the bound is the contract's |
| Code L9 no control for the guard or the estimate | Fixed | Three more controls (six in all) |
| Security M1 a DTD in a part not named .xml | Fixed | Every member scanned by content, streamed; XML cap by content; the PoC is a test |
| Security L1 the parent re-checks only magic and size | Fixed | `clean_picture` again in the parent; refused if it would change |
| Security L2 dependencies not pinned | Needs I1 | 3.1 |
| Security L3 `/hints` and `/estimate` unlimited; every owner's rows read | Fixed | Per-owner limits; `waiting_owner` equality query |
| Security L4 file names to Google with Documents "Never" | Fixed | None then (nor when unreadable); the privacy card says what goes as hints |
| Security I1, I2 (information) | Noted | I1 is closed by M1 (a file name can no longer steer an action); I2 found no defect |

Still open: only the "Needs I1" items (3.1–3.5) and what section 7 lists as not verifiable here.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.0 | 12 Nov 2026, 08:15 IST | R11.1 | First edition: Part B built (O3, O4), how to check it, Needs I1 (three libraries, one wiring line, the attachments field, the guide), what Part D may rely on from `turn_pictures`, eleven differences from the plan, nine existing tests changed, the eval-runner seam test to retire at I1, what is not verified live, owner checks | 🛠 Mark XV |
| v11.1.1 | 12 Nov 2026, 10:00 IST | R11.1 | The two reviews' findings fixed test first (section 9): the rules audited and tightened (5a), the fast tier limited to respellings with every action word kept, the estimate's "could not estimate", pictures from the stored conversation (`turn_pictures` contract, section 4), hidden sheets not read, every Office member scanned for a DTD, pictures cleaned again in the parent, two more route limits, no file names as hints with Documents off, three more eval controls; Needs I1 rewritten with exact diffs (pins, the wiring line with `sessions`, the two attachment bounds at 10, the guide, the tool-verb test at the merge) | 🛠 Mark XV |
