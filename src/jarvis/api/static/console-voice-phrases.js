// src/jarvis/api/static/console-voice-phrases.js - R5 workstream C (docs/plans/r5-voice.md D16): the
// "Words to recognise" editor in Voice -> JarvisVoice.panelSlot('phrases'). The owner adds names and
// words the cloud engine should listen for (Thiruvananthapuram, Trivandrum, family names ...); the list
// is saved through JarvisVoice.updateSettings({phrases}) with the limits GET /v1/voice reports
// (config().phraseLimits). The server checks every word again and refuses, in plain words, what is not
// acceptable; nothing is trimmed to fit. The words go only to the owner's own Google speech project when
// they talk, and are never logged, so this file never writes them to the event log either.
// No build step; CSP script-src 'self'; textContent only; existing classes only.
//   window.JarvisVoicePhrases  clean(raw) -> string | null   the same rules as the server
//                              list() -> string[]            the saved list as the panel shows it
//                              apply(recognition) -> bool    hands the list to a browser recogniser that
//                                  offers contextual biasing: on-device recognition only (processLocally
//                                  true) and feature-detected; false and nothing otherwise
(() => {
  'use strict';
  const DEFAULT_ITEMS = 50, DEFAULT_CHARS = 40;
  const MAX_MARK_RUN = 4;            // most combining marks in a row (as on the server)
  const SAVE_WATCH_MS = 8000;        // a refusal this soon after our save is about our words
  const PUNCT = "-'.&";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const V = () => window.JarvisVoice || null;

  function limits() {
    const v = V(), cfg = v && typeof v.config === 'function' ? v.config() : null, l = cfg && cfg.phraseLimits;
    return { items: l && l.items > 0 ? l.items : DEFAULT_ITEMS, chars: l && l.chars > 0 ? l.chars : DEFAULT_CHARS };
  }
  function list() {
    const v = V(), s = v && typeof v.settings === 'function' ? v.settings() : null;
    return s && Array.isArray(s.phrases) ? s.phrases.slice() : [];
  }

  /** The word as the server will keep it, or null when the server would refuse it. */
  function clean(raw, maxChars) {
    if (typeof raw !== 'string') return null;
    const max = maxChars || limits().chars;
    const text = raw.normalize('NFC').replace(/’/g, "'").replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/gu, (c) => (/\s|[\x1c-\x1f]/.test(c) ? ' ' : ''))
      .replace(/\s+/g, ' ').trim();
    if (!text || [...text].length > max || !/\p{L}/u.test(text)) return null;
    let run = 0;
    for (const ch of text) {
      if (!/[\p{L}\p{M}\p{Nd} ]/u.test(ch) && !PUNCT.includes(ch)) return null;
      run = /\p{M}/u.test(ch) ? run + 1 : 0;
      if (run > MAX_MARK_RUN) return null;
    }
    return text;
  }

  // ---------------------------------------------------------------------------------- the panel
  const UI = {};
  let savedAt = 0;
  const fold = (w) => w.normalize('NFKC').toLowerCase();
  const known = (words, w) => words.some(x => fold(x) === fold(w));

  function save(next) {
    const v = V();
    if (!v || typeof v.updateSettings !== 'function') return false;
    const ok = v.updateSettings({ phrases: next });
    savedAt = Date.now();
    render();
    return ok;
  }
  function say(text, bad) {
    UI.note.textContent = text;
    UI.note.className = 'bnote' + (bad ? ' bad' : '');
  }
  function add() {
    const lim = limits(), words = list(), w = clean(UI.input.value, lim.chars);
    if (w === null) {
      say(`Use 1 to ${lim.chars} characters with at least one letter. Letters, numbers, spaces and - ' . & only.`, true);
      return;
    }
    if (known(words, w)) { say('That one is already in the list.', true); UI.input.select(); return; }
    if (words.length >= lim.items) { say(`The list is full (${lim.items} at most). Remove one first.`, true); return; }
    UI.input.value = '';
    say('');
    save([...words, w]);
    UI.input.focus();
  }
  function remove(word) {
    save(list().filter(w => w !== word));
    say('');
  }

  function build(slot) {
    slot.textContent = '';
    const sec = mk('section', 'bsec'), h = mk('h3'), title = mk('span', '', 'Words to recognise');
    sec.setAttribute('aria-labelledby', 'vPhraseT');
    h.id = 'vPhraseT'; h.append(title); sec.append(h);
    sec.append(mk('p', 'bfine vlead',
      'Names and words JARVIS should listen for, such as Thiruvananthapuram, Trivandrum or the names you use. '
      + 'They help the cloud voice; the browser\'s own listening uses them only where your browser supports it. '
      + 'They are sent to your own Google speech project when you talk, and are never written to a log.'));
    const row = mk('div', 'bopt');
    UI.input = mk('input', 'bsel');
    UI.input.type = 'text'; UI.input.id = 'vPhraseIn'; UI.input.autocomplete = 'off'; UI.input.spellcheck = false;
    UI.input.setAttribute('aria-label', 'Add a word or name'); UI.input.style.cursor = 'text'; UI.input.style.flex = '1 1 auto';
    UI.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
    UI.addBtn = mk('button', 'btn bact', 'Add');
    UI.addBtn.type = 'button'; UI.addBtn.id = 'vPhraseAdd'; UI.addBtn.style.marginTop = '0';
    UI.addBtn.addEventListener('click', add);
    row.append(UI.input, UI.addBtn);
    UI.note = mk('p', 'bnote'); UI.note.id = 'vPhraseNote'; UI.note.setAttribute('role', 'status');
    UI.count = mk('p', 'bfine'); UI.count.id = 'vPhraseCount';
    UI.list = mk('div', 'vlist'); UI.list.id = 'vPhraseList';
    sec.append(row, UI.note, UI.count, UI.list);
    slot.append(sec);
    UI.slot = slot;
  }
  function item(word, index) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt'), b = mk('button', 'btn bact', 'Remove');
    t.append(mk('span', 'bl', word));
    b.type = 'button'; b.id = 'vPhraseRm-' + index; b.style.marginTop = '0';
    b.setAttribute('aria-label', 'Remove ' + word);
    b.addEventListener('click', () => remove(word));
    row.append(t, b);
    return row;
  }
  function render() {
    const v = V(), slot = v && typeof v.panelSlot === 'function' ? v.panelSlot('phrases') : null;
    if (!slot) return;
    if (!UI.slot || UI.slot !== slot || !slot.contains(UI.list)) build(slot);
    const words = list(), lim = limits();
    UI.list.textContent = '';
    words.forEach((w, i) => UI.list.append(item(w, i)));
    UI.count.textContent = words.length ? `${words.length} of ${lim.items} words.` : 'No words yet. JARVIS uses his usual list.';
    UI.input.maxLength = lim.chars * 2;  // the Add button stays live when the list is full: it says why
  }

  // ---------------------------------------------------------------------------------- browser engine
  /** Chrome's recogniser can take phrases only where it offers contextual biasing (newer Chrome, on-device
   *  recognition). The Web Speech spec ties phrases to processLocally: on a recogniser that does not process
   *  locally, start() fails with 'phrases-not-supported', so the list is handed over only when processLocally is
   *  true. Nothing is assumed: if the pieces are not there this does nothing. */
  function apply(recognition) {
    const Phrase = window.SpeechRecognitionPhrase, seen = new Set();
    // R11.1 D9: this turn's hints (file names as said, the conversation's nouns) first, then his own words
    const words = turnHints().concat(list()).filter(w => { const k = w.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; });
    if (!recognition || recognition.processLocally !== true) return false;
    if (typeof Phrase !== 'function' || !('phrases' in recognition) || !words.length) return false;
    try { recognition.phrases = words.map(w => new Phrase(w, 1.0)); return true; } catch (_) { return false; }
  }
  /** R11.1 D9: console-r111-files.js keeps GET /v1/input/hints fresh; each hint is cleaned like an owner word. */
  function turnHints() {
    const F = window.JarvisFixes && window.JarvisFixes.parts && window.JarvisFixes.parts.files;
    let hints = [];
    try { hints = F && typeof F.hints === 'function' ? F.hints() : []; } catch (_) { hints = []; }
    return (Array.isArray(hints) ? hints : []).map(w => clean(w)).filter(Boolean).slice(0, 60);
  }

  /** The panel's own save note says why a save failed; repeat a refusal here, by the words, for a few seconds. */
  function watchNote() {
    const src = document.getElementById('voiceNote');
    if (!src || typeof MutationObserver !== 'function') return;
    new MutationObserver(() => {
      const text = src.textContent || '';
      if (!UI.note || !savedAt || Date.now() - savedAt > SAVE_WATCH_MS) return;
      if (/\bbad\b/.test(src.className) && text.startsWith("Couldn't save")) say(text, true);
    }).observe(src, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  document.addEventListener('jarvis:voice-panel', render);
  document.addEventListener('jarvis:voice-config', render);
  document.addEventListener('jarvis:ready', render);
  render();
  watchNote();

  window.JarvisVoicePhrases = Object.freeze({ clean, list, apply });
})();
