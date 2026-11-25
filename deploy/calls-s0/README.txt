JARVIS CALLS - LAPTOP TEST (S0)
===============================

What this does
--------------
Before JARVIS's calls feature is built, this test proves on YOUR laptop that JARVIS will be able
to hear a phone call made through Windows Phone Link, and to speak into it. It takes about 30
minutes, costs nothing, sends nothing anywhere, and changes nothing that it does not change back.

You need: your phone with you, the laptop plugged in, and a friend or family member who can
answer a short call (Test B: they tell you whether they heard a test sentence).

The steps
---------
 1. PHONE LINK (skip if your laptop already makes calls through Phone Link).
    On the laptop: Start -> type Phone Link -> open it -> follow the steps to link your phone
    (your phone installs "Link to Windows"). Then in Phone Link click Calls -> Get started and
    allow the Bluetooth pairing on both the laptop and the phone. Make one short test call from
    Phone Link to be sure it works. If Phone Link says your laptop's Bluetooth cannot do calls,
    stop here and tell Claude: that is the test's first answer.
    If Phone Link says "Calls using Bluetooth headsets are not supported": a Bluetooth headset or
    earbuds are connected to the LAPTOP. Turn them off, or Settings -> Bluetooth & devices -> the
    headset -> Disconnect. Phone Link calls use the laptop's own speaker and microphone (or a
    wired or USB headset), and so does this test.

 2. VB-CABLE (a free virtual microphone cable, from VB-Audio).
    Open https://vb-audio.com/Cable/ -> download "VBCABLE_Driver_Pack" (Windows) -> right-click
    the zip -> Extract All. In the extracted folder right-click VBCABLE_Setup_x64.exe -> Run as
    administrator (say Yes) -> Install Driver. Restart the laptop.

 3. THIS KIT. Right-click the JARVIS-Calls-S0 zip -> Extract All -> extract it to C:\
    (this makes the folder C:\JARVIS-Calls-S0).

 4. RUN THE TEST. Start -> type PowerShell -> open Windows PowerShell (NOT as administrator).
    Type these two lines:
        cd C:\JARVIS-Calls-S0
        powershell -ExecutionPolicy Bypass -File .\s0.ps1
    If it offers to install Python 3.12 (free), type Y. When it says so, close PowerShell, open
    it again and type the two lines again.

 5. FOLLOW THE TEST ON SCREEN. It guides you through:
    Test A - you call your friend from Phone Link; the test listens to the laptop's speaker.
    Test B - the Sound window opens; you make "CABLE Output" the default microphone; the test
             plays a sentence into the call; you ask your friend what they heard.
    Test C - optional: you call your mobile operator's customer care number (free) and type
             the keys its menu asks for; the test plays the key tones into the call.
    At the end it asks you to switch your usual microphone back, and checks that you did.

 6. SEND THE RESULT. Copy the report the test prints between the two lines of ===== and paste
    it into the chat with Claude. (It is also saved as s0-report.txt in this folder.) It holds
    device names and results only: no phone numbers and no audio.

If anything goes wrong, copy the last lines PowerShell shows and paste them into the chat.

What the test leaves on your laptop: Python 3.12 (if it installed it), VB-CABLE (JARVIS's calls
feature uses it later), and the folder C:\JARVIS-Calls-S0, which you can delete afterwards.
Test A's 15-second recording stays in that folder only if you choose to keep it.
