// src/jarvis/api/static/console-voice-devices-panel.js - R5 workstream B (docs/plans/r5-voice.md D13, D14).
// Voice -> Sound devices: pick the sound output and the microphone, mark a device as earphones or
// a speaker, give it a nickname, choose what happens when a new device connects, and play a test
// sound. Rendered into JarvisVoice.panelSlot('devices') once the Voice panel is built.
// No build step; CSP script-src 'self'; textContent only. Device names never leave the browser.
(() => {
  'use strict';
  const NICK_MAX = 30;
  const TEST_TONE = Object.freeze({ freq: 660, ms: 260, gain: 0.15 });
  const KIND_OPTIONS = Object.freeze({ '': 'Auto-detect', headphones: 'Earphones', speakers: 'A speaker' });
  const POLICY_OPTIONS = Object.freeze({ ask: 'Ask me', auto: 'Switch automatically', never: 'Do nothing' });
  const KIND_WORDS = Object.freeze({ headphones: 'Earphones or headset', speakers: 'Speaker', unknown: 'Kind not known' });
  const NO_NAMES = 'Device names appear after you allow the microphone once (tap the mic).';
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hon = () => {
    const c = window.JarvisChat;
    try { return String((c && typeof c.honorific === 'function' && c.honorific()) || 'Sir'); } catch (_) { return 'Sir'; }
  };
  const route = () => window.JarvisAudioRoute;
  const prefs = () => window.JarvisAudioRoutePrefs;

  let slot = null;
  let ui = null;
  let lastSig = '';

  function build() {
    const sec = mk('section', 'bsec vdev');
    sec.setAttribute('aria-labelledby', 'vDevicesT');
    const h = mk('h3'); h.id = 'vDevicesT'; h.append(mk('span', '', 'Sound devices'));
    ui = {
      note: mk('p', 'bfine vlead'), outHead: mk('p', 'bl vdev-h', 'Where I sound'), outList: mk('div', 'vlist'),
      inHead: mk('p', 'bl vdev-h', 'What I listen through'), inList: mk('div', 'vlist'), inNote: mk('p', 'bfine'),
      browser: mk('p', 'bfine'), status: mk('p', 'bnote vdev-status'),
    };
    ui.status.setAttribute('role', 'status'); ui.status.setAttribute('aria-live', 'polite');
    ui.policy = mk('div', 'bopt');
    ui.test = mk('button', 'btn lift bact test', 'Test sound'); ui.test.type = 'button';
    ui.test.addEventListener('click', playTest);
    const again = mk('button', 'btn lift bact', 'Look for devices again'); again.type = 'button';
    again.addEventListener('click', () => { route().refresh(); });
    const actions = mk('div', 'vdev-actions'); actions.append(ui.test, again);
    sec.append(h, ui.note, ui.outHead, ui.outList, actions, ui.inHead, ui.inList, ui.inNote, ui.policy, ui.browser, ui.status);
    slot.replaceChildren(sec);
    buildPolicy();
  }
  function buildPolicy() {
    const t = mk('div', 'btxt');
    const l = mk('label', 'bl', 'When a new device connects'); l.htmlFor = 'vDevPolicy';
    t.append(l, mk('small', '', 'Headphones or a speaker switching on. I can ask, switch by myself, or stay quiet.'));
    const s = mk('select', 'bsel onconnect'); s.id = 'vDevPolicy';
    Object.keys(POLICY_OPTIONS).forEach((k) => { const o = mk('option', '', POLICY_OPTIONS[k]); o.value = k; s.append(o); });
    s.addEventListener('change', () => { prefs().setOnConnect(s.value); });
    ui.policy.append(t, s);
    ui.policySelect = s;
  }

  function say(text) { if (ui) ui.status.textContent = text; }
  async function playTest() {
    const s = window.JarvisVoice && window.JarvisVoice.speaker;
    const ok = s ? await s.tone(TEST_TONE) : false;
    say(ok ? 'Played a short sound on the current output.' : `I couldn't play the test sound, ${hon()}. Tap the page once and try again.`);
  }
  function outcome(r, name, mic) {
    if (!r.ok) return r.reason === 'unsupported' ? `This browser can't choose that, ${hon()}.` : `I couldn't switch to ${name}, ${hon()}.`;
    if (mic) return r.warning ? `Listening through ${name}, ${hon()}. Heads up: a headset microphone makes Windows play all sound in call quality.` : `Listening through ${name}, ${hon()}.`;
    return `Sound now plays through ${name}, ${hon()}.`;
  }

  function useButton(name, pressed, onUse) {
    const b = mk('button', 'btn lift bact use', pressed ? 'In use' : 'Use');
    b.type = 'button'; b.setAttribute('aria-pressed', String(pressed)); b.setAttribute('aria-label', `Use ${name}`);
    b.dataset.key = 'use:' + name;
    b.addEventListener('click', onUse);
    return b;
  }
  function kindSelect(d) {
    const s = mk('select', 'bsel kind'); s.setAttribute('aria-label', `This is, for ${d.name}`);
    Object.keys(KIND_OPTIONS).forEach((k) => { const o = mk('option', '', KIND_OPTIONS[k]); o.value = k; s.append(o); });
    s.value = prefs().prefs().kinds[d.id] || '';
    s.dataset.key = 'kind:' + d.id;
    s.addEventListener('change', () => { prefs().setKind(d.id, s.value || null); });
    return s;
  }
  function nickInput(d) {
    const i = mk('input', 'bsel nick'); i.type = 'text'; i.maxLength = NICK_MAX;
    i.placeholder = 'Nickname'; i.setAttribute('aria-label', `Nickname for ${d.label}`);
    i.value = prefs().prefs().names[d.id] || ''; i.dataset.key = 'nick:' + d.id;
    i.addEventListener('change', () => { prefs().setName(d.id, i.value); });
    return i;
  }
  function row(attr, d, pressed, isDefault, onUse) {
    const r = mk('div', 'bopt vdev-row'); r.dataset[attr] = d.id;
    const t = mk('div', 'btxt');
    t.append(mk('span', 'bl', d.name));
    const sub = isDefault ? 'Whatever the system is using' : KIND_WORDS[d.kind] || KIND_WORDS.unknown;
    t.append(mk('small', '', d.callQuality ? sub + ' (lower quality, for calls)' : sub));
    if (!isDefault && attr === 'in' && d.kind === 'headphones') {
      t.append(mk('small', 'warn', 'Using this microphone makes Windows play all sound in call quality.'));
    }
    const ctl = mk('div', 'vdev-ctl');
    ctl.append(useButton(d.name, pressed, onUse));
    if (!isDefault) ctl.append(kindSelect(d), nickInput(d));
    r.append(t, ctl);
    return r;
  }
  function renderOutputs(dev, cur) {
    const rows = [];
    if (prefs().canRoute()) {
      const sys = { id: 'default', name: 'System default', label: 'System default', kind: 'unknown', callQuality: false };
      const pick = async (d) => { const r = await route().chooseOutput(d.id === 'default' ? null : d.id); say(outcome(r, d.name, false)); };
      rows.push(row('out', sys, !cur.output, true, () => pick(sys)));
      dev.outputs.forEach((d) => rows.push(row('out', d, !!cur.output && cur.output.id === d.id, false, () => pick(d))));
    }
    ui.outList.replaceChildren(...rows);
  }
  function renderInputs(dev, cur) {
    const sys = { id: 'default', name: 'Laptop default microphone', label: 'Laptop default microphone', kind: 'unknown', callQuality: false };
    const rows = [];
    const pick = async (d) => { const r = await route().chooseInput(d.id === 'default' ? null : d.id); say(outcome(r, d.name, true)); };
    if (dev.inputs.length > 1 || !prefs().onAndroid()) {
      rows.push(row('in', sys, !cur.input, true, () => pick(sys)));
      dev.inputs.forEach((d) => rows.push(row('in', d, !!cur.input && cur.input.id === d.id, false, () => pick(d))));
    }
    ui.inList.replaceChildren(...rows);
    ui.inNote.textContent = rows.length ? '' : `Android picks the microphone, ${hon()}.`;
  }
  function renderNotes(dev) {
    const h = hon();
    const android = prefs().onAndroid();
    const can = prefs().canRoute();
    let note = dev.labelled ? 'Pick where I sound and what I listen through. Pairing a new device is done in your system settings.' : NO_NAMES;
    if (!can) {
      note = android
        ? `On this phone Android chooses where I sound, ${h}: open Quick Settings and pick it under media output (the name varies by phone).`
        : `This browser can't choose the sound output, ${h}. Use your system's sound settings.`;
    }
    ui.note.textContent = note;
    ui.browser.textContent = android ? '' : `My browser voice follows Windows' sound output, ${h}: press Windows + Ctrl + V to choose it.`;
    ui.test.hidden = !can;
    ui.outHead.hidden = !can;
  }

  function render() {
    if (!slot || !ui || !route() || !prefs()) return;
    const dev = prefs().devices(), cur = route().current();
    const sig = JSON.stringify([dev, prefs().prefs(), cur, prefs().canRoute()]);
    if (sig === lastSig) return;
    lastSig = sig;
    const key = document.activeElement && slot.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    renderNotes(dev); renderOutputs(dev, cur); renderInputs(dev, cur);
    ui.policySelect.value = prefs().prefs().onConnect;
    if (key) {
      const again = Array.from(slot.querySelectorAll('[data-key]')).find((n) => n.dataset.key === key);
      if (again) again.focus();
    }
  }
  function mount() {
    const s = window.JarvisVoice && window.JarvisVoice.panelSlot('devices');
    if (!s || s === slot || !route() || !prefs()) return;
    slot = s; lastSig = '';
    build(); render();
    route().refresh();
  }
  if (route() && prefs()) {
    route().on('devices', render);
    route().on('route', render);
    document.addEventListener('jarvis:voice-panel', mount);
    mount();
  }
})();
