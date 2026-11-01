// src/jarvis/api/static/console-voice-speech.js — slice 9 D5/D6 (docs/plans/phase1-slice9-voice.md):
// what JARVIS says out loud and how it sounds. No build step; CSP script-src 'self'.
//   window.JarvisSpeechChunker  create({honorific}) → {push(delta) → [chunks], end() → [chunks]}.
//     Pure. Feed the reply text (whole, or streamed deltas) and get speakable chunks in order: the
//     first sentence as soon as it ends, later ones packed up to ~400 characters. Fenced code
//     blocks, 4-space / tab indented code and tables are never spoken; the first one is replaced,
//     once, by "The details are on screen, {honorific}." List items ("1. ", "- ", "* ", "• ")
//     lose their marker and become sentences of their own (like the server's speakable(), which
//     stays the authority on what is said).
//   window.JarvisSpeaker  create({synth, fallback, finish}) → a playback queue. synth(text, signal)
//     → Promise<ArrayBuffer> (POST /v1/voice/speak); chunks are fetched one ahead, decoded and
//     played in order through Web Audio: "comms" (high-pass ~120 Hz, low-pass ~9 kHz, a gentle
//     compressor and a short generated room) or "clean". An AnalyserNode gives level() for the Core
//     and the mic ring (real output only). stop() is barge-in: sources stop, fetches abort. When
//     synth fails with err.fallback (503 / 402 / network), the rest is spoken by the browser voice,
//     and so is a reply whose AudioContext the browser keeps suspended (no tap yet: 'blocked').
//     The browser voice gets pieces of at most ~180 characters (Chrome's network voices stop after
//     ~15 s without saying so) and a watchdog per piece that moves on if no end event comes.
// Nothing here stores audio; spoken text goes only to the console's own /v1/voice/speak.
(() => {
  'use strict';

  // ================================================================================== chunker
  const FIRST_MAX = 400;
  const SOFT = 200;          // after the first chunk, send once this much is ready (keeps playback fed)
  const MAX = 400;           // never more than this per chunk (the server caps 600 speakable chars)
  // "Mr. Smith", "e.g. this": a full stop after these is not the end of a sentence
  const ABBREV = new Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'mt', 'vs', 'etc', 'eg', 'ie', 'no',
    'approx', 'dept', 'est', 'fig', 'inc', 'ltd', 'co', 'corp', 'rs', 'am', 'pm', 'jan', 'feb', 'mar', 'apr', 'jun',
    'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'govt', 'ref']);
  const FENCE = /^(\x60{3}|~{3})/; // a fenced code block opens or closes (\x60 is a backtick)
  const ITEM = /^(\d{1,3}[.)]|[-*+•])[ \t]/;     // a list item's marker, then a space
  const MAYBE_ITEM = /^(\d{1,3}[.)]?|[-*+•])$/;  // what could still become one
  const ENDED = /[.!?…:;,]["')\]}’”]*$/;          // a line that already ends like a sentence
  const CODE_INDENT = 4;                          // columns: markdown's indented code block
  const CLOSERS = '"\')]}’”';

  function words(s) { return /[\p{L}\p{N}]/u.test(s); }
  function tidy(s) { return s.replace(/\s+/g, ' ').trim(); }

  /** Index just past the end of each sentence in s (final: the text is complete). */
  function boundaries(s, final) {
    const out = [];
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (c === '\n') { out.push(i + 1); continue; }
      if (c !== '.' && c !== '!' && c !== '?' && c !== '…') continue;
      let j = i + 1;
      while (j < s.length && (s[j] === '.' || s[j] === '!' || s[j] === '?' || CLOSERS.includes(s[j]))) j++;
      if (j >= s.length) { if (final) out.push(j); break; }
      if (!/\s/.test(s[j])) { i = j - 1; continue; }        // "₹1,234.50", "example.com", "e.g.x"
      const dot = c === '.' || c === '…';
      // a full stop is only an end if the next word does not start in lower case: wait to see it
      if (dot && !final && !/[^ \t]/.test(s.slice(j))) break;
      if (dot && notAnEnd(s, i, j)) { i = j - 1; continue; }
      out.push(j); i = j - 1;
    }
    return out;
  }
  function notAnEnd(s, dot, after) {
    let k = dot - 1;
    while (k >= 0 && /[\p{L}\p{N}.]/u.test(s[k])) k--;
    const token = s.slice(k + 1, dot);
    const bare = token.replace(/\./g, '').toLowerCase();
    let n = after; while (n < s.length && /[ \t]/.test(s[n])) n++;
    const next = s[n] || '';
    if (/^\p{Ll}/u.test(next)) return true;                  // "approx. ten", "Well… then"
    if (ABBREV.has(bare)) return true;                       // "Mr. Smith", "e.g. This"
    if (/^\p{Lu}$/u.test(token)) return true;                // an initial: "J. K. Rowling"
    if (/^\d+$/.test(token) && /(^|\n)[ \t]*$/.test(s.slice(0, k + 1))) return true; // "2. Do this" (a list)
    return false;
  }
  function splitLong(s, max = MAX) {
    const out = [];
    let rest = s;
    while (rest.length > max) {
      const cut = Math.max(rest.lastIndexOf(', ', max), rest.lastIndexOf('; ', max), rest.lastIndexOf(' — ', max));
      const at = cut > max / 3 ? cut + 1 : (rest.lastIndexOf(' ', max) > 0 ? rest.lastIndexOf(' ', max) : max);
      out.push(rest.slice(0, at).trim()); rest = rest.slice(at).trim();
    }
    if (rest) out.push(rest);
    return out;
  }
  /** Text cut into pieces of at most `max` characters, at sentence ends where it can. */
  function pieces(text, max) {
    const t = tidy(text);
    if (t.length <= max) return t ? [t] : [];
    const sents = [];
    let from = 0;
    boundaries(t, true).forEach(at => { const x = tidy(t.slice(from, at)); if (x) sents.push(x); from = at; });
    if (from < t.length && tidy(t.slice(from))) sents.push(tidy(t.slice(from)));
    const out = [];
    let cur = '';
    sents.forEach(x => splitLong(x, max).forEach(part => {
      if (cur && cur.length + 1 + part.length > max) { out.push(cur); cur = part; } else cur = cur ? cur + ' ' + part : part;
    }));
    if (cur) out.push(cur);
    return out;
  }

  function createChunker(opts) {
    const honorific = (opts && typeof opts.honorific === 'string' && opts.honorific.trim()) || 'Sir';
    const NOTICE = `The details are on screen, ${honorific}.`;
    let prose = '';            // speakable text not yet cut into sentences
    let line = '', mode = null; // the current line and what it is: null (undecided), prose, table, fence, code
    let lineFrom = 0;          // where the current prose line starts in prose (a "a | b" row is a table too)
    let inFence = false, noticed = false, firstOut = false;
    let item = false;          // the current prose line is a list item (its marker already dropped)
    let inList = false;        // since the last list item: indented lines continue it, they aren't code
    const ready = [];          // whole sentences waiting to be packed
    const out = [];            // chunks for the caller

    function emit(text) { const t = tidy(text); if (t && words(t)) { out.push(t); firstOut = true; } }
    function pack(force) {
      while (ready.length) {
        if (!firstOut) { splitLong(ready.shift()).forEach(emit); continue; }
        let size = 0, k = 0;
        while (k < ready.length && size + ready[k].length + 1 <= MAX) { size += ready[k].length + 1; k++; }
        if (k === 0) { splitLong(ready.shift()).forEach(emit); continue; }
        if (!force && k === ready.length && size < SOFT) return; // wait for more (or the end)
        emit(ready.splice(0, k).join(' '));
      }
    }
    function sentences(final) {
      const cuts = boundaries(prose, final);
      let from = 0;
      cuts.forEach(at => { const t = tidy(prose.slice(from, at)); if (t && words(t)) ready.push(t); from = at; });
      prose = prose.slice(from);
      lineFrom = Math.max(0, lineFrom - from);
      if (final) { const t = tidy(prose); if (t && words(t)) ready.push(t); prose = ''; }
    }
    function skipped() {
      if (noticed) return;
      noticed = true;
      sentences(true); pack(true);  // what came before the block is said first
      out.push(NOTICE); firstOut = true;
    }
    function indentOf(lead) { let n = 0; for (const ch of lead) n += ch === '\t' ? CODE_INDENT : 1; return n; }
    function decide() {
      const s = line.replace(/^[ \t]+/, '');
      if (!s) return;
      if (inFence) { if (FENCE.test(s)) mode = 'fence'; else if (!/^[\x60~]{1,2}$/.test(s)) mode = 'code'; return; }
      if (s[0] === '|') { mode = 'table'; return; }
      if (FENCE.test(s)) { mode = 'fence'; return; }
      if (/^[\x60~]{1,2}$/.test(s)) return; // might still become a fence
      if (MAYBE_ITEM.test(s)) return;        // "1", "1.", "-": might still become a list item
      const deep = indentOf(line.slice(0, line.length - s.length)) >= CODE_INDENT;
      const marker = ITEM.exec(s);
      if (!marker && deep && !inList) { mode = 'code'; return; } // indented code: never spoken
      if (!marker && !deep) inList = false;
      item = !!marker;
      if (item) inList = true;
      mode = 'prose'; lineFrom = prose.length; prose += item ? s.slice(marker[0].length) : line; line = '';
    }
    function endLine() {
      if (mode === null) {
        const s = line.trim();
        if (!s) prose += '\n';                 // a blank line ends whatever sentence was open
        else if (inFence) skipped();
        else prose += line + '\n';
      } else if (mode === 'fence') { inFence = !inFence; if (inFence) skipped(); }
      else if (mode === 'code' || mode === 'table') skipped();
      else if (prose.slice(lineFrom).includes('|')) { prose = prose.slice(0, lineFrom); skipped(); } // "a | b": a table row
      else {
        const said = prose.slice(lineFrom).trimEnd();
        if (item && words(said) && !ENDED.test(said)) prose = prose.trimEnd() + '.'; // "Buy milk" → "Buy milk."
        prose += '\n';
      }
      line = ''; mode = null; item = false;
    }
    function feed(delta) {
      for (const ch of String(delta)) {
        if (ch === '\r') continue;
        if (ch === '\n') { endLine(); continue; }
        if (mode === 'prose') { prose += ch; continue; }
        line += ch;
        if (mode === null) decide();
      }
    }
    const take = () => out.splice(0, out.length);
    return {
      push(delta) { feed(delta); sentences(false); pack(false); return take(); },
      end() { if (line || mode) endLine(); if (inFence) inFence = false; sentences(true); pack(true); return take(); },
    };
  }
  window.JarvisSpeechChunker = Object.freeze({ create: createChunker, NOTICE: 'The details are on screen, {honorific}.' });

  // ================================================================================== speaker
  const PREFERRED = ['ryan', 'george', 'daniel', 'arthur', 'uk english male', 'oliver', 'male'];
  /** The best British male system voice, for the browser fallback (plan §4). */
  function browserVoice() {
    const ss = window.speechSynthesis;
    if (!ss || typeof ss.getVoices !== 'function') return null;
    let best = null, score = -1;
    (ss.getVoices() || []).forEach(v => {
      const lang = String(v.lang || '').replace('_', '-').toLowerCase(), name = String(v.name || '').toLowerCase();
      let s = lang === 'en-gb' ? 20 : lang.startsWith('en') ? 5 : 0;
      if (!s) return;
      const p = PREFERRED.findIndex(w => name.includes(w));
      if (p >= 0) s += 10 - p;
      if (/female|woman|susan|kate|serena|hazel|libby|sonia|mia/.test(name)) s -= 8;
      if (s > score) { score = s; best = v; }
    });
    return best;
  }
  /** A short, original room: decaying noise with a few early reflections (seeded, so it never varies). */
  function roomImpulse(ac) {
    const len = Math.round(ac.sampleRate * 0.32), ir = ac.createBuffer(2, len, ac.sampleRate);
    let seed = 0x5eed;
    const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x3fffffff - 1; };
    for (let ch = 0; ch < 2; ch++) {
      const d = ir.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = rnd() * Math.pow(1 - i / len, 3.2) * 0.6;
      [0.011, 0.019, 0.027 + ch * 0.003].forEach((t, k) => { const at = Math.round(t * ac.sampleRate); if (at < len) d[at] += 0.5 / (k + 1); });
    }
    return ir;
  }

  const BROWSER_MAX = 180;       // characters per utterance for the browser voice
  const BROWSER_CPS = 13;        // characters a second at rate 1 (slow on purpose: the watchdog never cuts speech)
  const WATCHDOG_SLACK_MS = 2500;
  const RESUME_WAIT_MS = 1500;   // an AudioContext the browser won't start (no tap yet) is given up on
  const settle = (p, ms) => Promise.race([Promise.resolve(p).catch(() => {}), new Promise(r => setTimeout(r, ms))]);

  function createSpeaker(opts) {
    const o = opts || {};
    let ac = null, master = null, analyser = null, probe = null, comms = null;
    let finish = o.finish === 'clean' ? 'clean' : 'comms';
    let queue = [], playing = null, ended = false, active = false, seq = 0, useBrowser = false, rate = 1;
    const listeners = { state: [], chunk: [], fallback: [] };
    const fire = (k, d) => listeners[k].forEach(fn => { try { fn(d); } catch (_) {} });

    function context() {
      if (ac) return ac;
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      ac = new C();
      master = ac.createGain();
      analyser = ac.createAnalyser(); analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.3;
      probe = new Float32Array(analyser.fftSize);
      master.connect(analyser); analyser.connect(ac.destination);
      // Comms finish (D5): band-limit, compress, add a little room. Built once, reused per chunk.
      const hp = ac.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 120; hp.Q.value = 0.7;
      const lp = ac.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 9000; lp.Q.value = 0.7;
      const comp = ac.createDynamicsCompressor();
      comp.threshold.value = -22; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.006; comp.release.value = 0.18;
      const dry = ac.createGain(); dry.gain.value = 1;
      const wet = ac.createGain(); wet.gain.value = 0.14;
      const room = ac.createConvolver(); room.buffer = roomImpulse(ac);
      hp.connect(lp); lp.connect(comp); comp.connect(dry); comp.connect(room); room.connect(wet);
      dry.connect(master); wet.connect(master);
      comms = hp;
      return ac;
    }
    function setActive(on, why) {
      if (active === on) return;
      active = on;
      fire('state', { speaking: on, reason: why || null });
    }

    function fetchItem(item) {
      if (item.started) return;
      item.started = true;
      item.ctrl = new AbortController();
      item.audio = Promise.resolve()
        .then(() => o.synth(item.text, item.ctrl.signal, item.meta))
        .then(buf => { const c = context(); if (!c) throw Object.assign(new Error('no_audio'), { fallback: true }); return c.decodeAudioData(buf); });
      item.audio.catch(() => {}); // handled where it is awaited
    }
    function fetchAhead() { if (!useBrowser) queue.slice(0, 2).forEach(fetchItem); }

    async function pump() {
      if (playing || !queue.length) {
        if (!playing && !queue.length && ended) { ended = false; setActive(false, 'done'); }
        return;
      }
      const item = queue[0], my = seq;
      playing = item;
      fetchAhead();
      if (useBrowser) { await speakBrowser(item, my); return; }
      let buffer = null;
      try { buffer = await item.audio; }
      catch (err) {
        if (my !== seq) return;
        if (err && err.name === 'AbortError') return;
        if (err && err.skip) { queue.shift(); playing = null; pump(); return; }
        if (err && err.fallback) { await toBrowser(item, my, err.reason || err.message || 'error'); return; }
        queue.shift(); playing = null; pump(); return; // undecodable audio: skip this chunk
      }
      if (my !== seq) return;
      const c = context();
      if (c.state === 'suspended') {
        try { await settle(c.resume(), RESUME_WAIT_MS); } catch (_) {}
        if (my !== seq) return;
        if (c.state === 'suspended') { await toBrowser(item, my, 'blocked'); return; } // no tap yet: the browser says it
      }
      const src = c.createBufferSource();
      src.buffer = buffer;
      src.connect(finish === 'comms' ? comms : master);
      item.node = src;
      src.onended = () => { if (my !== seq || playing !== item) return; queue.shift(); playing = null; pump(); };
      setActive(true);
      fire('chunk', { text: item.text, engine: 'cloud' });
      src.start();
    }
    /** The rest of this reply goes to the browser voice (cloud refused, or audio held back). */
    function toBrowser(item, my, reason) {
      useBrowser = true;
      queue.forEach(it => { if (it.ctrl) { try { it.ctrl.abort(); } catch (_) {} } }); // no paid call for chunks the browser says
      fire('fallback', { reason });
      return speakBrowser(item, my);
    }
    /** How long an utterance may take before the watchdog moves on (it never cuts real speech). */
    const patience = (text) => Math.max(3000, (text.length / (BROWSER_CPS * rate)) * 1000 + WATCHDOG_SLACK_MS);
    function speakBrowser(item, my) {
      const ss = window.speechSynthesis, U = window.SpeechSynthesisUtterance;
      return new Promise(resolve => {
        let done = false, timer = 0, k = 0;
        const finish = () => {
          if (done) return;
          done = true; clearTimeout(timer);
          if (my === seq && playing === item) { queue.shift(); playing = null; pump(); }
          resolve();
        };
        if (item.ctrl) { try { item.ctrl.abort(); } catch (_) {} }
        if (!ss || typeof U !== 'function') { finish(); return; }
        const parts = pieces(item.text, BROWSER_MAX), v = browserVoice();
        const next = () => {
          clearTimeout(timer);
          if (my !== seq || playing !== item || k >= parts.length) { finish(); return; }
          const u = new U(parts[k++]);
          if (v) { u.voice = v; u.lang = v.lang; } else u.lang = 'en-GB';
          u.rate = rate; u.pitch = 0.95;
          let over = false;
          const step = () => { if (!over) { over = true; next(); } };
          u.onend = step; u.onerror = step;
          // Chrome can stop a long utterance without onend: cancel it and go on with the next piece
          timer = setTimeout(() => { if (!over) { try { ss.cancel(); } catch (_) {} step(); } }, patience(u.text));
          item.utterance = u;
          try { ss.speak(u); } catch (_) { step(); }
        };
        setActive(true);
        fire('chunk', { text: item.text, engine: 'browser' });
        next();
      });
    }

    return {
      /** Queue one chunk; playback starts at once if idle. */
      say(text, meta) {
        const t = tidy(String(text || ''));
        if (!t) return;
        ended = false;
        queue.push({ text: t, meta: meta || null });
        if (!active) setActive(true);
        fetchAhead(); pump();
      },
      /** No more chunks for this reply: the speaker goes idle ('done') after the last one. */
      end() { ended = true; if (!playing && !queue.length) { ended = false; setActive(false, 'done'); } },
      /** Barge-in: stop now, abort pending fetches, forget the queue. */
      stop() {
        seq++;
        queue.forEach(it => { if (it.ctrl) { try { it.ctrl.abort(); } catch (_) {} } if (it.node) { try { it.node.onended = null; it.node.stop(); } catch (_) {} } });
        queue = []; playing = null; ended = false;
        if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (_) {} }
        setActive(false, 'stopped');
      },
      speaking: () => active,
      level() {
        if (!analyser || !active || useBrowser) return 0;
        analyser.getFloatTimeDomainData(probe);
        let sum = 0;
        for (let i = 0; i < probe.length; i++) sum += probe[i] * probe[i];
        return Math.min(1, Math.sqrt(sum / probe.length));
      },
      setFinish(f) { finish = f === 'clean' ? 'clean' : 'comms'; },
      setRate(r) { if (typeof r === 'number' && Number.isFinite(r)) rate = Math.min(1.25, Math.max(0.8, r)); },
      /** Use the browser voice from now on (cloud said 503/402), or the cloud again. */
      browser(on) { useBrowser = !!on; },
      usingBrowser: () => useBrowser,
      /** Make (or resume) the audio context inside a user gesture, so later playback may start. */
      unlock() { const c = context(); if (c && c.state === 'suspended') { try { c.resume().catch(() => {}); } catch (_) {} } },
      on(kind, fn) { if (listeners[kind] && typeof fn === 'function') listeners[kind].push(fn); },
    };
  }
  window.JarvisSpeaker = Object.freeze({ create: createSpeaker, browserVoice });
})();
