JARVIS CALL DESK - CALLS FROM YOUR LAPTOP (R18)
===============================================

What this does
--------------
The call desk is a small program on your laptop. When you approve a call in JARVIS, your phone
dials from your own number and the call's sound comes to the laptop through Phone Link (like a
car kit). The call desk then:
  - listens to what the laptop's speaker plays (the other person), and sends that sound to JARVIS
    only while the other person is speaking;
  - plays JARVIS's voice into the call through VB-CABLE, a free virtual microphone;
  - makes "CABLE Output" your default microphone for that call only, and puts YOUR microphone
    back afterwards - also after a crash, and when the laptop restarts;
  - mutes Windows' notification sounds during a JARVIS call, and switches them back on after.
Before every call it checks that VB-CABLE is there, that Phone Link is running, and that no
Bluetooth headset is connected to the laptop (Phone Link refuses calls then); JARVIS's call card
tells you if something is missing, and nothing is dialled.

It costs nothing, needs no administrator rights (VB-CABLE's own installer does, once), and
downloads no voice models. Your link to JARVIS stays in your own Windows profile folder.

You need: Windows 10 or 11, Phone Link working for calls with your phone, about 15 minutes.

The steps
---------
 1. PHONE LINK (skip if your laptop already makes calls through Phone Link).
    Start -> type Phone Link -> open it -> link your phone (the phone installs "Link to
    Windows") -> Calls -> Get started, and allow the Bluetooth pairing on both. Make one short
    test call from Phone Link. Calls use the laptop's own speaker and microphone (or a wired or
    USB headset): turn off any Bluetooth headset or earbuds connected to the LAPTOP.

 2. VB-CABLE (skip if the laptop test S0 installed it).
    Open https://vb-audio.com/Cable/ -> download "VBCABLE_Driver_Pack" (Windows) -> right-click
    the zip -> Extract All. In the extracted folder right-click VBCABLE_Setup_x64.exe -> Run as
    administrator (say Yes) -> Install Driver. Restart the laptop.

 3. THIS KIT. Right-click JARVIS-Call-desk-kit.zip -> Extract All -> extract it to C:\
    (this makes the folder C:\JARVIS-CallDesk).

 4. INSTALL. Start -> type PowerShell -> open Windows PowerShell (NOT as administrator).
    Type these two lines:
        cd C:\JARVIS-CallDesk
        powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1
    If it offers to install Python 3.12 (free), type Y. If it then asks you to, close
    PowerShell, open it again and type the two lines again.

 5. LINK. When the installer asks for a code: in JARVIS open Calls -> Settings -> "Call desk
    on your laptop" -> "Link the call desk", and type the code it shows (it works for 10
    minutes, once).

 6. START AT SIGN-IN. When asked, type Y: then the call desk starts whenever you sign in, and
    puts your microphone back even after a crash or a restart.

 7. CHECK. The installer ends with the laptop check. "ready for calls" is what you want; if it
    lists something, fix that and run the check again:
        .\.venv\Scripts\python.exe -I -m jarvis.calldesk check

Every day
---------
 - Start -> JARVIS -> "JARVIS Call Desk" starts it (it also starts at sign-in, and with JARVIS
   Home if that is on this laptop).
 - Start -> JARVIS -> "JARVIS Call Desk - Stop" stops it (JARVIS can't call from the laptop then).
 - Start -> JARVIS -> "JARVIS Call Desk - Give me back my microphone": if your microphone ever
   seems wrong (others can't hear you in a meeting), this puts it back at once. By hand:
   Settings -> System -> Sound -> Input -> choose your microphone.
 - During a call you can listen on the laptop's speaker. "Take over" in JARVIS gives you your
   microphone back at once; JARVIS goes quiet and the recording carries on.

If anything goes wrong
----------------------
 - The desk writes what happened (never sound, words, numbers or keys) to
   %LOCALAPPDATA%\JARVIS\CallDesk\calldesk.log. Copy its last lines into the chat with Claude.
 - JARVIS says the call desk is not linked: make a new code in JARVIS, then in this folder:
        powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Link
 - A newer kit: extract it over C:\JARVIS-CallDesk, then:
        powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -Update

On the server (optional speech keys)
------------------------------------
Calls use Google's free speech allowance first, with nothing to set up. For Microsoft Azure's free
tier (F0: it stops at its allowance and can never bill), Sarvam (paid: used only after your yes in
Calls -> Settings) or Bhashini, store the key in Secret Manager from Cloud Shell, then run
deploy/cloudrun.sh again: it mounts only the keys it finds there (never put a key in a file):
    read -r -s K && printf '%s' "$K" | gcloud secrets create jarvis-azure-speech-key --data-file=-
(jarvis-sarvam-key for Sarvam, jarvis-bhashini-key for Bhashini). Three plain settings go on the
service itself, only if you need them (a deploy run with --reconfigure clears them; set them again):
    gcloud run services update jarvis --region asia-south1 --update-env-vars \
      JARVIS_AZURE_SPEECH_REGION=<your Azure region>,JARVIS_SARVAM_ENABLED=true,JARVIS_BHASHINI_USER_ID=<your id>
Azure's region is centralindia unless you set it; Sarvam stays off on the server until
JARVIS_SARVAM_ENABLED=true; Bhashini needs its user id beside the key.

Laptop speech (R5.2)
--------------------
With the laptop speech kit (deploy/local-speech) on this same laptop, the desk can hear and speak
on the laptop itself, free, so no sound leaves it. The installer copies the kit's key into the
desk's own folder (%LOCALAPPDATA%\JARVIS\CallDesk\local-speech.key); if you install the kit
later, or make it a new key, run:
        powershell -ExecutionPolicy Bypass -File .\install-calldesk.ps1 -SpeechKit
then restart the desk. Without the kit, or while it is off or busy, calls use JARVIS's cloud
speech. JARVIS's language check decides which languages use the laptop (kit 1.0.0 hears English
only).

Removing it
-----------
Run "JARVIS Call Desk - Stop", delete the shortcuts in Start -> JARVIS and in your Startup
folder (Win+R, shell:startup), then delete C:\JARVIS-CallDesk and
%LOCALAPPDATA%\JARVIS\CallDesk. In JARVIS, Calls -> Settings -> "Call desk on your laptop" ->
Unlink (or Privacy -> Phone calls -> Call desk link).
