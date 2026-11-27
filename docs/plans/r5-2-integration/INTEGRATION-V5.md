# R5.2 builder V5: the speaker check (row 84). Notes for the integrator (I1)

Branch `r5-2-v5` (from `r5-2-i0`). Plan: `docs/plans/r5-2-voice.md` 3.5, D6. V5 edited no wiring file and no file another builder owns; the only existing file changed is `console-voice-barge.js` (the hook below).

## Files
| File | What |
|---|---|
| `static/console-voiceprint-math.js` | Pure: Kaldi fbank (80 bands, Hamming, CMN; matches a numpy reference), cosine, the print, verdicts |
| `static/console-voiceprint.js` | `window.JarvisVoicePrint`: the model slot (sha-checked), AES-GCM print with a non-extractable device key in IndexedDB, per-device switch, reading / session enrolment, `verify(frames)` |
| `static/console-voiceprint-panel.js` | Voice -> Speaker check (existing classes, textContent only) |
| `static/console-voice-barge.js` | +16 / -4 lines: with a print active, a check clip is judged on the device first |
| `static/vendor/speaker/spk-1/MANIFEST.json` | The model slot: WeSpeaker VoxCeleb CAM++, CC-BY-4.0; **no file shipped** (see "Model") |
| `api/speaker_assets.py` | `GET /static/vendor/speaker/{release}/{name}` (R7's sha check, like `tryon_assets`) |

## Wiring I1 adds
1. `api/console.py` `APP_ASSETS`: `"console-voiceprint-math.js": _JS`, `"console-voiceprint.js": _JS`, `"console-voiceprint-panel.js": _JS` (R5.2 V5, row 84).
2. `console.html`, right after `<script src="/static/console-voice-barge.js" defer></script>`, in this order: `console-voiceprint-math.js`, `console-voiceprint.js`, `console-voiceprint-panel.js` (each `defer`). Until then `tests/test_r51_console_assets_linked.py` fails for these three files (6 cases).
3. The router: `from jarvis.api.speaker_assets import router as speaker_router` and include it where `mannequin_router` is (`api/r13_wiring.py` line ~356) or in R5.2's own wiring.
4. Optional: add `'speaker'` to `console-voice.js`'s `panelSlot` names (after `'phrases'`); the panel uses it when present and otherwise inserts its own `#vSlotSpeaker` after the phrases slot.
5. V3's seam: the session screen calls `window.JarvisVoicePrint && JarvisVoicePrint.offerSessionClip(pcm)` with each clip's `Int16Array` (16 kHz mono) before it uploads it. Only embeddings are kept, in memory; the owner then taps "Use my voice session".

## Model (not shipped)
Licence verified from primary sources: WeSpeaker's `docs/pretrained.md` (VoxCeleb models follow CC BY 4.0) and VoxCeleb's `license.txt` (CC BY 4.0; the source videos' copyright stays with their owners). huggingface.co and wenet.org.cn were unreachable from the build session, so no file or SHA-256 was taken; the slot's `to_ship` list says what to do. Until then the console says "no model" and barge-in is unchanged. The 0.45 threshold and the plan's EER <= 5 % eval need the real model on the laptop.

## Not done here
- The "Spoken by the owner" display label: nothing sends or shows it yet (`SPOKEN_BY_HEADER` stays unused). `tests/test_r52_v5_never_approves.py` allows the label only in `voice/profile.py` and forbids it, and any voice-print word, in every module that decides an approval, passkey, unlock or Telegram approval.
- Book pages and guide cards for the speaker check.

## Tests
`tests/test_r52_v5_voiceprint_math.py` (6, node), `tests/test_r52_v5_console.py` (27), `tests/test_r52_v5_never_approves.py` (6), `tests/browser/test_r52_v5_voiceprint.py` (14; screenshots to `/tmp/r52-v5-shots/`). `tests/browser/test_voice_barge.py` and `test_voice_fixes_barge.py` pass unchanged (29).
