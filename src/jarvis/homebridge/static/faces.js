// The laptop Faces page (R3 D13). Same-origin only; textContent only; no inline script.
// API (this bridge): POST /faces/api/login {code} -> {csrf}; GET /faces/api/people ->
// {people:[{id, pictures}], recent:[file], max_pictures, retention: on|off}; POST /faces/api/enrol?person=<id> (raw
// image body, X-CSRF); POST /faces/api/classify {person, file}; POST /faces/api/logout.
(() => {
  'use strict';
  const ID = /^fp_[0-9a-f]{12}$/, FILE = /^[A-Za-z0-9._-]{1,120}$/;
  const MAX_BYTES = 5 * 1024 * 1024;
  let csrf = '';
  const $ = (id) => document.getElementById(id);
  const mk = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const say = (text, bad) => { const s = $('status'); s.textContent = text || ''; s.className = bad ? 'bad' : ''; };

  async function call(path, opts) {
    const o = Object.assign({ credentials: 'same-origin', headers: {} }, opts || {});
    if (o.method && o.method !== 'GET') o.headers['X-CSRF'] = csrf;
    const r = await fetch(path, o);
    let body = {};
    try { body = await r.json(); } catch (e) { body = {}; }
    if (!r.ok) { const err = new Error(typeof body.detail === 'string' ? body.detail : 'Something went wrong.'); err.status = r.status; throw err; }
    return body;
  }
  function showLogin() { $('login').hidden = false; $('people-box').hidden = true; $('code').focus(); }

  async function enrol(person, input) {
    const f = input.files && input.files[0];
    input.value = '';
    if (!f) return;
    if (f.size > MAX_BYTES) { say('That picture is over 5 MB.', true); return; }
    try {
      const r = await call('/faces/api/enrol?person=' + encodeURIComponent(person), { method: 'POST', body: f, headers: { 'Content-Type': f.type || 'application/octet-stream' } });
      say('Added. This person now has ' + (Number.isInteger(r.pictures) ? r.pictures : 'more') + ' picture(s).');
      await load();
    } catch (e) { say(e.message, true); }
  }
  async function classify(person, file) {
    try { await call('/faces/api/classify', { method: 'POST', body: JSON.stringify({ person, file }), headers: { 'Content-Type': 'application/json' } }); say('Added to that person.'); await load(); }
    catch (e) { say(e.message, true); }
  }

  function render(d) {
    // review S5: say so when the bridge can't clean up or delete pictures in Frigate's folder
    if (d.retention === 'off') say('Old pictures of visitors are not being cleaned up, and deleting a person waits until they are. Run setup-wsl.sh configure again on this laptop.', true);
    const people = Array.isArray(d.people) ? d.people.filter((p) => p && ID.test(p.id)) : [];
    const list = $('people'); list.textContent = '';
    if (!people.length) list.appendChild(mk('li', 'Nobody is listed yet. Add a person in JARVIS \u2192 Faces first (with their consent).'));
    people.forEach((p) => {
      const li = mk('li');
      const left = mk('div'); left.append(mk('code', p.id), mk('div', (Number.isInteger(p.pictures) ? p.pictures : 0) + ' picture(s) on this laptop', 'fine'));
      const inp = mk('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png'; inp.setAttribute('aria-label', 'Add a picture for ' + p.id);
      inp.addEventListener('change', () => enrol(p.id, inp));
      li.append(left, inp); list.appendChild(li);
    });
    const recent = $('recent'); recent.textContent = '';
    const files = Array.isArray(d.recent) ? d.recent.filter((f) => typeof f === 'string' && FILE.test(f)).slice(0, 40) : [];
    if (!files.length) recent.appendChild(mk('li', 'No recent visitors.'));
    files.forEach((f) => {
      const li = mk('li'); const img = mk('img'); img.alt = 'A face the camera saw'; img.src = '/faces/api/recent/' + encodeURIComponent(f);
      const sel = mk('select'); sel.setAttribute('aria-label', 'Who is this?');
      sel.appendChild(Object.assign(mk('option', 'Who is this?'), { value: '' }));
      people.forEach((p) => sel.appendChild(Object.assign(mk('option', p.id), { value: p.id })));
      sel.addEventListener('change', () => { if (ID.test(sel.value)) classify(sel.value, f); });
      li.append(img, sel); recent.appendChild(li);
    });
  }
  async function load() {
    try { const d = await call('/faces/api/people'); if (typeof d.csrf === 'string') csrf = d.csrf; $('login').hidden = true; $('people-box').hidden = false; render(d); }
    catch (e) { if (e.status === 401) showLogin(); else say(e.message, true); }
  }

  $('login').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { const r = await call('/faces/api/login', { method: 'POST', body: JSON.stringify({ code: $('code').value }), headers: { 'Content-Type': 'application/json' } }); csrf = typeof r.csrf === 'string' ? r.csrf : ''; $('code').value = ''; say(''); await load(); }
    catch (err) { say(err.message, true); }
  });
  $('logout').addEventListener('click', async () => { try { await call('/faces/api/logout', { method: 'POST' }); } catch (e) { /* signed out anyway */ } csrf = ''; showLogin(); });
  load();
})();
