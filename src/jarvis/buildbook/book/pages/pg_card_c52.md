---
page: pg_card_c52
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/permissions.py": "42dc725d201a9c43"
  "src/jarvis/api/rows.py": "ce44ffbc96a4122c"
  "src/jarvis/api/settings_audit.py": "9dec959653ce2070"
  "src/jarvis/api/static/console-permissions.js": "eb3446689d3bd5f1"
  "src/jarvis/permissions/__init__.py": "510511049c00348a"
  "src/jarvis/permissions/availability.py": "5208e7282127dd53"
  "src/jarvis/permissions/ceremony.py": "cdec19c471702f72"
  "src/jarvis/permissions/errors.py": "4d23c373369ba1cb"
  "src/jarvis/permissions/groups.py": "99a2940247d92ea1"
  "src/jarvis/permissions/models.py": "bca58e1d5d389311"
  "src/jarvis/permissions/notify.py": "5e89c30a0cf35e34"
  "src/jarvis/permissions/passkeys.py": "3f56a2944ccd1bf5"
  "src/jarvis/permissions/service.py": "92907281d5426e11"
  "src/jarvis/permissions/store.py": "124f378427b1cfb4"
---
## In plain words
This is where you decide how much JARVIS may do without asking. Each group of tools, such as reading your calendar, sending e-mail or getting a bill payment ready, offers a choice of Allow, Ask first or Never. A group whose actions can't be undone never offers Allow, so JARVIS always asks or refuses (`src/jarvis/permissions/groups.py`). On top of that you can add a passkey, the fingerprint or face check your phone or laptop already has, so that nothing irreversible happens without your own touch, even if someone gets into your Google sign-in (`src/jarvis/permissions/service.py`).

## Example (made up)
Anil sets "Send e-mail" to Ask first and "Read calendar" to Allow. A minute after signing in with Google again, he registers his laptop's fingerprint reader as a passkey. Next morning JARVIS drafts a reply to his landlord and shows a card. He taps Approve, touches the reader within the 2 minutes the check lasts, and the e-mail goes. That night someone with his stolen Google password asks JARVIS to remove all his passkeys. Nothing happens at once: the reset waits 24 hours, a notice lands in his inbox, and over breakfast Anil cancels it with his fingerprint.

## How it works
Each row in Approvals, Permissions is a `PermissionGroup` made of tool-name patterns, so a tool added later lands in the right row by itself (`src/jarvis/permissions/groups.py`).
`validate_choices` refuses Allow on an irreversible row before anything is saved, and `rules_for` drops such a choice if it was ever hand-edited into storage.
When one call matches more than one row, the strictest choice wins (`src/jarvis/permissions/groups.py`).
`PermissionsStore` keeps your choices in `permissions`; the tool gateway reads them on every call through a cache of {{fact:src/jarvis/permissions/store.py:CACHE_S}} seconds that a change refreshes at once, so a new Never applies to the very next call.
Each change is a transaction that bumps a revision number, so open tabs don't lose each other's edits (`src/jarvis/permissions/store.py`).
Passkeys use the browser's own support: `registration_options` and `verify_registration` set one up, `authentication_options` and `verify_assertion` check one, and only its public key is kept in `passkeys`.
Your first passkey needs a fresh Google sign-in in the browser; every later change, adding one, removing one or switching the rule off, needs a passkey check made for exactly that change (`PermissionsService`).
Each check is a single-use challenge in `webauthn_challenges`, and for an approval `approval_binding` ties it to that card's id, its exact arguments, the conversation and the tool.
A challenge is deleted as it is read, and the passkey's sign count must grow, so a copied answer is refused (`src/jarvis/permissions/passkeys.py`).
With the passkey rule on, the gateway lets an irreversible card run only after that check (`PermissionsService`).
If every passkey is lost, a fresh Google sign-in only starts a delayed reset that shows in the console, puts a notice in your Gmail inbox through `inbox_notifier`, and is cancelled by any passkey (`src/jarvis/permissions/service.py`).
Every change and every refused check goes into the audit chain, and `record_change` does the same for Drive folders and Home or Work.
`is_never` tells other settings screens when a row is Never, so they don't offer what every call would refuse (`src/jarvis/api/rows.py`).
`GET /v1/permissions` allows {{fact:src/jarvis/api/permissions.py:VIEW_PER_MINUTE}} reads a minute, changes {{fact:src/jarvis/api/permissions.py:CHANGE_PER_MINUTE}} and passkey steps {{fact:src/jarvis/api/permissions.py:CEREMONY_PER_MINUTE}} (`install_permissions`).

## What it costs
Nothing. Passkeys run in your own browser and device, and the checks run inside JARVIS with an open-source library (`src/jarvis/permissions/ceremony.py`). The only storage is a few small documents: your choices, at most {{fact:src/jarvis/permissions/passkeys.py:MAX_PASSKEYS}} public keys and challenges that last minutes (`src/jarvis/permissions/passkeys.py`).

## When it fails
If your stored passkeys can't be read, the passkey rule counts as on and irreversible actions are blocked until you reset (`PasskeyDataUnreadable`). If your choices can't be read, the gateway uses the last ones it saw, and with none it runs nothing (`src/jarvis/permissions/store.py`). A check that is too slow, used twice or made for another action is refused in plain words (`PasskeyRejected`). Without a public web address or Google sign-in, passkeys are off and the screen says why (`PasskeysUnavailable`). The terminal client can't use passkeys, so its approval of an irreversible card is refused while the rule is on (`PasskeyRequired`). If Gmail won't take the reset notice, the reset still goes ahead and the audit notes it (`inbox_notifier`).
