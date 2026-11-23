// src/jarvis/api/static/console-book-writer.js -- R6.3 D6, D7, D11, D12 (docs/plans/r6-3-book-content.md): Book settings ->
// Book writer: the Writer trial (the estimate first, what is sent and to whom, the YES box, "Step while I watch", both brains'
// sample pages side by side with their checks), the Writer (the brain, the tier never offered, the caps from the pick, "update
// by itself"; every grant shows the SERVER's rupee words above the YES box), the first write's YES, Update's YES, Stop, and the
// 80 % storage line at the top of the panel. console-book.js loads it ONCE and calls settings(host, deps) (deps = { api,
// booked, ask, say, render, token(), release(), top }); it reads GET /v1/book/writer whenever its host is shown. The YES box is
// never filled and sends what was typed (the server decides); no rupee from the page is trusted; never a dollar. Off or not
// reachable: nothing is drawn (the panel as it was). buildbook/writer/http.py. CSP script-src 'self'; textContent; ASCII.
(() => {
  'use strict';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
  const W = '/v1/book/writer', EST = /^we_[0-9a-f]{12}$/, TERMS = /^wt_[0-9a-f]{12}$/, BRAIN = /^[A-Za-z0-9_.:-]{1,40}$/, SVG = 'http://www.w3.org/2000/svg';
  const PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/, STEP_GAP_MS = 10000; // step: 6 a minute (http.LIMITS), one at a time
  const CAPS = [['first', 'First full write, one time (\u20b9)', 'bkCapFirst'], ['release', 'Each release (\u20b9)', 'bkCapRelease'],
    ['month', 'Each month (\u20b9)', 'bkCapMonth'], ['limit_pct', 'Stop before this share of your monthly limit (%)', 'bkCapPct']];
  const BOUNDS = { first: [0, 5000], release: [0, 2000], month: [0, 5000], limit_pct: [10, 100] }; // writer.model.CAP_BOUNDS
  const DEFAULTS = { trial: 100, first: 1500, release: 500, month: 1000, limit_pct: 80 }; // writer.model.Caps
  const CHECKS = { incomplete: 'cut short', empty: 'an empty section', tier: 'not the balanced tier', model: 'an unexpected model', refs: 'a file or name that is not in the code',
    numbers: 'a number typed instead of taken from the code', personal: 'personal data or a secret', unverified: 'an unverified fact not marked so',
    invented: 'a feature that is not built', planned: 'a planned feature outside "Planned"', shape: 'not in the six sections' };
  const KINDS = { chapter: 'Chapter', module: 'Module', card: 'Card', screen: 'Screen', service: 'Service' };
  const RUNS = { trial: 'The trial', first: 'The full write', update: 'The update' };
  const STATES = { queued: 'waiting to start', running: 'writing', paused: 'paused', done: 'done', stopped: 'stopped' };
  const TITLES = { trial: 'Start the Writer trial?', first: 'Write the full book?', update: 'Update the AI pages?' };
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v, d = 0) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : d);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const fmt = (n) => { try { return new Intl.NumberFormat('en-IN').format(n); } catch (_) { return String(n); } };
  const rs = (n) => '\u20b9' + fmt(Math.round(n)), inr = (v) => (v >= 100 || v === 0 ? rs(v) : '\u20b9' + (Math.round(v * 100) / 100).toFixed(2));
  const mib = (v) => String(Math.round(v * 10) / 10);
  const minutes = (lo, hi) => (hi <= 90 ? lo + '\u2013' + hi + ' minutes' : (lo / 60).toFixed(1) + '\u2013' + (hi / 60).toFixed(1) + ' hours');
  let D = null, H = null, T = null, V = null, E = null, rows = null, sample = null, form = null, wrap = null, head = null, sumEl = null, body = null, progEl = null, dlg = null;
  let stale = true, panelOpen = true, watching = false, stepping = false, stepTimer = 0, estWait = false, estTried = false, rowsWait = false;
  const notes = { trial: ['', ''], pick: ['', ''], full: ['', ''] };
  // ---- what the routes send, checked field by field ------------------------------------------------
  function brain(v) {
    const b = obj(v);
    return b && BRAIN.test(b.id || '') ? { id: b.id, label: txt(b.label, 60) || b.id, trains: b.trains_on_content === true,
      model: txt(b.model_name, 80), offered: b.offered === true, note: txt(b.note, 120) } : null;
  }
  function runOf(v) {
    const r = obj(v) || {};
    return { kind: RUNS[r.kind] ? r.kind : '', state: STATES[r.state] ? r.state : 'none', done: num(r.done), total: num(r.total),
      inr: num(r.inr), cap: num(r.cap_inr), why: txt(r.why, 200) };
  }
  function pickOf(v) {
    const p = obj(v) || {}, c = obj(p.caps) || {}, caps = {};
    Object.keys(DEFAULTS).forEach((k) => { caps[k] = Number.isInteger(c[k]) ? c[k] : DEFAULTS[k]; });
    return { brain: BRAIN.test(p.brain || '') ? p.brain : '', caps, auto: p.auto_update === true };
  }
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const t = obj(d.trial) || {}, s = obj(d.storage) || {}, u = obj(d.update_ready);
    return { on: d.on === true, brains: arr(d.brains).map(brain).filter(Boolean), pick: pickOf(d.pick), run: runOf(d.run),
      trial: { state: txt(t.state, 20), results: arr(t.results).filter((n) => Number.isInteger(n) && n >= 1 && n <= 10) },
      update: u && EST.test(u.estimate_id || '') ? { inr: num(u.inr_mid), pages: arr(u.pages).length } : null,
      storage: { used: num(s.used_mib), pages: num(s.pages_mib), limit: num(s.limit_mib), warn: s.warn === true } };
  }
  function est(raw) {
    const e = obj(raw);
    return e && EST.test(e.id || '') ? { id: e.id, brain: txt(e.brain, 40), pages: num(e.pages), low: num(e.low), mid: num(e.mid),
      high: num(e.high), cap: num(e.cap), lo: num(e.minutes_low), hi: num(e.minutes_high), gst: txt(e.gst_note, 120),
      sent: arr(e.sent_to).map((x) => txt(x, 300)).filter(Boolean) } : null;
  }
  function rowOf(v) {
    const r = obj(v);
    return r && Number.isInteger(r.nn) && PAGE.test(r.page || '') ? { nn: r.nn, page: r.page, title: txt(r.title, 120), brain: txt(r.brain, 40),
      state: txt(r.state, 20), checks: arr(r.checks).map((c) => txt(c, 20)).filter(Boolean), inr: num(r.inr), seconds: num(r.seconds) } : null;
  }
  const active = (r) => !!r && (r.state === 'queued' || r.state === 'running' || r.state === 'paused');
  const label = (id) => ((V && V.brains.find((b) => b.id === id)) || { label: id }).label;
  function titleOf(id) { // the id's words: only when the server sent no title (review I1 L-4)
    const m = /^pg_([a-z]+)_(.+)$/.exec(id) || [], name = (m[2] || id).replace(/_/g, ' ');
    return (KINDS[m[1]] || 'Page') + ' ' + (m[1] === 'card' ? name.toUpperCase() : name);
  }
  const named = (r) => r.title || titleOf(r.page);
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  /** A route's refusal: "yes" refused keeps the box open; a changed estimate or terms asks again; the rest close. */
  function refusal(e) {
    if (e && e.name === 'TypeError') return { detail: OFFLINE };
    const code = e && e.code, words = detailOf(e);
    if (code === 'not_yes') return { detail: words || 'Type YES to go ahead.' };
    if (code === 'estimate_changed' || code === 'terms_changed') return { again: true, detail: words };
    return { close: true, detail: words || 'That did not work. Please try again.' };
  }
  // ---- pieces --------------------------------------------------------------------------------------
  function button(text, kind, fn) { const b = mk('button', 'btn lift' + (kind ? ' ' + kind : ''), text); b.type = 'button'; if (fn) b.addEventListener('click', fn); return b; }
  function section(title, count) { const s = mk('div', 'bsec'), h = mk('h3', '', title); if (count) h.append(mk('span', 'bcount', count)); s.append(h); return s; }
  function actions(...buttons) { const a = mk('div', 'actions'); a.append(...buttons); return a; }
  function lines(items) { const ul = mk('ul', 'blines'); items.forEach((l) => ul.append(mk('li', '', l))); return ul; }
  function noteEl(name) { const [kind, words] = notes[name], n = mk('p', 'bnote', words); if (kind) n.classList.add(kind); n.setAttribute('role', 'status'); return n; }
  function say(name, kind, words) { notes[name] = [kind, words || '']; draw(); }
  function chevron() {
    const s = document.createElementNS(SVG, 'svg'), p = document.createElementNS(SVG, 'path');
    s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'dchev'); p.setAttribute('d', 'm6 8 4 4 4-4'); s.append(p); return s;
  }
  const isOpen = () => !!head && head.getAttribute('aria-expanded') === 'true';
  function estLines(e, kind) {
    const who = kind === 'trial' ? ' for ' + e.pages + ' sample pages from each brain' : ' for ' + e.pages + ' pages with ' + label(e.brain);
    // what is sent, to whom, and who may learn from it: the server's words only (review I1 L-5)
    return ['About ' + rs(e.mid) + ' (' + rs(e.low) + '\u2013' + fmt(Math.round(e.high)) + ')' + who + '.',
      'It stops at ' + rs(e.cap) + (kind === 'trial' ? ': each page starts only when its worst case still fits.' : '.'),
      'About ' + minutes(e.lo, e.hi) + ' with Book settings open.', ...e.sent, e.gst].filter(Boolean);
  }
  // ---- the YES box (a .bdialog, as the panel's confirm): never filled, sends what was typed --------------
  function yes(title, words, okText, keepText, go) {
    if (!dlg) { dlg = mk('dialog', 'bdialog'); dlg.id = 'bookYesDialog'; dlg.setAttribute('role', 'alertdialog'); document.body.append(dlg); }
    dlg.textContent = '';
    const h = mk('h2', '', title); h.id = 'bookYesTitle'; dlg.setAttribute('aria-labelledby', h.id); dlg.append(h);
    words.forEach((l) => dlg.append(mk('p', '', l)));
    const field = mk('div', 'bopt bk-name'), lab = mk('label', 'k', 'Type YES to confirm'), inp = mk('input', 'minput');
    inp.id = 'bookYes'; lab.htmlFor = inp.id; inp.type = 'text'; inp.autocomplete = 'off'; inp.spellcheck = false; inp.maxLength = 20;
    inp.setAttribute('autocapitalize', 'off');
    const why = mk('p', 'bnote bad'), keep = button(keepText, '', null), ok = button(okText, 'primary', null);
    why.setAttribute('role', 'alert'); field.append(lab, inp); dlg.append(field, why, actions(keep, ok));
    return new Promise((resolve) => {
      let done = false; const finish = (v) => { if (done) return; done = true; if (dlg.open) dlg.close(); resolve(v); };
      const send = async () => {
        if (ok.disabled) return;
        ok.disabled = true; why.textContent = '';
        const got = await go(inp.value);
        ok.disabled = false;
        if (got.ok || got.again || got.close) finish(got); else { why.textContent = got.detail || ''; inp.value = ''; inp.focus(); }
      };
      keep.addEventListener('click', () => finish({ kept: true })); ok.addEventListener('click', send);
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } });
      dlg.oncancel = () => finish({ kept: true }); // Esc: as "Keep" / "Not now", nothing is sent
      try { dlg.showModal(); } catch (_) { dlg.setAttribute('open', ''); }
      inp.focus();
    });
  }
  /** The trial, the first write and Update: the estimate shown, his YES on it; a changed estimate asks once more. */
  async function runYes(kind) {
    const at = kind === 'trial' ? 'trial' : 'full';
    let e = kind === 'trial' ? E : null, again = '';
    for (let tries = 0; tries < 2; tries += 1) {
      if (!e) {
        try { e = est(await D.api(W + '/estimate?run=' + kind)); } catch (err) { say(at, 'bad', detailOf(err) || 'Couldn\u2019t read the estimate.'); return; }
        if (!e) { say(at, 'bad', 'The estimate came back in a shape this page doesn\u2019t know.'); return; }
        if (kind === 'trial') E = e;
      }
      const shown = e;
      const got = await yes(TITLES[kind], (again ? [again] : []).concat(estLines(shown, kind)), 'Start', 'Not now', async (typed) => {
        try { return { ok: true, run: runOf(await D.api(W + '/' + kind, { method: 'POST', body: { typed: typed, estimate_id: shown.id } })) }; } catch (err) { return refusal(err); }
      });
      if (got.again) { again = got.detail || 'The estimate changed. Look at it again first.'; e = null; if (kind === 'trial') E = null; continue; }
      if (got.ok) { V.run = got.run; notes[at] = ['', '']; if (kind === 'trial') rows = sample = null; await load(); watch(true); }
      else if (got.detail) say(at, 'bad', got.detail);
      return;
    }
  }
  // ---- "Step while I watch": one step at a time while Book settings is open, 6 a minute at most ----------
  const canStep = () => watching && panelOpen && H.isConnected && isOpen() && !document.hidden && V && (V.run.state === 'queued' || V.run.state === 'running');
  function watch(on) { watching = !!on; clearTimeout(stepTimer); stepTimer = 0; if (watching) tick(); else drawProgress(); }
  const where = () => (V.run.kind === 'trial' ? 'trial' : 'full');
  async function tick() {
    if (stepping) return;
    if (!canStep()) { watching = false; drawProgress(); return; }
    const started = Date.now();
    stepping = true;
    try { V.run = runOf(await D.api(W + '/step', { method: 'POST' })); } catch (e) { if (!(e && e.code === 'busy')) { watching = false; notes[where()] = ['bad', detailOf(e) || 'The step did not work.']; } }
    stepping = false;
    if (!active(V.run)) { watching = false; await load(); return; }
    drawProgress();
    if (watching) stepTimer = setTimeout(tick, Math.max(0, STEP_GAP_MS - (Date.now() - started)));
  }
  function progress(r) {
    const box = mk('div', 'bk-sections');
    box.append(mk('p', 'snote', RUNS[r.kind] + ', ' + STATES[r.state] + ': ' + r.done + ' of ' + r.total + ' pages \u00b7 ' + inr(r.inr)
      + (r.cap ? ' of ' + rs(r.cap) : '')));
    if (r.why) box.append(mk('p', 'bfine', r.why));
    if (active(r)) box.append(actions(button(watching ? 'Pause watching' : 'Step while I watch', watching ? '' : 'primary', () => watch(!watching)),
      button('Stop', '', stop)), mk('p', 'bfine', 'It writes only while Book settings is open: one step at a time, at most 6 a minute.'));
    return box;
  }
  async function stop() {
    watch(false);
    try { V.run = runOf(await D.api(W + '/stop', { method: 'POST' })); } catch (e) { notes[where()] = ['bad', detailOf(e) || 'Couldn\u2019t stop it.']; }
    await load();
  }
  // ---- the Writer: the pick, its caps and every grant's YES on the server's words (H2) -----------------
  async function put(pick) { // JarvisChat.raw: the 422 yes_needed body (terms_id, words) is read here, not by api()
    const C = window.JarvisChat;
    if (!C || typeof C.raw !== 'function') throw new Error('Saving the pick isn\u2019t available in this page.');
    const r = await C.raw(W + '/pick', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pick) });
    return { status: r.status, json: obj(await r.json().catch(() => null)) || {} };
  }
  const errOf = (j) => Object.assign(new Error(txt(j.detail, 300)), { code: txt(j.error, 32) });
  function saved(raw) { V.pick = pickOf(raw); form = null; say('pick', 'ok', 'Saved.'); paint(); }
  async function savePick() {
    const caps = { trial: V.pick.caps.trial };
    for (const [k, name] of CAPS) {
      const n = Number(form.caps[k]), [lo, hi] = BOUNDS[k], b = (v) => (k === 'limit_pct' ? v + ' %' : rs(v));
      if (!Number.isInteger(n) || n < lo || n > hi) { say('pick', 'bad', name + ': a whole number from ' + b(lo) + ' to ' + b(hi) + '.'); return; }
      caps[k] = n;
    }
    const pick = { brain: form.brain, caps, auto_update: form.auto };
    let first;
    try { first = await put(pick); } catch (e) { say('pick', 'bad', detailOf(e) || 'Couldn\u2019t save the pick.'); return; }
    const j = first.json;
    if (first.status === 200) { saved(j); return; }
    if (first.status !== 422 || j.error !== 'yes_needed' || !TERMS.test(j.terms_id || '')) { say('pick', 'bad', txt(j.detail, 300) || 'Couldn\u2019t save the pick.'); return; }
    const words = arr(j.words).map((w) => txt(w, 300)).filter(Boolean).concat(txt(j.detail, 300) || []);
    const got = await yes('Confirm what the writer may spend', words, 'Confirm', 'Keep', async (typed) => {
      try {
        const r = await put(Object.assign({}, pick, { typed: typed, terms_id: j.terms_id }));
        return r.status === 200 ? { ok: true, pick: r.json } : refusal(errOf(r.json));
      } catch (e) { return refusal(e); }
    });
    if (got.ok) saved(got.pick);
    else if (got.kept) { form = null; say('pick', '', 'Kept your saved pick: nothing was changed.'); }
    else say('pick', 'bad', got.detail || 'The terms changed. Save again to see them.');
  }
  function brainRow() {
    const opt = mk('div', 'bopt'), t = mk('div', 'btxt'), sel = mk('select', 'bsel'), b = V.brains.find((x) => x.id === form.brain);
    sel.id = 'bkWriterBrain';
    const lab = mk('label', 'bl', 'Writer'); lab.htmlFor = sel.id;
    t.append(lab, mk('small', '', 'Balanced tier, always' + (b && b.model ? ' (' + b.model + ')' : '') + '.'
      + (b && b.trains ? ' ' + b.label + ' may learn from what it reads: it gets only JARVIS\u2019s public code and its facts.' : '')));
    V.brains.forEach((x) => {
      const o = mk('option', '', x.label + (x.offered ? '' : ' (not offered' + (x.note ? ': ' + x.note : '') + ')'));
      o.value = x.id; o.disabled = !x.offered; o.selected = x.id === form.brain; sel.append(o);
    });
    sel.addEventListener('change', () => { form.brain = sel.value; draw(); });
    opt.append(t, sel); return opt;
  }
  function capRow([k, name, id]) {
    const opt = mk('div', 'bopt bk-name'), lab = mk('label', 'k', name), inp = mk('input', 'minput');
    inp.id = id; lab.htmlFor = id; inp.type = 'number'; inp.inputMode = 'numeric'; inp.step = '1';
    inp.min = String(BOUNDS[k][0]); inp.max = String(BOUNDS[k][1]); inp.value = String(form.caps[k]);
    inp.addEventListener('input', () => { form.caps[k] = inp.value; });
    opt.append(lab, inp); return opt;
  }
  function autoRow() {
    const opt = mk('div', 'bopt'), t = mk('div', 'btxt'), b = mk('button', 'bsw'), tr = mk('span', 'track');
    t.append(mk('span', 'bl', 'Update by itself'), mk('small', '', 'Within the release cap after each deploy, with no question asked. Off: each release waits for your Update.'));
    b.type = 'button'; b.id = 'bkWriterAuto'; b.setAttribute('aria-pressed', String(form.auto)); b.setAttribute('aria-label', 'Update by itself');
    tr.append(mk('i')); b.append(tr, mk('span', 'st', form.auto ? 'On' : 'Off'));
    b.addEventListener('click', () => { form.auto = !form.auto; draw(); });
    opt.append(t, b); return opt;
  }
  function pickSec() {
    if (!form) form = { brain: V.pick.brain || ((V.brains.find((b) => b.offered) || {}).id || ''), caps: Object.assign({}, V.pick.caps), auto: V.pick.auto };
    const sec = section('Writer', V.pick.brain ? label(V.pick.brain) : 'Not picked yet');
    sec.append(brainRow(), mk('p', 'bfine', 'Picking a brain here is the writer\u2019s own choice: the switch "Allow a brain that may learn" '
      + 'in Book settings is only for the questions after the show.'), ...CAPS.map(capRow), autoRow(),
    mk('p', 'bfine', 'Saving spends nothing. Lowering a cap saves at once; a raise, a paid brain or "Update by itself" asks for your YES on the \u20b9 shown.'),
    actions(button('Save the pick', 'primary', savePick)), noteEl('pick'));
    return sec;
  }
  // ---- the trial, its pages side by side, one sample page; the full write and Update -------------------
  function trialSec() {
    const r = V.run, t = V.trial, mine = r.kind === 'trial' && active(r);
    const ended = r.kind === 'trial' && r.state === 'stopped';
    const sec = section('Writer trial', mine ? 'Writing' : t.results.length ? 'Done' : ended ? 'Stopped' : 'Not run yet');
    if (mine) sec.append(progEl = progress(r));
    else {
      if (ended && r.why) sec.append(progress(r)); // how the last one ended, and why (R6.3 hotfix 1)
      if (t.results.length) sec.append(mk('p', 'snote', 'Both brains wrote the same sample pages from the same code. Compare them, then pick the writer below.'),
        actions(button('Run another trial', '', () => runYes('trial')), button('Delete the trial pages', '', dropTrial)));
      else {
        sec.append(mk('p', 'snote', 'Two brains each write the same 5 sample pages, so you can compare them before you pick a writer. '
          + 'Nothing is spent before your YES.'));
        sec.append(E ? lines(estLines(E, 'trial')) : mk('p', 'bempty', 'Reading the estimate\u2026'), actions(button('Start the trial', 'primary', () => runYes('trial'))));
      }
    }
    sec.append(noteEl('trial')); return sec;
  }
  function verdict(r) { // passed the first time, after one redraft (and why), or refused and why
    const why = r.checks.map((c) => CHECKS[c] || c).join(', ');
    if (r.state === 'refused') return 'Refused' + (why ? ': ' + why : '');
    return r.state === 'redrafted' ? 'Passed after one redraft' + (why ? ' (first try: ' + why + ')' : '') : 'Passed every check the first time';
  }
  function sideBySide() {
    if (!rows || !rows.length || active(V.run) && V.run.kind === 'trial') return [];
    return [...new Set(rows.map((r) => r.page))].map((page) => {
      const title = named(rows.find((r) => r.page === page)), sec = section(title, ''), ul = mk('ul', 'bevents');
      rows.filter((r) => r.page === page).forEach((r) => {
        const li = mk('li', 'bev'), what = mk('div', 'bwhat'), go = button('Read', 'bact', () => readSample(r));
        go.setAttribute('aria-label', 'Read ' + title + ' by ' + label(r.brain));
        what.append(mk('b', '', verdict(r)), mk('small', '', inr(r.inr) + ' \u00b7 ' + Math.round(r.seconds) + ' s'), go);
        li.append(mk('span', 'btime', label(r.brain)), what); ul.append(li);
      });
      sec.append(ul); return sec;
    });
  }
  async function readSample(r) {
    try { const got = obj(await D.api(W + '/trial/pages/' + r.nn)); sample = got && obj(got.page) ? { r, page: got.page } : null; }
    catch (e) { say('trial', 'bad', detailOf(e) || 'Couldn\u2019t open that page.'); return; }
    draw();
    const top = body && body.querySelector('.bk-rhead'); if (top && top.scrollIntoView) top.scrollIntoView({ block: 'nearest' });
  }
  function sampleSec() {
    if (!sample || !rows) return [];
    const sec = section('Sample page', ''), h = mk('div', 'rhead bk-rhead'), box = mk('div', 'bk-sections'), P = window.JarvisBookPages;
    h.append(mk('span', 'k', named(sample.r) + ' by ' + label(sample.r.brain)), button('Close', '', () => { sample = null; draw(); }));
    if (!P || typeof P.page !== 'function' || !P.page(box, sample.page)) box.append(mk('p', 'bempty', 'This page can\u2019t be shown here.'));
    sec.append(h, box); return [sec];
  }
  async function dropTrial() {
    const go = await D.ask('Delete the trial pages?', ['Both brains\u2019 sample pages go. A new trial needs a new estimate and your YES.'],
      [{ id: '', label: 'Keep them' }, { id: 'go', label: 'Delete', kind: 'primary' }]);
    if (go !== 'go') return;
    try { await D.api(W + '/trial', { method: 'DELETE' }); rows = null; sample = null; E = null; estTried = false; } catch (e) { say('trial', 'bad', detailOf(e) || 'Couldn\u2019t delete them.'); return; }
    await load();
  }
  function fullSec() {
    const r = V.run, mine = r.kind && r.kind !== 'trial', busy = active(r);
    const sec = section('Full book', mine && busy ? 'Writing' : V.update ? 'Update waiting' : '');
    if (V.update && !busy) sec.append(mk('p', 'snote', 'The AI pages wait for your Update (about ' + rs(V.update.inr) + ').'), actions(button('Update', 'primary', () => runYes('update'))));
    if (mine && r.state !== 'none') sec.append(busy ? (progEl = progress(r)) : progress(r));
    if (!V.pick.brain) sec.append(mk('p', 'bempty', 'Pick the writer first: the full write needs your pick and its own YES.'));
    else if (!busy) sec.append(mk('p', 'snote', 'The first full write writes every page once, one at a time, while Book settings is open.'),
      actions(button('Write the full book', '', () => runYes('first'))));
    sec.append(noteEl('full')); return sec;
  }
  // ---- drawing -------------------------------------------------------------------------------------
  function summary() {
    const r = V.run, c = V.pick.caps;
    if (active(r)) return RUNS[r.kind] + ': ' + r.done + ' of ' + r.total + ' pages';
    if (V.update) return 'Your Update waits: about ' + rs(V.update.inr);
    if (V.pick.brain) return label(V.pick.brain) + ' \u00b7 caps ' + rs(c.first) + ' first write, ' + rs(c.release) + ' a release, ' + rs(c.month) + ' a month';
    return V.trial.results.length ? 'Trial done: pick the writer' : 'Try two brains on 5 sample pages, then pick one';
  }
  function keepFocus(fn) { // a repaint keeps the focused control (by its id or its words)
    const a = document.activeElement, k = a && body && body.contains(a) ? a.id || a.textContent : '';
    fn();
    const back = k && [...body.querySelectorAll('button, input, select')].find((n) => (n.id || n.textContent) === k); if (back) back.focus();
  }
  function draw() {
    if (!body || !V || !V.on || !isOpen()) return;
    keepFocus(() => { body.textContent = ''; progEl = null; body.append(trialSec(), ...sideBySide(), ...sampleSec(), pickSec(), fullSec()); });
    if (!E && !estTried && !estWait && !active(V.run) && !V.trial.results.length) loadEstimate();
    if (V.trial.results.length && rows === null && !rowsWait) loadRows();
  }
  function drawProgress() {
    if (!V || !body) return;
    if (sumEl) sumEl.textContent = summary();
    if (progEl && progEl.isConnected && active(V.run)) keepFocus(() => { const n = progress(V.run); progEl.replaceWith(n); progEl = n; });
    else draw();
  }
  function build() {
    wrap = mk('div', 'bset bk-sec'); head = mk('button', 'dsc'); body = mk('div', 'dbody'); sumEl = mk('span', 'dsum');
    head.type = 'button'; body.id = 'bkWriterBody'; head.setAttribute('aria-controls', body.id); head.setAttribute('aria-expanded', 'false'); body.hidden = true;
    head.append(mk('span', 'dl', 'Book writer'), chevron(), sumEl);
    head.addEventListener('click', () => { const on = !isOpen(); head.setAttribute('aria-expanded', String(on)); body.hidden = !on; if (on) draw(); else watch(false); });
    wrap.append(head, body); H.append(wrap);
  }
  function paintTop() {
    const s = V && V.storage, used = s ? s.used + s.pages : 0; // R6's sealed books + the AI pages (D11)
    T.textContent = ''; T.hidden = !(s && s.warn && s.limit);
    if (T.hidden) return;
    T.className = 'iopt bk-wtop';
    T.append(mk('span', '', 'The build books use ' + mib(used) + ' of ' + mib(s.limit) + ' MiB (' + Math.round((used / s.limit) * 100)
      + ' %). When a new release needs the room, the oldest kept release goes first.'));
  }
  function paint() {
    paintTop();
    if (!V || !V.on) { H.hidden = true; H.textContent = ''; wrap = head = body = sumEl = null; watching = false; return; }
    H.hidden = false;
    if (!wrap) build();
    sumEl.textContent = summary();
    draw();
  }
  // ---- loading -------------------------------------------------------------------------------------
  async function load() {
    try { V = normal(await D.api(W)); } catch (_) { V = null; } // not built, off or unreachable: nothing drawn
    paint();
  }
  async function loadEstimate() { // the trial's estimate, shown before anything else
    estWait = true;
    try { E = est(await D.api(W + '/estimate?run=trial')); if (!E) notes.trial = ['bad', 'The estimate came back in a shape this page doesn\u2019t know.']; }
    catch (e) { notes.trial = ['bad', detailOf(e) || 'Couldn\u2019t read the estimate.']; }
    estWait = false; estTried = true; draw();
  }
  async function loadRows() {
    rowsWait = true;
    try { rows = arr((obj(await D.api(W + '/trial/pages')) || {}).rows).map(rowOf).filter(Boolean); } catch (_) { rows = []; }
    rowsWait = false; draw();
  }
  function settings(host, deps) {
    if (H || !host || !deps || typeof deps.api !== 'function') return;
    H = host; D = deps; T = deps.top || mk('div'); H.hidden = true; T.hidden = true; H.classList.add('bk-set');
    const check = () => { if (stale && H.isConnected) { stale = false; load(); } };
    const panel = document.getElementById('p-book');
    if (panel && typeof MutationObserver === 'function') new MutationObserver(check).observe(panel, { childList: true, subtree: true });
    document.addEventListener('jarvis:panel', (e) => { // each open reads the writer again; a close stops the stepping
      const d = (e && e.detail) || {};
      if (d.id === 'book') { panelOpen = !!d.open; if (panelOpen) { stale = true; estTried = false; check(); } else watch(false); }
    });
    check();
  }
  window.JarvisBookWriter = Object.freeze({ settings });
})();
