// src/jarvis/api/static/console-vision-r8.js -- R8 I0 stub (docs/plans/r8-vision.md 4.2, seam S3; owner from I0 on:
// R8 builder A). The bodies of two engine tasks whose shells console-vision.js registers before its seal:
//   pose  v2  MediaPipe Pose Landmarker with 2 poses (lite at the desk; full on the workout phone when its setup test
//             keeps 15 frames a second, D4): follows the body that started the look alone (the torso centre's
//             continuity), DROPS every other body's points here and sets `others` (0 or 1). Data {points: 33 x {x, y, z,
//             visibility}, others}. A second body never leaves this module (ADR-48).
//   hands v1  MediaPipe Hand Landmarker, VIDEO mode, up to 2 hands. Data {hands: [{side: 'left'|'right', score,
//             points: 21 x {x, y, z}}]}
// Imported on first use by console-vision.js (an ES module); called only from there, never by a use case. The engine
// hands each call its own kit (KIT8): NOT_INSTALLED, NO_PICTURE, POSE_MODEL, POSE_FULL_MODEL, HAND_MODEL, MP_FILES,
// look(frame, fn), qualityOf(src), clamp, model(name) (r7-1), model8(name) (r8-1), mp() (the MediaPipe runtime),
// sha256hex(bytes). This file reads no camera, sends nothing and keeps no frame. ASCII source.
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

/** The page left: close the landmarkers (I0: none are open). */
export function unload() {}
