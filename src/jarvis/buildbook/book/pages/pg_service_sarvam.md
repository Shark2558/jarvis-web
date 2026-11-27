---
page: pg_service_sarvam
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/calls/prices.py": "09530bc93cd5d9f2"
  "src/jarvis/calls/speech/build.py": "2c70d34548a1d131"
  "src/jarvis/calls/speech/sarvam.py": "bc73208ec89e647f"
  "src/jarvis/config.py": "965b3658da16361e"
---
## In plain words
Sarvam is an Indian company's paid speech service, made for Indian languages: its Saaras model hears and its Bulbul model speaks. JARVIS can use it on phone calls, and it is the only speech option JARVIS treats as paid (`src/jarvis/calls/prices.py:speech_prices`). It is off by default and stays off until three things are true: a Sarvam key in `sarvam_api_key`, the server's switch `sarvam_enabled` on ({{fact:settings.sarvam_enabled}} by default), and your own yes to "Sarvam speech (paid)" in Calls → Settings. A call uses Sarvam for a language only when it passed the language check and you said yes, and only once no free option still covers the call: free comes first (`src/jarvis/calls/cards.py:offered`). What goes to Sarvam: each short clip of the other person's voice, with the call's language or a request to say which language it is, and the text of each line JARVIS says, with its language and a stock male voice.

## Example (made up)
You switch Sarvam on in Calls → Settings and confirm the prices it shows. Late in the month Google's free allowance is used up, so at 16:30 JARVIS calls a shop in Tamil on Sarvam to ask whether a part is in stock. The shopkeeper speaks for 90 seconds in all, and JARVIS's lines come to 1,200 characters. Hearing costs ₹0.75 and the voice ₹3.60, so the call's speech costs ₹4.35, counted in Vitals' calls line and well inside the call's cap.

## How it works
`build_speech` builds Sarvam only when `sarvam_api_key` is set and `sarvam_enabled` is on; otherwise the language table says it is a paid option and is off (`src/jarvis/calls/speech/build.py`). Even then, every request first asks `_sarvam_yes`, which needs both the server's switch and your own yes in Calls → Settings; without them nothing is sent and nothing is spent (`src/jarvis/calls/speech/sarvam.py:_Sarvam`). `speech_prices` reads Sarvam's prices in rupees from `voice_price_sarvam_inr_per_hour` and `voice_price_sarvam_inr_per_10k_chars`, so no dollar rate enters, and marks Sarvam as paid (`src/jarvis/calls/prices.py`). Before sending, `_Sarvam` checks the request against your monthly limit; after it, the rupees are counted exactly, and a request Sarvam may have billed, such as one that timed out after sending, is counted too (`_Sarvam`). `SarvamHearing` sends one clip of at most {{fact:src/jarvis/calls/speech/sarvam.py:MAX_AUDIO_S}} seconds as a WAV, counted in whole seconds, with the call's language, or with "unknown" when the call has several, so that Sarvam says which language it heard (`src/jarvis/calls/speech/sarvam.py:SarvamHearing`). It takes Sarvam's own language probability as its confidence, or {{fact:src/jarvis/calls/speech/sarvam.py:NO_CONFIDENCE}} when there is none, and keeps at most {{fact:src/jarvis/calls/speech/sarvam.py:MAX_TEXT}} characters of the text (`SarvamHearing`). `SarvamVoice` sends the line's text, at most {{fact:src/jarvis/calls/speech/sarvam.py:MAX_SAY_CHARS}} characters and counted per character, with the language and Bulbul's stock male voice, and reads the sound back (`src/jarvis/calls/speech/sarvam.py:SarvamVoice`). The key travels only in Sarvam's key header, and audio and text are never logged (`src/jarvis/calls/speech/sarvam.py`).

## What it costs
Sarvam is paid, in rupees, by default ₹{{fact:settings.voice_price_sarvam_inr_per_hour}} an hour of the other person's speech, counted in whole seconds, and ₹{{fact:settings.voice_price_sarvam_inr_per_10k_chars}} per ten thousand characters of JARVIS's voice (`speech_prices`). Every rupee counts against your monthly limit and the call's own rupee cap, and nothing is spent while it is off. The language check runs Sarvam only when you have turned it on, and shows its rupees before anything is sent.

## When it fails
With no key, or with `sarvam_enabled` off, Sarvam is not offered (`build_speech`). Without your yes, a request is refused before anything is sent, and nothing is charged (`_Sarvam`). At your monthly limit a request is refused before it is sent. A clip over {{fact:src/jarvis/calls/speech/sarvam.py:MAX_AUDIO_S}} seconds, or a line over {{fact:src/jarvis/calls/speech/sarvam.py:MAX_SAY_CHARS}} characters, is refused without sending (`SarvamHearing`). An answer that does not read counts as a failure Sarvam may have billed, so it is charged (`SarvamVoice`). Each failure is told in plain words, never in Sarvam's own text.
