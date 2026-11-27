// src/jarvis/api/static/console-calls-vitals.js -- R18 E (docs/plans/r18-calls.md section 6): Vitals' calls line,
// "Calls this month  \u2248 \u20b912.40 of \u20b9200", one more .kv row under "This conversation", in the list's own look. The
// figures are the cloud's (GET /api/calls/status: this month's rupees for calls and the calls cap), read when Vitals
// opens (or is open when he signs in: a restored panel fires no open event) and after a call ends; never before
// sign-in, never a guess ("\u2014" when it can't be read). ASCII source; textContent only.
import { PATHS, api, mk, rupees, signedIn, wholeRupees } from './console-calls-api.js';
import { readiness } from './console-calls-shapes.js';

const STALE_MS = 30 * 1000;

export function mount() {
  const cost = document.getElementById('sCost');
  const after = cost ? cost.closest('.kv') : null;
  if (!after || document.getElementById('sCalls')) return null;
  const row = mk('div', 'kv');
  const val = mk('b', '', '\u2014');
  val.id = 'sCalls';
  row.append(mk('span', '', 'Calls this month'), val);
  after.after(row);
  const S = { at: 0, busy: false };
  const shown = () => !!(window.JarvisDeck && window.JarvisDeck.isOpen('vitals'));
  function words(m) {
    if (m.cap === null) return rupees(m.used);
    return rupees(m.used) + ' of ' + wholeRupees(m.cap) + (m.used >= m.cap ? ' \u00b7 cap reached' : '');
  }
  async function load(force) {
    if (!signedIn() || S.busy || (!force && Date.now() - S.at < STALE_MS)) return;
    S.busy = true;
    try {
      const st = readiness(await api(PATHS.status));
      val.textContent = words(st.month);
      val.title = 'Calls: this month\u2019s spend and the calls cap (Calls, Settings)';
      S.at = Date.now();
    } catch (_) { val.textContent = '\u2014'; }
    S.busy = false;
  }
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'vitals' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (shown()) load(true); });
  document.addEventListener('jarvis:calls', () => { S.at = 0; if (shown()) load(true); });
  if (signedIn() && shown()) load(true);
  return Object.freeze({ load, show: (m) => { val.textContent = words(m); S.at = Date.now(); } });
}
