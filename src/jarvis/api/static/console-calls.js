// src/jarvis/api/static/console-calls.js -- R18 E (docs/plans/r18-calls.md; BUILD-BRIEF.md row E): the Calls panel
// (#p-calls, its shell in console.html, opened from the dock, from a call card and by ?open=calls) and the call cards
// in the chat. Loaded by console-r7.js; it brings its stylesheet (console-calls.css: places only, existing tokens and
// classes) and its parts:
//   console-calls-api.js      paths, checks, words, the shared builders      console-calls-shapes.js  the server's shapes
//   console-calls-list.js     Calls: today's and recent calls, a record      console-calls-card.js    the call card
//   console-calls-form.js     New call: templates (Laundry) and the fields   console-calls-live.js    the live call
//   console-calls-langs.js    Languages: the language check's table          console-calls-audio.js   Listen, recordings
//   console-calls-settings.js Settings: caps, limits, languages, answering   console-calls-vitals.js  Vitals' calls line
// The readiness line at the top says whether the laptop's call desk is ready, warns of a Bluetooth headset on the
// laptop (Phone Link refuses calls then) and whether the phone is linked. Asks the server NOTHING before sign-in and
// nothing while the panel is closed (a restored panel fires no open event: jarvis:ready looks); closing the panel ends
// Listen live and any recording playing. window.JarvisCalls {cards(row, list), open(tab), live(callId)}. ASCII source.
import { PATHS, api, chip, failed, mk, rupees, say, signedIn, wholeRupees } from './console-calls-api.js';
import { isLive, readiness } from './console-calls-shapes.js';
import { chatCards } from './console-calls-card.js';
import { mount as mountList } from './console-calls-list.js';
import { mount as mountForm } from './console-calls-form.js';
import { mount as mountLive } from './console-calls-live.js';
import { mount as mountLangs } from './console-calls-langs.js';
import { mount as mountSettings } from './console-calls-settings.js';
import { mount as mountVitals } from './console-calls-vitals.js';

const css = document.createElement('link');
css.rel = 'stylesheet';
css.href = '/static/console-calls.css';
document.head.append(css);

const panel = document.getElementById('p-calls');
const host = document.getElementById('callsBody');
const meta = document.getElementById('callsMeta');
const Deck = () => window.JarvisDeck || null;
const TABS = [['calls', 'Calls'], ['new', 'New call'], ['langs', 'Languages'], ['settings', 'Settings']];
const POLL_MS = 15 * 1000;
const BT = 'A Bluetooth headset is connected to the laptop: Phone Link refuses calls then. Use the laptop\u2019s speaker or a wired headset, or take calls on the phone.';
const S = { tab: 'calls', status: null, polling: 0, loading: false };

// ---- the readiness line ----------------------------------------------------------------------------------------------
const ready = mk('section', 'vt-card cl-ready');
ready.setAttribute('aria-label', 'Ready to call');
const chips = mk('div', 'cl-chips');
const readyNote = mk('p', 'sfine');
const readyWarn = mk('div', 'bnote bad'); readyWarn.hidden = true;
const readyState = mk('p', 'snote'); readyState.setAttribute('role', 'status');
ready.append(chips, readyNote, readyWarn, readyState);

function paintReady() {
  const st = S.status;
  chips.replaceChildren();
  if (!st) return;
  const d = st.desk;
  const deskWords = !d.connected ? ['Laptop desk: not running', 'red'] : d.ready ? ['Laptop desk: ready', 'ok'] : ['Laptop desk: needs you', 'amber'];
  chips.append(chip(deskWords[0], deskWords[1]), chip(st.phone.linked ? 'Phone: linked' : 'Phone: not linked', st.phone.linked ? 'ok' : 'red'));
  if (d.btHeadset) chips.append(chip('Bluetooth headset on the laptop', 'red'));
  const problems = d.problems.slice();
  if (d.btHeadset) problems.unshift(BT);
  if (!d.connected) problems.push('Start the JARVIS call desk on your laptop.');
  if (!st.phone.linked) problems.push('Link the JARVIS phone app (Integrations, Phone app).');
  readyWarn.replaceChildren();
  readyWarn.hidden = !problems.length;
  if (problems.length) {
    readyWarn.append(mk('b', '', 'Calls can\u2019t be placed until:'));
    const ul = mk('ul', 'blines');
    problems.forEach((p) => ul.append(mk('li', '', p)));
    readyWarn.append(ul);
  }
  const today = st.today.max ? st.today.calls + ' of ' + st.today.max + ' calls today' : st.today.calls + (st.today.calls === 1 ? ' call today' : ' calls today');
  const month = 'this month ' + rupees(st.month.used) + (st.month.cap ? ' of ' + wholeRupees(st.month.cap) : '');
  readyNote.textContent = today + ' \u00b7 ' + month;
  if (meta) meta.textContent = st.active ? 'On a call' : 'Today ' + st.today.calls;
}

// ---- the tabs (the Helpers frame's strip) -----------------------------------------------------------------------------
const tabsEl = mk('div', 'hp-tabs');
tabsEl.setAttribute('role', 'tablist');
tabsEl.setAttribute('aria-label', 'Calls');
const panes = {}, tabBtns = {};
TABS.forEach(([tid, label]) => {
  const b = mk('button', 'hp-tab', label);
  b.type = 'button'; b.id = 'clt-' + tid;
  b.setAttribute('role', 'tab'); b.setAttribute('aria-controls', 'clp-' + tid);
  b.addEventListener('click', () => choose(tid, true));
  tabBtns[tid] = b;
  tabsEl.append(b);
  const p = mk('div', 'hp-pane');
  p.id = 'clp-' + tid;
  p.setAttribute('role', 'tabpanel'); p.setAttribute('aria-labelledby', b.id);
  p.tabIndex = 0;
  panes[tid] = p;
});
tabsEl.addEventListener('keydown', (e) => {
  const ids = TABS.map(([t]) => t), at = ids.indexOf(S.tab);
  const next = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: ids.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  choose(ids[(next + ids.length) % ids.length], true);
  tabBtns[S.tab].focus();
});

// ---- the parts --------------------------------------------------------------------------------------------------------
const ctx = {
  ready: () => S.status,
  languages: () => langs.rows(),
  settings: () => settings.data(),
  openLive: (callId) => openLive(callId),
  openRecord: (rid) => { live.close(false); choose('calls', false); list.show(rid); },
  closedLive: () => { list.load(); const f = panes.calls.querySelector('button'); if (f) f.focus(); },
  ended: () => { document.dispatchEvent(new CustomEvent('jarvis:calls', { detail: { ended: true } })); status(); },
  edit: (card) => { openPanel(); choose('new', true); form.edit(card); },
  changed: () => {},
  settingsLoaded: (d) => form.templates(d.templates), // the ready cards (Laundry among them) come with the settings
  languagesChanged: () => { form.languagesChanged(); settings.languagesChanged(); },
};
// the order matters: the form reads the language table and the settings as it starts
const live = mountLive(panes.calls, ctx);
const list = mountList(panes.calls, ctx);
const langs = mountLangs(panes.langs, ctx);
const settings = mountSettings(panes.settings, ctx);
const form = mountForm(panes.new, ctx);
const vitals = mountVitals();
if (host) host.append(ready, tabsEl, ...TABS.map(([t]) => panes[t]));

function choose(tid, load) {
  S.tab = panes[tid] ? tid : 'calls';
  TABS.forEach(([t]) => {
    const on = t === S.tab;
    tabBtns[t].setAttribute('aria-selected', on ? 'true' : 'false');
    tabBtns[t].tabIndex = on ? 0 : -1;
    panes[t].hidden = !on;
  });
  if (load) loadTab();
}
function loadTab() {
  if (!signedIn() || hidden()) return;
  if (S.tab === 'calls') list.load();
  if (S.tab === 'new') { form.load(); langs.load(false); settings.load(); }
  if (S.tab === 'langs') langs.load(true);
  if (S.tab === 'settings') { langs.load(false); settings.load(); }
}
async function status() {
  if (!signedIn() || S.loading) return;
  S.loading = true;
  try {
    S.status = readiness(await api(PATHS.status));
    say(readyState, '');
    if (vitals) vitals.show(S.status.month);
    const a = S.status.active;
    if (a && isLive(a.state) && !live.shown() && S.tab === 'calls') live.open(a.callId, { state: a.state });
  } catch (e) { say(readyState, failed(e), 'bad'); }
  S.loading = false;
  paintReady();
}
function hidden() { return !panel || panel.hidden || !panel.getClientRects().length; }
function shown() {
  if (hidden()) return;
  status();
  loadTab();
  clearInterval(S.polling);
  S.polling = setInterval(() => { if (!hidden() && !document.hidden) status(); }, POLL_MS);
}
function gone() {
  clearInterval(S.polling);
  live.close(false);
  list.stop();
  langs.stop();
}
function openPanel() { const D = Deck(); if (D && !D.isOpen('calls')) D.open('calls', { focus: false }); }
function openLive(callId) {
  openPanel();
  choose('calls', false);
  const row = list.rows().find((r) => r.id === callId);
  live.open(callId, row ? { who: row.who, number4: row.number4, state: row.state } : null);
}

document.addEventListener('jarvis:panel', (e) => {
  const d = (e && e.detail) || {};
  if (d.id === 'calls' && d.open) shown();
  setTimeout(() => { if (hidden()) gone(); }, 0); // closed, or behind another tab on a phone
});
document.addEventListener('jarvis:ready', () => { if (!hidden()) shown(); });
choose('calls', false);
if (signedIn() && !hidden()) shown();

window.JarvisCalls = Object.freeze({
  cards: (row, cardsList) => chatCards(row, cardsList, ctx),
  open: (tid) => { openPanel(); choose(tid || 'calls', true); },
  live: (callId) => (typeof callId === 'string' && callId ? openLive(callId) : undefined),
});
