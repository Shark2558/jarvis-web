---
page: pg_card_c31
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/tools/gmail.py": "b20d7099344ef32a"
  "src/jarvis/tools/gmail_digest.py": "4f0089a3d92bebcd"
  "src/jarvis/tools/gmail_mime.py": "7096ad94b71e768a"
---
## In plain words
JARVIS searches and reads your Gmail, writes drafts, and sends mail only after you approve each send with your passkey. Ask "read my unread mail" and you get a short spoken round-up: who wrote, about what, and the first line, with codes, bank messages and long numbers kept out of anything said aloud. What other people wrote in their mail is treated as something to read, never as orders for JARVIS.

## Example (made up)
At 7:40 am, making tea, you ask "anything new in my mail?". JARVIS says: "Six unread in the last week. People: Suresh, about Saturday's cricket, two hours ago. Bills and orders: your broadband bill. One message withheld — it looks like a code or bank message." You then say "reply to Suresh that I'm in". Suresh's address came from his own mail rather than from your words, so JARVIS shows a draft card first; sending it later needs your approval and passkey.

## How it works
`gmail_tools` offers a search, a read, a draft and a send, each through the tool gateway (`src/jarvis/tools/gmail.py`).
A search returns at most {{fact:src/jarvis/tools/gmail.py:MAX_RESULTS}} messages with sender, date, subject and a short snippet, never whole bodies, and a read cuts the body to {{fact:src/jarvis/tools/gmail.py:BODY_LIMIT}} characters and lists attachments by name and size without opening them (`GmailAPI`).
Mail text reaches the brain fenced as outside content, and HTML mail is turned into plain text first (`html_to_text`).
A draft is saved without asking only when every recipient is an address you typed in this very message; an address taken from a mail, a page or memory makes it a card first (`src/jarvis/tools/gmail.py`).
A send is irreversible: its card shows every recipient, the subject, the start of the body and whether it replies in a thread, and it always needs your passkey (`GmailAPI`).
`build_raw_message` writes the outgoing message, and `check_header_value` refuses a subject or address that would sneak in extra header lines (`src/jarvis/tools/gmail_mime.py`).
`digest_tools` gives the unread round-up: metadata and Gmail's own snippet only, at most {{fact:src/jarvis/tools/gmail_digest.py:MAX_ITEMS}} items with sender, subject and a first line of up to {{fact:src/jarvis/tools/gmail_digest.py:FIRST_LINE}} characters (`src/jarvis/tools/gmail_digest.py`).
Anything that looks like a code, a card, an account or an ID is withheld, so the brain gets only a count, never the text (`withheld`).
`read_inbox` covers the whole inbox: the exact unread count, then the newest unread of the last {{fact:src/jarvis/tools/gmail_digest.py:WINDOW_DAYS}} days in every tab, at most `mail_summary_max_reads` messages, grouped into people, bills and orders, updates, and promotions and social as counts (`Inbox`).
A message listed but not read is counted and said, never taken for a quiet inbox (`summary_of`).

## What it costs
Nothing in rupees: it uses your own Google link (C29) and keeps no data of its own, because mail stays in Gmail (`GmailAPI`). Answering about mail is a normal brain reply on your AI bill (C54).

## When it fails
Mail text never becomes an instruction: it is fenced as other people's words (`src/jarvis/tools/gmail.py`). On Telegram, mail reads stay off unless you switch them on there (C04). A Google error becomes a short plain message, and an unlinked account answers "Google is not connected" (C29). A message the round-up could not read is said as "couldn't read" with a count rather than hidden (`read_inbox`).
