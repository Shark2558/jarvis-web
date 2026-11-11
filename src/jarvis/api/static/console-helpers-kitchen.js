// src/jarvis/api/static/console-helpers-kitchen.js -- R11 Part D's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D15, D19): your pantry, your tastes (diet, spice, oil, cuisines), saved recipes
// with rough nutrition, grocery spend a month from your e-mailed receipts, and cooking / washing-up times that go
// to your calendar only through an approval card. An ES module loaded by console-helpers.js (never linked); it
// uses only window.JarvisHelpers' builders and existing components (.btn.sact, .sacts, .minput, .bsw, .snote);
// server strings reach the page through textContent only. Talks to /v1/helpers/kitchen (api/helpers_kitchen.py).
// New recipe ideas come from the chat ("what can I cook?"): this tab never calls the AI.
const H = window.JarvisHelpers;
if (H) {
  const P = '/v1/helpers/kitchen';
  const DIETS = [['veg', 'Vegetarian (no meat, fish or egg)'], ['egg', 'Vegetarian with eggs'], ['nonveg', 'Non-vegetarian']];
  const SPICE = ['Not spicy', 'Mild', 'Medium', 'Hot'];
  const OIL = ['Very little oil', 'Normal oil', 'Rich'];
  const SHORT = { veg: 'vegetarian', egg: 'with eggs', nonveg: 'non-veg' };
  const UI = { host: null, body: null, note: null, view: null, busy: false };

  function btn(label, onClick, cls) {
    const b = H.mk('button', 'btn sact' + (cls ? ' ' + cls : ''), label);
    b.type = 'button';
    b.addEventListener('click', () => { if (!UI.busy) onClick(b); });
    return b;
  }
  function acts(...els) { const a = H.mk('div', 'sacts'); els.forEach((e) => a.append(e)); return a; }
  function field(label, input) {
    const l = H.mk('label', 'hp-field');
    l.append(H.mk('span', 'snote', label), input);
    return l;
  }
  function input(type, value, max) {
    const i = H.mk('input', 'minput');
    i.type = type;
    if (max) i.maxLength = max;
    i.value = value == null ? '' : String(value);
    i.autocomplete = 'off';
    return i;
  }
  function select(options, value) {
    const s = H.mk('select', 'minput');
    options.forEach(([v, text]) => { const o = H.mk('option', '', text); o.value = String(v); s.append(o); });
    s.value = String(value);
    return s;
  }
  function say(kind, text) { H.note(UI.note, kind, text); }
  function failed(e) {
    say('bad', e && e.name === 'TypeError' ? 'Can\u2019t reach JARVIS. Check your connection.' : (e && e.message) || 'That didn\u2019t work.');
  }
  async function send(path, method, body, done) {
    UI.busy = true;
    try {
      const v = await H.api(P + path, { method, body });
      if (v && v.sealed !== undefined) draw(v);
      say('ok', done || 'Saved.');
      return v;
    } catch (e) { failed(e); return null; } finally { UI.busy = false; }
  }

  // ---- the sections ------------------------------------------------------------------------------------------
  function pantry(v) {
    const s = H.section('Pantry');
    const items = Array.isArray(v.pantry) ? v.pantry : [];
    if (!items.length) s.append(H.empty('Nothing yet. Add what you have, or tell JARVIS "add rice and dal to my pantry".'));
    items.forEach((name) => s.append(H.row(name, '', [btn('Remove', () => send('/pantry', 'POST', { remove: [name] }, 'Taken out.'))])));
    const add = input('text', '', 200);
    add.placeholder = 'rice, toor dal, onions';
    s.append(field('Add to your pantry', add), acts(btn('Add', () => {
      const names = add.value.split(',').map((x) => x.trim()).filter(Boolean);
      if (names.length) send('/pantry', 'POST', { add: names }, 'Added.');
    })));
    return s;
  }
  function tastes(v) {
    const p = v.prefs || {};
    const s = H.section('Your tastes');
    const diet = select(DIETS, p.diet || 'veg');
    const spice = select(SPICE.map((t, i) => [i, t]), p.spice == null ? 1 : p.spice);
    const oil = select(OIL.map((t, i) => [i, t]), p.oil == null ? 1 : p.oil);
    const cuisines = input('text', (p.cuisines || []).join(', '), 200);
    cuisines.placeholder = 'Kerala, Odia, North Indian';
    const note = input('text', p.note || '', 200);
    note.placeholder = 'no mushrooms, less salt';
    s.append(field('Diet', diet), field('Spice', spice), field('Oil', oil), field('Cuisines you like', cuisines),
      field('A note for recipe ideas', note));
    s.append(acts(btn('Save tastes', () => send('/prefs', 'PUT', {
      diet: diet.value, spice: Number(spice.value), oil: Number(oil.value),
      cuisines: cuisines.value.split(',').map((x) => x.trim()).filter(Boolean).slice(0, 6), note: note.value,
    }))));
    s.append(H.mk('p', 'snote', 'JARVIS checks every recipe idea against your diet itself: one that breaks it is never shown.'));
    return s;
  }
  function recipes(v) {
    const s = H.section('Saved recipes');
    const list = Array.isArray(v.recipes) ? v.recipes : [];
    if (!list.length) s.append(H.empty('No saved recipes yet. Ask JARVIS "what can I cook?" and say "save it".'));
    list.forEach((r) => {
      const words = [r.minutes + ' min', SHORT[r.diet] || '', r.nutrition || ''].filter(Boolean).join(' \u00b7 ');
      s.append(H.row(r.title, words, [btn('Remove', () => send('/recipes/' + encodeURIComponent(r.id), 'DELETE', undefined, 'Removed.'))]));
    });
    const n = v.nutrition || {};
    s.append(H.mk('p', 'snote', n.installed ? n.attribution : 'Nutrition data isn\u2019t installed yet (USDA FoodData Central).'));
    s.append(H.mk('p', 'snote', 'New ideas use the AI from the chat, metered like a reply; with the AI off you get your saved recipes.'));
    return s;
  }
  function spend(v) {
    const sp = v.spend || {};
    const s = H.section('Grocery spend');
    s.append(H.row('Read my grocery receipts', sp.can_scan ? 'Each morning, from BigBasket, Blinkit, Zepto, Instamart and similar shops.'
      : 'Needs Google linked in Integrations.', [H.toggle('Read my grocery receipts', !!sp.on, (on) => send('/spend', 'PUT', { on }))]));
    (sp.months || []).forEach((m) => {
      s.append(H.row(m.label, m.total + ' from ' + m.orders + (m.orders === 1 ? ' order' : ' orders'), []));
    });
    if (sp.on && !(sp.months || []).length) s.append(H.empty('No grocery receipts found yet.'));
    if (sp.on && sp.can_scan) s.append(acts(btn('Check now', () => send('/spend/scan', 'POST', undefined, 'Checked.'))));
    s.append(H.mk('p', 'snote', 'Only the shop, the day and the amount are kept, sealed. Never the mail, the items or a card number.'));
    return s;
  }
  function blocks(v) {
    const b = v.blocks || {};
    const s = H.section('Cooking and washing-up');
    const ca = input('time', b.cooking_at || '19:00');
    const cm = input('number', b.cooking_minutes || 45);
    const wa = input('time', b.washing_at || '20:30');
    const wm = input('number', b.washing_minutes || 15);
    const days = input('text', (b.days || []).join(', '), 40);
    days.placeholder = 'every day, or mon, wed, fri';
    s.append(field('Cooking starts', ca), field('Cooking minutes', cm), field('Washing-up starts', wa),
      field('Washing-up minutes', wm), field('Days (empty: every day)', days));
    const plan = () => ({
      cooking_at: ca.value, cooking_minutes: Number(cm.value), washing_at: wa.value, washing_minutes: Number(wm.value),
      days: days.value.split(/[\s,]+/).map((x) => x.trim().toLowerCase().slice(0, 3)).filter(Boolean),
    });
    const ask = btn('Ask to add to my calendar', async () => {
      if (!(await send('/blocks', 'PUT', plan(), 'Saved.'))) return;
      const got = await send('/blocks/propose', 'POST', undefined, 'The card is waiting in Approvals.');
      if (got && got.message) say('ok', 'Waiting in Approvals: ' + got.message);
    });
    if (!v.calendar) ask.disabled = true;
    s.append(acts(btn('Save times', () => send('/blocks', 'PUT', plan())), ask));
    s.append(H.mk('p', 'snote', v.calendar ? 'Nothing is added until you approve the card.' : 'Link Google in Integrations to add calendar blocks.'));
    return s;
  }

  function draw(v) {
    UI.view = v;
    if (!UI.body) return;
    if (v && v.sealed === false) { UI.body.replaceChildren(H.empty(v.detail || 'The kitchen is off on this server.')); return; }
    UI.body.replaceChildren(pantry(v), tastes(v), recipes(v), spend(v), blocks(v));
  }
  async function load() {
    try { draw(await H.api(P)); } catch (e) {
      if (e && e.status === 404) { UI.body.replaceChildren(H.empty('The kitchen helper is off on this server.')); return; }
      failed(e);
    }
  }

  H.register('kitchen', {
    mount(host) {
      UI.host = host;
      UI.note = H.mk('p', 'sfine hp-note');
      UI.note.setAttribute('role', 'status');
      UI.body = H.mk('div', 'hp-kitchen');
      UI.body.append(H.empty('Loading your kitchen\u2026'));
      host.append(UI.note, UI.body);
      load();
    },
    refresh() { if (!UI.busy) load(); },
  });
}
