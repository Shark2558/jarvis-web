// src/jarvis/api/static/console-r111-look.js -- R11.1 Part D (docs/plans/r11-1-observations.md D17, D21-D):
// "Research a picture" in the People panel. The owner attaches a picture in the chat and sends it; the
// button asks the server to research the picture of his LAST message in the open conversation and the
// answer is shown as words and sources. JARVIS researches things, places, labels and logos; it never
// identifies a person from a picture: a picture with a person shows what is visible and the server's fixed
// sentence. A name can come only from the picture's own words, and then only as an offer: the button puts
// the name in the People box above and HE presses Research, so the usual check decides. The offer shows the
// very line of the picture's text the name was read from ("Caption read: '...'"), so he sees where it came from.
// (Part D's profile cards are in console-people.js, where the dossier is drawn.)
// Loaded by console-r111.js (an ES module). Built with window.JarvisFixes (mk, api, part) and the console's
// existing classes; every server string reaches the page through textContent; a source is a link only when
// it is plain https, and its site is read from the link itself. ASCII source; CSP script-src 'self'.
// API (src/jarvis/api/fix_look.py): GET /v1/picture -> {part, ready, can, why};
//   POST /v1/picture/research {session_id, picture} -> {status: 'done', message, person, text[],
//   sources[{title, url, snippet}], offer: {name, caption}|null} or {status, message} when it did not run.
const F = window.JarvisFixes;
const INTRO = 'Attach a picture in the chat and send it, then press the button. I research things, places, labels and logos, with sources. I don\'t identify people from pictures.';
const NEED_PICTURE = 'Attach a picture in the chat and send it first, Sir. Then press the button.';
const LOOKING = 'Looking at the picture\u2026';
const OFFERED = 'The name is in the People box above. Press Research: the usual check decides whether I may look them up.';
const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
const FAILED = 'That did not work, Sir. Please try again.';
const MAX_SOURCES = 8, MAX_LINES = 12;
const S = { busy: false, can: true };
let goBtn = null, noteEl = null, cardEl = null;

const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
const txt = (v, max = 300) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
function detailOf(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
  return m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : FAILED;
}
function say(kind, text) { noteEl.className = 'bnote' + (kind === 'bad' ? ' bad' : ''); noteEl.textContent = text || ''; }
const paint = () => { goBtn.disabled = S.busy || !S.can; };
// The console's rule for every panel script: no API call before sign-in. A call made at load is answered
// 401, and the transport answers a 401 with the sign-in gate, which could land after he has signed in.
const signedIn = () => { const c = window.JarvisConsole; return !!(c && typeof c.ready === 'function' && c.ready()); };

// A source is shown as a link only when it is plain https with no login in it; its site is the link's own.
function source(raw) {
  const it = obj(raw);
  if (!it) return null;
  try {
    const u = new URL(String(it.url));
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    return { url: u.href, site: u.hostname.replace(/^www\./, ''), title: txt(it.title, 160) || u.hostname, snippet: txt(it.snippet, 400) };
  } catch (_) { return null; }
}
function sourceRow(s) {
  const li = F.mk('li', 'trow'), t = F.mk('div', 'ttxt');
  t.append(F.mk('b', 'tname', s.title), F.mk('span', 'tmeta', s.site));
  if (s.snippet) t.append(F.mk('span', 'tmeta pline', s.snippet));
  const a = F.mk('a', 'btn bact lift plink', 'Open source');
  a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
  a.setAttribute('aria-label', 'Open source: ' + s.title + ' (' + s.site + ')');
  li.append(t, a);
  return li;
}
// D21-D: a name read from the picture's own words is only OFFERED. The button fills the People box; the
// look-up happens when he presses Research there, through the same check as a typed name.
function offerRow(name, caption) {
  const row = F.mk('div', 'actions'), b = F.mk('button', 'btn lift bact', 'Put this name in the People box');
  const line = F.mk('p', 'fine', caption ? 'Caption read: \'' + caption + '\'' : ''); line.id = 'lookCaption';
  b.type = 'button'; b.id = 'lookOffer';
  b.addEventListener('click', () => {
    const box = document.getElementById('peopleName'), ctx = document.getElementById('peopleContext');
    if (!box) return;
    box.value = name; if (ctx) ctx.value = '';
    box.focus(); say('', OFFERED);
  });
  row.append(b);
  return [line, row];
}
function render(d) {
  cardEl.replaceChildren();
  if (!d) return;
  const sources = arr(d.sources).map(source).filter(Boolean).slice(0, MAX_SOURCES), person = d.person === true;
  const card = F.mk('div', 'integ'); card.dataset.state = sources.length ? 'linked' : 'unlinked';
  const head = F.mk('div', 'ihead'), body = F.mk('div', 'ibody');
  const count = sources.length ? sources.length + (sources.length === 1 ? ' source' : ' sources') : 'No sources';
  head.append(F.mk('b', '', 'The picture'), F.mk('span', 'istate', person ? 'A person' : count));
  const message = txt(d.message, 1500), lines = arr(d.text).slice(0, MAX_LINES).map((t) => txt(t, 200)).filter(Boolean);
  if (message) body.append(F.mk('p', 'psum', message));
  if (person && lines.length) body.append(F.mk('p', 'fine', 'Text in the picture: ' + lines.join('; ')));
  if (sources.length) { const ul = F.mk('ul', 'tlist plinks'); sources.forEach((s) => ul.append(sourceRow(s))); body.append(ul); }
  const offer = obj(d.offer), name = offer ? txt(offer.name, 80) : '';
  if (name) body.append(...offerRow(name, txt(offer.caption, 200)));
  card.append(head, body); cardEl.append(card);
}

async function status() {
  if (!goBtn || !signedIn()) return;
  let why = '';
  try { const d = obj(await F.api('/v1/picture')); S.can = !d || d.can !== false; why = d && !S.can ? txt(d.why, 400) : ''; }
  catch (_) { S.can = true; }                       // can't tell: let him try, the answer will say why
  paint(); if (!S.busy && (why || !cardEl.firstChild)) say('', why);
}
async function research() {
  if (S.busy) return;
  const A = window.JarvisApprovals, sid = A && typeof A.session === 'function' ? A.session() : null;
  if (typeof sid !== 'string' || !sid) { say('', NEED_PICTURE); return; }
  S.busy = true; paint(); render(null); say('', LOOKING);
  try {
    const d = obj(await F.api('/v1/picture/research', { method: 'POST', body: { session_id: sid, picture: 1 } }));
    if (d && d.status === 'done') { render(d); say('', ''); } else say('', (d && txt(d.message, 600)) || FAILED);
  } catch (e) { say('bad', detailOf(e)); }
  S.busy = false; paint();
}

function build() {
  const panel = document.getElementById('p-people');
  const root = document.getElementById('people') || (panel && panel.querySelector('.pbody'));
  if (!root || document.getElementById('look')) return;
  const box = F.mk('section', 'look'); box.id = 'look'; box.setAttribute('aria-labelledby', 'lookTitle');
  const head = F.mk('div', 'rhead'), title = F.mk('h3', 'k', 'Research a picture'); title.id = 'lookTitle'; head.append(title);
  const intro = F.mk('p', 'bfine', INTRO); intro.id = 'lookIntro';
  goBtn = F.mk('button', 'btn lift', 'Research the picture'); goBtn.type = 'button'; goBtn.id = 'lookGo';
  goBtn.addEventListener('click', research);
  const acts = F.mk('div', 'actions'); acts.append(goBtn);
  noteEl = F.mk('div', 'bnote'); noteEl.id = 'lookNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
  cardEl = F.mk('div', 'lookcard'); cardEl.id = 'lookCard';
  box.append(head, intro, acts, noteEl, cardEl);
  const mode = root.querySelector('.pmode');
  if (mode) root.insertBefore(box, mode); else root.append(box);
  if (signedIn()) status();
}

if (F) {
  F.part('look', { research, status });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
  document.addEventListener('jarvis:ready', status);
  document.addEventListener('jarvis:brainmode', status);
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'people' && d.open) status(); });
}
