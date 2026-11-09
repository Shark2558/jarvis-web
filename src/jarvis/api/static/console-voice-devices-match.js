// src/jarvis/api/static/console-voice-devices-match.js - R5 workstream B (docs/plans/r5-voice.md D13).
// Pure helpers for the audio route: clean device text, classify a label, group Windows' call-quality
// endpoints, resolve "switch to my earphones" to a device, and word a device by KIND only.
// No DOM, no storage, no network. Loads BEFORE console-voice-devices.js. No build step; CSP script-src 'self'.
//   window.JarvisAudioMatch (frozen): clean, nick, tidy, norm, squash, classify, isBuiltIn, isHandsFree,
//     baseKey, isCallQuality, cleanTarget, queryOf, isDeviceWord, rank, outputPhrase, inputPhrase,
//     connectPhrases, kindListWord, DEFAULT_WORDS.
// Spoken text may use a kind word ("your earphones") but NEVER a device label or nickname (D18).
(() => {
  'use strict';
  if (window.JarvisAudioMatch) return;
  const LIM = Object.freeze({ id: 400, label: 120, nick: 30, match: 0.6, minSub: 3, nickDice: 0.7 });
  // Control, bidi, zero-width and BOM characters never belong in a device name (they can hide text).
  const HIDDEN_RE = /[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁤⁦-⁩﻿]/g;
  const USB_ID_RE = /\s*\([0-9a-f]{4}:[0-9a-f]{4}\)/gi;
  const HEADPHONE_RE = /head(phone|set)|ear(phone|bud|pod)|buds|airpods|hands-?free/i;
  const SPEAKER_RE = /speaker|soundbar|built-?in|realtek|high definition/i;
  const BUILTIN_RE = /realtek|high definition|built-?in|internal|intel|microphone array|smart sound|conexant|laptop/i;
  const NOT_BUILTIN_RE = /display|hdmi|nvidia|amd|s\/?pdif|digital output|monitor/i;
  const NOT_BLUETOOTH_RE = /s\/?pdif|digital|hdmi|display|nvidia|monitor/i;
  const HANDSFREE_RE = /hands-?free/i;
  const FILLER = Object.freeze(['my', 'the', 'your', 'our', 'a']);
  const STOP = Object.freeze(new Set(['audio', 'digital', 'output', 'device', 'devices', 'high', 'definition', 'sound', 'the', 'my', 'a', 'mic', 'microphone']));
  const DEFAULT_WORDS = Object.freeze(['default', 'system default', 'the default', 'normal']);
  const kindIs = (k) => (d) => d.kind === k;
  const inBuiltIn = (d) => !!d.builtIn;
  const ALIASES = new Map([
    ['laptop', inBuiltIn], ['computer', inBuiltIn], ['desktop', inBuiltIn], ['builtin', inBuiltIn],
    ['earphones', kindIs('headphones')], ['earphone', kindIs('headphones')], ['headphones', kindIs('headphones')],
    ['headphone', kindIs('headphones')], ['earbuds', kindIs('headphones')], ['buds', kindIs('headphones')],
    ['headset', kindIs('headphones')], ['airpods', kindIs('headphones')],
    ['speaker', kindIs('speakers')], ['speakers', kindIs('speakers')],
    ['bluetooth', (d) => !d.builtIn && !NOT_BLUETOOTH_RE.test(String(d.label))],
  ]);

  // ---- cleaning ------------------------------------------------------------------------------------
  const clean = (s, max) => String(s == null ? '' : s).replace(HIDDEN_RE, '').replace(/\s+/g, ' ').trim().slice(0, max || LIM.label);
  const nick = (s) => clean(String(s == null ? '' : s).normalize('NFKC'), LIM.nick);
  const tidy = (label) => clean(clean(label, LIM.id).replace(USB_ID_RE, ''), LIM.label);
  const norm = (s) => String(s == null ? '' : s).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{M}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
  // Spoken words reach the matcher with combining marks cut out, so compare Indic text without them too.
  const squash = (s) => String(s == null ? '' : s).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

  // ---- classification ------------------------------------------------------------------------------
  const classify = (label) => (HEADPHONE_RE.test(label) ? 'headphones' : SPEAKER_RE.test(label) ? 'speakers' : 'unknown');
  const isBuiltIn = (label) => BUILTIN_RE.test(label) && !NOT_BUILTIN_RE.test(label);
  const isHandsFree = (label) => HANDSFREE_RE.test(label);
  const builtInRank = (label) => (/^speakers/i.test(label) || /realtek/i.test(label) ? 0 : 1);
  function baseKey(label) {
    const t = tidy(label);
    const m = t.match(/\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$/);
    return norm(m ? m[1] : t).replace(/\bhands free( ag audio)?\b/g, '').replace(/\bag audio\b/g, '').replace(/\bstereo\b/g, '').replace(/\s+/g, ' ').trim();
  }
  /** Windows lists a Bluetooth headset twice: stereo, and a "Hands-Free" call-quality endpoint. */
  function isCallQuality(label, others) {
    const key = baseKey(label);
    const twin = (o, re) => re.test(o) && baseKey(o) === key;
    if (isHandsFree(label)) return others.some((o) => !isHandsFree(o) && baseKey(o) === key);
    if (/^headset\b/i.test(label)) return others.some((o) => twin(o, /^headphones\b/i));
    return false;
  }

  // ---- the query -----------------------------------------------------------------------------------
  function cleanTarget(text) {
    let w = norm(text).split(' ').filter(Boolean);
    while (w.length && FILLER.includes(w[0])) w = w.slice(1);
    if (w[w.length - 1] === 'instead') w = w.slice(0, -1);
    return w.join(' ');
  }
  const tokensOf = (q) => norm(q).replace(/\bbuilt in\b/g, 'builtin').split(' ').filter(Boolean);
  const isAlias = (t) => ALIASES.has(t);
  /** The query split into alias words (they filter) and name words (they score). */
  function queryOf(text) {
    const q = cleanTarget(text);
    const toks = tokensOf(q);
    const aliases = toks.filter(isAlias);
    const names = toks.filter((t) => !isAlias(t) && !STOP.has(t));
    return { q, aliases, names, preds: aliases.map((t) => ALIASES.get(t)), external: q === 'speaker' || q === 'speakers', laptop: aliases.some((t) => ALIASES.get(t) === inBuiltIn) };
  }
  function isDeviceWord(text) {
    const q = cleanTarget(text);
    return !!q && (DEFAULT_WORDS.includes(q) || (tokensOf(q).length > 0 && tokensOf(q).every(isAlias)));
  }

  // ---- scoring -------------------------------------------------------------------------------------
  function bigrams(s) { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) || 0) + 1); } return m; }
  function dice(a, b) {
    if (a.length < 2 || b.length < 2) return a === b && a ? 1 : 0;
    const x = bigrams(a), y = bigrams(b);
    let hits = 0;
    x.forEach((n, g) => { hits += Math.min(n, y.get(g) || 0); });
    return (2 * hits) / (a.length - 1 + b.length - 1);
  }
  const tokenHits = (t, l) => t === l || (t.length >= LIM.minSub && (l.includes(t) || (l.length > LIM.minSub && t.startsWith(l) && t.length - l.length <= 1)));
  function labelScore(names, label) {
    const lt = norm(label.replace(/\(call quality\)/i, '')).split(' ');
    const frac = names.filter((t) => lt.some((l) => tokenHits(t, l))).length / names.length;
    return Math.max(frac, dice(names.join(''), lt.join('')));
  }
  function nickScore(q, nickname) {
    const n = cleanTarget(nickname);
    if (!n || !q) return 0;
    if (n === q || (squash(n).length >= 2 && squash(n) === squash(q))) return 1;
    const s = dice(n.replace(/ /g, ''), q.replace(/ /g, ''));
    return s >= LIM.nickDice ? s : 0;
  }
  function scoreOne(d, pq, nickname) {
    const byNick = nickScore(pq.q, nickname);
    if (byNick > 0) return { s: byNick, nick: true };
    if (pq.preds.length && !pq.preds.every((p) => p(d))) return { s: 0, nick: false };
    if (!pq.names.length) return { s: pq.preds.length ? 1 : 0, nick: false };
    return { s: labelScore(pq.names, String(d.label)), nick: false };
  }
  /** Matching devices, best first. ctx {nameOf(d) -> nickname, prefer(d) -> bool}. Equal `key`s are a tie. */
  function rank(list, text, ctx) {
    const pq = queryOf(text);
    if (!pq.q) return [];
    const c = ctx || {};
    const out = [];
    list.forEach((d, i) => {
      const { s, nick: byNick } = scoreOne(d, pq, c.nameOf ? c.nameOf(d) : '');
      if (s < LIM.match) return;
      const parts = [(1 - s).toFixed(3), byNick ? 0 : 1, d.callQuality ? 1 : 0, c.prefer && c.prefer(d) ? 0 : 1, pq.external ? (d.builtIn ? 1 : 0) : 0, pq.laptop && d.builtIn ? builtInRank(String(d.label)) : 0];
      out.push({ d, i, s, key: parts.join('|') });
    });
    return out.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.i - b.i));
  }

  // ---- words for speaking: a KIND, never a name ----------------------------------------------------
  function outputPhrase(d) {
    if (!d || d.isDefault) return 'the default output';
    if (d.kind === 'headphones') return /headset/i.test(String(d.label)) ? 'your headset' : 'your earphones';
    if (d.kind === 'speakers') return d.builtIn ? 'the laptop speakers' : 'the speaker';
    return 'that device';
  }
  function inputPhrase(d) {
    if (!d || d.isDefault) return 'the default microphone';
    if (d.builtIn) return 'the laptop microphone';
    return d.kind === 'headphones' ? 'your headset microphone' : 'that microphone';
  }
  function connectPhrases(d) {
    if (d && d.kind === 'headphones') return { said: 'New earphones have connected', pronoun: 'them' };
    if (d && d.kind === 'speakers') return { said: 'A new speaker has connected', pronoun: 'it' };
    return { said: 'A new device has connected', pronoun: 'it' };
  }
  function kindListWord(d) {
    if (d.kind === 'headphones') return 'earphones';
    if (d.kind === 'speakers') return d.builtIn ? 'the laptop speakers' : 'a speaker';
    return 'another device';
  }

  window.JarvisAudioMatch = Object.freeze({
    LIM, DEFAULT_WORDS, clean, nick, tidy, norm, squash, classify, isBuiltIn, isHandsFree, baseKey, isCallQuality,
    cleanTarget, queryOf, isDeviceWord, rank, outputPhrase, inputPhrase, connectPhrases, kindListWord,
  });
})();
