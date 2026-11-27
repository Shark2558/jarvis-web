---
page: pg_card_c05
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/voice.py": "45227c5b0f4437c3"
  "src/jarvis/voice/__init__.py": "ba6969e9df92d919"
  "src/jarvis/voice/adc.py": "215d50701bc56fe5"
  "src/jarvis/voice/calls_bridge.py": "dee4357bb0a42ba0"
  "src/jarvis/voice/catalogue.py": "a7d5423e32e6e4ec"
  "src/jarvis/voice/commands.py": "f332fa895b7fb4d0"
  "src/jarvis/voice/google_cloud.py": "70b3d0637df4a58b"
  "src/jarvis/voice/laptop.py": "c05c622c3b08fee0"
  "src/jarvis/voice/ports.py": "5c43ac1ddeeb1566"
  "src/jarvis/voice/privacy.py": "7b3ccf362931cc54"
  "src/jarvis/voice/profile.py": "8a428dc0d00c93c3"
  "src/jarvis/voice/profile_ports.py": "313a15e9823c3ad8"
  "src/jarvis/voice/profile_store.py": "432ae0bcf26a64d7"
  "src/jarvis/voice/routing.py": "96b7f27c1fc3c066"
  "src/jarvis/voice/service.py": "61380b913e4265cf"
  "src/jarvis/voice/session.py": "7cb5e8c4163664f8"
  "src/jarvis/voice/session_api.py": "adb4e002a290f925"
  "src/jarvis/voice/session_compare.py": "6e54e7e25fdb3556"
  "src/jarvis/voice/session_privacy.py": "39bde552817991a3"
  "src/jarvis/voice/session_prompts.py": "2955f892f2e17b17"
  "src/jarvis/voice/session_score.py": "f4b2689cc3a36a17"
  "src/jarvis/voice/session_store.py": "ba2767fcf7779019"
  "src/jarvis/voice/settings.py": "d54739fc34d24078"
  "src/jarvis/voice/speakable.py": "ad9c138afcb8137b"
  "src/jarvis/voice/wakeword_api.py": "270a5741613f3b8f"
  "src/jarvis/voice/wav.py": "a96c3a9747fcada4"
---
## In plain words
The voice service is how JARVIS speaks and listens on the server. It turns replies into a British voice with Google's Text-to-Speech, and your recorded speech into text with Google's Speech-to-Text, in Indian English (`src/jarvis/voice/service.py`). It decides what is fit to be read aloud, keeps to Google's free allowance where it can, and asks your monthly limit before any paid call (`src/jarvis/voice/speakable.py`). No recording is ever stored (`src/jarvis/voice/wav.py`). Since {{fact:release.label}}, once your laptop's speech kit is set up, your listening goes first to the engine your voice session chose, on the laptop while it is healthy, then to Google, then to the browser, and your corrections apply after (`src/jarvis/voice/routing.py`).

## Example (made up)
You hold the mic button and say "what's on my calendar tomorrow?". The console sends the 2.4-second clip, Google returns three guesses, and the best one is shown as what JARVIS heard. JARVIS answers in a calm British voice at your chosen speed of 1.1. The reply held a link and a small table: the voice says "the link on screen" and skips the table. This month you have used 31 minutes of listening, inside the free 54, so it cost nothing.

## How it works
`POST /v1/voice/transcribe` takes a recording, and `parse_wav` accepts only plain {{fact:src/jarvis/voice/wav.py:BITS}}-bit mono sound at {{fact:src/jarvis/voice/wav.py:SAMPLE_RATE}} samples a second, from {{fact:src/jarvis/voice/wav.py:MIN_SECONDS}} to {{fact:src/jarvis/voice/wav.py:MAX_SECONDS}} seconds long, refusing anything else before any cloud call (`src/jarvis/voice/wav.py`). `GoogleSTT` sends it in `voice_language`, asks for up to {{fact:src/jarvis/voice/google_cloud.py:MAX_ALTERNATIVES}} guesses, and passes hints: JARVIS's names and command phrases, this turn's file names and nouns from your own messages, then your own "Words to recognise" (`src/jarvis/voice/google_cloud.py`). `POST /v1/voice/speak` runs the reply through `speakable`, which strips formatting, code and tables, says "the link on screen" for a web address, and stops at {{fact:src/jarvis/voice/speakable.py:MAX_SPEAK_CHARS}} characters at a sentence's end (`src/jarvis/voice/speakable.py`). `GoogleTTS` reads it in the voice and speed you chose, between {{fact:src/jarvis/voice/catalogue.py:RATE_MIN}} and {{fact:src/jarvis/voice/catalogue.py:RATE_MAX}} times normal (`src/jarvis/voice/catalogue.py`). `VoiceService` counts each month's free allowance, and only a call beyond it asks the spending gate first (`src/jarvis/voice/service.py`). Calls of one kind run one after another for each owner, so two at the edge of the allowance never both slip through (`VoiceService`). Google is reached as the server's own account, with no key stored anywhere, through `AdcTokens` (`src/jarvis/voice/adc.py`). With the kit and your voice profile wired, `EngineRoute` picks the engine: the laptop listens for free while its health is good, and any kit failure falls back silently to Google, then the browser (`src/jarvis/voice/routing.py`). Your voice is the laptop's only while the kit has a ready voice, never for a voice preview or a guest; this first kit has none, so Google speaks (`src/jarvis/voice/service.py`). The voice session's comparison asks `transcribe` for Google alone, with your words and without the laptop or your corrections (`src/jarvis/voice/service.py`). Your voice, speed, wit level and words to recognise live in `voice_settings` (`src/jarvis/voice/settings.py`). Each route has its own limit, such as {{fact:src/jarvis/api/voice.py:TRANSCRIBE_PER_MINUTE}} recordings a minute (`src/jarvis/api/voice.py`).

## What it costs
Nothing while you stay inside the free allowance JARVIS claims: {{fact:settings.voice_tts_free_chars}} characters of speech per voice type and {{fact:settings.voice_stt_free_seconds}} seconds of listening each Pacific-time month (`src/jarvis/voice/service.py`). Beyond it, HD voices are priced at {{fact:settings.voice_price_chirp3_hd_usd_per_m}} US dollars and Studio voices at {{fact:settings.voice_price_studio_usd_per_m}} per million characters, and listening at {{fact:settings.voice_price_stt_usd_per_min}} dollars a minute, all counted against your monthly limit in rupees (`voice_price_stt_usd_per_min`). What the laptop hears costs ₹0 and is never gated or metered (`src/jarvis/voice/routing.py`).

## When it fails
If Google answers that speech isn't switched on, or the server has no credentials, that half of voice is marked unavailable for {{fact:src/jarvis/voice/service.py:DOWN_TTL_S}} seconds and no calls are made meanwhile (`src/jarvis/voice/service.py`). The console then uses the browser's own voice and recognition instead (`VoiceUnavailable`). A laptop kit that is off, asleep or slow is skipped without a word (`LaptopVoice`). A recording in the wrong format is refused with a plain line before any cost (`BadAudio`), and a reply with nothing speakable answers "nothing to say" (`NothingToSay`). If your settings can't be read within {{fact:src/jarvis/voice/service.py:SETTINGS_READ_S}} second, the defaults are used. A call that may have reached Google before failing is metered on its estimate, so the meter never under-counts (`src/jarvis/voice/service.py`).
