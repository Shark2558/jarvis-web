---
page: pg_card_c22
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-whatsapp.js": "47858cdee58c9c9a"
  "src/jarvis/whatsapp/__init__.py": "2c6127ccd3a8f1dc"
  "src/jarvis/whatsapp/draft.py": "bd100390f46e3924"
  "src/jarvis/whatsapp/joining.py": "51980f85dbae36d6"
  "src/jarvis/whatsapp/pictographic.py": "1b5f10bcf89ca927"
  "src/jarvis/whatsapp/provenance.py": "d63df38ef6ac9776"
  "src/jarvis/whatsapp/restore.py": "cfbb0e2e7ae4d3c5"
  "src/jarvis/whatsapp/tools.py": "41279701513f70ea"
  "src/jarvis/whatsapp/zwj_sequences.py": "58f6b49f96b9a9ad"
---
## In plain words
JARVIS writes WhatsApp messages for you but never sends them. It shows a card with the person's name and number, the whole message and an Open in WhatsApp button; you read it, tap, and press Send in your own WhatsApp. Give it a name and it finds the number in your Google Contacts; when more than one person or number fits, it asks you which one rather than guessing.

## Example (made up)
You type "WhatsApp Arjun that I'll be 15 minutes late". Contacts holds one Arjun Pillai with one mobile number, so the reply carries a card: his name and number, the text "Running about 15 minutes late, sorry!" and Open in WhatsApp. You tap it, WhatsApp opens with the message ready, and you press Send. Had Contacts held two Arjuns, JARVIS would have asked which one and made no draft.

## How it works
`whatsapp_tools` gives the brain one tool, a draft with a recipient and a text, and it runs as a read-only tool through the gateway because nothing leaves JARVIS (`src/jarvis/whatsapp/tools.py`).
`recipient_arg` reads the recipient: with {{fact:src/jarvis/whatsapp/tools.py:NUMBERISH_DIGITS}} or more digits it is a phone number in full international form, and a number without a country code is read as Indian, with "Assumed India" on the card.
Otherwise it is a name looked up in Contacts, so your Contacts permission applies too; one contact with one number is used, and anything more comes back as a list the brain must ask you about (`WhatsAppDrafts`).
`clean_text` keeps the message as written, Malayalam joiners and emoji included, but strips characters that hide or reorder what you see, and refuses an empty text or one over {{fact:src/jarvis/whatsapp/draft.py:TEXT_MAX}} characters (`src/jarvis/whatsapp/draft.py`). More than {{fact:src/jarvis/whatsapp/draft.py:MAX_MARKS}} accent marks stacked on one letter are refused too, because they smear what the text says (`stacked`).
`number_source` checks where the number came from: typed by you, or shown by Contacts. Any other number, say one found in an e-mail, puts a warning line on the card (`src/jarvis/whatsapp/provenance.py`).
`draft_card` builds the card and its link from the checked number and text alone, so the link carries exactly the text you see (`wa_link`).
If you spoke the request, or the turn had read an e-mail or a web page, JARVIS asks first on a card that quotes every line of the text (`src/jarvis/whatsapp/tools.py`).
`src/jarvis/api/static/console-whatsapp.js` draws the card, rebuilds the link the same way and drops any card that does not match it.
When you reopen a conversation, `stored_drafts` rebuilds its draft cards from what the conversation already holds, skipping any that no longer pass the checks.

## What it costs
Nothing: no rupees, and JARVIS calls no WhatsApp service at all, because your own WhatsApp opens the link (`src/jarvis/whatsapp/tools.py`). It keeps no data of its own: drafts live inside the conversation (`sessions`).

## When it fails
Several contacts or numbers: JARVIS asks which one and makes no draft (`WhatsAppDrafts`). A name with no number in Contacts, or Contacts not granted, ends with JARVIS asking you for the number, and without a Google link only numbers work (`whatsapp_tools`). A smeared text gets "That text has stacked accent marks I can't show clearly; please retype it." (`stacked`). A card that fails any check is dropped, never shown half-right (`src/jarvis/api/static/console-whatsapp.js`).
