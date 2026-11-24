---
page: pg_module_approvals
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/permissions.py": "42dc725d201a9c43"
  "src/jarvis/api/rows.py": "ce44ffbc96a4122c"
  "src/jarvis/api/settings_audit.py": "9dec959653ce2070"
  "src/jarvis/api/static/console-approvals.js": "78988c35de701d28"
  "src/jarvis/api/static/console-approve-all.js": "1cd7335bb2a31ec1"
  "src/jarvis/api/static/console-permissions.js": "eb3446689d3bd5f1"
  "src/jarvis/core/approve_all.py": "59f16ea07d5207c5"
  "src/jarvis/core/brain_decisions.py": "c952c68c5f5ad1d6"
  "src/jarvis/integrations/vault.py": "b766226c56672432"
  "src/jarvis/keyring.py": "78e7ac914cd81e85"
  "src/jarvis/storage/approvals.py": "0091801c464bb3d8"
  "src/jarvis/storage/audit.py": "d268e84d6aa87ab5"
  "src/jarvis/tools/audit.py": "adc1ede80eab2146"
  "src/jarvis/tools/background.py": "c4d540d4ab2f2eb3"
  "src/jarvis/tools/base.py": "536fcc183a0dbfca"
  "src/jarvis/tools/budget.py": "bb2f9659efef5175"
  "src/jarvis/tools/builtin.py": "589add2b3f1ba5c6"
  "src/jarvis/tools/calendar_cards.py": "d85a1179488c9292"
  "src/jarvis/tools/card.py": "5a9985efcfe0b89a"
  "src/jarvis/tools/context.py": "65275a1c84e715ec"
  "src/jarvis/tools/gateway.py": "e0d2f8d358fa8c13"
  "src/jarvis/tools/observers.py": "53e994d68acbd9fe"
  "src/jarvis/tools/policy.py": "fe617242ea0cc7c4"
  "src/jarvis/tools/r1_tools.py": "4d7f8f07d7292b33"
  "src/jarvis/tools/registry.py": "41c4ea0f5dade1a6"
  "src/jarvis/tools/reply_cards.py": "7a72a7250223da81"
  "src/jarvis/tools/setup.py": "b430d38a376cac97"
  "src/jarvis/tools/tasks_cards.py": "18cb6c64d784d443"
---
## In plain words
This module is JARVIS's conscience. Every action it takes for you passes one door, the tool gateway, which decides whether it may simply do it, must ask you first, or must refuse. When it asks, you see a card written by code, not by the AI, saying exactly what will happen, and you approve or decline. You choose per group of tools: Allow, Ask first or Never, and anything final, such as cancelling an event other people are invited to, always asks. With a passkey (your fingerprint or face on your own phone or laptop) those final cards need you in person. Every call lands in an audit trail where any later change would show.

## Example (made up)
Kiran types: "Add swimming on Saturday at 7 am, and cancel Friday's lunch with the Mehtas." JARVIS shows 2 cards. The swimming event is easy to undo, but the lunch has 4 guests whom Google will e-mail, so that card is final. He taps Approve all: swimming is added, and the reply says the lunch card still waits for its own approval. He taps it, his phone asks for his fingerprint, and the lunch is cancelled. The audit trail now holds 2 more entries, each linked to the one before it.

## How it works
Every tool call goes through `Gateway`, which checks the arguments; then `Policy` decides deny, ask or allow, and deny always wins (`src/jarvis/tools/policy.py`). An irreversible call always asks, and an allowed write becomes a card when it comes from a spoken turn or after other people's text, such as an e-mail or a web page, reached the brain (`src/jarvis/tools/gateway.py`). Your own choices per group of tools are saved with `PUT /v1/permissions`, which never accepts Allow for an irreversible group (`put_permissions`). A card's words come from code such as `create_card` and `delete_card`, and `one_line` strips hidden characters so nothing is smuggled into a card. `TurnBudget` lets one message propose at most {{fact:src/jarvis/tools/budget.py:MAX_NEW_CARDS}} new cards and make {{fact:src/jarvis/tools/budget.py:MAX_FREE_DELETES}} undoable deletes without one (`src/jarvis/tools/budget.py`). Waiting cards are kept by `DocApprovalStore`, so they survive the server going to sleep, and a decided card spends its token, so it never runs twice. When you approve, `approved` has the gateway look at the call again; if it would now do more than its card said, the card is withdrawn and a new one proposed. Approve all runs only undoable cards you listed, at most {{fact:src/jarvis/core/approve_all.py:MAX_IDS}}, each exactly as a single approval (`run`). With the passkey rule on, `passkey_challenge` asks your device to sign a one-time challenge for that card, and `ApprovalGuard` checks it before the token is spent. Your first passkey needs a fresh Google sign-in (`passkey_register_options`); later changes need a passkey themselves (`passkey_remove`). Each call becomes one `AuditEntry` with its tool, risk, outcome and a hash of its arguments, chained to the entry before by `entry_hash`, so `verify_window` spots any change. `Keyring` gives each kind of data its own key from one secret, so the key for notes never opens the vault, and `TokenCipher` seals with AES-256-GCM (`src/jarvis/integrations/vault.py`).

## What it costs
Nothing: passkeys run on your own phone or laptop, and the gateway, cards and audit trail are JARVIS's own code and records (`src/jarvis/tools/gateway.py`).

## When it fails
If your rules can't be read, or a call has no owner, nothing runs (`Gateway`). A final action is written to the audit trail before it runs; if that entry can't be written, nothing is done and you are told so (`src/jarvis/tools/gateway.py`). If your stored passkeys can't be read, the passkey rule counts as switched on (`src/jarvis/api/permissions.py`). A passkey reset takes effect only after a waiting period and is announced in your own inbox (`passkey_reset`). A wrong key or a tampered sealed record is refused, never guessed at (`TokenCipher`).
