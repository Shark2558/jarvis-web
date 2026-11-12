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
  // ---- faces from the owner's photos (R11.1): GET /faces/api/groups -> {available, groups:[{id, n,
  // photos, crops}], strays, engine, folder, read, waiting, keep_days}; GET /faces/api/groups/<id>/<i>
  // (a crop); POST /faces/api/groups/forget {group}; POST /faces/api/groups/rescan. Naming is done in
  // JARVIS (the consent check lives there), never on this page.
  const GROUP = /^c_[0-9a-f]{12}$/;
  const count = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);
  const FOLDER = { off: 'Photo folder: off. It stays off until you choose a folder (PHOTOS_DIR).', unreadable: 'Photo folder: this laptop cannot open it. Check the folder you chose (PHOTOS_DIR).' };
  async function forget(id, btn) {
    if (btn.dataset.sure !== '1') { btn.dataset.sure = '1'; btn.textContent = 'Really forget this group?'; return; }
    try { await call('/faces/api/groups/forget', { method: 'POST', body: JSON.stringify({ group: id }), headers: { 'Content-Type': 'application/json' } }); say('Forgotten.'); await loadGroups(); }
    catch (e) { say(e.message, true); }
  }
  function renderGroups(d) {
    const box = $('groups-box'); box.hidden = d.available !== true; if (box.hidden) return;
    $('keep-days').textContent = String(count(d.keep_days) || 90);
    const engine = d.engine === 'ready' ? '' : ' The face reader is not ready yet: run the home kit update.';
    $('folder-line').textContent = (FOLDER[d.folder] || ('Photo folder: on. ' + count(d.read) + ' file(s) read, ' + count(d.waiting) + ' waiting.')) + engine;
    const list = $('groups'); list.textContent = '';
    const rows = Array.isArray(d.groups) ? d.groups.filter((g) => g && GROUP.test(g.id)).slice(0, 100) : [];
    if (!rows.length) list.appendChild(mk('li', 'No groups to name yet. A face becomes a group when it is in 3 photos.'));
    rows.forEach((g) => {
      const li = mk('li'); const head = mk('div');
      head.append(mk('b', 'Group ' + count(g.n)), mk('div', count(g.photos) + ' photo(s)', 'fine'), mk('code', g.id));
      const crops = mk('div', '', 'crops');
      for (let i = 0; i < Math.min(count(g.crops), 5); i += 1) { const img = mk('img'); img.alt = 'A face from group ' + count(g.n); img.src = '/faces/api/groups/' + g.id + '/' + i; crops.appendChild(img); }
      const drop = mk('button', 'Forget this group'); drop.type = 'button'; drop.addEventListener('click', () => forget(g.id, drop));
      li.append(head, crops, drop); list.appendChild(li);
    });
  }
  async function loadGroups() { try { renderGroups(await call('/faces/api/groups')); } catch (e) { $('groups-box').hidden = true; } }
  async function load() {
    try { const d = await call('/faces/api/people'); if (typeof d.csrf === 'string') csrf = d.csrf; $('login').hidden = true; $('people-box').hidden = false; render(d); await loadGroups(); }
    catch (e) { if (e.status === 401) showLogin(); else say(e.message, true); }
  }

  $('login').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { const r = await call('/faces/api/login', { method: 'POST', body: JSON.stringify({ code: $('code').value }), headers: { 'Content-Type': 'application/json' } }); csrf = typeof r.csrf === 'string' ? r.csrf : ''; $('code').value = ''; say(''); await load(); }
    catch (err) { say(err.message, true); }
  });
  $('rescan').addEventListener('click', async () => { try { await call('/faces/api/groups/rescan', { method: 'POST' }); say('The photo folder will be read again from the start.'); await loadGroups(); } catch (e) { say(e.message, true); } });
  $('logout').addEventListener('click', async () => { try { await call('/faces/api/logout', { method: 'POST' }); } catch (e) { /* signed out anyway */ } csrf = ''; showLogin(); });
  load();
})();
