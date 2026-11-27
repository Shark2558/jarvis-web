---
page: pg_service_hugging_face
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/calls/langcheck/fleurs.py": "46d38040fe11afaa"
---
## In plain words
Hugging Face is a public website where open AI models and datasets are shared. JARVIS uses it for one thing: the language check for phone calls, which you start in Calls → Languages. The check needs real recordings of people reading sentences aloud, with the words they read, to test how well each speech option hears a language over a phone line. JARVIS takes them from Google's open FLEURS set on Hugging Face, fetched while the check runs and never part of JARVIS's own code (`src/jarvis/calls/langcheck/fleurs.py`). It needs no key or setting, and nothing is asked of it until you run the check. Nothing about you goes to Hugging Face: each request names only the dataset, the language and which rows. The recordings are shared under a Creative Commons licence that asks for credit.

## Example (made up)
On a Sunday you open Calls → Languages and run the check for Tamil. JARVIS asks Hugging Face for 100 rows of the Tamil test set and picks 20 clips, 12 of them with numbers in their words, then downloads each one, about 400 KB apiece. Two clips are not readable sound and are skipped; the other 18 are enough for a verdict, and each is played through a pretend phone line to the speech options being checked.

## How it works
`FleursClips` asks Hugging Face's dataset viewer for the first {{fact:src/jarvis/calls/langcheck/fleurs.py:FETCH_ROWS}} rows of the FLEURS test split in the language's own set, and a language with no set there is not checked (`src/jarvis/calls/langcheck/fleurs.py:FleursClips`). `pick_rows` keeps the rows that have both a transcript and an audio address, puts first those whose words hold numbers, up to a share of {{fact:src/jarvis/calls/langcheck/fleurs.py:NUMBERS_SHARE}} of the set, because numbers are the key facts a call must hear right, and takes at most {{fact:src/jarvis/calls/langcheck/fleurs.py:CLIPS}} (`src/jarvis/calls/langcheck/fleurs.py:pick_rows`). Each transcript is cut at {{fact:src/jarvis/calls/langcheck/fleurs.py:MAX_TEXT}} characters (`pick_rows`). Everything that comes back is untrusted: `hf_url` accepts an audio address only over https on Hugging Face's own hosts and with no user name in it, and `_audio_src` prefers the WAV copy (`src/jarvis/calls/langcheck/fleurs.py:hf_url`). Redirects are followed by hand, each new address checked by `hf_url` before it is asked, at most {{fact:src/jarvis/calls/langcheck/fleurs.py:MAX_REDIRECTS}} times (`FleursClips`). A clip over {{fact:src/jarvis/calls/langcheck/fleurs.py:MAX_CLIP_BYTES}} bytes, longer than {{fact:src/jarvis/calls/langcheck/fleurs.py:MAX_CLIP_S}} seconds, or not a readable WAV is skipped (`FleursClips`). Each kept clip becomes a `Clip`: the language, the words as read and the clean sound, which the check then turns into phone-quality audio (`src/jarvis/calls/langcheck/fleurs.py:Clip`). With fewer than {{fact:src/jarvis/calls/langcheck/fleurs.py:MIN_CLIPS}} usable clips the language gets no verdict, and `FleursUnavailable` says so.

## What it costs
Nothing in rupees: the dataset viewer and the downloads are free and need no account or key (`src/jarvis/calls/langcheck/fleurs.py`). The check's own rupees are those of the speech options that hear the clips, shown in the check's plan before anything is sent.

## When it fails
Without the network, or when Hugging Face refuses, `FleursUnavailable` says in plain words that the test clips could not be fetched and nothing was checked, so that language stays unchecked until you try again (`src/jarvis/calls/langcheck/fleurs.py:FleursClips`). A single clip that fails to download, points elsewhere or is too big is skipped, and the log notes only why, never its address (`FleursClips`). A language with fewer than {{fact:src/jarvis/calls/langcheck/fleurs.py:MIN_CLIPS}} usable clips gets no verdict, and a language with no open test set is never checked.
