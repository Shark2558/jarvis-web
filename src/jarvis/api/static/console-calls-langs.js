// src/jarvis/api/static/console-calls-langs.js -- R18 E (docs/plans/r18-calls.md section 5.3, step 5): Calls ->
// Languages, the language check's table. Each language: whether it passed, the option that passed (free first, the
// laptop first), its rupees a minute, why it failed, "not yet heard by a native speaker" until a person who speaks it
// has scored it, and a language that needs the balanced brain (offered only with his yes). "Run language check" first
// asks the cloud what the run would cost, shows that estimate and runs only after his Run press (confirm before
// commit: it may spend from the free allowances or, past them, rupees). R18 review: "Score the voice" on a checked row
// (POST /v1/calls/languages/score {lang, option, scores}: his 1-5 for up to 3 samples heard over a real call; the
// owner step of plan 5.3.2), and the estimate says plainly when an option is left out because its price is unknown
// (Bhashini). ASCII source; textContent only.
import { PATHS, api, button, chip, choice, failed, mk, perMinute, rupees, say, uid, when } from './console-calls-api.js';
import { languages as checkLanguages } from './console-calls-shapes.js';

const POLL_MS = 5000;
const INTRO = 'Only the languages that pass are offered on a call card. The check hears phone-quality clips, speaks call sentences and hears them back, and times the replies. Then you score each voice after hearing it over a real call (or ask someone who speaks the language).';
const SAMPLES = 3;
const SCORES = [['1', '1'], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']];
const UNKNOWN = (names) => 'Left out: ' + names + '. Its price isn\u2019t published, and JARVIS never counts an unknown price as \u20b90, so it can\u2019t be checked or used from here.';
const OPTION_NAMES = { bhashini: 'Bhashini', sarvam: 'Sarvam', google: 'Google', azure: 'Azure', laptop: 'the laptop models' };
const STATUS = { passed: ['Passed', 'ok'], failed: ['Failed', 'red'], untested: ['Not checked', 'unknown'], running: ['Checking', 'amber'] };

export function mount(host, ctx) {
  const S = { data: null, busy: false, poll: 0 };
  const intro = mk('p', 'sfine', INTRO);
  const state = mk('p', 'snote'); state.setAttribute('role', 'status');
  const rows = mk('div', 'cl-langrows');
  const runBtn = button('Run language check', 'primary sact', () => estimate());
  const acts = mk('div', 'sacts'); acts.append(runBtn);
  const ask = mk('div', 'mbox'); ask.hidden = true; ask.setAttribute('role', 'group');
  const scoreBox = mk('div', 'mbox cl-score'); scoreBox.setAttribute('role', 'group'); // in the page only while open
  const err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
  host.append(intro, state, rows, acts, ask, err);

  function detail(l) {
    if (l.status === 'running') return 'Being checked now\u2026';
    if (l.status === 'untested') return 'Not checked yet.';
    if (l.status === 'failed') return 'Failed' + (l.why.length ? ': ' + l.why.join('; ') + '.' : '.') + (l.optionWords ? ' Best try: ' + l.optionWords + '.' : '');
    const bits = [l.optionWords, l.perMin === null ? 'price a minute unknown' : perMinute(l.perMin)].filter(Boolean);
    return bits.join(' \u00b7 ') + '.';
  }
  function item(l) {
    const r = mk('div', 'hp-row'), t = mk('div', 'hp-txt'), a = mk('div', 'hp-acts');
    t.append(mk('b', '', l.name), mk('small', '', detail(l)));
    if (l.status === 'passed' && !l.native) t.append(mk('small', 'cl-amber', 'Not yet heard by a native speaker.'));
    if (l.balanced) t.append(mk('small', 'cl-amber', 'Needs the balanced brain (\u2248 \u20b92\u20134 a minute): offered only with your yes.'));
    if (l.at) t.append(mk('small', '', 'Checked ' + when(l.at)));
    const [w, s] = STATUS[l.status];
    a.append(chip(w, s));
    if (l.option && l.at && (l.status === 'passed' || l.status === 'failed')) {
      const b = button(l.native ? 'Score again' : 'Score the voice', 'sact cl-scorebtn', () => openScore(l, b));
      b.setAttribute('aria-label', (l.native ? 'Score again: ' : 'Score the voice: ') + l.name);
      a.append(b);
    }
    r.append(t, a);
    return r;
  }
  /** His 1-5 for each sample he heard (plan 5.3 step 2): at least one, at most three. */
  function openScore(l, trigger) {
    const picked = new Array(SAMPLES).fill(null);
    const title = mk('p', 'strong', 'Score the ' + l.name + ' voice' + (OPTION_NAMES[l.option] ? ' (' + OPTION_NAMES[l.option] + ')' : ''));
    title.id = uid('clst');
    const how = mk('p', '', 'Listen to JARVIS speaking ' + l.name + ' over a real call, or ask someone who speaks it, and score each sample from 1 (hard to follow) to 5 (clear and natural). An average of 4 or more passes.');
    const samples = [...Array(SAMPLES).keys()].map((i) => {
      const w = mk('div', 'cl-hear'), lab = mk('span', 'bl', 'Sample ' + (i + 1));
      lab.id = uid('clsl');
      w.append(lab, choice('clsc', lab.id, SCORES, '', (v) => { picked[i] = parseInt(v, 10); }));
      return w;
    });
    const note = mk('p', 'lerr'); note.setAttribute('role', 'alert');
    const no = button('Not now', 'sact', () => { scoreBox.remove(); trigger.focus(); });
    const yes = button('Save the scores', 'primary sact', () => saveScores(l, picked.filter((x) => x !== null), yes, no, note, trigger));
    const row = mk('div', 'sacts'); row.append(no, yes);
    scoreBox.replaceChildren(title, how, ...samples, note, row);
    scoreBox.setAttribute('aria-labelledby', title.id);
    rows.after(scoreBox); // under the table, above Run: the table may repaint while he scores
    scoreBox.onkeydown = (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); no.click(); } };
    no.focus();
  }
  async function saveScores(l, scores, yes, no, note, trigger) {
    if (!scores.length) { note.textContent = 'Score at least one sample, from 1 to 5.'; return; }
    yes.disabled = true; no.disabled = true; note.textContent = '';
    try {
      await api(PATHS.languages + '/score', { body: { lang: l.code, option: l.option, scores } });
      scoreBox.remove();
      await load(true); // the table read again (the row's "not yet heard" goes), then the words
      say(state, 'Scores saved for ' + l.name + '.', 'ok');
      trigger.isConnected ? trigger.focus() : runBtn.focus();
    } catch (e) { note.textContent = failed(e); yes.disabled = false; no.disabled = false; }
  }
  function paint() {
    const d = S.data;
    rows.replaceChildren(...(d ? d.rows.map(item) : []));
    const running = !!d && (d.check.running || d.rows.some((l) => l.status === 'running'));
    runBtn.disabled = S.busy || running;
    runBtn.textContent = running ? 'Checking\u2026' : 'Run language check';
    if (d && !d.rows.length) say(state, 'No language has been checked yet. Run the check to find the ones JARVIS can use.');
    else if (running) say(state, 'The language check is running. This table fills in as each language finishes.');
    else if (d) say(state, '');
    clearTimeout(S.poll);
    if (running) S.poll = setTimeout(() => load(true), POLL_MS);
  }
  async function load(force) {
    if (S.busy || (S.data && !force)) { paint(); return; }
    S.busy = true;
    if (!S.data) say(state, 'Loading the language table\u2026');
    try {
      S.data = checkLanguages(await api(PATHS.languages));
      err.textContent = '';
      ctx.languagesChanged(S.data.rows);
    } catch (e) { say(state, failed(e), 'bad'); }
    S.busy = false;
    paint();
  }
  async function estimate() {
    if (S.busy) return;
    S.busy = true; err.textContent = ''; paint();
    try {
      const r = await api(PATHS.languages + '/check', { body: { confirm: false } });
      const est = r && typeof r.estimate_inr === 'number' && Number.isFinite(r.estimate_inr) ? r.estimate_inr : null;
      const n = r && Number.isInteger(r.languages) ? r.languages : null;
      const plan = r && r.plan && typeof r.plan === 'object' ? r.plan : {};
      const left = [...new Set((Array.isArray(plan.unknown_price) ? plan.unknown_price : []).map((x) => String(x).split(' ')[1]).filter((o) => OPTION_NAMES[o]))];
      confirmBox(est, n, left.map((o) => OPTION_NAMES[o]).join(', '));
    } catch (e) { err.textContent = failed(e); }
    S.busy = false; paint();
  }
  function confirmBox(est, n, unknown) {
    const what = n ? n + (n === 1 ? ' language' : ' languages') : 'every candidate language';
    const cost = est === null ? 'JARVIS couldn\u2019t estimate it.' : est <= 0 ? 'Estimate: \u20b90 (inside the free allowances).' : 'Estimate: ' + rupees(est) + ', counted in your calls cap.';
    const t = mk('p', 'strong', 'Run the language check for ' + what + '?');
    const c = mk('p', '', cost + ' It takes a few minutes; no real call is made.');
    const no = button('Not now', 'sact', () => { ask.hidden = true; runBtn.focus(); });
    const yes = button(est && est > 0 ? 'Run (' + rupees(est) + ')' : 'Run', 'primary sact', () => run(yes, no, est));
    const row = mk('div', 'sacts'); row.append(no, yes);
    ask.replaceChildren(t, c, ...(unknown ? [mk('p', 'sfine', UNKNOWN(unknown))] : []), row);
    ask.hidden = false;
    ask.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); no.click(); } }, { once: true });
    no.focus(); // the safe choice is where Enter lands
  }
  async function run(yes, no, est) {
    yes.disabled = true; no.disabled = true;
    try {
      await api(PATHS.languages + '/check', { body: { confirm: true, estimate_inr: est } });
      ask.hidden = true;
      if (S.data) S.data = { ...S.data, check: { ...S.data.check, running: true } };
      say(state, 'The language check has started.', 'ok');
      runBtn.focus();
      await load(true);
    } catch (e) { yes.disabled = false; no.disabled = false; err.textContent = failed(e); }
  }
  return Object.freeze({ load, rows: () => (S.data ? S.data.rows : []), stop: () => clearTimeout(S.poll) });
}
