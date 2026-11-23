---
page: pg_card_c04
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-telegram.js": "3a2ca68ffecee7e5"
  "src/jarvis/api/telegram.py": "4787df327efb86d5"
  "src/jarvis/notify/telegram_out.py": "b716c4ea72837feb"
  "src/jarvis/telegram/__init__.py": "a716a9e06bb7a620"
  "src/jarvis/telegram/alerts.py": "4dd37fab0cde0151"
  "src/jarvis/telegram/client.py": "c5efc78af12cb8f9"
  "src/jarvis/telegram/format.py": "eeca5a604aee947f"
  "src/jarvis/telegram/models.py": "4e354e857876c2c2"
  "src/jarvis/telegram/pairing.py": "100afc342ea8c4b5"
  "src/jarvis/telegram/rules.py": "1371706eba15ef7a"
  "src/jarvis/telegram/service.py": "abea8743a90bb292"
  "src/jarvis/telegram/store.py": "d226bbd7ff3a01ce"
---
## In plain words
Telegram is a second front door to JARVIS. After pairing your Telegram account once, you chat with JARVIS from your phone much as you do in the console, and its alerts reach you there too. Only you get in: a message from anyone else gets no reply. Bot chats sit on Telegram's servers rather than being locked end to end, so your mail, Drive, documents, contacts and other private reads stay off there until you switch them on, and anything irreversible still waits for your approval and passkey in the console.

## Example (made up)
In the console you press Pair and get the code 7KQ2M9XA, good for ten minutes. You tap the link on your phone, Telegram opens the bot with the code, and JARVIS answers "Paired. Ask me anything." That evening on the bus you type "add a to-do: buy milk". You set to-dos to Ask first, so JARVIS replies with a one-line card and two buttons; you tap Approve and it is done. When you ask it to send an e-mail, Telegram only says it is waiting in the console for your approval and passkey.

## How it works
Telegram delivers each message to `POST /telegram/webhook`, which answers only when the secret header matches (`telegram_webhook_secret`) and the body is at most {{fact:src/jarvis/api/telegram.py:WEBHOOK_BODY_BYTES}} bytes.
`TelegramService` accepts input only from the paired owner: sender and chat must both match the pairing, the chat must be private and the sender not a bot. Anyone else never reaches the brain, gets no reply and is noted in the `audit` trail, at most {{fact:src/jarvis/telegram/service.py:REJECTED_AUDIT_PER_HOUR}} an hour.
Each update is claimed once before any work (`telegram_updates`), so a retry from Telegram never runs a turn twice.
Pairing uses a code from `new_code`: {{fact:src/jarvis/telegram/pairing.py:CODE_LEN}} characters, alive {{fact:src/jarvis/telegram/pairing.py:CODE_TTL_S}} seconds, stored only as a hash and void after {{fact:src/jarvis/telegram/pairing.py:MAX_TRIES}} wrong tries.
A message becomes an ordinary brain turn on the Telegram channel, at most {{fact:src/jarvis/telegram/service.py:MAX_MESSAGES_PER_WINDOW}} messages in {{fact:src/jarvis/telegram/service.py:MESSAGE_WINDOW_S}} seconds, each turn limited to {{fact:src/jarvis/telegram/service.py:TURN_BUDGET_S}} seconds (`src/jarvis/telegram/service.py`). A forwarded message is wrapped as outside data, never instructions (`outside_message`).
During the turn `ChannelRules` refuses private reads (mail, Drive, documents, contacts, pictures, health), personal reads (vault, notes, things) and home reads (devices, camera history, faces), each group behind its own switch (`src/jarvis/telegram/rules.py`). Without those rules in place, no Telegram turn runs at all (`TelegramService`).
`reply_messages` sends the answer as plain text in pieces of up to {{fact:src/jarvis/telegram/format.py:LIMIT}} characters, at most {{fact:src/jarvis/telegram/format.py:MAX_MESSAGES}} messages, the rest left in the console.
A reversible approval card short enough to read whole ({{fact:src/jarvis/telegram/service.py:CARD_CHARS}} characters) gets Approve and Decline buttons; a longer, irreversible or console-only card never does, and an "approval waiting" alert goes out instead (`TelegramService`). A tap is checked again before it counts: same owner, same conversation, still reversible (`src/jarvis/telegram/service.py`).

## What it costs
The door itself costs nothing: no rupees, because the bot talks straight to Telegram (`TelegramClient`). Each chat turn costs the same as a reply in the console and counts against your monthly AI limit (`src/jarvis/telegram/service.py`).

## When it fails
A message from anyone but you gets no reply and is audited (`TelegramService`). If the AI is busy you read "The AI service is busy or unavailable right now. Please try again in a minute."; at your monthly limit, "The monthly AI limit has been reached. Open the console to change it." A turn over its time limit ends with "That took too long, Sir. Please try again, or use the console." If the privacy rules aren't confirmed, JARVIS declines to answer on Telegram and points you to the console (`src/jarvis/telegram/service.py`). If Telegram itself is down, alerts still reach your browsers through Web Push (C47).
