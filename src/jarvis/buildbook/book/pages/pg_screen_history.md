---
page: pg_screen_history
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
---
## In plain words
History is the list of your saved conversations with JARVIS, newest first. Each row shows the conversation's title, when it was last used and how many messages it holds; the one open in Chat is highlighted. Tap a row to carry on where you left off, on this device or another one. The bin beside a row deletes that conversation for good, after asking you first (`src/jarvis/api/static/console.html`).

## Example (made up)
On Saturday morning you remember a packing list JARVIS helped with on Wednesday. You open History and see "Trip to the hills · 3 Dec · 14 messages" fourth from the top. You tap it, Chat opens with the whole conversation and the line "Earlier conversation restored.", and you ask JARVIS to add a torch to the list. Later you tap the bin beside an old test chat, read "Delete for good? This cannot be undone.", and press Delete.

## How it works
The History panel in `src/jarvis/api/static/console.html` fills its list when the console starts and again after a new conversation begins. Each row is a button with the conversation's title, or "Untitled conversation", and below it the time (for today) or the date, and the number of messages (`src/jarvis/api/static/console.html`). Tapping a row opens that conversation in the Chat panel, with its replies, sources and WhatsApp drafts as they were (`src/jarvis/api/static/console.html`). The number beside the panel's title is how many conversations are listed (`src/jarvis/api/static/console.html`). The bin button opens a small question with Keep and Delete, and Esc means Keep without closing the panel (`src/jarvis/api/static/console.html`). Deleting the conversation that is open starts a fresh one in Chat (`src/jarvis/api/static/console.html`).

## What it costs
Listing and opening conversations uses no AI, so it costs nothing (`src/jarvis/api/static/console.html`). Deleting one is free too.

## When it fails
If a conversation fails to open, Chat says "Couldn't open that conversation." with the reason. If a delete fails, Chat says "Couldn't delete that conversation." with the reason, and the row stays. If you try to delete the conversation JARVIS is still answering in, the question changes to "JARVIS is still answering here. Delete once the reply has arrived." If the list itself fails to load, the panel keeps what it showed before. With nothing saved yet, it says "No saved conversations yet."
