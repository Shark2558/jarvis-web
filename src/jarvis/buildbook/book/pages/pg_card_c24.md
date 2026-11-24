---
page: pg_card_c24
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/belongings.py": "ed3598e69f3f0053"
  "src/jarvis/api/static/console-things.js": "03183aa2760ac6a0"
  "src/jarvis/belongings/__init__.py": "59061e81359444b0"
  "src/jarvis/belongings/models.py": "6e79e2818e4e0917"
  "src/jarvis/belongings/privacy.py": "e79dd6f3135aa7d9"
  "src/jarvis/belongings/service.py": "a7251e84667b0ff1"
  "src/jarvis/belongings/store.py": "30e8687c378a3973"
  "src/jarvis/belongings/text.py": "6e9b0da98196233c"
  "src/jarvis/belongings/tools.py": "01018502acb03987"
---
## In plain words
Things answers "where did I keep it?". Tell JARVIS where you put something, "the passport is in the blue suitcase", and ask later; a move keeps the old place in the thing's history (`src/jarvis/belongings/service.py`). It is sealed with JARVIS's own encryption before it is stored, and ID numbers or passwords are refused, since those belong in the Vault (`src/jarvis/belongings/store.py`).

## Example (made up)
In May you say "Hey Jarvis, I kept the spare scooter keys in the kitchen drawer". In August you move them and type "put the scooter keys in the hall cabinet"; JARVIS answers "Moved: they were in the kitchen drawer". In December you ask "where is my scooter key?", and JARVIS finds "spare scooter keys", in the hall cabinet, moved on 12 August. The Things panel shows both places in its history.

## How it works
`BelongingsService` adds a thing or, when the name matches one you already have, moves it and puts the old place into its history, up to {{fact:src/jarvis/belongings/models.py:MAX_HISTORY}} moves (`src/jarvis/belongings/service.py`). `thing_key` lets "My passport" and "Passport" match, drops simple plurals and knows a few synonyms such as specs, spectacles and glasses (`src/jarvis/belongings/text.py`). To answer "where", `search` tries the exact name first, then ranks the names, other names and places by your words, and offers at most {{fact:src/jarvis/belongings/service.py:CANDIDATES}} candidates. Every name, place and note passes the sensitive filter, and a thing can record whose it is (`src/jarvis/belongings/models.py`). `BelongingsStore` keeps the list in `belongings` and each history in `belongings_history`, sealed with the belongings key, and writes them together in one transaction (`src/jarvis/belongings/store.py`). The brain's tools come from `belongings_tools`: where, list and history only read, and put is a reversible write that saves without a card unless outside text was in view (`src/jarvis/belongings/tools.py`). Each thing records whether its words were typed, spoken or came from outside, and a move keeps the less trusted of the two, so a later move never vouches for someone else's text (`worse_origin`). Read aloud or sent to Telegram, the answer is masked, so a long number or an address is never spoken (`src/jarvis/belongings/tools.py`). `src/jarvis/api/belongings.py` serves the Things panel, with `GET /v1/things/export` for your own copy, and `src/jarvis/api/static/console-things.js` draws it.

## What it costs
Nothing: it is code and a few small records in the document store, with no AI call and no outside service (`src/jarvis/belongings/service.py`).

## When it fails
Without the token key the feature stays off, so nothing is ever stored in clear (`src/jarvis/belongings/store.py`). A record that can't be read or decrypted fails closed and is never overwritten (`ThingsUnavailable`). When the name isn't exact you get the best matches to choose from, not a guess (`search`). Removing a thing puts a copy in Recently deleted first; with no copy, nothing is removed (`src/jarvis/belongings/service.py`). Past {{fact:src/jarvis/belongings/models.py:MAX_LIVE}} things, a new one is refused (`src/jarvis/belongings/models.py`).
