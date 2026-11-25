---
page: pg_service_google_sign_in
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/auth.py": "02a9e121c2585fd8"
  "src/jarvis/api/scheduler_auth.py": "346bb43278c2d8f2"
  "src/jarvis/config.py": "e223e4b9e6e6333b"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
---
## In plain words
Google sign-in is how you prove to JARVIS that you are you. You press "Sign in with Google", Google checks your password and phone as usual, and tells JARVIS which e-mail address signed in. Google only says who you are; JARVIS decides who may enter, and only the owner addresses on its list get in. The same Google service links your account for the tools (calendar, mail, to-dos) through a second, separate permission screen, and it checks that the clock calls JARVIS gets really come from Google. What Google learns is that you signed in to JARVIS; JARVIS asks Google for your e-mail address and nothing else at sign-in.

## Example (made up)
On a new laptop you open JARVIS at 8:30 and press Sign in. Google asks you to pick your account and confirm on your phone. JARVIS checks the address is on its owner list and opens the console. A friend who tries the same with his own Google account sees "This JARVIS belongs to someone else."

## How it works
`build_oauth` sets up Google sign-in asking only for your identity and e-mail, with Google's account picker and PKCE protection, using `google_client_id` and `google_client_secret` (`src/jarvis/api/auth.py`). `GET /auth/login` sends you to Google, and `GET /auth/callback` takes Google's answer: the address must be verified by Google and listed in `owner_emails`, or the sign-in is refused (`callback`). JARVIS then gives your browser a signed session cookie that lasts `session_cookie_max_age_s` ({{fact:settings.session_cookie_max_age_s}} seconds) while you use it, and never more than {{fact:src/jarvis/api/auth.py:SESSION_ABSOLUTE_MAX_S}} seconds in all (`session_email`). Every request checks the owner list again, so removing an address logs that browser out at once (`session_email`). A change sent from the browser must carry JARVIS's own header, so another website can't act for you (`require_auth`). For sensitive steps such as a first passkey, `GET /auth/login` asks Google to check you again, and that fresh sign-in counts for {{fact:src/jarvis/api/auth.py:FRESH_SIGN_IN_S}} seconds (`fresh_sign_in_left`). With `reauth_requires_auth_time` on, that re-check counts only if Google confirms the time it asked (`_reauth_at`). The clock's calls are proven differently: `GoogleOIDCVerifier` checks a token signed by Google against Google's published keys, for one exact address and account (`src/jarvis/api/scheduler_auth.py`). The tools' link is a second client with its own permissions (`src/jarvis/integrations/google.py:register_tools_oauth`).

## What it costs
Nothing in rupees: Google sign-in is free.

## When it fails
A Google account that is not on the owner list sees "This JARVIS belongs to someone else." (`callback`). If the sign-in itself breaks, JARVIS says it could not be completed and to try again, with no detail from Google. Without the client id, the secret, the public address or an owner, the server refuses to start in Google sign-in mode (`src/jarvis/config.py:Settings`). After the absolute time, you simply sign in again. `POST /auth/logout` ends the session.
