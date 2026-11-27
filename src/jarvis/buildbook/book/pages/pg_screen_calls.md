---
page: pg_screen_calls
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/calls_routes.py": "4afdecf7fe9949c6"
  "src/jarvis/api/static/console-calls-api.js": "30e91b868cba4573"
  "src/jarvis/api/static/console-calls-audio.js": "4d3e16c6b71d771e"
  "src/jarvis/api/static/console-calls-card.js": "0a7f743bb3cc8942"
  "src/jarvis/api/static/console-calls-form.js": "7279e89d506cadd2"
  "src/jarvis/api/static/console-calls-langs.js": "3a0987ae383415f8"
  "src/jarvis/api/static/console-calls-list.js": "c0cf7507ca91abcf"
  "src/jarvis/api/static/console-calls-live.js": "b6559fad283919fe"
  "src/jarvis/api/static/console-calls-settings.js": "3159d528730c21d5"
  "src/jarvis/api/static/console-calls-shapes.js": "89915dbab755e8fe"
  "src/jarvis/api/static/console-calls-vitals.js": "63efa45173e7bab2"
  "src/jarvis/api/static/console-calls.js": "5820e269aee5d868"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
---
## In plain words
Calls is where JARVIS makes phone calls for you: the call goes out from your own phone, and the call desk on your laptop carries the talking. A line at the top says whether the laptop and the phone are ready, how many calls you made today and what calls have cost this month. Under it are four tabs: Calls lists your recent calls and their records, New call makes a call card, Languages shows which Indian languages JARVIS may use on a call, and Settings holds your caps and choices. Nothing is dialled until you press Call on a card, and while a call is on you read it live, listen in, step in or hang up (`src/jarvis/api/static/console-calls.js`). What the other person says is shown as their words and never taken as an order (`src/jarvis/api/static/console-calls-shapes.js`).

## Example (made up)
On Tuesday at 9:00 you click "Calls this month" in Vitals on your 1920-pixel laptop, and Calls opens. The top line reads "Laptop desk: ready" and "Phone: linked". In New call you choose "Book a laundry pickup", give tomorrow 10:00–12:00 and press Make the card. The card shows the number ending 0001, Malayalam (opens) and English, at most 6 minutes and ≈ ₹1.10. You press Call and the live call opens. You choose Listen live; each Malayalam line has "In English:" under it. In Tell JARVIS you type "Ask if Saturday works too". After 3 minutes the call ends, and Open the record shows the summary, the pickup added to your calendar with Undo, and the day it will be deleted. You press Keep this call.

## How it works
Calls opens from Vitals' "Calls this month" line, from a call card in the chat, and from the console's address ending in ?open=calls (`src/jarvis/api/static/console-calls-vitals.js`). Its tab joins the bar only where it fits beside all the others, so on a full-HD laptop screen it has none, on a wider screen it is last in the bar, and on a narrower one or a phone it waits behind More (`src/jarvis/api/static/console-calls.js`). While the panel is open the top line keeps asking `GET /v1/calls/status` for the desk, the phone, today's count and the month's rupees, and lists what stops a call, a Bluetooth headset on the laptop among them (`src/jarvis/api/static/console-calls.js`). The Calls tab lists calls from `GET /v1/calls/records` under Today and Earlier this week; Open shows the English summary with what was agreed and what needs you, the transcript with each line in English too, the recording's player, and Keep or Delete (Delete asks first) (`src/jarvis/api/static/console-calls-list.js`). New call starts from a ready card or a blank one: the number or a contact, the purpose, what JARVIS may say and agree to, a booking's times, the languages and the length (`src/jarvis/api/static/console-calls-form.js`). Make the card sends it to `POST /v1/calls/cards`; the card shows only the number's last digits, its limits, languages and rupee estimate, with Call, Edit and Cancel (`src/jarvis/api/static/console-calls-card.js`). Call is your approval, with your passkey first for a number JARVIS has never called, and it stays greyed while the laptop or the phone isn't ready (`POST /v1/calls/cards/{card_id}/approve`). Languages shows the check's table; Run shows its cost first and says Bhashini is left out, price unknown; Score the voice takes your scores of a voice heard on a real call (`src/jarvis/api/static/console-calls-langs.js`). Settings shows the server's limits and prices, sends only what you changed to `PUT /v1/calls/settings`, asks before a raise, paid speech, answering or fewer days, and in "Call desk on your laptop" has the kit, a one-use link code and Unlink (`src/jarvis/api/static/console-calls-settings.js`). The live view opens `WEBSOCKET /v1/calls/{call_id}/live` with a ticket that lasts {{fact:src/jarvis/api/calls_routes.py:TICKET_TTL_S}} seconds, shows captions with their English, and offers Listen live or Captions only, Take over, Tell JARVIS and Hang up (`src/jarvis/api/static/console-calls-live.js`).

## What it costs
The panel itself costs nothing: it reads JARVIS's own records of your calls (`calls`). A call costs its speech and its brain; the card shows the rupee estimate before you press Call, and every call is held to its own cap and to the month's calls cap, which sits inside your monthly limit in Vitals (`src/jarvis/api/static/console-calls-settings.js`). The language check shows its estimate before it runs, and inside the free allowances it is free (`src/jarvis/api/static/console-calls-langs.js`). Sarvam and the balanced brain cost more, and are used only after you switch them on and confirm (`src/jarvis/api/static/console-calls-settings.js`). Captions only uses less data than Listen live (`src/jarvis/api/static/console-calls-live.js`).

## When it fails
If calls aren't set up on this JARVIS the panel says "Calls are not set up on this JARVIS yet.", and if they are switched off, "Calls are switched off on this JARVIS." (`src/jarvis/api/static/console-calls-api.js`). Until the call desk runs and the phone app is linked, the top line lists what to fix and a card's Call stays greyed under "Nothing is dialled until this is fixed:". A Bluetooth headset on the laptop gets its own warning, because Phone Link refuses calls then. If the live view drops, it connects again a few times, then says the call goes on and to press Live in the list to look again (`src/jarvis/api/static/console-calls-live.js`). A browser that can't play the call keeps the captions (`src/jarvis/api/static/console-calls-audio.js`). Without JARVIS's https address on the server (`public_base_url`), Settings says the kit needs it.
