---
page: pg_card_c70
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r13/laundry.py": "7a0e2b1fd37edc35"
  "src/jarvis/api/laundry.py": "4ddf7920120f936f"
  "src/jarvis/wardrobe/laundry/__init__.py": "c06b166eb3ba666a"
  "src/jarvis/wardrobe/laundry/answers.py": "083f73adac0a897c"
  "src/jarvis/wardrobe/laundry/blind.py": "839e96f32a12e74b"
  "src/jarvis/wardrobe/laundry/cards.py": "035cb3971c03519a"
  "src/jarvis/wardrobe/laundry/checks.py": "bdb589eb43fbb9bc"
  "src/jarvis/wardrobe/laundry/corrections.py": "d58f15aec224c7ad"
  "src/jarvis/wardrobe/laundry/desk.py": "eb968be7ce1c94d0"
  "src/jarvis/wardrobe/laundry/flows.py": "b104698a9f9fc4b2"
  "src/jarvis/wardrobe/laundry/history.py": "f3d6ae6e7f701874"
  "src/jarvis/wardrobe/laundry/holds.py": "f2b8873ecd9be1c7"
  "src/jarvis/wardrobe/laundry/jobs.py": "ca238f949ee5e740"
  "src/jarvis/wardrobe/laundry/loads.py": "e907c19017ce5507"
  "src/jarvis/wardrobe/laundry/part.py": "15450b1dd178a058"
  "src/jarvis/wardrobe/laundry/providers.py": "f9bdb9e303faf33d"
  "src/jarvis/wardrobe/laundry/resolve.py": "0ee20b28664795be"
  "src/jarvis/wardrobe/laundry/review.py": "998f04046d2bfb94"
  "src/jarvis/wardrobe/laundry/store.py": "5733d24475ae1c1e"
  "src/jarvis/wardrobe/laundry/texts.py": "ddcfeb77a148b56e"
  "src/jarvis/wardrobe/laundry/tools.py": "d0d568bd876451bc"
  "src/jarvis/wardrobe/laundry/writer.py": "9d8ec4f9f445bc08"
---
## In plain words
Laundry follows your clothes from the basket through washing, drying and pressing back to ready, and keeps track of what you send to an outside laundry or dry-cleaner: the shop's name in your words, the bag, the pieces and the day they are due back. When something is unclear, such as which shirts went into the basket, JARVIS asks you in a review list instead of guessing (`src/jarvis/wardrobe/laundry/review.py`). It prepares and reminds you, but it never orders, pays, calls or messages a shop: no laundry tool has a way to (`src/jarvis/wardrobe/laundry/tools.py`).

## Example (made up)
On Saturday Pooja taps "Put in laundry" and says "the blue shirt and two black socks". She owns two blue shirts, so JARVIS holds both and asks "Which of these went into the basket?"; she taps the striped one. On Sunday she sends three sarees to "Lakshmi Dry Cleaners", bag 14, due Wednesday. On Thursday morning she gets "Laundry overdue: 3 pieces from 1 batch". Two sarees come back that evening; the batch shows "short" until the third returns.

## How it works
Every laundry change is one commit of the wardrobe's store, so a piece's state and the laundry records never disagree (`Desk`).
`plan_basket` puts the pieces you name into the basket and closes their wear; `match` accepts your words only when every word fits one piece, and more than one match becomes a question, never a guess.
`hold_events` is the only place a hold is made: a doubtful piece is held, unavailable for outfits, until you answer.
`plan_step` moves only the pieces named, or the washing pieces of a load, and refuses a step on a piece that isn't in that load (`src/jarvis/wardrobe/laundry/loads.py`).
A load holds at most {{fact:src/jarvis/wardrobe/laundry/loads.py:MAX_PIECES}} confirmed pieces.
For outside laundry, `clean_shop` keeps the shop's name only in your words and refuses anything that looks like a phone number, address or account number, and `mark_back` checks each piece in on its own, marking the batch "short" when some are still out (`src/jarvis/wardrobe/laundry/providers.py`).
"I moved things without scanning" holds every piece in the places you name until a rescan confirms them (`plan_blind`).
The review writer adds each hold's review entry in the same commit as the hold, so a hold never exists without its question (`src/jarvis/wardrobe/laundry/writer.py`).
`LaundryDaily` runs on the morning tick: a reminder for each overdue or short batch, once, a quiet note when old checks still wait, and a sweep of closed loads and answered checks.
The brain's laundry tools all sit in your laundry permission row and go through the tool gateway (`src/jarvis/wardrobe/laundry/tools.py`).

## What it costs
Nothing. It is plain code on JARVIS's own server with no outside service and no AI call (`src/jarvis/wardrobe/laundry/loads.py`).

## When it fails
An unclear name becomes a review entry and a hold, never a guess (`match`). A step on a piece that isn't in that load is refused (`plan_step`). A batch with no due date never sends an overdue alert (`LaundryDaily`). A reminder that no channel took is tried again at the next run. Without the token key the change rolls back and nothing is kept in clear (`src/jarvis/wardrobe/laundry/writer.py`). The review list keeps at most {{fact:src/jarvis/wardrobe/laundry/review.py:MAX_OPEN}} open entries, folding old checks together but never dropping a hold (`src/jarvis/wardrobe/laundry/review.py`).
