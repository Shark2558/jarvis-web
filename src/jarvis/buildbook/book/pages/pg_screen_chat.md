---
page: pg_screen_chat
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/routes.py": "4086daa780722d3f"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
---
## In plain words
Conversation is where you talk to JARVIS. You type a message, press Send, and the answer appears in the thread with a small line under it: which brain answered, how long it took and roughly what it cost in rupees. Every conversation is saved, so you pick it up again from History on any device. Anything that sends, pays or can't be undone waits for your approval first, as the hint under the message box says (`src/jarvis/api/static/console.html`).

## Example (made up)
At 8:40 on a Monday you open Chat. JARVIS greets you with "Good morning" and four suggestions. You tap "What's on my calendar today?" and, 2.3 seconds later, the reply lists three meetings. Under it the line reads: the brain's name, the model, 2.3 s, ≈ ₹0.40 and 1 tool call. You then type "Move the 4 pm call to Thursday". JARVIS answers that a change is waiting for your approval, and the Approvals button lights up with a 1. When you are done, you tap the pencil at the top of the panel to start a fresh conversation.

## How it works
The panel in `src/jarvis/api/static/console.html` holds the thread, a paperclip to attach files, the box that says "Message JARVIS", a microphone button when the browser hears speech, and the Send arrow. Enter sends and Shift + Enter starts a new line (`src/jarvis/api/static/console.html`). Send posts your words, the open conversation and the brain you picked to `POST /v1/chat`. The route `src/jarvis/api/routes.py:chat` stamps the message with your user id from your sign-in, never one the page sends. `_no_telegram` refuses a message that claims to come from Telegram, since only the Telegram service may say that. The answer from `POST /v1/chat` carries the reply, the brain, the model, the time taken, the cost in rupees and the number of tool calls, and the console writes them under the bubble. A reply that needs an approval leaves a card behind, listed by `GET /v1/approvals`. When JARVIS proposes a phone call, the answer from `POST /v1/chat` also carries a call card, drawn under the reply with Call, Edit and Cancel and the number's last digits only, while the same proposal waits in Approvals (`calls`). Each conversation is kept in the `sessions` collection, so it survives JARVIS going to sleep. The brain picker in the top bar is filled from `GET /v1/brains` (`list_brains`), and a brain's warning shows as a banner over the deck. The pencil button (`src/jarvis/api/static/console.html`) starts a new conversation; the old one stays in History.

## What it costs
The panel itself costs nothing: it is part of the page JARVIS serves (`src/jarvis/api/static/console.html`). Each reply costs what its brain charges, and the line under it shows that in rupees (`POST /v1/chat`). A free brain's reply shows no price, and a reply from a model JARVIS has no price for says "price unknown" instead, never ₹0 (`POST /v1/chat`). The conversation's running total is kept with it and shown when it is reopened, together with how many of its replies had no known price, which that total leaves out (`src/jarvis/api/routes.py:get_session`).

## When it fails
If the brain or the network fails, the thread shows "JARVIS couldn't answer." with the reason, and nothing else breaks. If the month's spending limit is used up, the server refuses the reply before any paid call and the thread shows its words, such as "This month's AI spending limit is used up. Raise it in Vitals, or switch to the free brain." If the same conversation changed in another window, `conflict_body` says whether your message was kept, and the console reloads the conversation so you never send it twice. If your sign-in has expired, the sign-in screen covers the console until you sign in again.
