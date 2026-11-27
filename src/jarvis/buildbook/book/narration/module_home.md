---
chapter: module_home
written_by: Workshop · Mark XXV
written_on: 2026-11-27
pages:
  "pg_module_home": "84ab717f3a1d6615"
  "pg_card_c38": "878bdff01668da4f"
  "pg_card_c39": "facffb4d93b62f5b"
  "pg_card_c40": "92ceecbea281d688"
  "pg_card_c63": "1ec495ec172f1e84"
  "pg_screen_home": "c5657891cbd889b1"
  "pg_screen_camera": "a0ff692ea924168c"
  "pg_service_frigate": "6ae656a399dd6aaf"
  "pg_service_home_assistant": "d38f3d1da741a5f1"
  "pg_service_mosquitto": "1b5bf6f3e7f572ff"
  "pg_service_tailscale": "b9ba8ed4591fc12f"
---
- [page:pg_module_home] [show:title] This chapter is about how JARVIS reaches your home: the alarm, the cameras, your devices, and the camera on your phone.
- [show:plain] A small bridge runs on your home laptop, beside Home Assistant for your devices, Frigate for your cameras, and Mosquitto for the messages between them.
- The JARVIS in the cloud talks to that bridge only over a private, signed link.
- So you can arm the burglar alarm, ask who was at the gate yesterday, and hear when a parcel arrives.
- Separately, the Camera panel lets your phone or laptop read text, codes and labels on the device itself.
- [show:overview] Here is what happens when someone walks up to a camera while the alarm is armed.
- [node:arm] It starts with you, arming the alarm in the Home panel.
- [edge:arm>frigate] [node:frigate] Now Frigate, the camera watcher, spots a person in a zone you drew.
- [edge:frigate>bridge] [node:bridge] It passes the sighting to the bridge, which filters it at home: only while armed, for a known label, and the first time in an alarm zone.
- [edge:bridge>watchdog] All the while, the bridge also sends a regular heartbeat to the cloud.
- [node:watchdog] [count:{{fact:settings.home_offline_after_s}}] With no heartbeat for {{fact:settings.home_offline_after_s}} seconds, the watchdog marks the laptop offline and tells you once.
- [edge:bridge>sign] [node:sign] A sighting that passes is signed and sent to the cloud, with a separate key for each direction.
- [edge:sign>webhook] [node:webhook] At JARVIS's door, the signature is checked before anything is read, and a message over {{fact:src/jarvis/home/signing.py:MAX_SKEW_S}} seconds off, or replayed, is turned away.
- [edge:webhook>refused] A bad signature is refused silently, without a word back.
- [edge:webhook>alert] [node:alert] A good one rings an urgent alert on your phone, before anything else happens.
- [edge:webhook>feed] [node:feed] It is also kept in the home feed, sealed, with ids and times only.
- [edge:alert>disarm] [node:disarm] To switch the alarm off, you need your passkey or a fresh Google sign-in, and the disarm is audited first.
- [show:how] [count:{{fact:src/jarvis/home/client.py:TIMEOUT_S}}] When the cloud calls home, it reaches only the bridge's fixed doors, and gives up after {{fact:src/jarvis/home/client.py:TIMEOUT_S}} seconds.
- The home tools answer "is the house armed?" from the last heartbeat, and a lock or plug that needs a passkey becomes a card with one.
- The brief's "Home overnight" line is written from fixed words and counts, never a name or a picture.
- [show:example] In the made-up example, Rhea arms the alarm as Away before a weekend away, and within a minute her laptop confirms.
- On Saturday afternoon Frigate sees a person at the back door, her phone rings, and it is the gardener, a day early.
- [show:costs] The software costs nothing: it runs on your laptop or in your browser, and asking the AI about a photo is the one paid step.
- [show:fails] With the laptop off, the home tools say so plainly, and if the disarm's audit entry can't be written, nothing is switched off.
- [page:pg_card_c38] [show:title] Now the first part: the home link.
- [show:plain] It is how the server in the cloud and the bridge on your laptop learn to trust each other, and keep doing so.
- [show:overview] Here is how the laptop is linked, once.
- [node:press] [edge:press>code] You press Link, under Integrations, and JARVIS makes a one-time code, keeping only a hash of it.
- [node:code] [count:{{fact:src/jarvis/home/link.py:CODE_LEN}}] The code has {{fact:src/jarvis/home/link.py:CODE_LEN}} characters, lasts {{fact:src/jarvis/home/link.py:CODE_TTL_S}} seconds, works once, and dies after {{fact:src/jarvis/home/store.py:MAX_CODE_TRIES}} wrong tries.
- [edge:code>bridge] [node:bridge] You type it into the laptop's setup script, and the bridge sends it to JARVIS with its address.
- [node:check] [edge:check>test] JARVIS checks that address, then sends a signed test call to the laptop.
- [node:test] The test call proves that the laptop at that address is the one that asked.
- [edge:test>save] [node:save] When the answer comes back signed, the link is saved, sealed with the home key.
- [edge:test>retry] [node:retry] If no answer comes, the code is kept for a retry, and the failed call doesn't count as a wrong try.
- [show:how] [count:{{fact:src/jarvis/home/signing.py:NONCE_TTL_S}}] Every message carries a time, a fresh random number and a signature, and a number seen in the last {{fact:src/jarvis/home/signing.py:NONCE_TTL_S}} seconds is refused.
- [count:{{fact:src/jarvis/home/ports.py:MAX_EXPOSED}}] You choose which devices JARVIS may see, at most {{fact:src/jarvis/home/ports.py:MAX_EXPOSED}}: lights are everyday, plugs ask for a passkey, and locks and gates always do.
- [show:example] In the example, the laptop falls asleep one night while the alarm is armed, and minutes later your phone rings: camera alerts are off until it is back.
- [show:costs] It costs nothing: the link, the signing and the watchdog are JARVIS's own code.
- [show:fails] A replayed, late or unsigned message gets a bare refusal, and a link record that can't be read is never overwritten.
- [page:pg_card_c39] [show:title] The second part is the home bridge itself.
- [show:plain] It is the only thing at home the internet can reach, and it answers only signed calls from your own JARVIS.
- It filters camera events at home, keeps faces and photos there, and serves a private Faces page that opens only on the laptop.
- [show:how] [count:{{fact:src/jarvis/homebridge/heartbeat.py:DEFAULT_INTERVAL_S}}] Every {{fact:src/jarvis/homebridge/heartbeat.py:DEFAULT_INTERVAL_S}} seconds, its heartbeat reports how Home Assistant, Frigate, the cameras and faces are doing.
- [count:{{fact:src/jarvis/homebridge/snapshot.py:MAX_LONG_SIDE}}] One small snapshot may go with an alert, only if you opted in, cleaned of all metadata, at most {{fact:src/jarvis/homebridge/snapshot.py:MAX_LONG_SIDE}} pixels on its long side.
- [count:{{fact:src/jarvis/homebridge/retention.py:UNKNOWN_HOURS}}] Face attempts of strangers are deleted after {{fact:src/jarvis/homebridge/retention.py:UNKNOWN_HOURS}} hours, and the others after {{fact:src/jarvis/homebridge/retention.py:KEPT_DAYS}} days.
- Your photos folder is mounted read-only, and unknown faces seen in at least {{fact:src/jarvis/homebridge/face_types.py:MIN_GROUP_PICS}} pictures form a group for you to name or forget.
- When you sign in on the laptop, the home kit starts, and the call desk with it when it is installed on the same laptop.
- [show:example] In the example, a person walks into the driveway zone in the small hours, and the bridge sends one short detection; a cat a minute later sends nothing.
- [show:costs] The software costs nothing; the laptop's electricity is yours, and its amount is Unverified here.
- [show:fails] A face model that is missing, or not the pinned one, is never loaded; the camera keeps working, and the photos wait.
- [page:pg_card_c40] [show:title] The third part is the camera, the alarm and its history.
- [show:plain] You arm the burglar alarm, Away or Night, and a spoken word, a chat or a Telegram message never disarms it.
- [show:how] The alarm says armed only once the laptop confirms, and a detection that arrives while disarmed is dropped.
- Recognising someone never softens an armed alert, and a child is never named in one.
- [count:{{fact:src/jarvis/camera/models.py:FEED_KEEP_DAYS}}] The home feed keeps {{fact:src/jarvis/camera/models.py:FEED_KEEP_DAYS}} days, with names looked up only when you view it.
- History rebuilds every word from your labels and fixed words, so nothing the camera software writes reaches the brain.
- [count:{{fact:src/jarvis/camera/packages.py:FLAP_WINDOW_S}}] A parcel at the door sends one alert, and another parcel signal within {{fact:src/jarvis/camera/packages.py:FLAP_WINDOW_S}} seconds counts as the same change.
- [show:example] In the example, you ask who was at the gate yesterday, and hear about someone JARVIS didn't recognise, and a person it did.
- [show:costs] It costs nothing: the alarm, the feed and the history make no AI call.
- [show:fails] [count:{{fact:src/jarvis/camera/models.py:ARM_FAIL_AFTER_S}}] An arm the laptop doesn't confirm within {{fact:src/jarvis/camera/models.py:ARM_FAIL_AFTER_S}} seconds sends one alert that JARVIS couldn't arm your home.
- If the arm record can't be read when a detection arrives, the alert still goes out, since a missed burglar is worse than a false alarm.
- [page:pg_card_c63] [show:title] The fourth part is the vision engine on your own device.
- [show:plain] It reads text, scans a QR code or barcode, checks if a picture is sharp, and, once their files are installed, spots objects or a pose.
- The picture never leaves the device unless you press a button that sends it, and JARVIS never keeps a frame.
- [show:how] Only one part of the console ever asks for the camera, only on your tap, and it stops when the page is hidden.
- [count:{{fact:src/jarvis/vision/results.py:TEXT_MAX}}] A kept result is checked against its task's shape, with text of at most {{fact:src/jarvis/vision/results.py:TEXT_MAX}} characters, and anything else is dropped.
- [count:{{fact:src/jarvis/vision/store.py:PER_DAY_MAX}}] Results are sealed, at most {{fact:src/jarvis/vision/store.py:PER_DAY_MAX}} a day, for {{fact:settings.vision_keep_days}} days, and the brain reads them fenced off as outside text.
- [show:example] In the example, you scan the QR code on a gas bill and keep its link, and later JARVIS lists it, marked as text other people wrote.
- [show:costs] Every task runs in your browser, so it costs nothing; only asking the AI about a photo costs a brain call.
- [show:fails] A vision file whose bytes don't match its recorded sum is never served, and without the token key nothing is kept.
- [page:pg_screen_home] [show:title] Now the screens, starting with Home.
- [show:plain] Home is your burglar alarm and gate camera in one panel; it is a home helper, not a monitored alarm service, as the panel warns.
- [show:overview] Here is how you arm the alarm, and later switch it off.
- [node:arm] You press Arm (Away) or Arm (Night).
- [edge:arm>arming] [node:arming] The panel shows Arming at once.
- [edge:arming>laptop] [node:laptop] The request reaches your home laptop, which confirms it.
- [edge:laptop>armed] [node:armed] Only then does the panel show Armed.
- [edge:armed>disarm] [node:disarm] Later you press Disarm, and the panel asks whether to switch off the burglar alarm.
- [edge:disarm>proof] [node:proof] You prove it is you, with your passkey for exactly this home, or a Google sign-in from the last few minutes.
- [edge:proof>off] [node:off] And the panel says the alarm is off.
- [show:how] Disarming works only from the console, and the Today and Yesterday list says what was seen, where, and whether you were alerted.
- [show:example] In the example, you search the history for yesterday's packages, and find the parcel left that afternoon.
- [show:costs] Home costs nothing to run: the camera, its detector and the recordings live on your own laptop.
- [show:fails] [count:{{fact:src/jarvis/api/camera.py:CHANGE_PER_MINUTE}}] With no camera given an alarm zone, Armed warns that nothing is protected yet, and changes are limited to {{fact:src/jarvis/api/camera.py:CHANGE_PER_MINUTE}} a minute.
- [page:pg_screen_camera] [show:title] Next, the Camera screen.
- [show:plain] It looks through this device's camera, or at a photo you choose, and that camera has its own off switch.
- [show:how] In Look you pick what to look for; Keep saves only the result, and Results lists what you kept, each with Delete.
- [show:example] In the example, JARVIS reads the batch and expiry off a medicine strip, and on the way out you say "Jarvis, cameras off".
- [show:costs] Looking is free, and asking the AI about a photo shows its rough price in rupees first.
- [show:fails] If the camera is blocked, busy in another app or missing, the panel says so in plain words.
- [page:pg_service_frigate] [show:title] Now the programs at home, starting with Frigate.
- [show:plain] Frigate is a free camera watcher that spots people and parcels, and keeps the recordings and the face library on your laptop.
- [show:how] [count:{{fact:settings.home_feed_days}}] Faces are named only for people added with consent, and the cloud keeps the alert feed for {{fact:settings.home_feed_days}} days, sealed.
- [show:fails] When Frigate stops answering, the Vitals board names it, and burglar alerts stop until you start the home kit again.
- [page:pg_service_home_assistant] [show:title] Next, Home Assistant.
- [show:plain] It talks to your lights, plugs and sensors, and the bridge reaches it with its own user, one that isn't an admin.
- [show:how] [count:{{fact:settings.home_heartbeat_s}}] The bridge's heartbeat comes every {{fact:settings.home_heartbeat_s}} seconds, and a hazard sensor you exposed rings even in quiet hours, unless you switched that off.
- [show:example] In the example, you ask from bed whether the kitchen plug is still on, and approve the card that switches it off.
- [show:fails] If Home Assistant stops answering, device commands fail with a short code, and a sensor you did not expose is ignored.
- [page:pg_service_mosquitto] [show:title] Then Mosquitto, the camera's messenger.
- [show:plain] It is a small, free post office on the laptop that carries the camera's news from Frigate to the bridge, and nothing on the internet reaches it.
- [show:fails] When the bridge loses it, the Vitals board says so, and the bridge keeps trying again, with a growing pause.
- [page:pg_service_tailscale] [show:title] Last, Tailscale.
- [show:plain] Its Funnel feature gives the laptop one safe public door, and the encryption ends on the laptop, so Tailscale sees only encrypted data.
- [show:how] [count:{{fact:settings.local_brain_timeout_s}}] JARVIS uses up to three such doors: the bridge, and the offline brain, where a call may take up to {{fact:settings.local_brain_timeout_s}} seconds because the laptop is slow.
- The third is the laptop speech kit's, on a port of its own, used only once you give JARVIS its address and key.
- [count:{{fact:settings.local_speech_health_s}}] JARVIS trusts the kit's health for {{fact:settings.local_speech_health_s}} seconds, and a kit that fails is left alone until then, while Google's speech takes over.
- [show:costs] JARVIS uses Tailscale's free personal plan; Unverified: the exact limits of that plan.
- That is the Home chapter: a bridge that keeps your home at home, a link that is always signed, and an alarm only you switch off.
