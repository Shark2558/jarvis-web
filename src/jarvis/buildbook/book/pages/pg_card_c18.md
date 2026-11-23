---
page: pg_card_c18
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-approvals.js": "78988c35de701d28"
  "src/jarvis/api/static/console-approve-all.js": "1cd7335bb2a31ec1"
  "src/jarvis/core/approve_all.py": "59f16ea07d5207c5"
  "src/jarvis/core/brain_decisions.py": "c952c68c5f5ad1d6"
  "src/jarvis/storage/approvals.py": "0091801c464bb3d8"
  "src/jarvis/tools/calendar_cards.py": "d85a1179488c9292"
  "src/jarvis/tools/card.py": "5a9985efcfe0b89a"
  "src/jarvis/tools/tasks_cards.py": "18cb6c64d784d443"
---
## In plain words
When JARVIS needs your say before acting, it shows an approval card that says exactly what will happen: the real event title and time, who will be told, what changes from what to what. The card's words are written by JARVIS's code from the action itself, never by the AI, so nobody's clever wording slips onto it. You press Approve or Decline in the console, and anything irreversible needs your passkey as well. When several undoable cards are waiting, Approve all clears them with one tap.

## Example (made up)
You forward a school circular and say "add these three events". Because the circular is outside content, JARVIS proposes three calendar cards, each with its date, time and title. You check them and press "Approve all (3)". Two are added; one fails because Google is busy. The reply says so plainly, and that card waits with its own Approve for another try.

## How it works
`one_line` and `quoted` flatten every value on a card to one honest line, removing characters that render as nothing or reorder their neighbours, because a title may come from someone else (`src/jarvis/tools/card.py`).
`create_card`, `update_card` and `delete_card` write calendar cards with the event's real title and time, each change as old to new, and the people Google will e-mail (`src/jarvis/tools/calendar_cards.py`); `src/jarvis/tools/tasks_cards.py` does the same for to-dos.
`DocApprovalStore` keeps waiting cards in `approvals`, so they survive the server going to sleep, and a single-use transaction means a double click never runs one twice (`src/jarvis/storage/approvals.py`).
On Approve, `approved` runs the call through the tool gateway with the card's token; if the action changed since you saw it, say an event gained guests, the card is withdrawn and proposed again and nothing runs (`src/jarvis/core/brain_decisions.py`).
`declined` cancels the card and records that you said no, and the conversation stores what happened before any AI words are added (`record_exchange`).
`run` handles Approve all: at most {{fact:src/jarvis/core/approve_all.py:MAX_IDS}} cards from one conversation, only undoable ones, each run exactly as a single approval would be (`src/jarvis/core/approve_all.py`).
A card that can't be undone, a draft to an address you didn't type, or a memory write never joins Approve all; it keeps its own Approve and the reply says why (`Batch`).
One card failing never stops the others, and the reply names each result in fixed words (`CardResult`).
`src/jarvis/api/static/console-approve-all.js` freezes the batch shown on the button, so a tap never lands on cards you haven't seen.

## What it costs
The cards themselves cost nothing: they are written by code, not AI (`src/jarvis/tools/card.py`). After a decision, one ordinary brain reply tells you the outcome, or fixed words when no AI is available (`narration`).

## When it fails
A card whose action changed since you saw it is withdrawn, not run (`approved`). An irreversible card with passkeys in force needs your passkey and never runs through Approve all (`src/jarvis/core/approve_all.py`). A card already decided or expired answers that it was already handled (`DocApprovalStore`). When no AI can describe a batch, you get the cards' own results in plain words, never "Done" for something half done (`response`).
