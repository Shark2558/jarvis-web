// src/jarvis/api/static/console-tryon-form.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D4, D16; AVT-03, AVT-05,
// OPS-05): the forms of Helpers -> Wardrobe -> Try it on, split out of console-tryon.js at I1 (review D-1 L12: the
// integrated reviews' fixes needed its room). Behaviour as it was there:
//   form(o)       his measurements (D4): each in whole cm, refused in its own words outside its range, marked typed or
//                 estimated; a draft shows on the figure until "Use these measurements" (the draft he saw: ?at=, 409 if
//                 it changed) or "Keep the current"
//   shapes(o)     his shape for each non-private piece of the look above (AVT-05): an approximate template of its slot,
//                 or its photo only, saved against the piece's id on the server
//   deleteAll(o)  OPS-05: Privacy's own delete of tryon_all (its passkey and its words), then o.reload()
// o = { H, api, btn, txt, failed(e), tryon(), look(), el: {form, shapes}, readTryon(), redraw(), reload() }: the section's
// own helpers and state (console-tryon.js). This module keeps nothing; no pixel API; textContent only. ASCII source.
import { MEASURE_WORDS, SHAPE_WORDS, slotWord } from './console-tryon-list.js';

export function form(o) {
  const h = o.H, box = o.el.form, t = o.tryon();
  if (!box || !t) return;
  const ver = (t.body && (t.body.draft || t.body.current)) || null, typed = new Set((ver && ver.typed) || []);
  const grid = h.mk('div', 'hp-grid tr-form'), err = h.mk('p', 'snote warn');
  err.setAttribute('role', 'alert');
  (t.ranges || []).forEach((r) => {
    const input = h.mk('input', 'minput');
    input.type = 'number'; input.inputMode = 'numeric'; input.min = String(r.low); input.max = String(r.high); input.step = '1';
    input.name = r.measure; input.value = ver ? String(ver[r.measure]) : '';
    input.setAttribute('aria-label', (MEASURE_WORDS[r.measure] || r.measure) + ' in cm');
    const f = h.mk('label', 'hp-field');
    f.append(h.mk('span', 'snote', (MEASURE_WORDS[r.measure] || r.measure) + ' (cm)'), input, h.mk('span', 'sfine', ver && !typed.has(r.measure) ? 'estimated' : ver ? 'typed' : ''));
    input.addEventListener('change', () => typeIn(o, r, input, err));
    grid.append(f);
  });
  const out = [h.mk('p', 'sfine', o.txt(t.words || '', 160)), grid, err];
  if (t.body && t.body.draft) {
    out.push(h.mk('p', 'snote', 'The figure shows your new measurements; your looks and saved comparisons keep their pieces.'));
    const a = h.mk('div', 'sacts');
    a.append(o.btn('Use these measurements', () => bodyStep(o, '/v1/tryon/body/use?at=' + encodeURIComponent(t.body.draft.at), 'POST')), o.btn('Keep the current', () => bodyStep(o, '/v1/tryon/body/draft', 'DELETE'))); // the draft he saw (409 if it changed)
    out.push(a);
  }
  box.replaceChildren(...out);
}
async function typeIn(o, r, input, err) {
  const v = Number(input.value);
  if (!Number.isInteger(v) || v < r.low || v > r.high) { err.textContent = o.txt(r.words, 120) + '.'; return; }
  err.textContent = '';
  const t = o.tryon(), ver = t.body && (t.body.draft || t.body.current), sent = {};
  ((ver && ver.typed) || []).forEach((k) => { sent[k] = ver[k]; });
  sent[r.measure] = v;
  try { t.body = await o.api('/v1/tryon/body', { method: 'PUT', body: sent }); } catch (e) { err.textContent = o.txt(e && e.message, 160); return; }
  o.redraw();
}
async function bodyStep(o, path, method) {
  try { o.tryon().body = await o.api(path, { method }); } catch (e) { o.failed(e); }
  o.redraw();
}

export function shapes(o) {
  const h = o.H, box = o.el.shapes, look = o.look();
  if (!box) return;
  const assets = new Map(((o.tryon() && o.tryon().assets) || []).map((a) => [a.piece, a]));
  const rows = ((look && look.slots) || []).filter((s) => !s.private && s.piece).map((s) => {
    const shapesOf = [...new Set([s.template].concat((s.options || []).map((x) => x.template)).filter(Boolean))];
    const a = assets.get(s.piece), now = a && a.card_only ? '' : (a && a.template) || s.template || '';
    const pick = h.mk('select', 'minput');
    pick.setAttribute('aria-label', 'Shape on the figure for ' + o.txt(s.words, 60));
    shapesOf.concat(['']).forEach((t) => { const x = h.mk('option', '', t ? (SHAPE_WORDS[t] || t) + ' (approximate)' : 'Image card only'); x.value = t; pick.append(x); });
    pick.value = now;
    pick.addEventListener('change', () => shapeOf(o, s.piece, pick.value));
    return h.row(slotWord(s.slot) + ': ' + o.txt(s.words, 60), now ? 'Drawn on an approximate shape; its photo stays beside it.' : 'Shown as its photo only.', [pick]);
  });
  box.replaceChildren(...(rows.length ? rows : [h.mk('p', 'sfine', 'The pieces of the look above will show here.')]));
}
async function shapeOf(o, piece, template) {
  try {
    await o.api('/v1/tryon/assets/' + encodeURIComponent(piece), { method: 'PUT', body: { piece, template: template || null, card_only: !template } });
    await o.readTryon();
  } catch (e) { o.failed(e); return; }
  shapes(o); o.redraw();
}

export async function deleteAll(o) { // OPS-05: Privacy's own delete of tryon_all (its passkey and its words); then re-read
  const P = window.JarvisPrivacy;
  if (!P || typeof P.remove !== 'function' || !(await P.remove('tryon_all'))) { o.failed(new Error('Open Privacy to delete your try-on data.')); return; }
  const gone = () => !document.querySelector('.pv-dlg');
  const obs = new MutationObserver(() => { if (gone()) { obs.disconnect(); o.reload(); } });
  obs.observe(document.body, { childList: true });
}
