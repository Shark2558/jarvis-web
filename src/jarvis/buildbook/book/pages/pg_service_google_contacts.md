---
page: pg_service_google_contacts
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/contacts/client.py": "afe0a7932af3d7aa"
  "src/jarvis/helpers/today/birthdays.py": "d69fe6eb17bd801f"
---
## In plain words
Google Contacts is the address book in your Google account. JARVIS reads it, never changes it, to find a person's phone number or e-mail address when you ask for a WhatsApp draft or a mail, and the helpers read it for birthdays. It is an extra permission you grant once in Integrations, read-only. What goes to Google is the name you ask about, or a request for the birthday list; JARVIS stores nothing about your contacts. For birthdays it takes only the month and the day: a birth year is never read, kept or shown.

## Example (made up)
You say: "Draft a WhatsApp to Ravi: running ten minutes late." JARVIS searches your contacts for "Ravi", finds two matches, and asks which one: Ravi at the office or Ravi from cricket. You pick the second, and the draft opens with his number. On 14 March at 9:00 the helpers remind you it is Meera's birthday today.

## How it works
`ContactsClient` searches your contacts through `GoogleConnector`, with one overall deadline of {{fact:src/jarvis/contacts/client.py:DEADLINE_S}} seconds, after checking that your link holds the Contacts permission (`src/jarvis/contacts/client.py`). It asks only for names, e-mail addresses and phone numbers, and keeps at most {{fact:src/jarvis/contacts/client.py:MAX_MATCHES}} matches, each with at most {{fact:src/jarvis/contacts/client.py:MAX_EMAILS}} addresses and {{fact:src/jarvis/contacts/client.py:MAX_PHONES}} numbers (`contact_of`). Google's search warms up slowly, so `ContactsClient` warms it once every {{fact:src/jarvis/contacts/client.py:WARM_TTL_S}} seconds and, if a search right after a warm-up finds nothing, waits {{fact:src/jarvis/contacts/client.py:COLD_RETRY_S}} seconds and asks once more. A contact's name is other people's words, so `_name` makes it one clean line, and the tools fence it before the brain sees it. `BirthdayReader` reads your contacts' names and birthdays at most {{fact:src/jarvis/helpers/today/birthdays.py:MAX_PAGES}} pages of {{fact:src/jarvis/helpers/today/birthdays.py:PAGE_SIZE}}, about once a day, and keeps that day's reading in memory only (`src/jarvis/helpers/today/birthdays.py`). `_month_day` takes only the month and the day, and the year is never read. Each background read follows your permission row for Contacts: on "Never" or an unreadable row nothing is read (`row_allows`).

## What it costs
Nothing in rupees: Google charges nothing for Contacts calls. Google's daily quotas apply. Unverified: the exact quota numbers for your project.

## When it fails
Without the permission, JARVIS says it has no permission to look up your contacts yet and to press Grant next to "Contacts" in Integrations (`ContactsNotGranted`). If the People service is off in your Google project, it says so and how to switch it on. A slow Google gives "Google Contacts took too long to answer" (`src/jarvis/contacts/client.py`). A paused birthday read says why in one fixed line, such as your Contacts permission being set to Ask first (`denied_note`). A number you type yourself still works.
