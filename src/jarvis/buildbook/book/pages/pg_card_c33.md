---
page: pg_card_c33
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/contacts/__init__.py": "549d5efa21d99d8a"
  "src/jarvis/contacts/client.py": "afe0a7932af3d7aa"
  "src/jarvis/contacts/phones.py": "8e963b0fabe76b87"
  "src/jarvis/contacts/tools.py": "eae818db76f2c0e7"
---
## In plain words
When you say "message Arjun" or "mail the plumber", JARVIS looks the person up in your Google Contacts to find the number or address. It only reads your contacts, never changes them, and keeps nothing it finds. When several people match, it asks you which one instead of picking.

## Example (made up)
You ask JARVIS to WhatsApp "Deepak from the gym". It searches your contacts for "Deepak" and finds two people, so it asks: "Deepak Nair or Deepak Shetty?". You say "Nair", and the draft gets his mobile number in full international form, with the plus sign and the country code. A week later you type a landline number without its country code for a draft: JARVIS reads it as Indian and the card says "Assumed India".

## How it works
`contacts_tools` gives the brain one read-only look-up, passing the tool gateway like every tool (`src/jarvis/contacts/tools.py`).
`ContactsClient` asks Google's People service for names, e-mail addresses and phone numbers only, and returns at most {{fact:src/jarvis/contacts/client.py:MAX_MATCHES}} matches with up to {{fact:src/jarvis/contacts/client.py:MAX_PHONES}} numbers and {{fact:src/jarvis/contacts/client.py:MAX_EMAILS}} addresses each.
Google's search needs warming up, so the client sends an empty warm-up search every {{fact:src/jarvis/contacts/client.py:WARM_TTL_S}} seconds, and a search that finds nothing straight after a warm-up waits {{fact:src/jarvis/contacts/client.py:COLD_RETRY_S}} seconds and asks once more (`src/jarvis/contacts/client.py`).
The whole look-up has a {{fact:src/jarvis/contacts/client.py:DEADLINE_S}}-second limit, and every answer is checked for shape before use (`ContactsClient`).
A contact's name is whatever that person or a synced profile says, so `fenced` hands it to the brain as outside text, and a result makes any later write in the same turn a card.
`to_e164` turns each number into full international form; a number with no country code is read as Indian, and `india_assumed` lets the card say so (`src/jarvis/contacts/phones.py`).
`typed_numbers` finds the numbers in your own words, written in the same form, so a draft knows whether you typed the number yourself.
The audit keeps only a hash of the name you asked for (`src/jarvis/contacts/tools.py`).

## What it costs
Nothing in rupees: it uses your own Google link and its Contacts grant (C29), and stores nothing but the time of the last warm-up (`src/jarvis/contacts/client.py`).

## When it fails
Without the Contacts grant it answers with how to grant it and asks Google nothing (`ContactsNotGranted`). With the People service switched off in the cloud project, the look-up says which switch to turn on, and numbers you type still work (`ContactsClient`). A search slower than its limit ends with "Google Contacts took too long to answer; try again shortly." No match means "No contact matches that name. Ask the owner for the number or the address." (`src/jarvis/contacts/tools.py`). A number that isn't a valid phone number is shown as not usable rather than guessed (`match_view`).
