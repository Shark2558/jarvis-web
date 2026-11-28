// src/jarvis/api/static/console-coach-bp.js -- R8 builder D, row 262's reading (docs/plans/r8-vision.md v8.0.4 D7, seam
// S26). PURE (held to the use-case guard, `export` aside): numbers in, numbers out; no page, network, storage, camera
// or engine, and it keeps nothing. The monitor's seven-segment display is read by the engine's `digits` task (its
// body, segment arithmetic, is in console-vision-r8.js: the engine alone sees pixels); this is the rule that turns
// that task's lines into what the pane shows him, the same rule as jarvis.coach.bp.proposal_from_digits: three lines
// top to bottom, each read with a score of at least READ_MIN_SCORE, the top number the larger; else null (never a
// guess). The desk pane shows the proposal; he confirms or corrects it; only then is it sent (POST
// /v1/coach/bp/readings), and the server keeps only a confirmed reading (BpConfirm).
export const READ_MIN_SCORE = 0.8;
const within = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
export function proposal(lines) {
  if (!Array.isArray(lines) || lines.length !== 3 || lines.some((l) => !l || !(l.score >= READ_MIN_SCORE))) return null;
  const [s, d, p] = lines.map((l) => l.value);
  if (!within(s, 60, 260) || !within(d, 30, 160) || !within(p, 30, 220) || d >= s) return null;
  return Object.freeze({ systolic: s, diastolic: d, pulse: p });
}
// R8 I1 (the review's safety items): the same words as jarvis.coach.bp (tests/test_r8_i1_safety.py holds them equal).
// A screen the reader can't be sure of is never a guess: the pane says CANT_READ. Above 180/120 the pane shows the
// American Heart Association's own steps, its source named, before anything else; never a diagnosis or a dose.
export const CANT_READ = "I can't read that screen. Please type the numbers, or hold it up and retake.";
export const SEVERE_SYSTOLIC = 180, SEVERE_DIASTOLIC = 120;
export const SEVERE_STEPS = 'Above 180/120, the American Heart Association (Blood Pressure Categories, 2025) says: wait'
  + ' 5 minutes and measure again. If it is still that high, contact your doctor right away. If'
  + ' there is chest pain, shortness of breath, back pain, numbness or weakness, a change in'
  + ' vision or difficulty speaking, call emergency services now (112 in India).';
export function steps(reading) { // the AHA's steps for a reading above 180/120 (either number), else null
  if (!reading || !Number.isInteger(reading.systolic) || !Number.isInteger(reading.diastolic)) return null;
  return reading.systolic > SEVERE_SYSTOLIC || reading.diastolic > SEVERE_DIASTOLIC ? SEVERE_STEPS : null;
}
export function shown(lines) { // what the pane shows for the camera's lines: a proposal to confirm, or CANT_READ
  const p = proposal(lines);
  return Object.freeze(p ? { proposal: p, steps: steps(p), words: '' } : { proposal: null, steps: null, words: CANT_READ });
}
