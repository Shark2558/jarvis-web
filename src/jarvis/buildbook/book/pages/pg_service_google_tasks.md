---
page: pg_service_google_tasks
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "3d154bdd78268162"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
  "src/jarvis/tools/tasks_api.py": "e6481d1913414507"
---
## In plain words
Google Tasks is the to-do list in your Google account, the same one you see in Gmail and Calendar. JARVIS uses it as your to-do list: it lists, adds, changes, completes and deletes to-dos, with undo, and the morning brief shows what is due. The Groceries list lives there too, and the helpers read it for what is pending. It is an extra permission you grant once in Integrations. What goes to Google is each change you ask for and the reads of your lists. A to-do JARVIS wrote from outside content, such as a mail, is marked so it is never later treated as your own words.

## Example (made up)
At 20:10 you say: "Add 'renew car insurance' for Friday, and tick off 'buy printer ink'." JARVIS adds the first to your default list with Friday as its due date and marks the second done. The next morning the brief says one to-do is due on Friday.

## How it works
`TasksClient` is the one client the to-do tools and the morning brief share, and every call goes through `GoogleConnector` with its timeout of {{fact:src/jarvis/integrations/google.py:HTTP_TIMEOUT_S}} seconds (`src/jarvis/tools/tasks_api.py`). It first checks that your link holds the Tasks permission, which must allow changes, not only reads (`can_use_tasks`). Google keeps only the date of a to-do, never a time, so `due_to_api` sends a plain date and `date_of` reads it back without any time-zone shift. A due date that comes with a time of day is read in your own time zone and the time is dropped (`parse_due`). Reads are bounded: at most {{fact:src/jarvis/tools/tasks_api.py:MAX_LISTS}} lists, pages of {{fact:src/jarvis/tools/tasks_api.py:PAGE_SIZE}} to-dos, {{fact:src/jarvis/tools/tasks_api.py:PAGES_PER_LIST}} pages a list, and past that the brief says "at least" (`DueScan`). A title may be at most {{fact:src/jarvis/tools/tasks_api.py:TITLE_MAX}} characters and notes at most {{fact:src/jarvis/tools/tasks_api.py:NOTES_MAX}}, as Google allows (`TasksClient`). Every id is checked before it goes into an address, so an id can never point anywhere else (`valid_task_id`).

## What it costs
Nothing in rupees: Google charges nothing for Tasks calls. Google's daily quotas apply. Unverified: the exact quota numbers for your project.

## When it fails
Without the permission, JARVIS says it has no permission for your to-do list yet and tells you to press Grant next to "To-do list" in Integrations (`TasksNotGranted`). If the Tasks service is switched off in your Google project, it says so and how to switch it on (`TasksServiceOff`). Not linked, or a link Google stopped accepting, asks you to connect or reconnect Google. A to-do that is already gone is reported as gone.
