# People research + no-AI mode (R4 Workstream D) — integration

The owner's legal line (binding): people research is for PUBLIC FIGURES and WORK DUE-DILIGENCE only.
It must never assemble a private individual's accounts, home or movements, or face-match a stranger
(India DPDP Act 2023 + platform ToS).

## 0. How research decides (the gate)

1. **Pre-filter** (`people/guard.py`, deterministic, free): refuses private phrasing and face
   matching before any credit is spent. Text is folded first (NFKD, Cyrillic/Greek look-alikes,
   leetspeak, `s t a l k`, `s.t.a.l.k`, zero-width characters); English + Hinglish terms. It also
   runs on the COMBINED text of a follow-up about the same target (the last target is remembered
   per owner for 1 hour, even when refused). It is not the real control.
2. **Verification gate** (`people/gate.py`): ONE first-pass search (1 credit). Links are produced
   only when the results verify the subject:
   - public figure: a Wikipedia/Wikidata page for the name, or (AI mode only) >= 2 news/official
     pages on different sites naming the person with a public role;
   - due-diligence subject (AI mode only): the context names an organisation or professional role
     AND a page the person did not write (company registry, the organisation's own site, LinkedIn
     COMPANY page, organisation GitHub, press) ties the name to it. A LinkedIn personal profile and
     social profiles never count.
   Otherwise the fixed line "I can only research public figures or people in a stated professional
   role that I can verify, Sir." with at most that 1 credit spent, no links, and nothing cached to
   open later.
3. **Classifier** (`people/classifier.py`, AI mode only, when a model is admitted): FAST tier, no
   tools, output `{"label": public_figure|due_diligence|private|unclear}`. It can only restrict;
   anything but the first two refuses; any error fails closed. In no-AI mode, or when no model may be
   called (no private brain, or the monthly budget is used up), the classifier is skipped and ONLY the
   Wikipedia/Wikidata route verifies.
4. **Link scoping**: public figure -> the full public set (LinkedIn, GitHub, YouTube, X, Wikipedia,
   Instagram, Facebook); due diligence -> LinkedIn, LinkedIn company, GitHub, Wikipedia only (never
   Instagram, Facebook, personal X) and no personal-social snippets in the findings.
5. **Telemetry**: `PeopleService.refusal_counts(uid)` counts refusals by category
   (`private_phrasing | face_match | bad_input | unverified | classifier`); logs carry the category
   only, never a name.

The eval set is `tests/test_people_gate_eval.py` (target-type x mode rows, a bare private name is a
headline row, and a negative control that runs the rows with the gate disabled and requires them to
fail). `PeopleService(gate_enabled=False)` exists only for that; nothing reads it from settings.

## 1. Build the service (e.g. in `tools/setup.py` / the app factory)

```python
from jarvis.offline.mode import BrainMode
from jarvis.people.cache import DossierCache
from jarvis.people.model import BrainPeopleModel
from jarvis.people.research import PeopleService, WebSearcher

brain_mode = BrainMode(s, docs, audit=audit)  # the persisted switch (see 5); one per app
app.state.brain_mode = brain_mode
if web_service is not None and s.people_research_enabled:  # None: no Tavily key
    people = PeopleService(
        WebSearcher(web_service),  # public search, uses the monthly web allowance
        BrainPeopleModel(
            brains, billing
        ),  # classifier + summary: admitted and metered (None = links only)
        mode=lambda: brain_mode.current,
        cache=DossierCache(
            docs
        ),  # 1 h per-owner LRU, also in `<prefix>people_last/<uid>`; omit docs = in-process
    )
app.state.people = people  # the routes read this (None -> 503)
brain = Brain(..., brain_mode=brain_mode)  # the SAME BrainMode object (see 5)
```

Model use: `BrainPeopleModel` picks the brain exactly as the morning brief does (`choose_brain`: a
brain with `tools_allowed`, never one that trains on content), checks `Billing.ensure_allowed` before
each call, calls the FAST tier with no tools, and `record`s the dossier's total cost ONCE
(`Dossier.cost_usd`). A budget-paused owner gets links only, with no model call.

Rate limit: `PeopleService` keeps a per-owner sliding window (burst 2 per minute) shared by the HTTP
route (429) and the tool (a fixed "Too many lookups" result). `turn_budget().people` allows 2
`research_person` calls per owner message. Searches are charged per call, so a refusal costs 1 credit,
never 3 (there is deliberately no up-front reserve of all three).

## 2. Tools (through the gateway, row `people`, R1)

```python
from jarvis.people.tools import PeopleDeps, people_tools

for t in people_tools(PeopleDeps(service=people)):  # brain mode is read from the service
    reg.register(t)
```

Registers `research_person` (row `people`/`research_*`) and `people_open_profiles`.
`research_person` returns a refusal as a normal result `{refused: true, message, spoken}` in fixed
words (and `{unavailable: true, ...}` for a failed search or a rate limit); private PHRASING is
rejected earlier by the tool's argument check. Model-facing text is fenced: titles, findings and the
summary are wrapped as external content, and the `spoken` form of a model summary is NOT returned to
the model (a template `spoken` is, when there is no summary).

Persona line (optional, `core/prompts.py`): "research_person is for public figures and work
due-diligence only; it refuses private individuals. people_open_profiles hands links to the
owner's browser."

## 3. Routes

```python
from jarvis.people.routes import install_people

install_people(app)  # POST /v1/people/research, GET /v1/people/last,
# GET|POST /v1/settings/brain-mode
```
Owner-only (`require_auth` + `current_user`, CSRF header on cookie writes). 422 `out_of_scope` carries
the fixed refusal; 429 is the service's limit.

## 4. Console

New static file `src/jarvis/api/static/console-people.js` (the repo's static dir, not a root `web/`).
- Add `"console-people.js": _JS` to the static map in `api/console.py`.
- In `console.html`: a panel shell `<section id="p-people"> ... <div class="pbody"></div></section>`
  and `<script src="/static/console-people.js" defer></script>`; optionally an empty
  `<span id="brainModeSlot"></span>` in the HUD header to show the "Brain: AI on / No-AI (brain only)" badge.
- It fires `jarvis:brainmode` on `document` and exposes `window.JarvisBrainMode.{get,set}`.
- "Open all profiles" does `window.open(url, '_blank', 'noopener,noreferrer')` once per URL, from the
  click; its host allow-list mirrors the server's exact-host rule. "Speak" uses the existing
  `JarvisVoice.speaker.say(...)` (`/v1/voice/speak`, metered there).
- The badge and the switch text say plainly that No-AI covers the BRAIN only; speech is metered
  separately.

## 5. No-AI mode and the persisted switch

- `offline/mode.py` `BrainMode(settings, docs, audit=...)`: the switch is persisted in
  `<prefix>settings/<uid>` (`{brain_mode, set_by, updated_at}`), read per turn and cached 5 s, every
  flip appends an audit entry (`brain_mode_set`), and a missing document uses `Settings.brain_mode`.
  An unreadable or invalid document reads as `none` (fail closed: no model when we cannot tell).
  Without a Docs store it is the setting itself (CLI/tests).
- `POST /v1/settings/brain-mode` is owner-only (`current_user`); GET reports the persisted value.
- `core/brain.py` takes `brain_mode=` and owns an `offline.no_ai.NoAIRunner`. While the switch is
  `none`, `chat` / `chat_stream` skip the provider entirely: no `_admit`, no billing, no recall, no
  learning, and the monthly limit never refuses a no-AI turn (`check_budget` returns early). The turn
  is stored with `save_owner_turn` (attachments bound) and the conflict-safe `Rounds.store`; a
  pending approval is returned in `ChatResponse.pending_approvals` and, when streaming, in
  `StreamMeta.pending` / `StreamMeta.cards`.
- `offline/rules.py` `route_no_ai(text, now)` is CONSERVATIVE: no model to arbitrate, so it
  under-matches and answers `NO_AI_LINE` ("That needs the AI switched on, Sir.") rather than guess.
  `research` / `profiles of` must start the command and take a proper name (2-4 capitalised words);
  `schedule`, `tasks`, `quota` must be command-shaped. Timers round UP to the next minute, amounts
  are 1..10000, compound durations and bare clock times ("at 5") ask for a clear time.
- `llm/router.py`: `ModelRouter(blocked=...)` / `bind_blocked(fn)` (called once by `Brain`) makes a
  model call raise `BrainOff`; `is_blocked()` lets background users (`brief/summarize.py`,
  `recall/extract.py`) skip quietly. R1's laptop fallback is NOT tried for `BrainOff`.
- Errors: `api/app.py` `friendly_llm_error(BrainOff)` is `NO_AI_REFUSAL` and the API answers a stray
  `BrainOff` with 409 `{"error": "brain_off"}`; `telegram/service.py` and `cli.py` say the same line.
- Tools the router calls by name — they must be registered for each skill to work in no-AI mode:
  `systems_check`, `vitals_show` (Builders A/B), `calendar_list_events`, `reminders_list`,
  `reminder_add` (timers and "remind me"), `tasks_list`, `kb_add_note`, `kb_search`,
  `research_person`, `people_open_profiles`. A missing one answers "That isn't available right now,
  Sir." Gateway error text is never repeated to the owner except the project's own fixed refusals.
  Writes still go through the gateway policy, so they may come back as an approval card.
- Wire: pass the SAME `BrainMode` to `Brain(brain_mode=...)`, `app.state.brain_mode` and
  `PeopleService(mode=brain_mode.load)` (an ASYNC per-owner reader, awaited on every call).

## 6. Data / tick jobs / brief

New documents: `<prefix>settings/<uid>` (brain mode) and, when `DossierCache(docs)` is used,
`<prefix>people_last/<uid>` (last dossier + last target, 1 h, expiry checked on read, deleted by
`clear`; carries `expires_at`). A REFUSED target is never written (memory only). Dossiers are never
written to long-term memory. TODO for `deploy/cloudrun.sh` (not yet added): a Firestore TTL policy on
collection group `jarvis_people_last`, field `expires_at`
(`gcloud firestore fields ttls update expires_at --collection-group=jarvis_people_last --enable-ttl`),
so an unread entry is removed too. The privacy panel has a People research category (export + delete).
No tick jobs; the brief's AI summary skips quietly while the switch is `none`.
