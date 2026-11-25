---
page: pg_chapter_example
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/api/activity.py": "039fe358ea1af9ad"
  "src/jarvis/api/permissions.py": "42dc725d201a9c43"
  "src/jarvis/api/rows.py": "ce44ffbc96a4122c"
  "src/jarvis/api/settings_audit.py": "9dec959653ce2070"
  "src/jarvis/api/static/console-activity.js": "531a9ab9aa75238e"
  "src/jarvis/api/static/console-approvals.js": "78988c35de701d28"
  "src/jarvis/api/static/console-approve-all.js": "1cd7335bb2a31ec1"
  "src/jarvis/api/static/console-permissions.js": "eb3446689d3bd5f1"
  "src/jarvis/api/static/console-voice-barge.js": "bf50083732d8c6e4"
  "src/jarvis/api/static/console-voice-capture.js": "09f45d685b4b5ea0"
  "src/jarvis/api/static/console-voice-commands.js": "5fce1e68f0de2831"
  "src/jarvis/api/static/console-voice-conversation.js": "a38e545b0e8e0fa3"
  "src/jarvis/api/static/console-voice-devices-match.js": "77d44118460dadc6"
  "src/jarvis/api/static/console-voice-devices-panel.js": "78cfb8b6c2809e36"
  "src/jarvis/api/static/console-voice-devices.js": "b4c87df5f59fe1b6"
  "src/jarvis/api/static/console-voice-loop-browser.js": "99b3682d4d1b3222"
  "src/jarvis/api/static/console-voice-loop-glue.js": "e7c4f4e36a17595a"
  "src/jarvis/api/static/console-voice-mic.js": "a0e90bc03322a5c8"
  "src/jarvis/api/static/console-voice-micoff.js": "08a923d63f6f93f2"
  "src/jarvis/api/static/console-voice-pace.js": "d455ab39738c612b"
  "src/jarvis/api/static/console-voice-phrases.js": "b45dc811d8b70af6"
  "src/jarvis/api/static/console-voice-speech.js": "3ac2e294edcc281c"
  "src/jarvis/api/static/console-voice-wake.js": "906de367b5e856ef"
  "src/jarvis/api/static/console-voice.js": "69224f06a0ee9c0e"
  "src/jarvis/api/static/console-wakeword.js": "f339e7c5c064c699"
  "src/jarvis/api/static/voice-capture-worklet.js": "4b1dbae36264b075"
  "src/jarvis/api/voice.py": "12fae33259cea1d6"
  "src/jarvis/core/approve_all.py": "59f16ea07d5207c5"
  "src/jarvis/core/brain.py": "976861b3c96f073a"
  "src/jarvis/core/brain_decisions.py": "01cc210182d5e7a3"
  "src/jarvis/core/brain_types.py": "fa3d9df28ac632ba"
  "src/jarvis/core/channel.py": "0c46ee25a780e41b"
  "src/jarvis/core/finish.py": "a5f2f201ead235f7"
  "src/jarvis/core/fixed_lines.py": "f7628651dff9b5b5"
  "src/jarvis/core/models.py": "b81cc65f474ac5d8"
  "src/jarvis/core/rounds.py": "f6a5203fab82caa5"
  "src/jarvis/core/saving.py": "c92f295af587766d"
  "src/jarvis/core/window.py": "06c365d979fdc3cf"
  "src/jarvis/llm/anthropic_provider.py": "60484f5c3cd11faf"
  "src/jarvis/llm/base.py": "8904b3d0d806dc4a"
  "src/jarvis/llm/brains.py": "a1fa670cdd1f62ae"
  "src/jarvis/llm/fallback.py": "785b07e24d85a2ff"
  "src/jarvis/llm/gemini_provider.py": "46855ef23dd8aabb"
  "src/jarvis/llm/local_provider.py": "aa111fafc89f4a46"
  "src/jarvis/llm/mock_provider.py": "e846975cd22e657f"
  "src/jarvis/llm/openai_compat_provider.py": "4d0317770f7ba34f"
  "src/jarvis/llm/pricing.py": "a2d1278419157236"
  "src/jarvis/llm/router.py": "c72db7b28cbba849"
  "src/jarvis/storage/approvals.py": "0091801c464bb3d8"
  "src/jarvis/storage/audit.py": "d268e84d6aa87ab5"
  "src/jarvis/tools/addresses.py": "7ebd4b775eca6e2a"
  "src/jarvis/tools/audit.py": "adc1ede80eab2146"
  "src/jarvis/tools/background.py": "c4d540d4ab2f2eb3"
  "src/jarvis/tools/base.py": "536fcc183a0dbfca"
  "src/jarvis/tools/budget.py": "bb2f9659efef5175"
  "src/jarvis/tools/builtin.py": "589add2b3f1ba5c6"
  "src/jarvis/tools/calendar_alerts.py": "9a4b67b7f2509a33"
  "src/jarvis/tools/calendar_cards.py": "d85a1179488c9292"
  "src/jarvis/tools/calendar_gather.py": "bb5900cc1d2b3878"
  "src/jarvis/tools/calendar_undo.py": "63f51a0c90832f7b"
  "src/jarvis/tools/card.py": "5a9985efcfe0b89a"
  "src/jarvis/tools/context.py": "65275a1c84e715ec"
  "src/jarvis/tools/gateway.py": "e0d2f8d358fa8c13"
  "src/jarvis/tools/google_calendar.py": "a296ba2d81650abd"
  "src/jarvis/tools/observers.py": "53e994d68acbd9fe"
  "src/jarvis/tools/policy.py": "fe617242ea0cc7c4"
  "src/jarvis/tools/r1_tools.py": "4d7f8f07d7292b33"
  "src/jarvis/tools/registry.py": "41c4ea0f5dade1a6"
  "src/jarvis/tools/reminders.py": "71b05fbd96e5a679"
  "src/jarvis/tools/reply_cards.py": "7a72a7250223da81"
  "src/jarvis/tools/setup.py": "b430d38a376cac97"
  "src/jarvis/tools/tasks_cards.py": "18cb6c64d784d443"
  "src/jarvis/voice/catalogue.py": "a7d5423e32e6e4ec"
  "src/jarvis/voice/commands.py": "f332fa895b7fb4d0"
  "src/jarvis/voice/google_cloud.py": "70b3d0637df4a58b"
  "src/jarvis/voice/service.py": "3bdab151205a517d"
  "src/jarvis/voice/settings.py": "d54739fc34d24078"
  "src/jarvis/voice/speakable.py": "ad9c138afcb8137b"
  "src/jarvis/voice/wav.py": "a96c3a9747fcada4"
---
## In plain words
This chapter follows one everyday request through the whole of JARVIS, so you see how the parts fit together. You tap the microphone and ask for a dentist appointment on Friday evening, and seconds later, once you approve, the event is in your calendar. Then you say "Cancel it", and the event goes, with a copy kept so one tap brings it back. On the way the request passes the voice, the brain, the tool gateway, an approval card, Google Calendar and the activity log; each has its own page with the details.

## Example (made up)
On Tuesday at 18:45 Meera taps the mic and says, "Add a dentist appointment on Friday at 5 pm." The console shows what it heard. A card appears: "Add event: Dentist appointment, Fri 27 Nov, 17:00 to 18:00". She taps Approve and JARVIS answers aloud, "Done, Ma'am. Dentist on Friday at 5." At 19:10 the clinic rings to move it, so she says "Cancel it". A second card asks first, she approves, and Activity shows the delete with an Undo button for the next 30 days.

## How it works
Your voice is captured by `src/jarvis/api/static/console-voice-capture.js` and sent to `transcribe`, where `GoogleSTT` turns it into text with the language code {{fact:settings.voice_language}}; without Google's voice the browser's own recogniser does it (`src/jarvis/api/static/console-voice-loop-browser.js`). The text reaches `Brain`, which loads the conversation, adds what JARVIS remembers, and asks the router for the {{fact:settings.default_tier}} tier, {{fact:settings.model_balanced}} unless you picked another brain (`src/jarvis/llm/router.py`). The brain doesn't act by itself: it answers with a request to use the calendar tool from `calendar_tools`, with the day and time filled in (`parse_when`). Every tool call passes `Gateway`, which checks your rules for that group of tools. Because the request was spoken, the gateway asks first even where your rule says Allow, since someone else in the room might have said it (`src/jarvis/tools/gateway.py`). `create_card` writes the card's words in code, never the AI, and `src/jarvis/api/static/console-approvals.js` shows it with Approve and Decline. An event with guests would send invitations that are impossible to recall, so it always asks and, with the passkey rule on, needs your passkey (`ApprovalGuard`). On your approval the event goes into Google Calendar and the call into the append-only audit trail; the reply is shown and, for a spoken question, read aloud by `speak` once `speakable` has cleaned it. For "Cancel it", `delete_risk` finds the event undoable, `delete_card` asks first because it was spoken, and `delete_kept` keeps a copy before Google deletes it (`src/jarvis/tools/calendar_undo.py`). The activity log, served by `activity`, shows each step in plain words, and the Undo button brings the event back through `CalendarRestorer`. One message may propose at most {{fact:src/jarvis/tools/budget.py:MAX_NEW_CARDS}} new cards and make {{fact:src/jarvis/tools/budget.py:MAX_FREE_DELETES}} undoable deletes without one (`TurnBudget`).

## What it costs
A couple of brain replies at the {{fact:settings.default_tier}} tier, counted in rupees against your monthly limit, plus a few seconds of listening and speech inside the free voice allowance (`src/jarvis/voice/google_cloud.py`). Had you picked a brain whose model has no known price, each reply would be marked "price unknown", never ₹0, and counted against your limit at the dearest price JARVIS knows (`unpriced`, `dearest`). The calendar, the cards, the audit trail and the activity log cost nothing (`src/jarvis/tools/gateway.py`).

## When it fails
A blocked microphone gets a plain line on how to allow it, and typed chat still works (`src/jarvis/api/static/console-voice-capture.js`). If Google's speech is off, the browser's own voice and recogniser take over (`src/jarvis/api/static/console-voice.js`). At your monthly limit no paid call is made, and the reply says so (`src/jarvis/core/brain.py`). If the event changed after its card was shown, for instance it gained guests, the card is withdrawn and a new one proposed (`src/jarvis/core/brain_decisions.py`). If the copy can't be kept, the event is not deleted (`delete_kept`).
