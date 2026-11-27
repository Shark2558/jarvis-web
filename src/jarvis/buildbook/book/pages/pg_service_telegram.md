---
page: pg_service_telegram
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/telegram.py": "4787df327efb86d5"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/telegram/client.py": "c5efc78af12cb8f9"
  "src/jarvis/vitals/own.py": "9f8aef630fa0d168"
---
## In plain words
Telegram is a free messaging app. JARVIS has its own Telegram bot, so you chat with JARVIS from your phone like with a person, and JARVIS sends you alerts there: an approval waiting, offline mode, a ready morning brief, a document about to expire, a burglar alert. Only the one Telegram account you pair is answered. What goes to Telegram: your chat with the bot and the alert texts. Telegram keeps bot chats on its servers and they are not end-to-end encrypted, which is why reading your mail, Drive files and contacts, your vault list, notes and things, and your home over Telegram each stay off until you switch them on (`src/jarvis/api/telegram.py:SettingsBody`).

## Example (made up)
In the console you press Pair; JARVIS shows a short code and a link that stays alive for a few minutes. You tap the link on your phone and Telegram opens the bot with the code. From then on, at 8:02 each morning the bot says your brief is ready, and when you write "add milk to groceries" from the shop, JARVIS replies "Added" in about three seconds.

## How it works
`build_telegram` turns Telegram on only when both `telegram_bot_token` and `telegram_webhook_secret` are set (`src/jarvis/api/telegram.py`). Telegram delivers each message you write to `POST /telegram/webhook`; `_secret_ok` compares the secret header in constant time, and a wrong or missing one is turned away with nothing read (`src/jarvis/api/telegram.py:webhook`). A message body above {{fact:src/jarvis/api/telegram.py:WEBHOOK_BODY_BYTES}} bytes is refused, and anything accepted or ignored is answered with success, because Telegram repeats a message after a failure (`webhook`). JARVIS answers through `TelegramClient`, which calls the Bot API over HTTPS with a timeout of {{fact:src/jarvis/telegram/client.py:TIMEOUT_S}} seconds, refuses an answer above {{fact:src/jarvis/telegram/client.py:MAX_RESPONSE_BYTES}} bytes and follows no redirect (`src/jarvis/telegram/client.py`). The bot token sits inside the address Telegram wants, so `TelegramClient` logs method names only, never an address, and its errors use JARVIS's own words (`TelegramError`). A burglar photo goes with Telegram's "protect content" flag, which stops forwarding and saving, and its caption is cut at {{fact:src/jarvis/telegram/client.py:CAPTION_MAX}} characters (`TelegramClient`). Pairing goes through `POST /v1/telegram/pair`, at most {{fact:src/jarvis/api/telegram.py:PAIR_PER_MINUTE}} tries a minute; `PUT /v1/telegram/settings` changes the read switches and alerts, and every pair, unpair and change is written to the audit trail (`src/jarvis/api/telegram.py:settings`). `GET /v1/telegram` shows the bot's name, the pairing, the last four digits of your Telegram id and whether Telegram is delivering (`_view`). Vitals trusts the systems check's Telegram result for at most {{fact:src/jarvis/vitals/own.py:TELEGRAM_MAX_AGE_S}} seconds (`src/jarvis/vitals/own.py`).

## What it costs
Nothing in rupees: the Telegram Bot API is free, and there is no paid plan in use. Each chat turn over Telegram costs a normal reply from the brain, counted with the brain. Telegram's own rate limits apply to how fast the bot may send.

## When it fails
Without the token and the secret, the console says Telegram isn't set up on this server yet (`_off`). If Telegram is unreachable, pairing says to try again in a minute and the status shows "Telegram can't be reached" (`src/jarvis/api/telegram.py:pair`). A failed send names only the method and a short reason, such as "could not reach Telegram" or "Telegram said no" (`TelegramError`). If the database fails while taking a message, the webhook answers with a temporary error and Telegram delivers it again. Vitals shows the bot as not answering, slow, or not checked lately, from the last systems check.
