# People research + no-AI mode (R4 Workstream D) — integration

## 1. Build the service (e.g. in `tools/setup.py` / the app factory)

```python
from jarvis.people.composer import router_composer
from jarvis.people.research import PeopleService, WebSearcher

if web_service is not None:  # the existing WebService (None: no Tavily key)
    people = (
        PeopleService(
            WebSearcher(web_service),  # public search, uses the monthly web allowance
            router_composer(brain.router),  # the ONE brain call (FAST tier); None = links only
        )
        if s.people_research_enabled
        else None
    )
app.state.people = people  # the routes read this (None -> 503)
```

## 2. Tools (through the gateway, row `people`, R1)

```python
from jarvis.people.tools import PeopleDeps, people_tools

for t in people_tools(PeopleDeps(service=people, brain_mode=lambda: s.brain_mode)):
    reg.register(t)
```

Registers `research_person` (row `people`/`research_*`) and `people_open_profiles`.
NOTE: the brief called the second one `open_profiles`, but the `people` permission row only matches
`people_*` and `research_*`, so it is named `people_open_profiles` (constant `OPEN_PROFILES` in
`people/tools.py`; change it there and in `offline/rules.py` if the row pattern is widened instead).
Both declare `activity_words`; add `people_` / `research_` to `activity/words.py` prefixes only if
you want nicer activity lines (not required).

Persona line (optional, `core/prompts.py`): "research_person is for public figures and work
due-diligence only; it refuses private individuals. people_open_profiles hands links to the
owner's browser."

## 3. Routes

```python
from jarvis.people.routes import install_people

install_people(app)  # POST /v1/people/research, GET /v1/people/last,
# GET|POST /v1/settings/brain-mode
```
Owner-only (`require_auth` + `current_user`, CSRF header on cookie writes). Research is limited to
6 a minute per owner. The brain-mode POST flips `app.state.settings.brain_mode` for the running
process (the same object `Brain` reads); the start-up default is the `brain_mode` setting / env.
It is not persisted across restarts.

## 4. Console

New static file `src/jarvis/api/static/console-people.js` (the repo's static dir, not a root `web/`).
- Add `"console-people.js": _JS` to the static map in `api/console.py`.
- In `console.html`: a panel shell `<section id="p-people"> ... <div class="pbody"></div></section>`
  and `<script src="/static/console-people.js" defer></script>`; optionally an empty
  `<span id="brainModeSlot"></span>` in the HUD header to show the "Brain: AI on / No-AI" badge.
- It fires `jarvis:brainmode` on `document` and exposes `window.JarvisBrainMode.{get,set}`.
- "Open all profiles" does `window.open(url, '_blank', 'noopener,noreferrer')` once per URL, from the
  click. "Speak" uses the existing `JarvisVoice.speaker.say(...)`, i.e. `/v1/voice/speak`
  (`voice.service`, metered there); the spoken text is already passed through `voice.speakable`.
- Optional CSS: reuses `bnote`, `btn`, `tlist` classes; `.pcard`, `.brainmode` are unstyled hooks.

## 5. No-AI mode (already in the three files this builder owns; nothing to register)

- `core/brain.py`: when `settings.brain_mode == "none"`, `chat` and `chat_stream` skip the provider
  entirely (no billing, no memory recall) and answer via `offline/no_ai.py` (`no_ai_turn`).
- `offline/rules.py`: `route_no_ai(text, now)` (pure) and `NO_AI_LINE`
  ("That needs the AI switched on, Sir.").
- `llm/router.py`: `ModelRouter.blocked` (set by `Brain` for every router) makes a stray model call
  raise `BrainOff`. R1's automatic laptop fallback is untouched (it only runs after a cloud miss).
- Tools the router calls by name — they must be registered for each skill to work in no-AI mode:
  `systems_check`, `vitals_show` (Builders A/B), `calendar_list_events`, `reminders_list`,
  `reminder_add` (timers and "remind me"), `tasks_list`, `kb_add_note`, `kb_search`,
  `research_person`, `people_open_profiles`. A missing one answers "That isn't available right now,
  Sir." Writes (`reminder_add`, `kb_add_note`) still go through the gateway policy, so they may
  come back as an approval card.
- The HUD must not hide the `brain_mode` switch behind the AI: `/v1/settings/brain-mode` calls no model.

## 6. Data / tick jobs / brief

None. Dossiers are session-only (in-process, per owner, 1 hour, never written to Docs or memory).
