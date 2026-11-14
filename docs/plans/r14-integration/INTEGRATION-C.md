Version v14.0.1 · 14 Nov 2026, 17:05 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 — Part C integration notes (cost and the skill register)

Built by builder C for the Workshop (🛠 Mark XIX) on branch `r14-c`, from `r14-i0` @ `9eb9d8b`,
test first throughout (each test file was run red before its code). Plan:
`docs/plans/r14-hardening.md` v14.0.2, D8–D11 and the Part split's row C. The contract
(`jarvis.hardening.ports`, `jarvis.skills.ports`) is unchanged.

**Read "Needs I1" A first: the persona must change in the same release, or `tool_offer` stays
"all".** Today's persona tells the model that a tool it isn't offered "is not connected"; with the
offer on, that turns every tool left out of a turn into a refusal instead of a `skills_open` call.

## 1. What Part C built

| Deliverable | What it does |
|---|---|
| `core/window.py` (D9) | Every block counts toward `session_max_chars` (text, a call's name and arguments, a result); results older than the last 2 tool rounds are cut to `tool_result_chars` (default 2,000 = the setting's default) with `… [shortened]`, keeping the "untrusted tool output" header line, `is_error` and `trusted` (send-side only; the taint check gives the same answer on the cut window, tested); old turns go in chunks down to 70 % of either cap, replayed over the history so the start holds for several replies; the newest turn is always kept. |
| `llm/*` (D9, fact 13) | `LLMAuthError`, `LLMUnreachable`, `LLMTransientError`, `LLMError` carry fixed words (`llm.base`: `AUTH_REFUSED`, `UNREACHABLE`, `BUSY`, `NO_ANSWER`; `FIXED_ERROR_WORDS`) in Anthropic, Gemini and OpenAI-compatible (the laptop brain inherits them); the vendor's message is never chained (`from None`) or logged (the log keeps our class and the HTTP status); the router logs `type(exc).__name__`. `AnthropicProvider(cache_history=…)` adds a second breakpoint on the last message's last non-empty block of every `complete()` (plain messages go out as one text block so the next round's prefix is byte-for-byte the same); `stream()` keeps the system breakpoint only (one call a reply). `llm/factory.py` builds Claude from the settings for both `router.build_provider` and `brains.BrainRegistry.from_settings` (the plan's "factory"; `brains.py` is under `llm/*`, BRIEF-COMMON §3). No slot, no hint in the shared interface. |
| `skills/catalogue.json` (D11) | The 11 skills in `skills.ids` order, each with its one-line "about" and **groups** (40 in all): tool patterns (an exact name wins over a family) and words, English and common Hinglish. Plus `core`, `telegram_open` (the read tools Telegram answers), `no_ai` (what No-AI mode reaches, pass 1, the helpers' routers and Part D's D12 list) and `planned` (A's and D's tools, named before they exist). Groups, not whole skills, are what a word offers: one skill (Task & Productivity) holds 31 tools. |
| `skills/registry.py` (D11) | `load_catalogue` / `parse_catalogue` (refuses a wrong version, a missing, unknown or reordered skill, a group id used twice, upper-case words, a group with no tools); `SkillRegister` files a tool by name; its card: skill, group, risk R1/R2/R3, permission rows (`groups_for`), Telegram class (private / personal / home / both from `telegram/rules.py`, open when listed, or a write), No-AI. `problems(registry)` is the check: no skill, filed twice, a pattern matching nothing, a read with no Telegram class, a read both open and refused, a list naming an unregistered tool that isn't planned. |
| `skills/offer.py` (D9) | `SkillOffer`, the `ToolOffer`: the groups his words name ∪ the groups of tools used in the last 3 turns ∪ the previous turn's set while under `tool_offer_sticky_s` (dropped when the union passes 40 tools) ∪ the core ∪ every tool a replayed `tool_use` names; fixed per turn (keyed by trace id, owner-message count and text), `skills_open(skill)` adds that whole skill from the next round; registry order; a tool the register can't file is always offered. Words match at a word's start; three letters or fewer match the whole word or with an `s` ("emi", "emis", never "email"). `offer_all` kept. |
| `skills/open_tool.py` | `skills_open(skill)`: R1, no row (the risk default), Telegram open, `trusted_output` (its answer is the register's own fixed data), an argument check refusing an unknown skill; answers the label, the about and the skill's registered tool names; description 1,288 characters (each skill's id and about). |
| `billing/ledger.py` (D8) | `TokenLedgerStore` (the `TokenLedger`): per call, per owner per day in his zone, `{prefix}token_ledger/{uid}_{yyyymmdd}`: calls, cold calls (no cache read), input / cache read / cache write / output tokens from the vendor's `Usage`, characters by part (persona, tools, history, tool results, memory: the trailer after the recall heading, trailer), tools offered, skills opened, and the call's cost by part (output priced as "replies", the rest shared by characters, the rounding into the largest part so they add up). One transaction per call; the first call of a day drops days older than 90. Counts only (a test plants a word in the prompt, messages, trailer and reply and finds it nowhere in the document). `ai_parts_note`: the Vitals line in ₹. `NoLedger` kept. |
| `skills/part.py` | `build(ctx)`: the register (an unreadable catalogue raises: the wiring leaves the part out, so every tool is offered), `skills_open`, services `offer` (only while `tool_offer = "by_skill"`), `ledger` (only while `token_ledger_enabled` and a document store exists), and for its routes `register` and `ledger_view`; the quiet Vitals item `ai_parts` (`kind="billing"`, ₹ at the app's daily rate, the default rate if it can't be read; "unknown" with fixed words when the ledger is off or unreadable); the privacy row `token_ledger` (section "Activity and messages", count = days kept, "90 days", no export, no delete). Ready word: `ready`, or `ready: <why>` for the kill switch, the ledger switched off, or no document store. |
| `api/skills.py` | `GET /v1/skills` (the 11 skills with tools and No-AI counts, the core, `tool_offer`, the registry's size) and `GET /v1/costs/ledger` (this month: days, calls, cold calls, tokens, characters, tools per call, skills opened, cache share, ₹ by part, ₹ in all, the rate). Owner-only, `no-store`, counts and names only; an unreadable ledger is 503 `ledger_unreadable` with no detail; before the part is built, `{part, ready}` as I0's stub. |
| `scripts/skill_coverage.py` | Prints the two tables (skills; every tool with skill, group, risk, rows, Telegram, No-AI) from the fullest fake registry; exit 1 with the problems listed. For the guide's C68 and the build book. |
| `evals/r14/offer.py` (BUILT) | See §3. |
| Tests | `tests/test_r14_c_{window,llm_errors,cache,register,offer,open_tool,ledger,part}.py`, `tests/test_r14_skill_coverage.py`, `tests/r14_fakes_c.py`: 108 tests. |

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
4. **The history breakpoint rides every `complete()`, never `stream()`.** A stream is one call a
   reply: a cache write it could never read.
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
| `evals/r14/run.py --mock --part offer` | **9/9 pass**; control **fails** the suite: words emptied → `offer:recall` fails; the pre-R14 window → `offer:window_counts_blocks` fails; hint off → `offer:history_hint` fails (each its own case) |
| Recall, 122 labelled messages (the plan's 120+) | **100 %**. Honestly: **95.9 %** (5 misses) as first written; 7 words were then added from those misses ("cancel", "sync", "block", "delete", "things", "where has my", "where was my"). The same builder wrote the words and the messages. |
| Recall, 24 held-out messages written after, never tuned on | **83.3 %**, then **87.5 %** after one rule fix (short words with a plural `s`); 3 misses left on purpose ("put a call with…", "go to bed", "anyone at the door"). Expect about 1 message in 8 to need a `skills_open` round live; the ledger's `skills_opened` will say. |
| Tools offered (fresh offer, no history) | **9.5** on average (held-out 8.6), at most 19–20, of **136**; D10 assumed about 25, so the per-reply saving is likely larger than its estimate until sticky sets and history add their share (the ledger measures it) |
| `whole r14 runner --mock` | 22/22 pass, combined control fails the suite |
| D11 check on the fullest fake registry | 136 tools filed once each, every pattern used, every read classed; 0 problems |
| Own tests, Python 3.12 | 381 passed (mine and the existing tests of every file I touched) |
| Own tests, Python 3.11 | 185 passed |
| Coverage (my tests) | `skills/offer` 99 %, `registry` 98 %, `part` 98 %, `ports` 88 %, `billing/ledger` 98 %, `core/window` 99 %, `api/skills` 93 %, `llm/anthropic_provider` 97 %, `llm/factory` 88 % |
| `ruff check` / `ruff format --check` | clean (1,672 files) |
| `mypy src` | **1 error** (`memory/redis_store.py`); the 8 baseline errors in `core/window.py` and `llm/anthropic_provider.py` are fixed |
| `arch_coverage.py`, `check_doc_versions.py` | OK; 28 documents (29 with this one) |
| Seam set | 265 passed, 13 failed: the 3 I0 pins and 1 Telegram pin of "Needs I1" E and D, and 9 `test_claude_guard` cases (G: the worktree's location) |
| Sizes | every module ≤ 307 lines; every new function ≤ 50 lines. Pre-existing long functions in `llm/` untouched in length or shorter (`router.complete` 68, `router.stream` 70, the two providers' `complete` 61, `local_provider.stream` 52, `brains.from_settings` 77 → 73) |

## 4. Needs I1 (files Part C may not edit; exact changes)

**A. Persona p14.0 (`core/prompts.py`; RELEASE BLOCKER for `tool_offer = "by_skill"`).** Five
lines say "not offered = not connected". Replace them (then `PERSONA_VERSION = "p14.0"`, the 19
pins, the persona and voice evals, per D14):

- `_RULES` (`:136–137`), replace the "Use only the tools offered…" bullet with:
  `- Use only the tools offered in this request. If none fits and skills_open is offered, call
  skills_open with the skill that holds it first; only if that skill has no such tool either, say
  the capability is not yet connected and offer what you can do with reasoning alone. Never
  pretend an action happened.`
- Web search (`:183–184`): `If no web_search tool is offered, call skills_open("research") first
  when it is offered; if web_search still isn't there, web search is not available here (not set
  up, or this brain is chat-only): say so plainly rather than guess.`
- Drive (`:260`): `- If no drive_* tool is offered, call skills_open("research") first when it is
  offered; if Drive still isn't there, it isn't switched on here: say so plainly.`
- `TOOLS_RULE` (`:267–275`), the first bullet becomes D14's words and the fallback:
  `- This turn you may hold only some of your tools. If he asks for something none of them does,
  call skills_open first; never say you can't before that. Only when skills_open is not offered,
  or the skill it opened has no such tool (the calendar, mail, Drive, Maps, to-dos, payments),
  say plainly that it is not connected here yet and offer what you can do without it.`
  (the second bullet, on tool-call markup, stays).
- `MEDIA_RULES` (`:283–284`): `If no maps_* or youtube_* tool is offered, call skills_open first
  (research for Maps, creative for YouTube); if it still isn't there, it is not set up here: say
  so plainly.`

If p14.0 can't land with the release, ship with `JARVIS_TOOL_OFFER=all` (the kill switch): the
ledger still counts, the window and the cache point still save.

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
rewrite (D8) waits for a week of ledger data.

**G. `tests/test_claude_guard.py`, 9 `rm -rf` cases fail in every builder's worktree** (not
Part C's change: no file of the hook or its test was touched). The hook's `SAFE_ROOTS` holds the
worktrees' parent folder, and the test runs the hook with the worktree as its directory, so
`rm -rf src` resolves inside an allowed root. CI's checkout is elsewhere, so it passes there.

**H. Security review of the `jarvis.llm` change** (`security-reviewer`, required by the row; not
run here: builders start no agents): fixed words and `from None` in the three providers;
logs keep class and status only; `cache_control` added to this call's own copies, never the
stored messages; `llm/factory.py` reads the key from `SecretStr` only and logs nothing; plus
decision 2.3 (`skills_open` as `trusted_output`) and the ledger's counts-only rule.

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
narrowed tool list (needs A and the persona evals).

## 7. Commits on `r14-c`

`9aa7176` window · `335861f` vendor text · `5fb6ca2` cache point and factory · `4050086` register
and check · `930cc31` offer · `d5d21b7` ledger and `skills_open` · `7e99c95` part and routes ·
`e103330` eval (BUILT) · `003d484` gateway test, description · `1e7b947` unhappy paths · this file.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 17:05 IST | R14 | First edition: Part C built (window, vendor text, history cache point, register and its check, the turn's tools, `skills_open`, the token ledger, the part, its routes, the eval with three controls), the decisions taken, the measurements with recall reported honestly (tuned and held-out), Needs I1 A–H with exact changes (the persona p14.0 as a release blocker), contract notes, what can't be verified | 🛠 Mark XIX |
