Version v18.0.0 · 27 Nov 2026, 13:55 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 — builder D · the phone app and the phone's cloud side (what I1 needs to know)

Written by builder D on branch `r18-d` (from `r18-i0`, I0's seams merged). Brief:
`BUILD-BRIEF.md` row D and its "Phone ↔ cloud" contract. No wiring file was edited; the server door
registration below is left to I1 because `tests/test_r7_seams.py` pins the four R7 routes.

## 1. The decision: how the cloud reaches the phone

R7 has no cloud → phone channel for the app itself, only Web Push that Chrome hands to the app's
notification service (R7 D10); no Firebase, no foreground service (R7 D9, D22). So **Web Push is
the doorbell and the door carries the commands**: `PhoneCalls.send` signs a command, queues it
for the phone and sends one push of kind `call_command` (a plain sentence, never a number or a
name); the app's notification service sees that kind and asks `POST /phone/v1/calls`, whose
answer carries the pending commands. The phone also asks on every call-state change and when the
app opens, and may wait up to 25 s for a command. Each command is signed by the cloud (P-256,
`jarvis-cloud-v1`) and checked on the phone (key from the door's answer, this phone, time, never
acted on). Shapes: `src/jarvis/phone/calls_wire.py`; vectors: `tests/fixtures/r18/phone_calls_vectors.json`.

## 2. What D built

| Part | Where | State |
|---|---|---|
| Commands `call.dial/answer/end/route` (I0's protocol, `from_protocol`) and `call.card`; the cloud's signer; the strict `calls` door body (`call.state`, `call.result`, `card.decision`) | `src/jarvis/phone/calls_wire.py` | built, tested |
| `PhoneCalls`: outbox per phone (16, TTLs), doorbell, dial only with a live approval (fail closed), events strict + fresh + deduplicated + rate-limited (40/min/phone), incoming number only while answering is on, masked numbers in logs and audit, readiness; `OwnerPhoneLink` = I0's `PhoneLink` | `src/jarvis/phone/calls.py` | built, tested (95 %) |
| Android core: strict JSON reader, command verification, door body, call state machine | `android/core/.../{JsonRead,Calls,CallMachine}.kt` | built, 102 JVM cases pass |
| Android app: permissions + first-run screen, doorbell hook, dial / answer / end / route, "Tap to let JARVIS call <name>", Approve / Decline card notification, PHONE_STATE receiver, Calls panel launcher; version 18.0.0 (code 2) | `android/app/.../calls/*`, `shell/{JarvisDelegationService,LaunchGate}.kt`, manifest | built; compiled by CI only |
| APK checker and R7 tests allow the four call permissions; CI reads the R18 vectors and has two new negative controls | `scripts/apk_check.py`, `.github/workflows/android.yml`, `tests/test_r7_e_{manifest,workflow}.py` | done |

## 3. Needs I1

1. **Register the door route `calls`.** `jarvis/mobile/ports.py`: add `"calls"` to `DoorRoute`,
   `DOOR_OWNER["calls"] = "phone"`, `DOOR_CAPS["calls"] = phone.calls.DOOR_CAP` (16 KB).
   `jarvis/mobile/contract.py` `_PATH`: `hello|health|inbox|sos|calls`. Update
   `tests/test_r7_seams.py` (lines 325–326) to the five routes.
2. **Build one `PhoneCalls`** where the phone part is built (`jarvis/phone/part.py`) and offer its
   route: `services["door"] = {**svc.handlers.services(), **phone_calls.door_handlers()}` and
   `services["phone_calls"] = phone_calls`. Arguments: `phones=StoreDirectory(svc.store)`,
   `signer=CommandSigner.from_secret(ring.secret("calls_phone", length=48))` after adding
   `"calls_phone"` to `keyring.SECRET_PURPOSES` (else `CommandSigner.ephemeral()`),
   `doorbell=PushDoorbell(lambda: ctx.state("push"))`, `audit=ctx.audit`.
3. **Late wiring** (public attributes, all fail closed while unset): `phone_calls.approvals` = A1's
   `ApprovalCheck` (`live_until(uid, approval_id, call_id, number)`, must not spend the token;
   **until it is set every dial is refused**); `phone_calls.sink` = A2's engine (`PhoneEventSink`:
   `phone_state(uid, CallStateEvent)`, `phone_result(uid, PhoneCommandResult)`);
   `phone_calls.cards` = A1's `CardDesk.decide(...)`; `phone_calls.answering` = A1's
   `AnsweringView.rule(uid)`. A2's engine holds `OwnerPhoneLink(phone_calls, uid)` as its
   `PhoneLink`; `send` raises `PhoneCommandRefused(code)` when nothing was queued.
4. **The card on the phone**: when a card waits for approval, `phone_calls.send(uid,
   Card.for_card(card, expires_at=...))` shows Approve / Decline; Approve of a card with
   `new_number` opens the console's Calls panel for the passkey (`/?source=app&open=calls`).
5. **Console (E)**: the launch address `/?source=app&open=calls` must open the Calls panel (the
   R7 `open=` allow-list in `console-r7-links.js`). Optional: `"call_command": "calls"` in
   `webpush/service.py` `TARGETS`, so the laptop's doorbell notification opens Calls too.
6. **Ready check**: `calls_api.status` can show `await phone_calls.readiness(uid)` (`problems`:
   `no_phone`, `not_checked_in`, `cannot_place`, `cannot_answer`, `no_call_state`,
   `no_notifications`).
7. **What Android cannot tell**: an outgoing call stays `dialing` until it ends (no "answered"
   signal for an ordinary app); A2 should take the desk's voice detector as "they picked up".
   `call.route` usually reports `route_refused` (Android gives the call's route to the dialer):
   the console then tells him to tap "Phone" on the call screen.

## 4. The owner's steps on his phone

1. Install the new app build (About: 18.0.0) from his laptop as for R7, and open it.
2. The calls screen opens once: tap **Allow calls** (make and manage calls, answer calls, phone
   state). Only if he will let JARVIS answer missed calls from saved contacts only (or everyone
   except them): **Who is calling → Allow** (call log). If Android greys that out: App info → ⋮ →
   Allow restricted settings, then try again.
3. Keep JARVIS's notifications on (the doorbell rides on them) and set the app's battery use to
   **Unrestricted** (Settings → Apps → JARVIS → Battery), so a command or a ringing call is not
   held back.
4. Phone Link on the laptop with calls set up over Bluetooth (no Bluetooth headset on the laptop).
5. Live checks: one approved call with the phone locked in his pocket (does it dial by itself, or
   does "Tap to let JARVIS call …" appear?), one Take over (does the sound move to the phone, or
   does he tap "Phone"?), and, if answering is on, one missed call.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v18.0.0 | 27 Nov 2026, 13:55 IST | R18 | First edition: the doorbell + door decision, what D built, what I1 wires, the owner's phone steps | 🛠 Mark XXV |
