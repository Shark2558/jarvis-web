Version v14.0.2 · 14 Nov 2026, 17:50 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 — Part C integration notes (cost and the skill register)

Built by builder C for the Workshop (🛠 Mark XIX) on branch `r14-c`, from `r14-i0` @ `9eb9d8b`,
test first throughout (each test file was run red before its code). Plan:
`docs/plans/r14-hardening.md` v14.0.2, D8–D11 and the Part split's row C. The contract
(`jarvis.hardening.ports`, `jarvis.skills.ports`) is unchanged.

**Read "Needs I1" A first: the persona must change in the same release, or `tool_offer` stays
"all".** Today's persona tells the model that a tool it isn't offered "is not connected"; with the
offer on, that turns every tool left out of a turn into a refusal instead of a `skills_open` call.
A now gives the five passages word for word, the 24 test cases they move (20 files, 22 lines,
checked by a dry run) and a seam test that fails while the two disagree.

v14.0.2: the three fresh-context reviews (security APPROVE, code APPROVE, Python WARN) are
answered in section 8, "Review follow-ups": every MEDIUM and LOW is fixed test first, except the
persona itself (code review MEDIUM-2), which is not Part C's file and is A below.

## 1. What Part C built

| Deliverable | What it does |
|---|---|
| `core/window.py` (D9) | Every block counts toward `session_max_chars` (text, a call's name and arguments, a result); results older than the last 2 tool rounds are cut to `tool_result_chars` (default 2,000 = the setting's default) with `… [shortened]`, keeping the "untrusted tool output" header line, `is_error` and `trusted` (send-side only; the taint check gives the same answer on the cut window, tested); the gateway's own status answers (`{"status": …}`, an approval waiting among them) are never cut; old turns go in chunks down to 70 % of either cap, the start decided on each turn's stored (uncut) size, so it only ever moves forward and holds for several replies; the newest turn is always kept. |
| `llm/*` (D9, fact 13) | `LLMAuthError`, `LLMUnreachable`, `LLMTransientError`, `LLMError` carry fixed words (`llm.base`: `AUTH_REFUSED`, `UNREACHABLE`, `BUSY`, `NO_ANSWER`; `FIXED_ERROR_WORDS`) in Anthropic, Gemini and OpenAI-compatible (the laptop brain inherits them); the vendor's exception is never chained: our error is built in the `except` block and raised after it, so neither `__cause__` nor `__context__` holds it (timeouts, transport errors and a non-JSON body included); the log keeps our class, the original's class name (`cause`) and the HTTP status; the router logs `type(exc).__name__`. `AnthropicProvider(cache_history=…)` adds a second breakpoint on the last message's last non-empty block of every `complete()` **with tools** (plain messages go out as one text block so the next round's prefix is byte-for-byte the same); a call without tools and `stream()` keep the system breakpoint only. The request is built from the SDK's own TypedDicts, no `cast`. `llm/factory.py` builds Claude from the settings for both `router.build_provider` and `brains.BrainRegistry.from_settings` (the plan's "factory"; `brains.py` is under `llm/*`, BRIEF-COMMON §3). No slot, no hint in the shared interface. |
| `skills/catalogue.json` (D11) | The 11 skills in `skills.ids` order, each with its one-line "about" and **groups** (40 in all): tool patterns (an exact name wins over a family) and words, English and common Hinglish. Plus `core`, `telegram_open` (the read tools Telegram answers), `no_ai` (what No-AI mode reaches, pass 1, the helpers' routers and Part D's D12 list) and `planned` (A's and D's tools, named before they exist). Groups, not whole skills, are what a word offers: one skill (Task & Productivity) holds 31 tools. |
| `skills/registry.py` (D11) | `load_catalogue` / `parse_catalogue` (refuses a wrong version, a missing, unknown or reordered skill, a group id used twice, upper-case words, a group with no tools or an empty tool pattern); `SkillRegister` files a tool by name (remembering at most 1,024 names' filing); its card: skill, group, risk R1/R2/R3, permission rows (`groups_for`), Telegram class (private / personal / home / both from `telegram/rules.py`, open when listed, or a write), No-AI. `problems(registry)` is the check: no skill, filed twice, a pattern matching nothing, a read with no Telegram class, a read both open and refused, a list naming an unregistered tool that isn't planned. |
| `skills/offer.py` (D9) | `SkillOffer`, the `ToolOffer`: the groups his words name ∪ the groups of tools used in the last 3 turns ∪ the previous turn's set while under `tool_offer_sticky_s` (dropped when the union passes 40 tools) ∪ the core ∪ every tool a replayed `tool_use` names; fixed per turn (kept under (owner, trace id), keyed by trace id, owner-message count and text, so two surfaces of one owner keep their own sets; the newest 32 turn sets only), `skills_open(skill)` adds that whole skill from the next round (a `skill` value that isn't a string adds nothing); registry order; a tool the register can't file is always offered. Words match at a word's start; three letters or fewer match the whole word or with an `s` ("emi", "emis", never "email"). `offer_all` kept. |
| `skills/open_tool.py` | `skills_open(skill)`: R1, no row (the risk default), Telegram open, `trusted_output` (its answer is the register's own fixed data), an argument check refusing an unknown skill; answers the label, the about and the skill's live tool names that the register files and that are plain tool names (`[a-z][a-z0-9_]{0,63}`: its answer is trusted); description 1,288 characters (each skill's id and about). |
| `billing/ledger.py` (D8) | `TokenLedgerStore` (the `TokenLedger`): per call, per owner per day in his zone, `{prefix}token_ledger/{uid}_{yyyymmdd}`: calls, cold calls (no cache read), input / cache read / cache write / output tokens from the vendor's `Usage`, characters by part (persona, tools, history, tool results, memory: the trailer after the recall heading, trailer), tools offered, skills opened, and the call's cost by part (output priced as "replies", the rest shared by characters, the rounding into the largest part so they add up). One transaction per call; the first call of a day keeps today and the 89 days before it. Characters counted with `core.window`'s own functions. Counts only (a test plants a word in the prompt, messages, trailer and reply and finds it nowhere in the document). Only the brain's record slot writes it, so it counts **chat replies**, not recall, the brief or the helpers. `ai_parts_note`: the Vitals line in ₹, "Chat replies this month ≈ ₹…", always within the Vitals note's 300 characters. `NoLedger` kept. |
| `skills/part.py` | `build(ctx)`: the register (an unreadable catalogue raises: the wiring leaves the part out, so every tool is offered), `skills_open`, services `offer` (only while `tool_offer = "by_skill"`), `ledger` (only while `token_ledger_enabled` and a document store exists), and for its routes `register` and `ledger_view`; the quiet Vitals item `ai_parts` (`kind="billing"`, ₹ at the app's daily rate, the default rate if it can't be read; "unknown" with fixed words when the ledger is off or unreadable); the privacy row `token_ledger` (section "Activity and messages", count = days kept, "90 days", no export, no delete). Ready word: `ready`, or `ready: <why>` for the kill switch, the ledger switched off, or no document store. |
| `api/skills.py` | `GET /v1/skills` (the 11 skills with tools and No-AI counts, the core, `tool_offer`, the registry's size) and `GET /v1/costs/ledger` (this month: days, calls, cold calls, tokens, characters, tools per call, skills opened, cache share, ₹ by part, ₹ in all, the rate). Owner-only, `no-store`, counts and names only; an unreadable ledger is 503 `ledger_unreadable` with no detail; before the part is built, `{part, ready}` as I0's stub. |
| `scripts/skill_coverage.py` | Prints the two tables (skills; every tool with skill, group, risk, rows, Telegram, No-AI) from the fullest fake registry; exit 1 with the problems listed. For the guide's C68 and the build book. |
| `evals/r14/offer.py` (BUILT) | See §3. |
| Tests | `tests/test_r14_c_{window,llm_errors,cache,register,offer,open_tool,ledger,part}.py`, `tests/test_r14_skill_coverage.py`, `tests/r14_fakes_c.py`: 128 tests (108 at v14.0.1; 20 from the review follow-ups). |

## 2. Decisions taken in Part C (safe defaults)

1. **Groups inside skills.** A word offers a group (2–10 tools), not a whole skill; `skills_open`
   opens the whole skill. Without groups one Task word would offer 31 tools and the ≤ 30 average
   could not hold. A check pins every group at ≤ 10 tools on the fullest registry.
2. **Open reads are data.** "A read tool has no Telegram class" needs a declared open list, so the
   catalogue's `telegram_open` mirrors the guard's `TELEGRAM_SAFE` (a test keeps them equal, R14's
   own three apart).
3. **`skills_open` is `trusted_output`.** Its answer is fixed register text, never other people's
   words; otherwise opening a skill would taint the round and turn the next write into a card.
   For the security review.
4. **The history breakpoint rides every `complete()` with tools, never `stream()` or a call
   without tools.** A stream is one call a reply, and a one-shot caller (recall, the brief, the
   helpers) never calls again with the same prefix: a cache write neither could read (code
   review MEDIUM-1).
5. **Sticky cap 40 tools**, so a long busy session can't grow the offer without bound.
6. **The dev twins stay unfiled.** Without a Google link the app registers `get_calendar`,
   `send_message`, `create_reminder`; they are not in the fullest registry (the check would call
   their patterns stale), so the offer always includes them (fail safe). Dev only.
7. **The eval's helpers live in `tests/r14_fakes_c.py`** (my file) rather than a new file under
   `evals/r14/`. `Controls` is a `NamedTuple`: `run.py` loads a part outside `sys.modules`, which a
   dataclass with postponed annotations can't survive.

## 3. Measured (fakes, no model, ₹0)

| Check | Result |
|---|---|
| `evals/r14/run.py --mock --part offer` | **9/9 pass**; control **fails** the suite: words emptied → `offer:recall` fails; the pre-R14 window → `offer:window_counts_blocks` fails; hint off → `offer:history_hint` fails (each its own case; re-run at v14.0.2) |
| Recall, 122 labelled messages (the plan's 120+) | **100 %**. Honestly: **95.9 %** (5 misses) as first written; 7 words were then added from those misses ("cancel", "sync", "block", "delete", "things", "where has my", "where was my"). The same builder wrote the words and the messages. |
| Recall, 24 held-out messages written after, never tuned on | **83.3 %**, then **87.5 %** after one rule fix (short words with a plural `s`); 3 misses left on purpose ("put a call with…", "go to bed", "anyone at the door"). Expect about 1 message in 8 to need a `skills_open` round live; the ledger's `skills_opened` will say. |
| Tools offered (fresh offer, no history) | **9.5** on average (held-out 8.6), at most 19–20, of **136**; D10 assumed about 25, so the per-reply saving is likely larger than its estimate until sticky sets and history add their share (the ledger measures it) |
| `whole r14 runner --mock` | 22/22 pass, combined control fails the suite |
| D11 check on the fullest fake registry | 136 tools filed once each, every pattern used, every read classed; 0 problems (`scripts/skill_coverage.py`: "problems: none") |
| Own tests, Python 3.12 | **128 passed** (Part C's own); **384 passed** with the existing tests of every file touched (`test_anthropic_provider`, `test_llm_unreachable`, `test_trust_flag`, `test_r51_out_of_credit`, `test_real_evals`, `test_r11_1_seams`, `test_gemini_provider`, `test_openai_compat_provider`, `test_local_provider`, `test_fallback_tools`, `test_window`, `test_r11_1_a_finish`, `test_brain`) |
| Own tests, Python 3.11 | **321 passed** (the same set less `test_real_evals` and `test_r11_1_seams`) |
| Coverage | `skills/offer` 99 %, `registry` 98 %, `part` 98 %, `open_tool` 100 %, `ports` 88 %, `billing/ledger` 97 %, `core/window` 98 %, `api/skills` 93 % (Part C's tests); `llm/anthropic_provider` 98 %, `gemini_provider` 98 %, `openai_compat_provider` 97 % (with their own test files) |
| `ruff check` / `ruff format --check` | clean (1,672 files) |
| `mypy src` | **1 error**, the pre-existing `memory/redis_store.py:67` (the 8 baseline errors in `core/window.py` and `llm/anthropic_provider.py` stay fixed); no `cast` and no `type: ignore` in Part C's src |
| mypy strict on Part C's tests, eval and script | `MYPYPATH=src:tests mypy tests/test_r14_c_*.py tests/test_r14_skill_coverage.py tests/r14_fakes_c.py evals/r14/offer.py scripts/skill_coverage.py`: nothing in those files (10 at v14.0.1); the 12 it still prints are in files they import (`tests/test_telegram_tool_guard.py` 6, `billing_fakes` 2, `media_fakes`, `photos_fakes`, `research_fakes` 1 each, and src's `redis_store.py`), none Part C's. Without `MYPYPATH`, mypy resolves `jarvis` through the editable install of another checkout |
| `arch_coverage.py`, `check_doc_versions.py` | OK; 28 documents (it reads top-level folders only; this file carries its version line and change log anyway) |
| Seam set | 265 passed, 13 failed, the same 13 as v14.0.1: the 3 I0 pins of "Needs I1" E, the 1 Telegram pin of D, and 9 `test_claude_guard` cases (G: the worktree's location) |
| Persona p14.0 dry run (A) | the five passages of A and `PERSONA_VERSION = "p14.0"` patched in for one run of the 29 test files that read the persona, nothing in the tree changed: **24 test cases fail, all version pins** (listed in A), 610 pass; no wording pin fails |
| Sizes | every module ≤ 388 lines (`llm/anthropic_provider.py`); every function written or touched ≤ 50 lines: Anthropic `complete` 62 → 34, OpenAI-compatible `complete` 61 → 41. Pre-existing long functions in `llm/` untouched (`router.complete` 68, `router.stream` 70, `local_provider.stream` 52, `brains.from_settings` 73) |

## 4. Needs I1 (files Part C may not edit; exact changes)

**A. Persona p14.0 (`core/prompts.py`; RELEASE BLOCKER for `tool_offer = "by_skill"`, code
review MEDIUM-2).** `tool_offer` defaults to "by_skill" (`config.py:582`), and five passages, the
only five places the persona says "offered", tell the model a tool it isn't offered is not
connected. Merged as they are, every tool the offer leaves out (about 1 message in 8 on the
held-out set) is answered "not connected yet" instead of with a `skills_open` call. Land p14.0 in
the same merge as Part C, or flip the default to "all" until it lands (`JARVIS_TOOL_OFFER=all`
works too: the ledger still counts, the window and the cache point still save).

A1. The five passages, word for word (each `-` block is the current text exactly, each `+` block
fits the 100-column limit; the TOOLS_RULE bullet leads with D14's words):

```diff
@@ _RULES (core/prompts.py:136–137)
-- Use only the tools offered in this request; if none fits, say the capability is not yet
-  connected and offer what you can do with reasoning alone. Never pretend an action happened.
+- Use only the tools offered in this request. If none fits and skills_open is offered, call
+  skills_open with the skill that holds it first; only if that skill has no such tool either,
+  say the capability is not yet connected and offer what you can do with reasoning alone.
+  Never pretend an action happened.
@@ WEB_RULES (core/prompts.py:183–184)
-  results or one the owner typed. If no web_search tool is offered, web search is not available
-  here (not set up, or this brain is chat-only): say so plainly rather than guess.
+  results or one the owner typed. If no web_search tool is offered, call skills_open("research")
+  first when it is offered; if web_search still isn't there, web search is not available here
+  (not set up, or this brain is chat-only): say so plainly rather than guess.
@@ DRIVE_RULE (core/prompts.py:260)
-- If no drive_* tool is offered, Google Drive isn't switched on here: say so plainly.
+- If no drive_* tool is offered, call skills_open("research") first when it is offered; if
+  Drive still isn't there, Google Drive isn't switched on here: say so plainly.
@@ TOOLS_RULE (core/prompts.py:269–271, its first bullet; the second, on tool-call markup, stays)
-- Use only the tools offered in this conversation. If a request needs one that is not offered
-  (the calendar, mail, Drive, Maps, to-dos, payments), say plainly that it is not connected
-  here yet and offer what you can do without it.
+- This turn you may hold only some of your tools. If he asks for something none of them does,
+  call skills_open first; never say you can't before that. Only when skills_open is not
+  offered, or the skill it opened has no such tool (the calendar, mail, Drive, Maps, to-dos,
+  payments), say plainly that it is not connected here yet and offer what you can do without it.
@@ MEDIA_RULES (core/prompts.py:283–284)
-  Maps or to tell you the address. If no maps_* or youtube_* tool is offered, it is not set up
-  here: say so plainly.
+  Maps or to tell you the address. If no maps_* or youtube_* tool is offered, call skills_open
+  first (research for Maps, creative for YouTube); if it still isn't there, it is not set up
+  here: say so plainly.
```

Then `PERSONA_VERSION = "p14.0"` and a `# p14.0:` note in the header comment, per D14.

A2. The pins. **20 test files, 22 lines, assert `PERSONA_VERSION == "p7.0"`** (D14 says 19; I0
added `tests/test_r14_seams.py:644` since): `test_media_persona.py:23`,
`test_r11_1_i1_persona.py:16`, `test_r14_seams.py:644`, `test_r1_seams.py:291`,
`test_r3_persona.py:16` and `:56`, `test_r11_persona.py:17`, `test_r1_persona.py:15`,
`test_r2_persona.py:21`, `test_r4_persona.py:18`, `test_r51_persona.py:14`,
`test_r5_persona.py:16`, `test_r7_i1_persona.py:22`, `test_r6_persona.py:17`,
`test_r7_seams.py:875`, `test_tools_not_offered_persona.py:17`, `test_voice_persona.py:80` and
`:235`, `test_web_persona.py:10`, `test_whatsapp_persona.py:18`, `test_tasks_tools.py:420`,
`test_undo_persona.py:48`. A dry run (A1 and the version patched in for one run of the 29 test
files that read the persona; nothing in the tree changed) fails exactly these **24 test cases**
(`test_tasks_tools.py`'s pin runs once per wit level, 3 cases), and nothing else:
`tests/test_media_persona.py::test_persona_version_was_bumped_at_the_slice_12_integration`,
`tests/test_r11_1_i1_persona.py::test_the_release_has_one_persona_version`,
`tests/test_r11_persona.py::test_persona_is_p11_0`,
`tests/test_r14_seams.py::test_the_persona_is_left_alone_until_i1`,
`tests/test_r1_persona.py::test_persona_is_p4_6`,
`tests/test_r1_seams.py::test_persona_version_is_p4_6`,
`tests/test_r2_persona.py::test_persona_is_p11_0`,
`tests/test_r3_persona.py::test_home_rules_match_the_permission_rows_and_name_no_pronoun`,
`tests/test_r3_persona.py::test_persona_is_p11_0`,
`tests/test_r4_persona.py::test_persona_is_p11_0_after_r4`,
`tests/test_r51_persona.py::test_persona_is_p11_0`,
`tests/test_r5_persona.py::test_persona_is_p11_0_after_r5`,
`tests/test_r6_persona.py::test_persona_is_p11_0`,
`tests/test_r7_i1_persona.py::test_the_release_has_one_persona_version_with_its_note`,
`tests/test_r7_seams.py::test_the_persona_version_is_r7s_after_i1`,
`tests/test_tasks_tools.py::test_the_persona_has_its_own_todo_paragraph_and_the_version_was_bumped[extra]`,
`tests/test_tasks_tools.py::test_the_persona_has_its_own_todo_paragraph_and_the_version_was_bumped[film]`,
`tests/test_tasks_tools.py::test_the_persona_has_its_own_todo_paragraph_and_the_version_was_bumped[measured]`,
`tests/test_tools_not_offered_persona.py::test_persona_version_is_bumped_for_the_rule`,
`tests/test_undo_persona.py::test_persona_version_was_bumped_once_per_slice`,
`tests/test_voice_persona.py::test_new_sessions_record_the_persona_version`,
`tests/test_voice_persona.py::test_version_and_levels`,
`tests/test_web_persona.py::test_persona_version_was_bumped_once_for_slice_10`,
`tests/test_whatsapp_persona.py::test_persona_version_was_bumped_for_slice_12`.

No wording pin fails: `test_drive_persona.py` ("If no drive_* tool is offered", "isn't switched
on"), `test_media_persona.py` and `test_web_persona.py` ("not set up") and the paragraph-order
tests still pass. `tests/test_r7_i1_persona.py:25` (`"# p7.0: R7" in text`) reads the header
comment, which keeps that line. The persona and voice evals rerun per D14 (real runs, keys).

A3. **`tests/test_tools_not_offered_persona.py` must be rewritten, not only re-versioned.** Its
rule test still passes on p14.0 only because "not connected" survives; its point (a tool that
is not offered is not connected) is what p14.0 changes. Proposed (checked: fails on p7.0,
passes on A1):

```python
def test_persona_version_is_bumped_for_the_rule() -> None:
    assert PERSONA_VERSION == "p14.0"


@pytest.mark.parametrize("wit", [w.id for w in WIT_LEVELS])
def test_every_wit_level_opens_a_skill_before_it_says_not_connected(wit: str) -> None:
    prompt = build_system_prompt(honorific="Sir", wit=wit)
    assert TOOLS_RULE in prompt
    rule = " ".join(TOOLS_RULE.lower().split())
    assert "never write tool-call markup" in rule
    assert rule.index("call skills_open first") < rule.index("not connected")
```

A4. **A seam test so the two can't disagree again** (for `tests/test_r14_seams.py`; checked in
three states: fails today, passes on A1 with "p14.0", passes with the default flipped to "all"):

```python
def _offer_bullets(prompt: str) -> list[str]:
    """Each persona bullet ("- ..." to the next bullet or a blank line) about an offered tool."""
    bullets = re.findall(r"^- .*?(?=^- |^\s*$|\Z)", prompt, flags=re.M | re.S)
    return [" ".join(b.split()) for b in bullets if "offered" in b]


def test_the_persona_opens_a_skill_while_the_offer_is_on_by_default() -> None:
    """R14 C code review MEDIUM-2: with `tool_offer` "by_skill" by default, every persona bullet
    about a tool that isn't offered sends the model to skills_open first."""
    from jarvis.core.prompts import PERSONA_VERSION, WIT_IDS, build_system_prompt

    if Settings.model_fields["tool_offer"].default != "by_skill":
        return  # the kill switch is the default: nothing to keep in step
    for wit in WIT_IDS:
        bullets = _offer_bullets(build_system_prompt(honorific="Sir", wit=wit))
        assert len(bullets) >= 5, bullets  # the rules, web, Drive, the tools rule, Maps/YouTube
        stale = [b[:70] for b in bullets if "skills_open" not in b]
        assert not stale, f"{wit}: {stale}"
    assert PERSONA_VERSION != "p7.0"
```

It replaces `test_the_persona_is_left_alone_until_i1` (`:644`, one of the 24); the file already
imports `Settings`, and needs `import re`.

**B. `core/brain.py` `_window_for` (`:205–207`), +3 lines (710 → 713, guard 741):**

```diff
         return build_window(
-            turns, max_turns=self.s.session_max_turns, max_chars=self.s.session_max_chars
+            turns,
+            max_turns=self.s.session_max_turns,
+            max_chars=self.s.session_max_chars,
+            tool_result_chars=self.s.history_tool_result_chars,
         )
```
Without it the window uses 2,000 (the setting's default) whatever the setting says.

**C. `pyproject.toml` package data (the deploy installs non-editable):**

```diff
 "jarvis.helpers.kitchen" = ["data/*.json"]
+# R14 Part C (D11): the skill register's catalogue (data)
+"jarvis.skills" = ["catalogue.json"]
```
Without it the image has no catalogue: the part is left out ("setup failed") and every tool is
offered (safe, but no saving). Suggested pin (a seam test): `assert '"jarvis.skills" =
["catalogue.json"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")`.

**D. `tests/test_telegram_tool_guard.py` `TELEGRAM_SAFE`** (after `"people_open_profiles",`):

```diff
+        # R14 Part C: the register's own words (labels, abouts, tool names); no side effect
+        "skills_open",
```
(Part A's `vitals_backups` and Part D's `maint_service_request` join it at the merge; the
catalogue's `telegram_open` already names all three, and `tests/test_r14_skill_coverage.py`
keeps the two lists equal.)

**E. `tests/test_r14_seams.py`, I0's "not built yet" pins Part C moves:**

```diff
@@ test_the_app_starts_with_four_parts_and_their_status_routes
-        assert all(p.ready == "not built yet" for p in parts.values())
+        assert parts["skills"].ready == "ready"  # Part C built (A, B, D as they land)
         for name, route in STATUS_ROUTE.items():
             r = await client.get(route)
             assert r.status_code == 200, name
-            assert r.json() == {"part": name, "ready": "not built yet"}
+            assert r.json()["part"] == name and r.json()["ready"] == parts[name].ready
             assert r.headers["cache-control"] == "no-store"
         r = await client.get(R14_STATUS_ROUTE)
-        assert r.json() == {"parts": {n: "not built yet" for n in PARTS}}
+        assert r.json() == {"parts": {n: parts[n].ready for n in PARTS}}
@@ test_the_parts_privacy_rows_reach_the_dashboard
-        assert wiring.r14_privacy_sources(app) == ()  # no part is built yet
+        assert "token_ledger" in [s.id for s in wiring.r14_privacy_sources(app)]
@@ test_the_r14_runner_passes_and_its_contract_control_fails_it
-    for part in ("backup", "selfwatch", "offer", "noai", "needles"):
+    for part in ("backup", "selfwatch", "noai", "needles"):  # those still unbuilt
         assert f"{part}:not_built_yet" in ids, part
     control = report["negative_control"]
     assert control["suite_failed"] is True and control["failed_cases"]["contract"]
+    assert "offer:recall" in ids and control["failed_cases"]["offer"]
```

**F. The guide's card C68** (Skill register and the turn's tools), facts to fill it:
where in the code `skills/` (`catalogue.json`, `registry.py`, `offer.py`, `open_tool.py`,
`part.py`), `billing/ledger.py`, `core/window.py`, `llm/factory.py`, `api/skills.py`,
`scripts/skill_coverage.py`; data `token_ledger` (counts, 90 days); outside services none new;
cost ₹0 to run (saves; one ledger transaction a model call, about 40 reads and 40 writes a day);
when it fails: catalogue unreadable → every tool offered; offer raises → every tool; a missed
tool → `skills_open`; ledger write fails → logged, reply unaffected; ledger unreadable → Vitals
"unknown", the route 503. The skills table comes from `scripts/skill_coverage.py`. §9's cost
rewrite (D8) waits for a week of ledger data, and must say what the ledger covers: **the chat
replies' model calls only** (the brain's record slot); recall, the brief's summary, pass-1
understanding and the picture, kitchen, people and build-book helpers call the router directly
and are not in it, so the billed total is higher (code review LOW-1; the Vitals item says "chat
replies").

**G. `tests/test_claude_guard.py`, 9 `rm -rf` cases fail in every builder's worktree** (not
Part C's change: no file of the hook or its test was touched). The hook's `SAFE_ROOTS` holds the
worktrees' parent folder, and the test runs the hook with the worktree as its directory, so
`rm -rf src` resolves inside an allowed root. CI's checkout is elsewhere, so it passes there.

**H. Security review of the `jarvis.llm` change: done.** The fresh-context `security-reviewer`
pass over the whole of Part C (the `jarvis.llm` change, `skills_open` as `trusted_output`, the
ledger's counts-only rule) answered APPROVE with four LOWs, all fixed in v14.0.2 (section 8).

## 5. Contract notes

No port or contract change. Part C's services beyond `SERVICE_OWNER`'s `offer` and `ledger` are
`register` and `ledger_view`, read only by `api/skills.py` (`check_part` allows extra keys). The
offer only narrows the list: a tool the model calls without being offered still meets the
gateway (tested through the app: an R3 call the offer left out is audited and never run, and the
next round offers it because the replayed call names it).

## 6. What can't be verified here

Anthropic's cache with two breakpoints on live calls (reads within a reply, writes, the 512-token
minimum, a changed tool list invalidating everything); whether each of the five providers
accepts a replayed `tool_use` for a tool missing from the next offer (the offer always includes
them; the real-run evals need keys); real token counts and ₹ by part (the ledger measures them
after deploy); recall on his own messages (held-out 87.5 % on 24; `skills_opened` in the ledger
will show it); the catalogue inside the built image (needs C); the persona's behaviour with a
narrowed tool list (needs A and the persona evals); whether 32 remembered turn sets are ample
live (one owner, a few surfaces: far more than needed, but unmeasured).

## 7. Commits on `r14-c`

`9aa7176` window · `335861f` vendor text · `5fb6ca2` cache point and factory · `4050086` register
and check · `930cc31` offer · `d5d21b7` ledger and `skills_open` · `7e99c95` part and routes ·
`e103330` eval (BUILT) · `003d484` gateway test, description · `1e7b947` unhappy paths ·
`f4ca9e2`, `ddb445f` this file (v14.0.1). Review follow-ups (v14.0.2): `7f18da0` no vendor
exception on `__context__`, the `cause` class · `eb1b9f5` the history breakpoint only with tools ·
`19ee2c0` the Anthropic request from the SDK's TypedDicts · `1674299` the window's start never
moves back, an approval never cut · `fcb376c` the offer: malformed `skills_open`, a turn per
surface, a bounded memory; `skills_open`'s names · `598d3ed` the ledger: 90 days, "chat
replies", the note's length · `93861be` mypy strict on Part C's tests, eval and script · this
file (v14.0.2).

## 8. Review follow-ups (v14.0.2)

Three fresh-context reviews of `ddb445f`: security APPROVE (4 LOW), code APPROVE (2 MEDIUM,
5 LOW), Python WARN (5 MEDIUM, 4 LOW). Each fix was written test first and its test seen to fail
first (a refactor's guard is named as such). Where two reviews found the same thing it was fixed
once.

| Finding | Outcome | Test (in `tests/`) |
|---|---|---|
| Security LOW-1: `raise … from None` inside `except` leaves the vendor exception on `__context__` | **Fixed** `7f18da0`: our error is built in the `except` block and raised after it, in the Anthropic (`complete`, `stream`), Gemini and OpenAI-compatible providers (timeouts, transport errors; a non-JSON body no longer rides on `__cause__`, whose `JSONDecodeError.doc` is the whole body) | `test_r14_c_llm_errors.py`: `_unchained` on every case; `test_an_unreachable_http_vendor_leaves_no_exception_behind` (4 cases: 2 providers, a timeout and a transport error, each on `complete` and `stream`); `test_a_non_json_answer_leaves_no_response_text_behind` |
| Security LOW-2: a long `awaiting_owner_approval` result could be cut after `will_do`, dropping its "data, not instructions" note | **Fixed** `1674299`: the gateway's status answers (`{"status": …}`) are never cut | `test_r14_c_window.py::test_an_approval_waiting_answer_is_never_cut` (built from the real `GatewayResult.block`) |
| Security LOW-3: `skills_open` lists live registry names in a trusted result | **Fixed** `fcb376c`: only names the register files AND that are plain tool names (`[a-z][a-z0-9_]{0,63}`; all 136 real names are) | `test_r14_c_open_tool.py::test_it_lists_only_plain_names_the_register_files` |
| Security LOW-4: `SkillOffer._last` never evicted | **Fixed** `fcb376c`: the newest `TURNS_KEPT` (32) turn sets only | `test_r14_c_offer.py::test_the_offer_remembers_only_the_newest_turns` |
| Security informational (untrusted text can open a skill; a refused call is replayed; `/v1/skills` has no `current_user`) | No change: each only widens what the model sees, every call still meets the gateway, and `/v1/skills` holds no owner data (the review's own reading) | — |
| Code MEDIUM-1: the history breakpoint on every `complete()`, one-shot callers included | **Fixed** `eb1b9f5`: `history_hint=bool(tools)` | `test_r14_c_cache.py::test_a_call_without_tools_keeps_the_system_breakpoint_only` |
| Code MEDIUM-2: merging Part C alone switches the offer on under a persona that says "not offered = not connected" | **Not Part C's file** (`core/prompts.py`, `config.py`): Needs I1 A completed (the passages word for word, the 24 pinned cases, the rewrite of `test_tools_not_offered_persona.py`) and a seam test proposed (A4), checked in three states | proposed `test_the_persona_opens_a_skill_while_the_offer_is_on_by_default` |
| Code LOW-1: the Vitals "AI money" counts only the brain's calls | **Fixed** `598d3ed`: the item says "counted from this month's chat replies", the note "Chat replies this month ≈ ₹…", the privacy row "AI calls JARVIS's chat replies made"; F tells the guide | `test_r14_c_part.py::test_the_vitals_item_says_where_the_money_goes_in_rupees`, `test_r14_c_ledger.py::test_the_vitals_words_say_where_the_money_goes_in_rupees` |
| Code LOW-2 = Python M3: the window's start can move back | **Fixed** `1674299`: decided on each turn's stored size; the window sent is still the cut one (never over a cap) | `test_r14_c_window.py::test_the_start_never_moves_back_as_the_history_grows` (its history went 13, 14, 13; a sweep of 756 size and cap combinations finds no backward move) |
| Code LOW-3: retention keeps 91 days | **Fixed** `598d3ed`: today and the 89 days before it | `test_r14_c_ledger.py::test_exactly_ninety_days_are_kept` |
| Code LOW-4: Needs I1 A miscounts the pins and leaves out `tests/test_tools_not_offered_persona.py` | **Fixed** (this file): A2 lists 20 files, 22 lines, 24 cases (a dry run); A3 rewrites that file | the dry run (section 3) |
| Code LOW-5 = Python L3: two surfaces of one owner share one offer memory | **Fixed** `fcb376c`: turn sets kept under (owner, trace id) | `test_r14_c_offer.py::test_two_surfaces_of_one_owner_keep_their_own_turn_sets` |
| Code, cosmetic: parts and the total are rounded apart (a few paise) | No change: display only; the route gives both | — |
| Python M1: `opened_skills` with an unhashable model-supplied value raises on every later round | **Fixed** `fcb376c`: only a string counts | `test_r14_c_offer.py::test_a_malformed_skills_open_call_adds_nothing_and_never_breaks_the_offer` (a list, an object, a number, None) |
| Python M2: `_failed` logs only "LLMError" for our own bugs | **Fixed** `7f18da0`: `cause` = the original's class name (never its words) | `test_r14_c_llm_errors.py::test_a_failure_log_names_the_cause_class_without_its_words` (complete, stream), `test_a_vendor_failure_log_names_the_vendors_class` |
| Python M4: about 10 mypy strict errors in Part C's tests, eval, script | **Fixed** `93861be`: none left, no ignores (`Settings.model_validate`, `ToolOffer`'s own signature, typed literals) | mypy (section 3; CI type-checks `src` only) |
| Python M5: the casts in `_to_params` / `_mark_last` | **Fixed** `19ee2c0`: the SDK's TypedDicts, no `cast` | mypy strict, and the byte-exact tests unchanged (refactor guard) |
| Python L1: `_vitals` returns `Any` | **Fixed** `598d3ed`: `VitalsReader` | mypy |
| Python L2: the register's filing cache grows with made-up names; an empty tool pattern allowed | **Fixed** `fcb376c`: at most `FILED_KEPT` (1,024) names remembered; an empty pattern refused | `test_r14_c_register.py::test_the_filing_memory_is_bounded`, `test_a_broken_catalogue_is_refused` (a new case) |
| Python L4: the ledger repeats the window's character count; frozen records hold dicts | **Fixed** `598d3ed`: `core.window`'s `block_chars` / `message_chars`; `Mapping` fields | `test_r14_c_ledger.py::test_the_ledger_counts_a_message_as_the_window_does` (refactor guard, green before and after) |
| Python, size: Anthropic `complete` 61 lines | **Fixed** `7f18da0`: 34 lines (OpenAI-compatible `complete` 61 → 41) | — |
| Found while fixing: the Vitals note can pass its 300-character limit with large sums (the item then can't be built) | **Fixed** `598d3ed`: the smallest parts are left out first | `test_r14_c_ledger.py::test_the_vitals_words_always_fit_the_vitals_note` |

Declined: none inside Part C's files. Seen and not Part C's: the mypy errors in other parts'
fakes that Part C's tests import (section 3), and `pyproject.toml`'s package data (C).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.2 | 14 Nov 2026, 17:50 IST | R14 | Review follow-ups (section 8): every MEDIUM and LOW of the three reviews fixed test first (vendor exceptions off `__context__`, the `cause` class, the history breakpoint only with tools, the request from the SDK's TypedDicts, the window's start never back, an approval never cut, the offer's malformed `skills_open`, per-surface turns and bounded memory, `skills_open`'s plain filed names, the ledger's 90 days and "chat replies" words, mypy strict on Part C's tests); Needs I1 A completed (the five passages word for word, 20 files / 22 lines / 24 cases from a dry run, the rewrite of `test_tools_not_offered_persona.py`, a seam test checked in three states); F says what the ledger covers; H done; measurements re-run | 🛠 Mark XIX |
| v14.0.1 | 14 Nov 2026, 17:05 IST | R14 | First edition: Part C built (window, vendor text, history cache point, register and its check, the turn's tools, `skills_open`, the token ledger, the part, its routes, the eval with three controls), the decisions taken, the measurements with recall reported honestly (tuned and held-out), Needs I1 A–H with exact changes (the persona p14.0 as a release blocker), contract notes, what can't be verified | 🛠 Mark XIX |
