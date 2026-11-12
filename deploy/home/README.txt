JARVIS HOME KIT
================

What this does
--------------
It puts a small "home" on your Windows laptop: Home Assistant (your devices), Frigate (the camera
watcher), Mosquitto (their messenger) and the JARVIS bridge, which is the ONLY door between your
home and JARVIS. Video, pictures, face pictures and your Home Assistant password stay on this
laptop. JARVIS only gets short messages like "a person at the Gate, 18:42".

IMPORTANT: it works only while this laptop is on, awake and online. If it sleeps, shuts down or
loses Wi-Fi, the camera cannot see or alert you. If the laptop stops answering while the alarm is
armed, JARVIS tells you within about 15 minutes. This is not a monitored alarm system.

This is a trial. Neither Home Assistant nor Frigate officially supports Windows with WSL2; a
Raspberry Pi 5 is the proper long-term home, and this kit moves there unchanged.

The steps
---------
 1. Check your laptop: Windows 10 22H2 or Windows 11, plugged in. Task Manager -> Performance ->
    CPU says "Virtualization: Enabled". If not, ask Claude for the BIOS steps.
 2. In JARVIS: Integrations -> Home -> Download home kit. Right-click the zip -> Extract All.
    Extract it to C:\ (this makes the folder C:\JARVIS-Home).
 3. Start -> type PowerShell -> right-click Windows PowerShell -> Run as administrator (say Yes).
    Type these two lines:
        cd C:\JARVIS-Home
        powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
    If it asks you to restart, do, then open PowerShell as administrator and type them again.
 4. When Ubuntu opens the first time, choose a user name and a password and write them down.
 5. Say Yes when the script offers to keep the laptop awake when plugged in and to ignore closing
    the lid.
 6. Old phone: install IP Webcam from the Play Store. In it: Connection settings -> Login/password
    (set both); Video preferences -> 1280x720; turn off the phone's battery optimisation for the
    app. Plug in the charger and mount the phone facing YOUR OWN gate. Press Start server and note
    the address it shows.
 7. Type that address, login and password into the script. It says "Camera works" when Frigate
    sees the picture.
 8. Home Assistant (optional; the camera works without it). Do this after the script has finished,
    when Home Assistant is running: open http://localhost:8123 and create your account. Settings ->
    People -> add a person "JARVIS bridge" who can log in and is NOT an administrator. Log in as it
    in a private window -> Profile -> Security -> Long-lived access tokens -> Create. Then, in
    PowerShell as administrator in C:\JARVIS-Home, type
        powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HaToken
    and paste the token (it is not shown while you paste).
 9. Tailscale (installed for offline mode; if not, install it and sign in). When the script asks,
    allow Funnel in the browser page that opens.
10. In JARVIS: Integrations -> Home -> Link -> type the code into the script. Wait for "Linked" (it
    can take 10 minutes the first time). JARVIS now shows "Online".
11. Frigate: open http://localhost:8971 (the password is printed by the script). On the camera, draw
    a zone named gate around your gate and, for parcels, one named doorstep. In JARVIS -> Home ->
    Cameras, give them names you like. Draw zones only over your own gate and doorstep. Mask the
    road and your neighbours' doors and windows - JARVIS must not watch them.
12. Parcels (optional, about 15 minutes over a few days): Frigate -> Classification -> new state
    model "doorstep" with states "package" and "empty"; draw the box over the doorstep; sort 10-20
    example pictures of each.
13. Faces (optional): JARVIS -> Faces -> Add person (ask them first; for a child, you must be the
    parent or guardian). Then on the laptop open http://localhost:8098/faces (the code is printed
    by the script) and add 5-10 clear photos.
14. JARVIS -> Integrations -> Alerts: set quiet hours and VIPs. On your phone's Chrome and on the
    laptop: Enable browser notifications -> Test. Telegram alerts need the Telegram pairing.
15. Optional, private camera view on your phone: install Tailscale on the phone, sign in with the
    same account, and say Yes when the script offers it (it runs tailscale serve on port 5443).
16. Try it: Home panel -> Arm (Away). Walk past the camera -> an alert within 10 seconds. Disarm
    with your passkey -> walk past -> nothing.

Everyday use
------------
 - It starts by itself when you log in to Windows (the "JARVIS Home" task).
 - start-home.ps1 starts it, stop-home.ps1 stops it.
 - To see what is running: open Ubuntu and run  bash ~/jarvis-home/setup-wsl.sh status
 - To unlink: JARVIS -> Integrations -> Home -> Unlink (the bridge notices within minutes).

Safety notes
------------
 - bridge.env on this laptop holds your Home Assistant token and passwords. Never send it to
   anyone, and never put it in the download kit. JARVIS never asks for it.
 - frigate.env holds the phone camera's address with its login and Frigate's broker password;
   only Frigate reads it (not the bridge, not JARVIS).
 - Mosquitto, the message broker inside the kit, lets nobody in without a password: Frigate's
   user may publish its events, the bridge's user may only read them (mosquitto/acl).
 - The bridge sees Frigate's media folder only to delete a removed person's face pictures and to
   clean up strangers' face pictures after 72 hours and doorstep pictures after 7 days.
 - The published ports listen on 127.0.0.1 (this laptop only). Home Assistant listens on 127.0.0.1
   and on 172.29.80.1, the kit's private Docker network, so the bridge can reach it; nothing else
   can. The only thing on the internet is the bridge's signed door, through Tailscale Funnel on
   port 8443.
 - Anyone with this laptop (or its disk) can act as your home. Use a Windows login password.
 - An old phone on a charger 24/7 can overheat or swell its battery: keep it out of direct sun and
   check it monthly.
 - Face recognition: only people you added with their consent (a parent's for a child). Personal use
   in your own home only.

Updating the kit
----------------
JARVIS -> Integrations -> Home says "Your home kit is older than this JARVIS" when a newer kit is
ready. Your camera, passwords, Home Assistant token and link are kept.
 1. In JARVIS: Integrations -> Home -> Download home kit.
 2. Right-click the zip -> Extract All -> extract it to C:\ again. When Windows asks, choose
    "Replace the files in the destination".
 3. Start -> type PowerShell -> right-click Windows PowerShell -> Run as administrator. Type:
        cd C:\JARVIS-Home
        powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Update
    It downloads the two face model files once (about 40 MB) and restarts only the bridge.
 4. Wait for "Updated." JARVIS -> Integrations -> Home says Online again within two minutes.

Photos and faces
----------------
This laptop can look at still photos and group the faces in them, so you name each person once.
The photos, the small face pictures it keeps and the numbers it compares faces by never leave
this laptop. JARVIS only gets a group's code, its number and how many photos it is in.
 - Photos you pick in JARVIS -> Connectors -> Google Photos are sent here one at a time.
 - A photo folder (optional, off until you choose one). Put copies of your photos in one folder
   on this laptop, for example C:\Users\you\Pictures\JARVIS, then in PowerShell as
   administrator, in C:\JARVIS-Home:
        powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir "C:\Users\you\Pictures\JARVIS"
   The bridge gets that folder read-only: it never changes, moves or deletes a photo. It reads a
   few new photos a minute. Only JPEG photos (.jpg, .jpeg) are read; iPhone HEIC photos are
   skipped (set the iPhone camera to "Most Compatible", or export as JPEG).
   To switch it off:
        powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir off
 - A face that is in 3 or more photos becomes a group. See WHO a group is on this laptop only:
   http://localhost:8098/faces -> "Faces from your photos" (the code is printed by the script).
 - Name a group in JARVIS -> Faces -> Unnamed groups (the person must agree first; a parent or
   guardian for a child). From then on new photos of that person, and the camera, recognise
   them with nothing more to do.
 - A group you do not name is forgotten after 90 days (FACE_GROUPS_KEEP_DAYS in bridge.env), and
   each group has "Forget this group", here and in JARVIS. Your photos are never touched.
 - The face reader uses two small open model files from OpenCV (YuNet, MIT licence; SFace,
   Apache-2.0 licence). The script downloads them and checks them; models\MODELS.txt lists them.
 - How a picture is kept safe to open: JPEG only; its size is read before it is opened; a photo
   from JARVIS is at most 2048 pixels a side and one photo a request; your own larger photos are
   opened at a smaller size.
