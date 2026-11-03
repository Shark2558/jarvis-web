// src/jarvis/api/static/console-whatsapp.js -- slice 12 D6 (docs/plans/phase2-slice12-integrations.md):
// the WhatsApp draft card under a reply. JARVIS writes the message; the owner opens it in WhatsApp and
// presses Send there. JARVIS sends nothing. No build step; CSP script-src 'self'; ASCII source with
// backslash-u escapes only; every server string reaches the page through textContent, never markup.
//   window.JarvisWhatsApp  render(row, cards) -> the row's first card (or null). console.js calls it
//     for a fresh reply with ChatResponse.cards; only kind "whatsapp" is drawn here
//     ({kind: "whatsapp", name, number, text, link, warning, assumed}); console-media.js draws the rest.
//   The one link is built HERE from the checked number and the text (encodeURIComponent):
//   https://wa.me/<digits>?text=<encoded>; the server builds the same string (jarvis.whatsapp.draft
//   wa_link), so a card whose `link` differs was not made by it and is dropped (review FE-7). It is an
//   ordinary link -- it opens only when the owner clicks it, in a new tab, with rel="noopener
//   noreferrer" and no referrer.
//   Review FE-8: a text with more than 4 combining marks in a row (Unicode M*) on one character is
//   refused by the server, so such a card is dropped here too; a card whose character count differs
//   from what renders (accents, emoji made of several characters) says "N characters" in its head.
//   A draft that is malformed (number not E.164, text longer than 2,000 characters, a hidden character,
//   a lone surrogate, anything the server's cleaning would have changed) is dropped, never shown
//   half-right.
// Review S3: the whole text is shown (no inner scroll box), with "N lines" in the card's head when it is
// long; `clean` mirrors the server's jarvis.whatsapp.draft.clean_text (characters that render blank,
// trailing spaces, more than two blank lines in a row). S5: "Assumed India (+91)" when the number was
// written without a country code. S7: the hint names who nothing is sent to, and what opening does.
// Security review SEC-1: the same rule as the server, character for character (both are tested over
// tests/fixtures/whatsapp_clean_cases.json): spaces and tabs become one plain space; ZWNJ / ZWJ only
// between two letters of a non-Latin script (ZWJ also inside an emoji sequence); FE0E / FE0F only after
// an emoji or a keycap base -- so no invisible channel can ride on a card that shows only the words.
(() => {
  'use strict';
  const KIND = 'whatsapp'; // its kind in ChatResponse.cards (jarvis.tools.reply_cards)
  const MAX_CARDS = 5;
  const TEXT_MAX = 2000;
  const NAME_MAX = 100;
  const LONG_LINES = 4; // from this many lines (or LONG_CHARS characters) the head says "N lines"
  const LONG_CHARS = 400;
  const DIGITS = /^[1-9][0-9]{6,14}$/;
  // what the server already removed (bidi controls and marks, zero-width space, BOM, controls but
  // new lines and tabs): a card whose name or text still holds one is dropped
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/;
  // the server's cleaning, one character at a time: the categories it drops (control, format,
  // private use, lone surrogates) ...
  const DROPPED = /^[\p{Cc}\p{Cf}\p{Co}\p{Cs}]$/u;
  // ... and the letters and marks that render blank: Hangul fillers, braille blank, combining
  // grapheme joiner, Khmer inherent vowels, Mongolian selectors, variation selectors but an emoji's
  const BLANK = /^[\u115f\u1160\u3164\uffa0\u2800\u034f\u17b4\u17b5\u180b-\u180d\u180f\ufe00-\ufe0d\u{e0100}-\u{e01ef}]$/u;
  // Security review SEC-1, the server's exact rule (jarvis.whatsapp.draft): every Zs space and tab
  // is one plain space; ZWNJ / ZWJ stay only between two letters of a non-Latin script (or a ZWJ
  // between an emoji and the next emoji); FE0E / FE0F only right after an emoji or a keycap base.
  const JOINERS = new Set(['\u200c', '\u200d']);
  const ZWJ = '\u200d';
  const SELECTORS = new Set(['\ufe0e', '\ufe0f']);
  const SPACEISH = /^[\t\p{Zs}]$/u;
  const EMOJI = /^\p{Extended_Pictographic}$/u;
  const SKIN = /^[\u{1f3fb}-\u{1f3ff}]$/u;
  const KEYCAP_BASE = /^[0-9#*]$/;
  const LETTER = /^[\p{L}\p{M}]$/u;
  // the server's NOT_A_SCRIPT: Latin and the generic marks, next to which no joiner is kept
  const NOT_A_SCRIPT = /^[\u0000-\u036f\u1ab0-\u1aff\u1d00-\u1eff\u20d0-\u20ff\u2c60-\u2c7f\ua720-\ua7ff\uab30-\uab6f\ufb00-\ufb06\ufe00-\ufe0f\ufe20-\ufe2f\uff21-\uff3a\uff41-\uff5a\u{10780}-\u{107bf}\u{1df00}-\u{1dfff}]$/u;
  // more than MAX_MARKS combining marks in a row: the server's draft.py refuses the text (FE-8);
  // a joiner between two marks does not break the run (as on the server)
  const MAX_MARKS = 4;
  const MARK = /^\p{M}$/u;
  const MARKISH = /[\p{M}\u200c\u200d]/gu; // what a grapheme count would fold into its base
  const WARN = 'This number didn\u2019t come from you or your contacts \u2014 check it before you send.';
  const ASSUMED = 'Assumed India (+91)';
  const HANDS_OVER = 'Opening the link hands this text to WhatsApp.';

  const scriptLetter = (ch) => !!ch && ch.codePointAt(0) > 0x7f && LETTER.test(ch) && !NOT_A_SCRIPT.test(ch);
  const emoji = (ch) => !!ch && EMOJI.test(ch);

  /** Pass 1: each character kept (joiners and selectors for pass 2), dropped, turned into a new
   *  line or one plain space. */
  function visible(text) {
    const out = [];
    for (const ch of text) {
      if (ch === '\n' || JOINERS.has(ch) || SELECTORS.has(ch)) out.push(ch);
      else if (SPACEISH.test(ch)) out.push(' ');
      else if (BLANK.test(ch)) continue;
      else if (ch === '\u2028' || ch === '\u2029') out.push('\n');
      else if (!DROPPED.test(ch)) out.push(ch);
    }
    return out;
  }

  /** Pass 2: joiners and selectors judged against their immediate neighbours in pass 1's text. */
  function joined(chars) {
    const out = [];
    chars.forEach((ch, i) => {
      const prev = i > 0 ? chars[i - 1] : '';
      const next = i + 1 < chars.length ? chars[i + 1] : '';
      if (JOINERS.has(ch)) {
        const before = prev === '\ufe0f' ? (i > 1 && emoji(chars[i - 2])) : (emoji(prev) || SKIN.test(prev));
        if ((scriptLetter(prev) && scriptLetter(next)) || (ch === ZWJ && before && emoji(next))) out.push(ch);
      } else if (SELECTORS.has(ch)) {
        if (prev && (KEYCAP_BASE.test(prev) || emoji(prev))) out.push(ch);
      } else out.push(ch);
    });
    return out.join('');
  }

  /** The text as the server's clean_text leaves it (so a card whose text differs is dropped). */
  function clean(text) {
    const once = joined(visible(text.replace(/\r\n?/g, '\n'))).replace(/ {2,}/g, ' ');
    const lines = once.split('\n').map((line) => line.replace(/ +$/, ''));
    return lines.join('\n').replace(/\n{4,}/g, '\n\n\n').trim();
  }

  /** True when `text` has more than MAX_MARKS combining marks in a row (a joiner between two
   *  marks does not break the run): the server refuses such a text (FE-8). */
  function stacked(text) {
    if (typeof text !== 'string') return false;
    let run = 0;
    for (const ch of text) {
      if (JOINERS.has(ch)) continue;
      run = MARK.test(ch) ? run + 1 : 0;
      if (run > MAX_MARKS) return true;
    }
    return false;
  }

  /** How many characters the text has, and how many show (grapheme clusters; without
   *  Intl.Segmenter, the characters that are not marks or joiners). */
  function lengths(text) {
    const chars = Array.from(text).length;
    let seen;
    try { seen = Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text)).length; }
    catch (_) { seen = Array.from(text.replace(MARKISH, '')).length; }
    return { chars, seen };
  }

  /** https://wa.me/<digits>?text=<encoded>, or null when the number is not E.164 or the text
   *  can't be encoded (a lone surrogate makes encodeURIComponent throw). */
  function waLink(number, text) {
    if (typeof number !== 'string' || number[0] !== '+') return null;
    const digits = number.slice(1);
    if (!DIGITS.test(digits) || typeof text !== 'string') return null;
    try { return 'https://wa.me/' + digits + '?text=' + encodeURIComponent(text); } catch (_) { return null; }
  }

  /** '+91 98765 43210' for an Indian mobile, else the E.164 number as it is. */
  function shown(number) {
    const m = /^\+91([0-9]{5})([0-9]{5})$/.exec(number);
    return m ? `+91 ${m[1]} ${m[2]}` : number;
  }

  /** The WhatsApp drafts in ChatResponse.cards, checked field by field; anything odd is dropped. */
  function normal(list) {
    const drafts = (Array.isArray(list) ? list : []).filter((d) => d && typeof d === 'object' && d.kind === KIND);
    return drafts.slice(0, MAX_CARDS).map((d) => {
      if (typeof d.text !== 'string') return null;
      const text = d.text;
      if (!text.trim() || Array.from(text).length > TEXT_MAX || INVISIBLE.test(text)) return null;
      if (clean(text) !== text) return null; // the server would never have sent it so
      if (stacked(text)) return null; // ... nor this (FE-8)
      const link = waLink(d.number, text);
      if (!link || d.link !== link) return null; // FE-7: exactly the server's link, or no card
      const name = typeof d.name === 'string' && !INVISIBLE.test(d.name)
        ? d.name.replace(/\s+/g, ' ').trim().slice(0, NAME_MAX) : '';
      const flag = (v) => typeof v === 'string' && v.length > 0;
      return { name, number: d.number, text, link, warn: flag(d.warning), assumed: flag(d.assumed) };
    }).filter(Boolean);
  }

  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  /** "14 lines" for a long text, else null. */
  function lineCount(text) {
    const lines = text.split('\n').length;
    if (lines < LONG_LINES && Array.from(text).length <= LONG_CHARS) return null;
    return lines === 1 ? '1 line' : lines + ' lines';
  }

  /** Who nothing is sent to (the name isolated, so a right-to-left name can't reorder the words
   *  around it), and that opening the link hands the text to WhatsApp. */
  function hint(d) {
    const box = mk('span', 'wahint');
    const who = d.name || shown(d.number);
    const first = mk('span', 'wahintline');
    first.append('Nothing is sent to ', mk('bdi', 'wawho', who), ' until you press Send in WhatsApp.');
    box.append(first, mk('span', 'wahintline', HANDS_OVER));
    return box;
  }

  function card(d) {
    const who = d.name ? `${d.name}, ${shown(d.number)}` : shown(d.number);
    const box = mk('div', 'wadraft');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', `WhatsApp draft to ${who}`);
    const head = mk('div', 'wahead');
    head.append(mk('span', 'walabel', 'WhatsApp draft'));
    const count = lineCount(d.text);
    if (count) head.append(mk('span', 'walines', count));
    const len = lengths(d.text);
    if (len.chars !== len.seen) { // FE-8: what WhatsApp gets is more than what shows
      const c = mk('span', 'wachars', len.chars + (len.chars === 1 ? ' character' : ' characters'));
      c.title = `The text has ${len.chars} characters; ${len.seen} show on screen (accents and some emoji are made of several).`;
      head.append(c);
    }
    head.append(mk('span', 'wastate', 'Not sent'));
    const to = mk('div', 'wato');
    to.append(mk('span', 'wak', 'To'));
    if (d.name) to.append(mk('b', 'waname', d.name));
    to.append(mk('span', 'wanum', shown(d.number)));
    if (d.assumed) to.append(mk('span', 'waassumed', ASSUMED));
    box.append(head, to, mk('p', 'watext', d.text));
    if (d.warn) {
      const w = mk('p', 'wawarn', WARN);
      w.setAttribute('role', 'note');
      box.append(w);
    }
    const acts = mk('div', 'waacts');
    const a = mk('a', 'btn primary lift waopen', 'Open in WhatsApp');
    const link = d.link;
    a.href = link;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.referrerPolicy = 'no-referrer';
    a.setAttribute('aria-label', `Open in WhatsApp: draft to ${who} (opens in a new tab; nothing is sent until you press Send)`);
    acts.append(a, hint(d));
    box.append(acts);
    return box;
  }

  function render(row, list) {
    const items = normal(list);
    if (!row || !items.length) return null;
    const cards = items.map(card);
    cards.forEach((c) => row.appendChild(c));
    return cards[0];
  }

  window.JarvisWhatsApp = Object.freeze({ render, normal, waLink, clean, stacked });
})();
