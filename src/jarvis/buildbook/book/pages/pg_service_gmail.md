---
page: pg_service_gmail
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/brief/deliver.py": "b961684f4ad40dc0"
  "src/jarvis/config.py": "3d154bdd78268162"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
  "src/jarvis/tools/gmail.py": "b20d7099344ef32a"
---
## In plain words
Gmail is your Google e-mail. Through your Google link, JARVIS searches and reads your mail, counts what is unread in your inbox, writes drafts, and sends a message only after you approve it on a card. The morning brief puts its own copy in your inbox, and some helpers read mail you allow, such as e-mailed receipts and breach notices. What goes to Google is each request: a search, the message JARVIS opens, a draft or a mail you approved. What comes back is treated as outside content, never as orders: a mail can't make JARVIS do anything (`src/jarvis/tools/gmail.py:GmailAPI`).

## Example (made up)
At 9:15 you ask: "Did the plumber reply about Saturday?" JARVIS searches your mail, opens the one reply and tells you he can come at 11. You say "Reply that 11 is fine." JARVIS shows a card with the recipient, the subject and the first lines; you approve, and the reply goes out in the same thread.

## How it works
`gmail_tools` gives JARVIS four tools: search and read, which only read; save a draft, which changes nothing outside your mailbox; and send, which is irreversible and always needs your approval, with no "don't ask again" (`src/jarvis/tools/gmail.py`). A search returns at most {{fact:src/jarvis/tools/gmail.py:MAX_RESULTS}} messages with sender, date, subject and a short snippet, never whole bodies (`GmailAPI`). Reading one message gives its text cut at {{fact:src/jarvis/tools/gmail.py:BODY_LIMIT}} characters and the names and sizes of its attachments, which are never fetched (`_attachments`). Names and attachment names other people wrote are fenced as outside content before the brain sees them (`_people`). A draft asks first unless every recipient is an address you typed in that message (`_untyped_recipient`). The send card shows every recipient, the subject, the first {{fact:src/jarvis/tools/gmail.py:CARD_BODY_LIMIT}} characters of the body and whether it replies in a thread (`_compose_card`). On a voice or Telegram turn, text that looks like a code or a bank message is withheld, and numbers and links are masked (`_heard`). The brief's copy goes into your own inbox with Gmail's insert, which has no recipient, at most once a day and never retried (`src/jarvis/brief/deliver.py:InboxDelivery`). Every call goes through `GoogleConnector`, with a timeout of {{fact:src/jarvis/integrations/google.py:HTTP_TIMEOUT_S}} seconds, and only reads are ever tried twice.

## What it costs
Nothing in rupees: Google charges nothing for Gmail calls. Google's daily quotas apply. Unverified: the exact quota numbers for your project. The inbox summary reads at most `mail_summary_max_reads` ({{fact:settings.mail_summary_max_reads}}) messages (`mail_summary_max_reads`).

## When it fails
Not linked: JARVIS says Google is not connected and points to Integrations; a link Google stopped accepting asks you to reconnect (`GoogleNotConnected`). Without the inbox permission, the brief stays in the console and is not put in your inbox (`can_insert`). A Google error becomes one short sentence in JARVIS's own words. A send that got no answer from Google is never repeated, so a mail is never sent twice.
