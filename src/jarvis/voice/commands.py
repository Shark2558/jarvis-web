"""Speech hints for the console's local voice-command router (R5, docs/plans/r5-voice.md D16).

``BASE_PHRASES`` is the base list every transcription request starts with: the names JARVIS is
called by and the multi-word command phrases. The honorific is added by the voice service (it is
not known here). Single common words such as "stop" are never hints: they would bias ordinary
speech. ``COMMAND_HINTS`` is every multi-word phrase the router understands (the table in
``console-voice-commands.js``; ``tests/test_r5_seams.py`` keeps the two in step). Sending them all
is the caller's choice. No ``boost`` is set (D16).

R7 (docs/plans/r7-mobile.md D11, D19, I0 seam 13): ``R7_PHRASES`` are the multi-word phrases of the
two local commands R7's parts register through ``JarvisVoiceCommands.register`` (``camera.off``:
Part B, locks this device's camera, never touches the home burglar camera; ``sos.open``: Part D,
only OPENS the SOS screen, which still needs his hold). Nothing here turns a camera on. They are
hints too. The single word "SOS" is understood by the router but is never a hint.
"""

from __future__ import annotations

BASE_PHRASES: tuple[str, ...] = (
    "JARVIS",
    "Jarvis",
    "Hey Jarvis",
    "mic off",
    "stop listening",
    "switch off the mic",
    "switch to the keyboard",
    "switch to my earphones",
    "switch to my speaker",
)

COMMAND_HINTS: tuple[str, ...] = (
    # mic.off
    "mic off",
    "switch off mic",
    "switch off the mic",
    "turn off the mic",
    "switch mic off",
    "switch the mic off",
    "turn the mic off",
    "mute mic",
    "mute the mic",
    "mute yourself",
    "stop listening",
    "stop listening to me",
    "don't listen",
    "don't listen to me",
    # speech.stop
    "stop it",
    "stop talking",
    "stop speaking",
    "stop there",
    "wait a moment",
    "hold on",
    "hang on",
    "one moment",
    "be quiet",
    "that's enough",
    "never mind",
    "forget it",
    # conversation.keyboard
    "keyboard mode",
    "switch to keyboard",
    "switch to the keyboard",
    "i'll type",
    "let me type",
    "typing mode",
    "that's all",
    "that'll be all",
    "we're done",
    "end conversation",
    "end the conversation",
    # devices
    "switch to my earphones",
    "switch to my speaker",
    "what's connected",
    "which devices are connected",
    "list devices",
    "list my devices",
    "list sound devices",
    "list audio devices",
    "which speaker are you using",
)

# R7 D11 ("Jarvis, cameras off" in twenty phrasings) and D19 ("Jarvis, SOS" only opens the screen)
R7_PHRASES: dict[str, tuple[str, ...]] = {
    "camera.off": (
        "cameras off",
        "camera off",
        "stop the camera",
        "stop the cameras",
        "turn off the camera",
        "turn the camera off",
        "turn off the cameras",
        "switch off the camera",
        "switch the camera off",
        "switch off the cameras",
        "close the camera",
        "shut the camera",
        "shut off the camera",
        "kill the camera",
        "disable the camera",
        "lock the camera",
        "put the camera off",
        "no more camera",
        "stop looking",
        "stop watching me",
    ),
    "sos.open": (
        "open sos",
        "emergency sos",
        "open emergency sos",
        "open the sos screen",
        "show the sos screen",
    ),
}
COMMAND_HINTS = (*COMMAND_HINTS, *(p for phrases in R7_PHRASES.values() for p in phrases))
