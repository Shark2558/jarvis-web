---
page: pg_screen_vitals
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/static/console-vitals.js": "dd7cc4ee3cec2353"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
  "src/jarvis/vitals/api.py": "ed0a191b7a2b3219"
---
## In plain words
Vitals is JARVIS's health and money page. At the top it shows how quickly replies arrive, then "This month": what the paid AI has cost so far in rupees and the monthly limit you set. Below that is a board of everything JARVIS keeps an eye on, its keys and connections, free allowances and bills, each with a plain status: OK, Watch, Act now or Unknown. You add your own renewals too. The last line says which version of JARVIS is running and when it was built (`src/jarvis/api/static/console-vitals.js`). A "Calls this month" line shows what phone calls have cost this month, and pressing its name opens the Calls panel (`calls`).

## Example (made up)
On the 20th you open Vitals. The tiles show the last reply took 1.8 s and the average is 2.4 s. "This month" reads ≈ ₹212 of your ₹300 limit. On the board, the Google link says OK, the web search allowance says Watch with "612 of 900 used", and a bill you track yourself, the domain renewal, says Act now because it expires in 5 days. You press Set limit, type 400, and a window asks you to confirm raising it before it is saved.

## How it works
The tiles, the latency line and the list of the brain, the last model, this conversation's cost and the audit chain are filled in as you chat (`src/jarvis/api/static/console.html`). Under "This conversation", "Calls this month" shows the rupees your `calls` records say calls have used this month and the calls cap, or a dash when they can't be read; its name is a link to the Calls panel, the way in on a screen whose tab bar has no room for Calls (`src/jarvis/api/static/console.html`). "This month" shows the paid AI's spend and your limit; Set limit opens a box for whole rupees, and lowering the limit saves at once while raising or removing it asks you first (`src/jarvis/api/static/console.html`). The board comes from `GET /v1/vitals`, which gathers every key, allowance and bill JARVIS watches with its status, usage, dates and, when one needs you, the reason and what to do (`src/jarvis/vitals/api.py:board`). Its spend part also carries the month's replies with no known price, counted at an upper estimate and never as ₹0 (`GET /v1/vitals`). The board groups them under "Keys & connections", "Allowances & quotas" and "Bills", with the worst first, and shows each status in words, never colour alone (`src/jarvis/api/static/console-vitals.js`). "Track something JARVIS can't see" adds your own item with a name, a limit and a date through `PUT /v1/vitals/keys`, and Stop tracking removes it with `DELETE /v1/vitals/keys/{pid}` (`src/jarvis/vitals/api.py:put_key`). JARVIS never asks for a key's value there, and refuses one if pasted (`src/jarvis/api/static/console-vitals.js`). The "About JARVIS" line takes the version and build date from the same answer (`GET /v1/vitals`).

## What it costs
Looking at Vitals costs nothing: it reads JARVIS's own counters and a few outside dashboards (`src/jarvis/vitals/api.py`). The rupee figures are estimates, because Anthropic bills in US dollars and your bank converts (`src/jarvis/api/static/console.html`). The limit is checked before each paid reply, so one reply may go a little over it (`src/jarvis/api/static/console.html`).

## When it fails
If Vitals is not set up on the server, the board says it is not available. If an outside service doesn't answer, its chip says Unknown; GitHub's row says "GitHub didn't answer; press Refresh." If your own tracked items are out of reach just then, the board says so and the rest still shows (`src/jarvis/api/static/console-vitals.js`). Reading the board is limited to {{fact:src/jarvis/vitals/api.py:GET_PER_MINUTE}} times a minute and changes to {{fact:src/jarvis/vitals/api.py:WRITE_PER_MINUTE}}.
