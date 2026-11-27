// src/jarvis/api/static/console-vision-r8.js -- R8 I0 stub (docs/plans/r8-vision.md 4.2, seam S3; owner from I0 on:
// R8 builder A). The bodies of two engine tasks whose shells console-vision.js registers before its seal:
//   pose   v2  MediaPipe Pose Landmarker with up to 4 poses (lite in the browser; full on the workout phone when its setup
//              test keeps 15 frames a second, D4). The owner's D6: everyone in view. Each body gets a `track` that follows
//              it from frame to frame (the torso centre's continuity). Data {bodies: [{track: 0..63, who: '', points: 33 x
//              {x, y, z, visibility}}]}: `who` is always '' here (no face is matched in a browser; the engine's driver
//              calls a lone body 'me', and the home laptop names enrolled people)
//   hands  v1  MediaPipe Hand Landmarker, VIDEO mode, up to 2 hands. Data {hands: [{side: 'left'|'right', score,
//              points: 21 x {x, y, z}}]}
//   digits v1  a seven-segment display's numbers (D7: a blood-pressure monitor's), from one frame on a tap. Data {lines:
//              [{value: 0..999, score}]} top to bottom, at most 4; the method (segment arithmetic, or a pinned model with a
//              permissive licence recorded in the r8-1 manifest) is builder D's, with A
// Imported on first use by console-vision.js (an ES module); called only from there, never by a use case. The engine
// hands each call its own kit (KIT8): NOT_INSTALLED, NO_PICTURE, POSE_MODEL, POSE_FULL_MODEL, HAND_MODEL, MP_FILES,
// look(frame, fn), qualityOf(src), drawn(src, side), clamp, model(name) (r7-1), model8(name) (r8-1), mp() (the
// MediaPipe runtime), sha256hex(bytes). This file reads no camera, sends nothing and keeps no frame. ASCII source.
//
// I0: neither body is built. Each load reads its model file first, so a file that has not arrived is "not installed"
// and a server that fails is "could not load" (R7's words), then says "not installed": the task is not built yet.

/** Pose v2's landmarker; I0: not built. */
export async function loadPose(kit) {
  await kit.model(kit.POSE_MODEL);
  throw new Error(kit.NOT_INSTALLED);
}

/** One frame through pose v2 -> {data: {points, others}, quality}; I0: never reached (loadPose refuses). */
export async function runPose(frame, opts, kit) {
  throw new Error(kit.NOT_INSTALLED);
}

/** The hand landmarker; I0: not built. */
export async function loadHands(kit) {
  await kit.model8(kit.HAND_MODEL);
  throw new Error(kit.NOT_INSTALLED);
}

/** One frame through the hand landmarker -> {data: {hands}, quality}; I0: never reached. */
export async function runHands(frame, opts, kit) {
  throw new Error(kit.NOT_INSTALLED);
}

/** The seven-segment reader; I0: not built (nothing to fetch yet, so plainly "not installed"). */
export async function loadDigits(kit) {
  throw new Error(kit.NOT_INSTALLED);
}

/** One frame through the reader -> {data: {lines}, quality}; I0: never reached. */
export async function runDigits(frame, opts, kit) {
  throw new Error(kit.NOT_INSTALLED);
}

/** The page left: close the landmarkers (I0: none are open). */
export function unload() {}
