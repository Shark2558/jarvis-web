Version v7.0.2 · 13 Nov 2026, 22:10 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — putting the JARVIS app on your phone (your steps, Sir)

These are the steps for your Windows 11 laptop with **Android Studio Rabbit 2 | 2026.2.2 Patch 1** and your
**OnePlus 12R on Android 16**. They take about 30 minutes the first time and cost ₹0. The Workshop copies the
project to `C:\Jarvis\android` and writes your JARVIS address into it for you; you never type the address.

What the app is: an icon that opens the same JARVIS you use today, full screen in Chrome, plus a few small
parts of its own: the Talk and SOS tiles in the pull-down shade, alerts with JARVIS's icon, your watch's
steps, heart rate and sleep through Health Connect, the SOS screen, and sharing photos and PDFs into JARVIS.

One honest note before you start: this workspace could not open Android Studio itself, so a few menu words
below are taken from Google's descriptions rather than seen on your screen. Each one is marked *(words not
checked)*. If your screen says something slightly different, choose the item that means the same thing.

## A · In Health Connect first (5 minutes, on the phone)

1. Open **Settings → Health Connect** (on Android 16 it is part of Android) *(words not checked on OxygenOS)*.
   You should see a list that includes **App permissions** and **Data and access**. Open **Data and access**,
   then **Sleep**. After a night with the watch on, look for an entry from **NoiseFit**, and tell the
   Workshop whether you see one. Do the same under **Heart rate** (under Vitals). No entry yet is fine: the
   watch has to be worn overnight first.
2. **App priority.** In each of **Sleep**, **Steps** (under Activity) and **Heart rate**, open **App priority**
   and move **NoiseFit** to the top. Some Android versions call it "Data sources and priority" *(words not
   checked)*. You should see NoiseFit first in the list. This makes the watch's numbers win over the phone's
   and Google Fit's, so your steps are counted once.
3. Think of who your emergency contacts will be and whether they use Telegram. You add them later, in step C15.

## B · Today, with no app (optional, until the real app is installed)

1. On the phone open JARVIS in Chrome and sign in.
2. Tap the three dots, then **Add to Home screen**, then **Install**. You should see a JARVIS icon on your
   home screen. This icon is removed again in step C13, once the real app is installed.

## C · Build the app and install it (about 25 minutes)

1. Wait until the Workshop says "the project is in `C:\Jarvis\android`".
2. Open **Android Studio**. Choose **Open**, pick the folder `C:\Jarvis\android`, and press **OK**. If it
   asks whether to trust the project, choose **Trust Project**. You should see the project's files on the left.
3. Wait for the first **Gradle sync** to finish (the bar at the bottom of the window). The first time it
   downloads about 1.5 GB of Android tools, so allow 5 to 15 minutes. You should see "Gradle sync finished".
   - If a blue link offers to **Install missing SDK package** (or "Android SDK Platform 36"), click it,
     accept the licence, and press **Finish**.
   - **If the sync stops with a message about the Java or JDK version** (Android Studio Rabbit 2 runs on
     its own Java 25, which Google's pages do not promise for this project): open
     **File → Settings → Build, Execution, Deployment → Build Tools → Gradle**, set **Gradle JDK** to a
     version **17** or **21** (Studio offers to download one), press **OK**, then **File → Sync Project
     with Gradle Files**. This is step C3 in the plan.
   - If it stops with "Please add the line jarvis.host=… to android/local.properties, Sir", the address
     file is missing: tell the Workshop. Do not type an address yourself.
4. Open the **Build Variants** panel (on the left edge of the window, or **View → Tool Windows → Build
   Variants**) and set the variant of **app** to **personal** *(words not checked)*. You should see
   "personal" next to **app**.
5. Build the app: **Build → Generate App Bundles or APKs → Generate APKs**. Older Studio versions call the
   same menu **Build → Build Bundle(s) / APK(s) → Build APK(s)** *(words not checked on Rabbit 2)*. Wait for
   "Build completed" or "APK(s) generated" in a small message at the bottom right.
6. In that small message click **locate**. You should see a folder window with `app-personal.apk`. The file is
   `C:\Jarvis\android\app\build\outputs\apk\personal\app-personal.apk`.
7. Connect the phone with its USB cable. *What the OnePlus 12R on Android 16 is expected to show (the exact
   wording was not checked on your phone):* a notice such as "Charging this device via USB" in the pull-down
   shade. Tap it and choose **File transfer** (some versions say "Use USB for: File transfer"). On the laptop,
   open **File Explorer**: the phone appears under **This PC**. Open it, then **Internal storage → Download**,
   and copy `app-personal.apk` into **Download**. You should see the file there. (No USB debugging is needed.)
8. On the phone open **Files** (it may be called **My Files** or **File Manager**), then **Download**, and tap
   `app-personal.apk`. *Expected, wording not checked:* the first time, a screen says the phone is not allowed
   to **Install unknown apps** from this source. Choose **Settings**, switch on **Allow from this source**,
   and press Back. Then press **Install**. If Play Protect asks, choose **Install anyway** (or **More
   details**, then **Install anyway**): it is your own app, and it asks for no SMS, accessibility or
   notification-reading access. You should see "App installed" and an **Open** button.
9. Open **JARVIS** on the phone. You should see "JARVIS on this phone" and a box for a link code. On the
   laptop open JARVIS → **Integrations → Phone app → Link a phone**, confirm with your passkey, and type the
   8 characters it shows into the phone. Press **Link this phone**. The code works once, for 10 minutes. You
   should see a short list (Notifications, Watch data, SOS location, DigiLocker folder, tiles).
10. Do each line you want, now or later:
    - **Notifications → Allow**: alerts with the app closed. You should see Android's "Allow JARVIS to send
      notifications?" box.
    - **Watch data → Allow**: Health Connect opens its own screens. Allow **Steps**, **Heart rate** and
      **Sleep**. Then allow reading **in the background** on the second screen *(Android 16 has this switch
      under JARVIS in Health Connect → App permissions, often called "Additional access" or "Access data in
      the background")*. **If "in the background" is not offered**, skip it: the watch is then read only
      while JARVIS's set-up screen is open, and the line says so. Nothing is broken. NoiseFit stays first in
      App priority (step A2).
    - **SOS location → Allow**: choose **While using the app** and keep **Precise** on.
    - **DigiLocker folder → Pick a folder** (optional): choose the one folder where DigiLocker saves your
      documents. Android does not let any app watch the Download folder itself; if DigiLocker saves there,
      share each document to JARVIS instead (step F2).
    - **Quick Settings tiles → Add Talk** and **Add SOS**: Android asks whether to add each tile; choose
      **Add**. You should see each tile in the pull-down shade.
11. Press **Open JARVIS** and sign in with Google once. The first time you talk, Chrome asks for the
    microphone; the first time you open the camera, for the camera.
12. Add a passkey from this phone: in JARVIS open **Approvals → Permissions**, type a name such as
    "Phone", press **Add another passkey** and confirm on the phone. If the phone cannot offer one, stop
    and tell the Workshop: nothing is lost, and the app lock simply stays off.
13. If you installed JARVIS from Chrome earlier (step B), remove that older icon: long-press it →
    **Uninstall** (or **Remove**). Otherwise you have two JARVIS icons.
14. *(Optional)* Let the watch read run on time: **Settings → Apps → JARVIS → Battery** → allow background
    activity *(OxygenOS words not checked)*. Without it the 6-hourly read may wait until you open the app.
15. In JARVIS → **Integrations → Emergency SOS**: type your name as your family should see it, add a
    contact, send them the join link yourself, then press **Send a test** (or **Test SOS** in the phone's
    set-up screen). What you must see on your phone: a screen titled **Test SOS** with a 10-second count, a
    big **Cancel**, a **Call 112** button and **no** "Open the text message" button (a test never opens the
    text message app). Let it run: it ends with "Sent", and only YOU get a Telegram notice that a test was
    sent; your contacts get nothing. The **I'm safe** button is not shown for a test.
    **Check once with the phone locked** (unverified): pull the shade down on the lock screen and tap the SOS
    tile. Android may ask you to unlock first; that is normal. Tell the Workshop what happened.

## D · Updating later, and a new laptop

When the Workshop says "a new project is in `C:\Jarvis\android`", do steps C2 to C8 again. The new app
installs over the old one and nothing is lost. **Never uninstall JARVIS to update it** from the same
laptop: that throws away the phone's link, and you would link again (step C9).

**A new laptop, or a new debug key.** Android Studio signs the app with a "debug key" kept on your laptop.
A different laptop, a reinstalled Android Studio or a deleted `.android` folder makes a new key, and Android
then refuses to install the new app over the old one (it says "App not installed" or "signature mismatch").
Then: (1) **uninstall JARVIS once** (long-press the icon → **App info → Uninstall**), (2) install the new
`app-personal.apk` (steps C7 and C8), (3) **link the phone again** (step C9), and (4) tell the Workshop,
because the app's fingerprint changed and the site's link to the app (assetlinks) must be updated. Until it
is, a browser bar shows at the top of JARVIS; it goes after the Workshop updates the site and you wait about
10 minutes (step H). Keep the key safe: do not copy `.android` to a cloud folder.

## E · Using it

1. **Talk tile**: pull down the shade and tap **Talk to JARVIS**. JARVIS opens with the mic button ready;
   tap the mic button once and it listens. On a locked phone it asks you to unlock first.
2. **Long-press the JARVIS icon** for **Talk**, **Camera**, **SOS** and **Set-up**. (Talk and Camera
   reload JARVIS once when you use them while it is already open.)
3. **SOS tile or SOS shortcut**: a 10-second countdown with sound and vibration and a large **Cancel**
   button; the screen stays on while it counts. Cancel sends nothing. At the end JARVIS sends the Telegram
   message to your contacts and opens your SMS app with every number and the message filled in, for you to
   press Send. **Call 112**, **Open the text message** and **Call your first contact** are on the screen the
   whole time, and **I'm safe** appears after the send. Pressing the tile again after "Sent" or "Cancelled"
   starts a new countdown; pressing it during a countdown changes nothing. If you press Back or leave the
   screen for good during the countdown, it is cancelled and says so. Whether it works from the lock screen
   is **unverified, check on the phone** (step C15). This is a message to your family, not an emergency
   service: in danger, call 112, and set up Android's own Emergency SOS too (press the power button five times).
4. **Test SOS** (in the set-up screen): the same countdown, sending a test message on Telegram to you only.

## F · Sharing into JARVIS

1. In the Gallery (or any app) choose **Share → JARVIS** on a photo. JARVIS opens with the photo waiting in
   its tray; nothing reaches the server until you press one of the tray's buttons.
2. In DigiLocker open a document and press its **Share** button, then **JARVIS**. Choose **Add to my
   vault**, and JARVIS shows it in "Check details" for you to confirm.

## G · What each screen asks, and what happens if you say no

| Screen | Why | If you say no |
|---|---|---|
| Allow JARVIS to send notifications | Alerts with the app closed, sorted into Urgent, Alerts and Nudges | Alerts come on Telegram only |
| Health Connect: Steps, Heart rate, Sleep | Your watch's and phone's numbers for the brief and the Watch tab | The Watch tab stays empty; you can type your sleep |
| Health Connect: in the background | The read every 6 hours | The watch is read only while the set-up screen is open |
| Location: while using the app, precise | Your place in an SOS (asked once when the SOS screen opens, 10 seconds at most) | SOS still goes, saying "location not available" |
| Pick a folder | DigiLocker documents arrive by themselves | Share each document instead |
| Add the tile | Talk and SOS from the shade | Use the long-press shortcuts instead |
| Chrome: microphone / camera | Talking; the Camera panel | Typing only; shared photos still work |
| Create a passkey (step C12) | The app lock, and approvals on the phone | The app lock stays off; approvals need the laptop |

The set-up screen blocks screenshots. Battery: nothing listens or runs all the time; the app wakes for a
few seconds every 6 hours (watch) and about every hour (the folder, only if you picked one).

## H · If something goes wrong

- **"Install or update Chrome"** appears: JARVIS needs Chrome. Install or update it from the Play Store.
- **A browser bar shows at the top** after linking: wait 10 minutes, close JARVIS and open it again
  (Chrome checks the site-and-app link in its own time).
- **The link code is refused**: codes last 10 minutes and work once. Make a new one on the laptop.
- **The phone says "This phone needs linking again, Sir"**: the JARVIS server stopped recognising it (for
  example after you removed the phone on the laptop). Make a new code on the laptop and link again (C9).
- **A message says the phone's clock looks wrong**: set **Settings → System → Date and time → Set time
  automatically** on, then try again.
- **The first watch read is the first proof** that Health Connect's reading works on your phone (no test could
  run it): after step C10 open the set-up screen and press **Sync now**. If it says "Nothing to send yet", wear
  the watch for a day and try again.
- **Health Connect never opens its screens**: check Settings → Health Connect → App permissions lists
  JARVIS; tell the Workshop if it does not.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.2 | 13 Nov 2026, 22:10 IST | R7 | Review follow-ups: section B restored (Today, with no app) so the letters run A to H; App priority is A2 as in the plan; a new laptop or a new debug key (uninstall once, link again, assetlinks); what a OnePlus 12R on Android 16 is expected to show when installing over USB (wording not checked); what to see after each step; Health Connect's background switch missing; what a Test SOS shows; the lock-screen tile marked unverified; the clock and re-link messages | 🛠 Mark XVII |
| v7.0.1 | 13 Nov 2026, 19:50 IST | R7 | First edition (Part E): Health Connect's App priority, building `personal` in Android Studio Rabbit 2 with the Gradle JDK fallback (C3), installing over USB by file transfer, linking, the set-up list, the tiles, SOS, sharing, what each screen asks, and where the menu words were not checked | 🛠 Mark XVII |
