---
page: pg_card_c81
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/static/console-voice-session.css": "dfaf4ffbd9310e07"
  "src/jarvis/api/static/console-voice-session.js": "9c299abb8bacdcdf"
  "src/jarvis/api/voice_profile_routes.py": "2aceda9e3d8bcd04"
  "src/jarvis/voice/profile.py": "1e4413929541d0aa"
  "src/jarvis/voice/profile_ports.py": "313a15e9823c3ad8"
  "src/jarvis/voice/profile_store.py": "432ae0bcf26a64d7"
  "src/jarvis/voice/session.py": "62f6a4f09d3bb6dc"
  "src/jarvis/voice/session_api.py": "e4f51093cb23971d"
  "src/jarvis/voice/session_compare.py": "6e54e7e25fdb3556"
  "src/jarvis/voice/session_privacy.py": "98c49f9f5883f6cd"
  "src/jarvis/voice/session_prompts.py": "2955f892f2e17b17"
  "src/jarvis/voice/session_score.py": "f4b2689cc3a36a17"
  "src/jarvis/voice/session_store.py": "ba2767fcf7779019"
  "tests/test_r52_i0_routes.py": "a50b4eba830d75ce"
  "tests/test_r52_v3_api.py": "77c231c644361f21"
  "tests/test_r52_v3_privacy.py": "eaffd2dc03fea02f"
  "tests/test_r52_v3_score.py": "a5a2cdefc5c8b1f5"
  "tests/test_r52_v3_session.py": "bc4df7991097b14c"
---
## In plain words
Your voice session teaches JARVIS how you speak. In Voice, Your voice, you read about {{fact:src/jarvis/voice/profile.py:PROMPTS_TARGET}} short lines aloud in {{fact:src/jarvis/voice/profile.py:BLOCKS}} blocks of about {{fact:src/jarvis/voice/profile.py:BLOCK_MINUTES}} minutes, with a break after each: about {{fact:src/jarvis/voice/profile.py:SESSION_MINUTES}} minutes of your time, and only you can do it (`src/jarvis/voice/profile.py`). JARVIS then tests each listening engine on your voice, picks the one that understands you best, and turns the mishearings you repeat into corrections (`src/jarvis/voice/session_score.py`). It needs the laptop speech kit first, because your recordings are kept only there, encrypted; the cloud keeps no audio (`src/jarvis/voice/session.py`). Delete my recordings removes them whenever you like, and what JARVIS learnt stays (`src/jarvis/voice/session.py`).

## Example (made up)
Sana starts her session on a Saturday evening and types 6 words of her own, among them a cousin's nickname and two shop names. This month's free Google minutes are already used, so the screen shows the rupees first: at most about ₹46 for the comparison's 20 minutes, at about ₹2.29 a minute. She types YES. She reads each block, takes the breaks, and finishes in 22 minutes. Her laptop scores the clips: Whisper small comes within 2 points of Google for her voice, so the laptop is chosen. JARVIS learnt that it hears "Java's" when she says "JARVIS", and fixes that from then on.

## How it works
The lines are commands JARVIS knows, your words to recognise, places and names, numbers and times, everyday requests, and "Hey Jarvis" said {{fact:src/jarvis/voice/profile.py:WAKE_PROMPTS}} ways in all; you may type up to {{fact:src/jarvis/voice/session_prompts.py:TYPED_WORDS_MAX}} words of your own at the start (`src/jarvis/voice/session_prompts.py`). Record stops by itself when you pause; while the pop-up is open a voice conversation ends and "Hey Jarvis" is paused (`src/jarvis/api/static/console-voice-session.js`). Each clip goes to the cloud as a WAV and straight on to your laptop, where the kit keeps it encrypted (`VoiceSessions`). For {{fact:src/jarvis/voice/session_prompts.py:HELD_OUT_PER_BLOCK}} comparison lines a block, Google, with your words, hears the clip on its way through, at most {{fact:settings.voice_session_compare_minutes}} minutes of its listening; inside this month's free minutes every such call is free-only and can never be priced (`src/jarvis/voice/session_compare.py`). Beyond them nothing is sent until you type YES to the rupees shown, or you go on without Google; it asks at the start, and again before a clip if the free minutes run out (`src/jarvis/voice/session_compare.py`). If you choose, this browser's own listening hears those lines too, said plainly: in Chrome that audio goes to the browser's maker (`src/jarvis/api/static/console-voice-session.js`). Then the laptop's Whispers hear the comparison clips in a job on the kit; each engine is ranked by word error and command accuracy on the lines all of them heard, after numbers, money and times are written the same way on both sides (`src/jarvis/voice/session_score.py`). The best is chosen, but a laptop engine close behind it with nearly every command right wins instead: it is free and your audio stays home (`choose`). Mishearings the chosen engine makes {{fact:src/jarvis/voice/session_score.py:REPEAT_MIN}} times or more become corrections applied after listening, whole words only, never from the numbers block and never a number, money or code word (`Correction`). New words join your words to recognise, one list of at most {{fact:src/jarvis/voice/profile.py:WORDS_MAX}} (`src/jarvis/voice/session.py`). Your profile keeps the ranking, the chosen engine, the corrections and their switch (`DocProfileStore`, `voice_profile`). Check again has the laptop hear the clips again (`POST /v1/voice/profile/recheck`). Delete my recordings asks for a confirm, then deletes the clips on the laptop and the session's transcripts here (`POST /v1/voice/profile/recordings/delete`). The Privacy panel has rows for your profile, the recordings and the wake-word files (`src/jarvis/voice/session_privacy.py`).

## What it costs
₹0 a month. The one comparison uses about {{fact:settings.voice_session_compare_minutes}} of Google's free listening minutes, each clip counted at Google's own billing step (`src/jarvis/voice/session_compare.py`). Past this month's free minutes the rupees are shown first and nothing is spent without your typed YES; free minutes that can't be read are never promised, so you are asked (`src/jarvis/voice/session_compare.py`). The laptop's scoring costs nothing (`src/jarvis/voice/session.py`).

## When it fails
With no kit set up the session doesn't start and says why, and Delete my recordings clears only the comparison's words here, the laptop's recordings still counted; a kit of another version asks to be updated first (`src/jarvis/voice/session.py`). A clip too long, not a WAV, or for a line not in the session is refused. Too few comparison lines: "record more"; failed scoring: "Try Check again"; recordings gone from the laptop: "start a new session" (`VoiceSessions`). With `voice_profile_enabled` off the routes answer with status 503 and listening keeps its usual order (`src/jarvis/api/voice_profile_routes.py`). An unreachable laptop makes the privacy rows say "Couldn't check right now", and a delete then fails rather than claim anything is gone (`src/jarvis/voice/session_privacy.py`). A stored profile or session that doesn't validate reads as none (`DocProfileStore`, `DocSessionStore`).
