Version v8.0.1 · 28 Nov 2026, 05:50 IST · Release R8 · Status: Current · Owner: 🛠 Mark XXVI

# R8 and R8.1 — the rows' success checks, from the workbook

The plan (`docs/plans/r8-vision.md` v8.0.4, section 2) writes each row's acceptance test; this page copies the workbook's own words for the same rows, **verbatim**, so the builders and the review see both. Source: the owner's requirements workbook `JARVIS_Requirements_Complete_v13.1.10.xlsx` (kept outside the repository), sheet **Requirements**, column "Your one check", and sheet **Vision use cases**, column "Success check (your sheet's KPIs)". Where the workbook's figure is stricter than the plan's, the workbook's wins (plan section 2). "Camera" is where each row looks after the owner's D3 (28 Nov 2026).

## R8 `v8.0.0` (14 rows)

| Row | Feature (workbook) | Workbook release | Camera | Your one check (verbatim) | Success check, the Vision use cases sheet (verbatim) | Use case |
|---|---|---|---|---|---|---|
| 216 | Vision engine on the device: browser, phone and home laptop | R8 | — | A rep count runs with the Wi-Fi off. | — (not a vision use case row) | — |
| 217 | Camera setup: each camera and its spot, per-camera and per-room off switches, "Jarvis, cameras off", camera health on Vitals | R8 | — | "Jarvis, cameras off" turns every camera light off. | — (not a vision use case row) | — |
| 184 | Indoor-camera privacy controls | R8 | — | A family member in frame leaves no record. | — (not a vision use case row) | — |
| 377 | A home camera that works with JARVIS and your laptop with no cloud service | R8 | — | — | — (not a vision use case row) | — |
| 181 | Posture checks from the camera | R8 | home | Slouch 10 min → a nudge. | Static-duration accuracy; reminder acceptance; retention | HF-02 |
| 182 | Activity timeline (desk, away, phone, eating) | R13 | home | The day's timeline shows. | — (not a vision use case row) | — |
| 183 | Screen time via ActivityWatch | R13 | — | Top apps/sites for today show. | — (not a vision use case row) | — |
| 224 | Gesture-Controlled Fitness Reaction Game | R8 | webcam | Exit check: Target hit precision; reaction-event timing; completion rate | Target hit precision; reaction-event timing; completion rate | HF-25 |
| 227 | Adaptive Seated Fitness Movement Coach | R8 | home | Exit check: Rep-count error by movement; user comfort; false prompts | Rep-count error by movement; user comfort; false prompts | HF-21 |
| 238 | Visual Breath-Pacing Companion | R8 | webcam | Exit check: Rhythm-match error vs manual observation | Rhythm-match error vs manual observation | HF-47 |
| 248 | Water-intake logger at the desk | R9 | webcam | Exit check: Drink-event F1; user correction rate; false logs | Drink-event F1; user correction rate; false logs | DN-06 |
| 262 | Home Blood-Pressure Measurement Posture Coach | R10 | home (checklist); webcam (reading) | Exit check: Visible setup checklist accuracy; prompts per session | Visible setup checklist accuracy; prompts per session | HC-86 |
| 268 | Hand & Finger Rehabilitation Exercise Game | R10 | webcam | Exit check: Task count error; finger-gesture F1; adherence | Task count error; finger-gesture F1; adherence | HC-17 |
| 276 | Occupational Therapy Reach-and-Grasp Task Scoring | R10 | webcam | Exit check: Task completion agreement; reach timing error; missed grasps | Task completion agreement; reach timing error; missed grasps | HC-19 |

## R8.1 `v8.1.0` (20 rows)

| Row | Feature (workbook) | Workbook release | Camera | Your one check (verbatim) | Success check, the Vision use cases sheet (verbatim) | Use case |
|---|---|---|---|---|---|---|
| 132 | Workout rep counting (merged with your HF-03 rep & tempo counter) | R8 | tripod phone | — | Count error; valid-rep precision; tempo error | HF-03 |
| 218 | Dynamic Warm-Up Exercise Checklist | R8 | tripod phone | Exit check: Exercise presence precision; missed-step rate | Exercise presence precision; missed-step rate | HF-38 |
| 219 | Resistance-Band Exercise Tracker & Anchor Visibility Prompt | R8 | tripod phone | Exit check: Exercise-count error; anchor-visibility recall; false prompts | Exercise-count error; anchor-visibility recall; false prompts | HF-24 |
| 220 | AI Personal Trainer & Form Corrector | R8 | tripod phone | Exit check: Repetition error; trainer agreement; feedback latency | Repetition error; trainer agreement; feedback latency | HF-01 |
| 221 | Smart Yoga & Mobility Coach | R8 | tripod phone | Exit check: Pose accuracy; hold-time error; user usefulness | Pose accuracy; hold-time error; user usefulness | HF-04 |
| 222 | Plank Hold Duration & Alignment Coach | R8 | tripod phone | Exit check: Hold-time MAE; false form warnings; pose confidence | Hold-time MAE; false form warnings; pose confidence | HF-16 |
| 223 | Home Workout Space Clearance Checker | R8 | tripod phone | Exit check: Visible obstacle recall; nuisance alerts; user action rate | Visible obstacle recall; nuisance alerts; user action rate | HF-22 |
| 226 | Single-Leg Balance & Stability Coach | R8 | tripod phone | Exit check: Hold-time error; task-state F1; repeatability | Hold-time error; task-state F1; repeatability | HF-07 |
| 228 | Shadowboxing Punch & Combination Tracker | R8 | tripod phone | Exit check: Punch-event precision/recall; combination accuracy; latency | Punch-event precision/recall; combination accuracy; latency | HF-08 |
| 230 | Agility Drill & Cone-Crossing Timer | R8 | tripod phone | Exit check: Split-time error; crossing F1; missed drill events | Split-time error; crossing F1; missed drill events | HF-13 |
| 231 | Pilates Movement-Sequence Adherence Coach | R8 | tripod phone | Exit check: Sequence recall; hold-time error | Sequence recall; hold-time error | HF-34 |
| 232 | Tai-Chi Form Sequence & Flow Reviewer | R8 | tripod phone | Exit check: Form-step recognition F1; sequence completion | Form-step recognition F1; sequence completion | HF-35 |
| 235 | Jump Height & Landing Mechanics Analyzer | R8 | tripod phone | Exit check: Flight-time error; jump count; expert agreement | Flight-time error; jump count; expert agreement | HF-06 |
| 236 | Dance Choreography Synchronization Coach | R8 | tripod phone | Exit check: Timing error; instructor rating agreement; fairness across styles | Timing error; instructor rating agreement; fairness across styles | HF-09 |
| 237 | Handstand hold drift & safe exit (with a wall or spotter only) | R8 | tripod phone | Exit check: Hold duration MAE; reposition-event precision | Hold duration MAE; reposition-event precision | HF-113 |
| 239 | Kettlebell Swing Path & Hip-Hinge Feedback | R8 | tripod phone | Exit check: Swing count error; hinge-phase agreement | Swing count error; hinge-phase agreement | HF-99 |
| 240 | Assisted Stretching Partner-Interaction Monitor | R8 | tripod phone | Exit check: Phase F1; practitioner agreement | Phase F1; practitioner agreement | HF-70 |
| 263 | Remote Six-Minute Walk Test Lap & Turn Counter | R10 | tripod phone | Exit check: Lap count accuracy; turn event recall | Lap count accuracy; turn event recall | HC-101 |
| 269 | Sit-to-Stand Functional Test Assistant | R10 | tripod phone | Exit check: Repetition agreement; test-time error; measurement reliability | Repetition agreement; test-time error; measurement reliability | HC-06 |
| 247 | Eating Pace & Meal Duration Tracker | R9 | tripod phone | Exit check: Gesture precision/recall; meal duration error; user comfort | Gesture precision/recall; meal duration error; user comfort | DN-03 |

## Notes for the builders

- **Row 181:** the workbook's check is "a nudge after 10 minutes of slouching"; the plan nudges after 60 seconds held, at most 3 an hour. The plan's figure is the stricter one (an earlier nudge), so it stands; the eval also proves the workbook's 10-minute case.
- **Row 184 conflicts with the owner's D6 (28 Nov, 04:33 IST):** the workbook says "A family member in frame leaves no record"; his later answer is "Keep everything and save the results" (a family member is saved under their name if enrolled with consent, else as a session's "Guest N", deletable in Privacy). The later answer is built; the workbook's check needs his confirmation and a new wording (open item for the review).
- **Row 217 and D11:** "turns every camera light off" holds for the webcam and the phone (their track stops). For the home camera, "cameras off" stops the coaches' looking on the laptop, but Frigate keeps its stream for the burglar alarm (D11: it never disarms the alarm), so the home camera's own light may stay on while the alarm is armed. Open item for the review.
- **Rows 182 and 183** have no row on the Vision use cases sheet; their checks are the Requirements sheet's and the plan's.
- **Rows 216, 217, 184 and 377** are the engine, camera setup, privacy and the no-cloud check: no use case.
- **Row 132** is the Vision sheet's HF-03 ("Exercise Repetition & Tempo Tracker"), recorded there against the v2 row "Workout rep counting".
- The workbook's "Release" column still shows the releases before the 14 Nov build lists for rows 132, 182, 183, 247, 248, 262, 263, 268, 269 and 276 (plan section 2, "Row placement"); the Workshop changes them when it regenerates chapter 10.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v8.0.1 | 28 Nov 2026, 05:50 IST | R8 | First edition: the 34 rows' "Your one check" and the Vision use cases sheet's success checks, verbatim from workbook v13.1.10; each row's camera after D3; notes where the plan and the workbook differ | 🛠 Mark XXVI |
