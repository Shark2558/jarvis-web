---
page: pg_screen_approvals
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/routes.py": "4086daa780722d3f"
  "src/jarvis/api/static/console-approvals.js": "78988c35de701d28"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
---
## In plain words
Approvals is where JARVIS waits for your yes. Whenever it wants to do something that sends, pays, deletes or changes your accounts, it stops and puts a card here instead of doing it. Each card says which tool, how risky it is, what exactly it would do, and has two buttons: Approve and Decline. Nothing on a card happens until you press Approve. Under the cards, Permissions lets you choose what JARVIS may do without asking (`src/jarvis/api/static/console.html`).

## Example (made up)
At 10:15 you ask JARVIS to e-mail Meera the agenda for Friday. The reply says a draft is ready for your approval, and the Approvals button shows a 1. You open it and read the card: "send email", the risk tag, and the exact address, subject and text. You spot a typo, press Decline, and ask JARVIS to fix it. The new card looks right, so you press Approve. Chat opens, JARVIS confirms the mail went, and the card is gone.

## How it works
The panel lists the cards from `GET /v1/approvals`, and `src/jarvis/api/routes.py:list_approvals` returns only the cards of your own conversations (`_pending_models`). Each card shows the tool, its risk tag, a one-line summary and the exact details JARVIS would send (`src/jarvis/api/static/console.html`). Approve sends `POST /v1/approvals/{approval_id}/approve` with the card's conversation, and the outcome arrives as a reply in that conversation, which the panel opens for you (`src/jarvis/api/static/console-approvals.js`). Decline sends `POST /v1/approvals/{approval_id}/decline`, and JARVIS answers that it did not go ahead (`src/jarvis/api/routes.py:decline`). Only one decision runs at a time, and both buttons stay greyed while it does (`src/jarvis/api/static/console-approvals.js`). When you ask for a passkey on actions that can't be undone, that card's button reads "Approve with passkey" and your device's own passkey prompt runs first (`src/jarvis/api/routes.py:Decision`). With several cards waiting, "Approve all" runs the ones that can be undone, in order, through `POST /v1/approvals/approve-all`; cards that can't be undone stay waiting for their own press (`src/jarvis/api/routes.py:approve_all`). A phone call JARVIS proposes waits here as a "calls place" card, one of those: Approve places the same call as Call on its call card in Chat or Calls, and whichever you press first, the stored card is used once (`calls`). The Permissions section sets Allow, Ask first or Never for each group of tools, and holds your Passkey (`src/jarvis/api/static/console.html`).

## What it costs
Approving or declining a card costs nothing by itself (`src/jarvis/api/routes.py:approve`). The action you approve may cost something, a paid reply after it for instance, and that shows under the reply in Chat, in rupees or as "price unknown" when its model has no known price (`POST /v1/chat`).

## When it fails
If the list fails to load, the panel says "Couldn't load approvals." with a Retry button, and the count shows a dash rather than a made-up zero. If an approve or decline fails, Chat shows "Couldn't approve." or "Couldn't decline." with the reason, and the card stays for another try. If the card's conversation has been deleted, Chat says "This approval belongs to a conversation that no longer exists." If a passkey check is cancelled, the card says so and nothing runs.
