---
page: pg_card_c75
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/calls_ws.py": "1963a0a1fef6419e"
  "src/jarvis/api/static/calls-listen-worklet.js": "652d3339bf8b5fa9"
  "src/jarvis/api/static/console-calls-audio.js": "4d3e16c6b71d771e"
  "src/jarvis/api/static/console-calls-live.js": "b6559fad283919fe"
  "src/jarvis/calls/brain.py": "f741c4f2234f0b37"
  "src/jarvis/calls/captions.py": "8a531f5a22e1a8b7"
  "src/jarvis/calls/engine.py": "5cf42570e813ff4b"
  "src/jarvis/calls/engine_ports.py": "366a3fcfbd2253a0"
  "src/jarvis/calls/engine_turns.py": "e3dd50d216e63efb"
  "src/jarvis/calls/engine_voice.py": "cac890f0a4d3bff9"
  "src/jarvis/calls/guard.py": "d300d7c800d4f2c2"
  "src/jarvis/calls/hub.py": "436e3b281b7c1603"
  "src/jarvis/calls/join.py": "f68ef2ff854983c4"
  "src/jarvis/calls/live.py": "8b4d2ae45dacb29b"
  "src/jarvis/calls/protocol.py": "3bc2ebd613b92b89"
  "src/jarvis/calls/summary.py": "ad280e3f27d4930f"
  "tests/test_calls_engine.py": "ad38764f0b3f5a8d"
  "tests/test_calls_guard.py": "050f3e56e8305335"
  "tests/test_calls_hub_ws.py": "0823049bca06b82e"
---
## In plain words
This is the part that runs a call while it is on. It holds one call at a time, in memory, and takes it through its steps: the ready check, the dial, JARVIS's opening words saying it is an AI assistant calling for you and that the call is recorded, the conversation, and the wrap-up with an English summary (`src/jarvis/calls/engine.py`). It never dials on its own and never redials: trying again is a new card and a new tap from you (`CallSession`). While the call is on you can listen live to both sides with English captions, follow the captions only, take over, tell JARVIS something the other person doesn't hear, or hang up, from the Calls panel or the console in your phone's browser (`src/jarvis/calls/live.py`).

## Example (made up)
JARVIS calls the clinic for Leela. The receptionist answers in Tamil, which the card allows, so JARVIS speaks Tamil from its next sentence. Leela opens the call and presses Listen live: she hears both sides, with English captions underneath. Asked for a card number, JARVIS says "I will check with Leela and call back." Leela types "ask for Saturday instead" in Tell JARVIS; the receptionist offers Saturday at 11, inside the card's window, and JARVIS repeats it back. Then Leela presses Take over to say thank you herself.

## How it works
`CallHub` holds one call at a time, so a second gets "A call is already on: one call at a time."; it starts the call your approval asked for, takes the phone's events and the desk's sound, and keeps the live listeners (`src/jarvis/calls/hub.py`). A call runs as a state machine: preparing (the ready check, the desk's prepare and the dial gate, which spends your approval for that call), dialling, opening, talking or taken over, wrapping up, then ended, no answer or failed (`CallSession`). Each turn hears the other person in the call's language; when the hearing is unsure the language is detected, and another language the card allows takes over once the detector is {{fact:src/jarvis/calls/engine_turns.py:SWITCH_CONFIDENCE}} sure, while one it doesn't allow gets a polite line in English and Hindi (`Turns`). The brain makes one fast-tier call a turn with no tools: its reply is one JSON document whose actions the engine carries out in code, and the other person's words sit inside tags they can't close (`src/jarvis/calls/brain.py`). Every line passes `check_reply` before it is spoken: a run of {{fact:src/jarvis/calls/guard.py:MIN_SECRET_DIGITS}} or more digits, in any script or as number words, unless it is on the card or the other person said it (at most {{fact:src/jarvis/calls/guard.py:MAX_ECHO_DIGITS}} digits), PAN, IFSC, e-mail, UPI and link shapes, and agreeing to pay are refused, and JARVIS says it will check with you and call back instead. JARVIS's voice goes to the desk a little ahead of real time and stops at the next chunk when the other person talks over it (`CallVoice`). Listen live mixes both sides into one stream and sends it only after you ask, since Captions only is the default (`Mixer`). A caption is the English line itself, else the brain's own English, else one fast-tier translation (`Captioner`). Take over makes JARVIS say one handover line and go quiet, gives your microphone back at the laptop and, pressed in the phone's browser, also asks the phone to move the call's sound; the recording carries on (`src/jarvis/api/calls_ws.py`). Tell JARVIS takes at most {{fact:src/jarvis/api/calls_ws.py:TELLS_PER_MINUTE}} lines a minute and never widens the card (`src/jarvis/calls/brain.py`). If the other person objects to the recording, it stops and what was kept is dropped (`Turns`). Afterwards `Summarizer` writes the English summary.

## What it costs
Each turn is one fast-tier brain call, and the summary one more; a caption costs a call only when a line needs translating (`Captioner`). Every rupee is added to the call's record and held to the call's own cap and the month's calls cap: at a cap JARVIS says goodbye and ends (`src/jarvis/calls/engine.py`). A brain whose maker may train on what it is sent is never used for calls (`NoPrivateBrain`).

## When it fails
If the desk or the phone is lost, the call wraps up (`src/jarvis/calls/engine.py`). The brain failing {{fact:src/jarvis/calls/engine_turns.py:MAX_BRAIN_FAILURES}} times brings the check-back line and the end, and a language the card doesn't allow, heard {{fact:src/jarvis/calls/engine_turns.py:MAX_UNSUPPORTED}} times, ends the call (`Turns`). A dial the phone couldn't place ends the call at once (`HubPhoneSink`). A live listener too far behind is closed and may reconnect, losing audio first, and {{fact:src/jarvis/api/calls_ws.py:MAX_BAD_LIVE}} malformed live messages close it (`src/jarvis/calls/live.py`). A summary the model can't make is written plainly from the outcome (`Summarizer`). A restart ends any call in memory, and no approval is left to dial on (`CallHub`).
