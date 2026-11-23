---
page: pg_service_github
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/integrations/github.py": "adc322d129055173"
---
## In plain words
GitHub is where code projects live. If you have an account there, JARVIS reads it for you, read-only: your profile, your projects sorted by the latest change, and your recent activity. You connect it once by pasting a GitHub token in the Connectors panel, never in the chat. What goes to GitHub is only that token, sent with each read; nothing of yours is written there. The token is stored sealed with JARVIS's own key, so the database never holds it in plain text (`src/jarvis/integrations/github.py:GithubStore`).

## Example (made up)
You paste a read-only token at 21:10. JARVIS checks it with one read of your profile and shows "Connected as riverfox". Later you ask: "Which of my projects changed this week?" JARVIS reads your ten latest projects and answers that two changed, one on Monday and one on Thursday. The Vitals board shows the token's calls this hour, 3 of 5,000.

## How it works
`GithubClient` calls only GitHub's API address, over HTTPS, with reads only, no redirects, a deadline and a size cap of {{fact:src/jarvis/integrations/github.py:MAX_RESPONSE_BYTES}} bytes (`src/jarvis/integrations/github.py`). `token_ok` refuses anything that doesn't look like a token, up to {{fact:src/jarvis/integrations/github.py:MAX_TOKEN_CHARS}} characters, and connecting reads your profile once to prove the token works. `GithubStore` seals the token and your login with the keyring's connectors key, and a record that no longer opens asks you to reconnect, with `GithubNeedsReconnect`, rather than saying "not connected". Lists ask for {{fact:src/jarvis/integrations/github.py:DEFAULT_ITEMS}} items by default and never more than {{fact:src/jarvis/integrations/github.py:MAX_ITEMS}} (`GithubClient`). What GitHub returns about a project is other people's words, so each field is cut to one clean line of at most {{fact:src/jarvis/integrations/github.py:FIELD_LIMIT}} characters (`_text`), and only links on GitHub's own site are kept (`_own_url`). GitHub's answers carry the token's expiry and hourly limit, which `GithubClient` stores for the Vitals board. A token with no stored limits is asked about once, through GitHub's free rate-limit read, at most every {{fact:src/jarvis/integrations/github.py:FACTS_EVERY_S}} seconds; the mark is written before the read, so a restart doesn't read again (`facts_recent`). `_status_error` turns each refusal into plain words, never GitHub's text and never the token.

## What it costs
Nothing in rupees: reading your own GitHub with your token is free. GitHub's hourly rate limit for the token applies, and the Vitals board shows how much of it is used.

## When it fails
Before you connect, JARVIS says GitHub is not connected yet and points to the Connectors panel. A revoked or deleted token gives "GitHub refused the token: make a new one and connect again", and Vitals shows it in red (`_status_error`). A spent hourly limit says to try again later; a token without read access to something says so. A GitHub outage, a timeout or an unreadable answer each give one short sentence (`GithubError`). A server without the encryption key leaves GitHub off.
