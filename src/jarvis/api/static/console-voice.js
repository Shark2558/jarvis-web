// src/jarvis/api/static/console-voice.js — the Voice panel and the voice settings (slice 9,
// docs/plans/phase1-slice9-voice.md §3–§5). No build step; CSP script-src 'self'.
// Every server string reaches the page through textContent; a field of the wrong type is dropped,
// never guessed. Costs are rupees only. Transport is the console's own api() for JSON
// (window.JarvisConsole) and JarvisChat.raw() for audio (same cookie / X-Requested-With: JARVIS /
// bearer token; 401 → the sign-in gate).
// Two kinds of setting:
//   the owner's (server, PUT /v1/voice/settings, debounced and one at a time): voice, rate, wit;
//   this device's (localStorage, wrapped in try/catch): speech engine, voice finish, speak replies,
//   send straight away, keep listening, "Hey Jarvis" (off by default).
// window.JarvisVoice (used by console-voice-mic.js and console-3d.js):
//   config() (undefined = not loaded, null = no voice service here), load(force), device(),
//   setDevice(patch), settings(), inputEngine() / outputEngine() ('cloud' | 'browser' | 'none'),
//   markDown(kind), language(), speaker (JarvisSpeaker), visual() / setVisual(fn) for the Core.
// Fires: jarvis:voice-config, jarvis:voice-device, jarvis:voice-note {text}, jarvis:speech {text, engine}.
// Listens: jarvis:ready, jarvis:panel (Voice shown), jarvis:wake {state} (console-voice-mic.js).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const panel = $('p-voice'), box = $('voice'), noteEl = $('voiceNote'), metaEl = $('voiceMeta');
  const Deck = window.JarvisDeck || { rupees: () => '' };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const DEVICE_KEY = 'jarvis_voice_device_v1';
  const ENGINES = { auto: 'Automatic', cloud: 'Google Cloud', browser: 'This browser' };
  const SPEAKS = { voice: 'When I speak', always: 'Always', never: 'Never' };
  const FINISHES = { comms: 'Comms', clean: 'Clean' };
  const DEVICE_DEFAULTS = Object.freeze({ engine: 'auto', finish: 'comms', speak: 'voice', autoSend: true, keepListening: true, wake: false });
  const RATE_MIN = 0.8, RATE_MAX = 1.25, RATE_STEP = 0.05;
  const SAVE_DEBOUNCE_MS = 500, FRESH_MS = 60 * 1000, DOWN_MS = 10 * 60 * 1000, NOTE_MS = 5000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const GCLOUD_FIX = 'gcloud services enable texttospeech.googleapis.com speech.googleapis.com';
  const WAKE_LICENCE = 'Wake word model: openWakeWord (CC BY-NC-SA 4.0), personal use';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const own = (map, key) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key);
  const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const count = (n) => { try { return Math.round(n).toLocaleString('en-US'); } catch (_) { return String(Math.round(n)); } };
  const clampRate = (r) => Math.min(RATE_MAX, Math.max(RATE_MIN, Math.round(r / RATE_STEP) * 5 / 100)); // 1.15, never 1.1500000000000001
  function detailOf(e) { // the server's plain-English message, never a bare code or "[object …]"
    if (e && e.name === 'TypeError') return OFFLINE;
    const t = (e && typeof e.message === 'string' ? e.message : '').replace(INVISIBLE, '').trim();
    return t && t.length <= 300 && !t.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(t) ? t : '';
  }

  // ---- this device's settings ------------------------------------------------------------------
  function readDevice() {
    let saved = null;
    try { saved = obj(JSON.parse(store.get(DEVICE_KEY) || 'null')); } catch (_) { saved = null; }
    const s = saved || {}, d = Object.assign({}, DEVICE_DEFAULTS);
    if (own(ENGINES, s.engine)) d.engine = s.engine;
    if (own(FINISHES, s.finish)) d.finish = s.finish;
    if (own(SPEAKS, s.speak)) d.speak = s.speak;
    ['autoSend', 'keepListening', 'wake'].forEach(k => { if (typeof s[k] === 'boolean') d[k] = s[k]; });
    return Object.freeze(d);
  }
  let device = readDevice();
  function setDevice(patch) {
    const next = Object.assign({}, device);
    const p = obj(patch) || {};
    if (own(ENGINES, p.engine)) next.engine = p.engine;
    if (own(FINISHES, p.finish)) next.finish = p.finish;
    if (own(SPEAKS, p.speak)) next.speak = p.speak;
    ['autoSend', 'keepListening', 'wake'].forEach(k => { if (typeof p[k] === 'boolean') next[k] = p[k]; });
    device = Object.freeze(next);
    store.set(DEVICE_KEY, JSON.stringify(device));
    speaker.setFinish(device.finish);
    emit('jarvis:voice-device', device);
    render();
  }

  // ---- what GET /v1/voice sends, checked field by field ------------------------------------------
  const CLOUD_STATES = ['ready', 'off', 'unavailable'];
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const cloud = obj(o.cloud) || {}, st = obj(o.settings) || {}, al = obj(o.allowance) || {};
    const tts = obj(al.tts) || {}, stt = obj(al.stt) || {}, month = obj(o.month) || {};
    const voices = arr(o.voices).map(obj).filter(Boolean)
      .filter(v => v.available === true && typeof v.id === 'string' && ID.test(v.id))
      .map(v => ({ id: v.id, label: txt(v.label, 60) || v.id, style: txt(v.style, 60), type: txt(v.type, 30) }));
    const wit = arr(o.wit_levels).map(obj).filter(Boolean)
      .filter(w => typeof w.id === 'string' && ID.test(w.id))
      .map(w => ({ id: w.id, label: txt(w.label, 40) || w.id, description: txt(w.description, 300) }));
    const lang = txt(o.language, 20);
    const rate = num(st.rate);
    return {
      cloud: {
        tts: CLOUD_STATES.includes(cloud.tts) ? cloud.tts : 'off',
        stt: CLOUD_STATES.includes(cloud.stt) ? cloud.stt : 'off',
        reason: typeof cloud.reason === 'string' && /^[a-z_]{1,40}$/.test(cloud.reason) ? cloud.reason : null,
      },
      settings: {
        voice: typeof st.voice === 'string' && ID.test(st.voice) ? st.voice : null,
        rate: rate !== null ? clampRate(rate) : 1,
        wit: typeof st.wit === 'string' && ID.test(st.wit) ? st.wit : null,
      },
      voices, wit,
      allowance: {
        chars: num(tts.used_chars), freeChars: num(tts.free_chars),
        seconds: num(stt.used_seconds), freeSeconds: num(stt.free_seconds),
      },
      inr: num(month.voice_inr),
      language: /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(lang) ? lang : 'en-IN',
    };
  }

  // ---- state + server ------------------------------------------------------------------------------
  const S = {
    cfg: undefined, error: '', seq: 0, at: 0, loading: null,
    local: null, sending: null, saving: false, timer: 0,
    down: { tts: 0, stt: 0 }, noteTimer: 0, wake: { state: 'off', note: '' }, built: false,
  };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);

  function load(force) {
    if (!hasApi()) return Promise.resolve(S.cfg === undefined ? null : S.cfg);
    if (S.loading) return S.loading;
    if (!force && S.cfg !== undefined && Date.now() - S.at < FRESH_MS) return Promise.resolve(S.cfg);
    const seq = ++S.seq;
    S.loading = (async () => {
      try {
        const d = normal(await api('/v1/voice'));
        if (seq === S.seq) { if (d) { S.cfg = d; S.error = ''; } else S.error = 'The server sent something unexpected.'; }
      } catch (e) {
        if (seq === S.seq && e.status !== 401) {
          if (e.status === 404) { S.cfg = null; S.error = ''; } else S.error = detailOf(e) || 'Please try again.';
        }
      } finally { S.loading = null; S.at = Date.now(); }
      emit('jarvis:voice-config', { ready: !!S.cfg });
      render();
      return S.cfg === undefined ? null : S.cfg;
    })();
    render();
    return S.loading;
  }

  /** The owner's settings as this page wants them: saved, then in flight, then not yet sent. */
  function settings() {
    const base = S.cfg ? S.cfg.settings : { voice: null, rate: 1, wit: null };
    return Object.freeze(Object.assign({}, base, S.sending || {}, S.local || {}));
  }
  function change(patch) {
    S.local = Object.assign({}, S.local || {}, patch);
    clearTimeout(S.timer);
    S.timer = setTimeout(save, SAVE_DEBOUNCE_MS);
    renderValues();
  }
  /** One PUT at a time; changes made meanwhile go in the next one. */
  async function save() {
    if (S.saving || !S.local || !hasApi()) return;
    const body = S.local;
    S.local = null; S.sending = body; S.saving = true;
    try {
      const r = obj(await api('/v1/voice/settings', { method: 'PUT', body }));
      ++S.seq; // an older GET still on its way must not overwrite what was just saved
      if (r && S.cfg) {
        const fresh = normal({ settings: r }).settings;
        S.cfg = Object.assign({}, S.cfg, { settings: { voice: fresh.voice || S.cfg.settings.voice, rate: fresh.rate, wit: fresh.wit || S.cfg.settings.wit } });
      }
      flash('ok', 'Saved.');
      log('info', 'Voice settings saved');
    } catch (e) {
      if (e.status !== 401) flash('bad', 'Couldn\'t save. ' + (detailOf(e) || 'Please try again.'));
      if (e.status === 422) load(true); // what the server holds may differ: show it again
    } finally {
      S.sending = null; S.saving = false;
      renderValues();
      if (S.local) save();
    }
  }
  function flash(kind, text) {
    if (!noteEl) return;
    clearTimeout(S.noteTimer);
    noteEl.textContent = kind ? text : '';
    noteEl.className = 'bnote vlive' + (kind ? ' ' + kind : '');
    if (kind === 'ok') S.noteTimer = setTimeout(() => flash(null), NOTE_MS);
  }

  // ---- engines (§1 D3: cloud when ready, else the browser's, else typing) -------------------------
  const recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const capture = () => !!(window.JarvisAudio && window.JarvisAudio.supported());
  const cloudReady = (kind) => !!(S.cfg && S.cfg.cloud[kind] === 'ready' && Date.now() >= S.down[kind]);
  function inputEngine() {
    const cloud = cloudReady('stt') && capture(), browser = !!recognition();
    if (device.engine === 'browser') return browser ? 'browser' : cloud ? 'cloud' : 'none';
    return cloud ? 'cloud' : browser ? 'browser' : 'none';
  }
  function outputEngine() {
    if (cloudReady('tts')) return 'cloud';
    return window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function' ? 'browser' : 'none';
  }
  /** The cloud said no (503 / 402): use the browser's engine for ten minutes, then ask again. */
  function markDown(kind) { if (kind === 'tts' || kind === 'stt') { S.down[kind] = Date.now() + DOWN_MS; render(); } }

  // ---- speech out: POST /v1/voice/speak → MP3 → the shared speaker ---------------------------------
  function speakError(status, code, reason) {
    const e = new Error(code || 'speak_failed'); e.status = status;
    if (status === 422) e.skip = true;                                  // nothing_to_say: skip the chunk
    else if (status === 402 || status === 503) { e.fallback = true; e.reason = status === 402 ? 'budget' : reason || 'unavailable'; markDown('tts'); }
    else if (status === 401) e.skip = true;                             // the sign-in gate takes over
    else e.fallback = true;                                             // 429, 5xx: the browser says it
    return e;
  }
  async function synth(text, signal, meta) {
    const raw = window.JarvisChat && window.JarvisChat.raw;
    if (!raw) throw Object.assign(new Error('no_transport'), { fallback: true });
    const s = settings();
    const body = meta && meta.preview ? { preview: true, voice: meta.preview, rate: s.rate } : { text };
    if (!(meta && meta.preview)) { if (s.voice) body.voice = s.voice; body.rate = s.rate; }
    let r;
    try {
      r = await raw('/v1/voice/speak', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' }, signal });
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      if (err && err.status === 401) throw speakError(401);
      throw Object.assign(new Error('network'), { fallback: true, reason: 'network' });
    }
    if (r.ok) return r.arrayBuffer();
    let detail = null;
    try { detail = obj((await r.json()).detail); } catch (_) {}
    throw speakError(r.status, detail && typeof detail.code === 'string' ? detail.code : '', detail && typeof detail.reason === 'string' ? detail.reason : '');
  }
  const speaker = window.JarvisSpeaker.create({ synth, finish: device.finish });
  speaker.on('chunk', (d) => emit('jarvis:speech', { text: d.text, engine: d.engine }));
  let visualFn = null;

  // ---- rendering ---------------------------------------------------------------------------------
  // The structure is built once (a re-render must never interrupt a slider being dragged); every
  // render after that only updates values, states and texts.
  const UI = {};
  function section(title, id) {
    const s = mk('section', 'bsec'); s.setAttribute('aria-labelledby', id);
    const h = mk('h3'); h.id = id; h.append(mk('span', '', title)); s.append(h);
    return s;
  }
  function toggle(id, label, help, onPress) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('span', 'bl', label); l.id = id + 'L';
    const d = mk('small', '', help); d.id = id + 'D';
    t.append(l, d);
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
    b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-labelledby', l.id); b.setAttribute('aria-describedby', d.id);
    const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
    const st = mk('span', 'st', 'Off'); st.setAttribute('aria-hidden', 'true');
    b.append(track, st);
    b.addEventListener('click', () => onPress(b.getAttribute('aria-pressed') !== 'true'));
    row.append(t, b);
    return { row, button: b, help: d };
  }
  function setPressed(b, on) { b.setAttribute('aria-pressed', String(on)); b.querySelector('.st').textContent = on ? 'On' : 'Off'; }
  function select(id, label, help, options, onChange) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('label', 'bl', label); l.htmlFor = id;
    const d = mk('small', '', help); d.id = id + 'D';
    t.append(l, d);
    const s = mk('select', 'bsel'); s.id = id; s.setAttribute('aria-describedby', d.id);
    Object.keys(options).forEach(k => { const o = mk('option', '', options[k]); o.value = k; s.append(o); });
    s.addEventListener('change', () => onChange(s.value));
    row.append(t, s);
    return { row, select: s, help: d };
  }
  function build() {
    box.textContent = '';
    UI.state = mk('div', 'vstate'); UI.state.id = 'voiceState';
    UI.status = mk('div', 'vstatus'); UI.status.id = 'voiceStatus'; UI.status.setAttribute('role', 'status');
    // the owner's settings (saved on the server)
    UI.voiceSec = section('Voice', 'vVoiceT');
    UI.voiceList = mk('div', 'vlist'); UI.voiceList.setAttribute('role', 'radiogroup'); UI.voiceList.setAttribute('aria-labelledby', 'vVoiceT');
    UI.voiceSec.append(mk('p', 'bfine vlead', 'An original British voice. Press Preview to hear one.'), UI.voiceList);
    UI.rateSec = section('Speed', 'vRateT');
    const rr = mk('div', 'vrate');
    UI.rate = mk('input', 'vrange'); UI.rate.type = 'range'; UI.rate.id = 'vRate';
    UI.rate.min = String(RATE_MIN); UI.rate.max = String(RATE_MAX); UI.rate.step = String(RATE_STEP);
    UI.rate.setAttribute('aria-labelledby', 'vRateT');
    UI.rateOut = mk('output', 'vrout'); UI.rateOut.id = 'vRateOut'; UI.rateOut.htmlFor = 'vRate';
    UI.rate.addEventListener('input', () => { UI.rateOut.textContent = rateText(+UI.rate.value); UI.rate.setAttribute('aria-valuetext', rateText(+UI.rate.value)); });
    UI.rate.addEventListener('change', () => change({ rate: clampRate(+UI.rate.value) }));
    rr.append(UI.rate, UI.rateOut);
    UI.rateSec.append(rr);
    UI.witSec = section('Wit', 'vWitT');
    UI.witList = mk('div', 'vlist'); UI.witList.setAttribute('role', 'radiogroup'); UI.witList.setAttribute('aria-labelledby', 'vWitT');
    UI.witSec.append(mk('p', 'bfine vlead', 'How much dry humour JARVIS allows himself. Never in approvals, bad news or money matters.'), UI.witList);
    // this device's settings
    UI.devSec = section('On this device', 'vDevT');
    const eng = select('vEngine', 'Speech engine', '', ENGINES, (v) => setDevice({ engine: v }));
    UI.engine = eng.select; UI.engineHelp = eng.help;
    const fin = select('vFinish', 'Voice finish', 'Comms adds a light radio-and-room finish to the cloud voice. Clean plays it as it is.', FINISHES, (v) => setDevice({ finish: v }));
    UI.finish = fin.select;
    const sp = select('vSpeak', 'Speak replies', '', SPEAKS, (v) => setDevice({ speak: v }));
    UI.speak = sp.select; UI.speakHelp = sp.help;
    const auto = toggle('vAuto', 'Send what I say straight away', 'Off: your words wait in the message box so you can check them first.', (on) => setDevice({ autoSend: on }));
    const keep = toggle('vKeep', 'Keep listening after replies', 'After a spoken reply JARVIS listens for 6 seconds, so you can carry on talking.', (on) => setDevice({ keepListening: on }));
    UI.auto = auto.button; UI.keep = keep.button;
    UI.devSec.append(eng.row, sp.row, auto.row, keep.row, fin.row);
    // "Hey Jarvis": only when the wake-word module is here and works in this browser
    const wake = toggle('vWake', 'Say "Hey Jarvis"', 'This device only, off by default. Listens on this device; no audio leaves it until you say "Hey Jarvis".', (on) => setDevice({ wake: on }));
    UI.wake = wake.button;
    UI.wakeRow = mk('div', 'vwake'); UI.wakeRow.id = 'vWakeRow';
    UI.wakeChip = mk('p', 'vchip'); UI.wakeChip.id = 'vWakeChip'; UI.wakeChip.setAttribute('role', 'status');
    UI.wakeRow.append(wake.row, UI.wakeChip, mk('p', 'bfine', WAKE_LICENCE));
    UI.devSec.append(UI.wakeRow);
    // this month
    UI.useSec = section('This month', 'vUseT');
    UI.allow = mk('p', 'vallow'); UI.allow.id = 'vAllow';
    UI.useSec.append(UI.allow, mk('p', 'bfine', 'Google\'s free allowance is per billing account; these are JARVIS\'s own use. Rupee figures are estimates.'));
    box.append(UI.state, UI.status, UI.voiceSec, UI.rateSec, UI.witSec, UI.devSec, UI.useSec);
    S.built = true;
  }
  const rateText = (r) => r.toFixed(2) + '×';

  /** A radio list, rebuilt only when its options change (a re-render must not move the focus or the
   *  ground under a click); otherwise only which one is checked is updated. */
  function radio(list, name, items, current, onPick, extra) {
    const key = JSON.stringify(items);
    if (list.dataset.key === key) {
      list.querySelectorAll('input.vin').forEach(inp => { inp.checked = inp.value === current; });
      return;
    }
    list.dataset.key = key;
    const keepFocus = list.contains(document.activeElement) ? document.activeElement.id : null;
    list.textContent = '';
    items.forEach((it, i) => {
      const row = mk('div', 'vopt');
      const id = `${name}-${i}`;
      const inp = mk('input', 'vin'); inp.type = 'radio'; inp.name = name; inp.id = id; inp.value = it.id;
      inp.checked = it.id === current;
      inp.addEventListener('change', () => { if (inp.checked) onPick(it.id); });
      const lab = mk('label', 'vlab'); lab.htmlFor = id;
      lab.append(mk('b', '', it.label));
      const sub = it.style || it.description; if (sub) lab.append(mk('small', '', sub));
      row.append(inp, lab);
      if (extra) row.append(extra(it, i));
      list.append(row);
    });
    if (keepFocus && $(keepFocus)) $(keepFocus).focus({ preventScroll: true });
  }
  function previewButton(v, i) {
    const b = mk('button', 'btn lift bact vprev'); b.type = 'button'; b.id = `vPrev-${i}`;
    b.setAttribute('aria-label', `Preview ${v.label}`);
    b.append(mk('span', 'vplay', '▶'), document.createTextNode(' Preview'));
    b.firstChild.setAttribute('aria-hidden', 'true');
    b.addEventListener('click', () => preview(v.id));
    return b;
  }
  function preview(id) {
    if (outputEngine() !== 'cloud') { flash('bad', 'Previews need the cloud voice, which isn\'t available right now.'); return; }
    speaker.stop();
    speaker.unlock();
    speaker.browser(false);
    const h = window.JarvisChat && typeof window.JarvisChat.honorific === 'function' ? window.JarvisChat.honorific() : 'Sir';
    speaker.say(`Good evening, ${h}. Systems are running smoothly.`, { preview: id });
    speaker.end();
  }

  function statusLines(cfg) {
    if (cfg === null) return [['', 'Not available in this setup: this server has no voice service yet. This browser\'s own voice and speech recognition still work where supported.']];
    if (!cfg) return [];
    const c = cfg.cloud, worst = [c.tts, c.stt].includes('unavailable') ? 'unavailable' : [c.tts, c.stt].includes('off') ? 'off' : 'ready';
    const downNow = Date.now() < S.down.tts || Date.now() < S.down.stt;
    if (worst === 'ready' && !downNow) return [['ok', 'Cloud voice ready: Google speech, in your own Google Cloud project.']];
    if (worst === 'ready') return [['warn', 'Google\'s voice service said no just now (busy, or this month\'s limit), so JARVIS uses this browser\'s voice. It tries the cloud again in about 10 minutes.']];
    if (worst === 'off') return [['', 'Cloud voice is switched off on this server (JARVIS_VOICE_CLOUD). JARVIS uses this browser\'s voice and speech recognition.']];
    if (c.reason === 'api_disabled') return [['warn', 'Google\'s speech services aren\'t switched on in your Google Cloud project yet, so JARVIS uses this browser\'s voice for now. To fix it, run this once in Cloud Shell:'], ['code', GCLOUD_FIX]];
    if (c.reason === 'not_configured') return [['warn', 'This server has no Google Cloud credentials for speech, so JARVIS uses this browser\'s voice. Deploying on Cloud Run with the jarvis-run account switches it on.']];
    return [['warn', 'Google\'s speech service isn\'t answering right now, so JARVIS uses this browser\'s voice. It tries again in about 10 minutes.']];
  }
  function allowanceText(a, inr) {
    const parts = [];
    if (a.chars !== null && a.freeChars !== null) parts.push(`${count(a.chars)} of ${count(a.freeChars)} free characters`);
    if (a.seconds !== null && a.freeSeconds !== null) parts.push(`${count(Math.ceil(a.seconds / 60))} of ${count(Math.floor(a.freeSeconds / 60))} free minutes`);
    if (inr !== null) {
      const r = typeof Deck.rupees === 'function' ? Deck.rupees(inr) : '';
      if (r) parts.push(/^[≈<]/.test(r) ? r : '≈ ' + r);
    }
    return parts.length ? 'This month: ' + parts.join(' · ') : '';
  }
  const WORDS = { cloud: 'Google Cloud', browser: 'this browser', none: 'not available here' };
  const WAKE_WORDS = { loading: 'Loading the wake word…', on: 'Listening for ‘Hey Jarvis’', paused: 'Paused while JARVIS speaks or listens',
    resume: 'Paused: tap anywhere on the page to resume ‘Hey Jarvis’', error: '' };

  function renderValues() {
    if (!S.built) return;
    const cfg = S.cfg, s = settings(), server = !!cfg;
    [UI.voiceSec, UI.rateSec, UI.witSec, UI.useSec].forEach(n => { n.hidden = !server; });
    if (server) {
      radio(UI.voiceList, 'vVoice', cfg.voices, s.voice, (id) => change({ voice: id }), previewButton);
      if (!cfg.voices.length) UI.voiceList.append(mk('p', 'bfine', 'No cloud voice is available right now.'));
      if (document.activeElement !== UI.rate) { UI.rate.value = String(s.rate); UI.rateOut.textContent = rateText(s.rate); UI.rate.setAttribute('aria-valuetext', rateText(s.rate)); }
      radio(UI.witList, 'vWit', cfg.wit, s.wit, (id) => change({ wit: id }));
      const allow = allowanceText(cfg.allowance, cfg.inr);
      UI.allow.textContent = allow; UI.useSec.hidden = !allow;
    }
    UI.engine.value = device.engine; UI.finish.value = device.finish; UI.speak.value = device.speak;
    UI.engineHelp.textContent = `Now: ${WORDS[inputEngine()]}. Google Cloud keeps your audio in your own project (60 free minutes a month); this browser's recognition is free and shows your words as you speak, but your audio goes to the browser's maker.`;
    UI.speakHelp.textContent = `Out loud with ${WORDS[outputEngine()]}. "When I speak" answers spoken messages aloud; typed ones stay quiet.`;
    setPressed(UI.auto, device.autoSend); setPressed(UI.keep, device.keepListening); setPressed(UI.wake, device.wake);
    const W = window.JarvisWake;
    UI.wakeRow.hidden = !(W && typeof W.supported === 'function' && safe(() => W.supported()));
    const ws = S.wake.state;
    UI.wakeChip.textContent = ws === 'error' ? S.wake.note || 'Couldn\'t start ‘Hey Jarvis’.' : WAKE_WORDS[ws] || '';
    UI.wakeChip.className = 'vchip' + (ws === 'on' ? ' on' : ws === 'error' ? ' bad' : '');
    UI.wakeChip.hidden = !UI.wakeChip.textContent;
  }
  const safe = (fn) => { try { return !!fn(); } catch (_) { return false; } };
  function render() {
    if (!box || !panel) return;
    const opened = !panel.hidden || S.built;
    if (!opened) return;
    if (!S.built) build();
    UI.state.textContent = '';
    if (S.cfg === undefined && !S.error) UI.state.append(mk('div', 'empty', S.loading ? 'Loading voice settings…' : 'Voice settings load when this panel opens.'));
    if (S.error) {
      const retry = mk('button', 'btn lift bact', 'Retry'); retry.type = 'button'; retry.id = 'voiceRetry';
      retry.addEventListener('click', () => { S.error = ''; load(true); });
      UI.state.append(mk('p', 'bmiss warn', (S.cfg ? 'Couldn\'t refresh: showing what was loaded earlier. ' : 'Couldn\'t load voice settings. ') + S.error), retry);
    }
    UI.status.textContent = '';
    statusLines(S.cfg).forEach(([kind, text]) => {
      if (kind === 'code') { const c = mk('code', 'vfix', text); UI.status.append(c); return; }
      UI.status.append(mk('p', 'vline-s' + (kind ? ' ' + kind : ''), text));
    });
    UI.status.hidden = !UI.status.childElementCount;
    box.setAttribute('aria-busy', String(!!S.loading));
    if (metaEl) {
      const out = outputEngine();
      metaEl.textContent = S.cfg === null ? 'Not available' : S.cfg === undefined ? '' : out === 'cloud' ? 'Cloud voice' : out === 'browser' ? 'Browser voice' : 'Typing only';
    }
    renderValues();
  }

  // ---- wiring ------------------------------------------------------------------------------------
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'voice' && d.open) { render(); load(false); } });
  document.addEventListener('jarvis:wake', (e) => {
    const d = e.detail || {};
    S.wake = { state: typeof d.state === 'string' ? d.state : 'off', note: typeof d.note === 'string' ? d.note.slice(0, 200) : '' };
    if (d.state === 'error' && device.wake) setDevice({ wake: false }); else renderValues();
  });
  function onReady() { if (device.speak === 'always' || device.wake) load(false); }
  document.addEventListener('jarvis:ready', onReady);
  const JC = window.JarvisConsole;
  const readyNow = JC && typeof JC.ready === 'function' ? JC.ready() : null;
  if (readyNow) onReady();

  window.JarvisVoice = Object.freeze({
    config: () => S.cfg,
    load: (force) => load(!!force),
    device: () => device,
    setDevice,
    settings,
    inputEngine,
    outputEngine,
    markDown,
    language: () => (S.cfg ? S.cfg.language : 'en-IN'),
    speaker,
    visual: () => (visualFn ? visualFn() : null),
    setVisual(fn) { if (!visualFn && typeof fn === 'function') visualFn = fn; },
  });
})();
