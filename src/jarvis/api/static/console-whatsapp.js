// src/jarvis/api/static/console-whatsapp.js -- slice 12 D6 (docs/plans/phase2-slice12-integrations.md):
// the WhatsApp draft card under a reply. JARVIS writes the message; the owner opens it in WhatsApp and
// presses Send there. JARVIS sends nothing. No build step; CSP script-src 'self'; ASCII source with
// backslash-u escapes only; every server string reaches the page through textContent, never markup.
//   window.JarvisWhatsApp  render(row, cards) -> the row's first card (or null). console.js calls it
//     for a fresh reply with ChatResponse.cards, and for a conversation opened again with the drafts
//     GET /v1/sessions/{id} rebuilt (final review); only kind "whatsapp" is drawn here
//     ({kind: "whatsapp", name, number, text, link, warning, assumed}); console-media.js draws the rest.
//     quoteParts(summary) -> {head, quote} | null: a whatsapp_draft approval's summary split so
//     console.js can give the quoted text its own dir="auto" paragraph (security review SEC-5).
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
// spaces at either end of a line, more than two blank lines in a row). S5: "Assumed India (+91)" when the
// number was written without a country code. S7: the hint names who nothing is sent to, and what
// opening does.
// Security reviews SEC-1 and SEC-5: the same rule as the server, character for character (both are
// tested over tests/fixtures/whatsapp_clean_cases.json): spaces and tabs become one plain space; FE0E
// never stays; FE0F only inside a keycap or right after a code point whose emoji is cp + FE0F
// (FE0F_BASES); ZWNJ / ZWJ only right after a virama (VIRAMAS), a ZWNJ also between two Arabic letters
// (ARABIC_LETTERS), a ZWJ also inside an emoji sequence; unassigned code points go, but future emoji --
// so no invisible channel can ride on a card that shows only the words. The three tables are exact
// copies of the server's (tests/test_whatsapp_console.py compares them).
(() => {
  'use strict';
  const KIND = 'whatsapp'; // its kind in ChatResponse.cards (jarvis.tools.reply_cards)
  const MAX_CARDS = 5;
  const TEXT_MAX = 2000;
  const NAME_MAX = 100;
  const LONG_LINES = 4; // from this many lines (or LONG_CHARS characters) the head says "N lines"
  const LONG_CHARS = 400;
  const DIGITS = /^[1-9][0-9]{6,14}$/;
  // what the server already removed (bidi controls and marks, zero-width space, BOM, tags, controls
  // but new lines and tabs): a card whose name or text still holds one is dropped. That is the
  // console's lenient display rule (console-text.js, final review: it keeps every ZWNJ / ZWJ); a
  // draft's TEXT must ALSO come back unchanged from the strict `clean` below, so for the text the
  // stricter rule always wins.
  const hidden = (s) => window.JarvisText.hasInvisible(s);
  // the server's cleaning, one character at a time: the categories it drops (control, format,
  // private use, lone surrogates) ...
  const DROPPED = /^[\p{Cc}\p{Cf}\p{Co}\p{Cs}]$/u;
  // ... the unassigned code points but future emoji (SEC-5 M3: this browser's Unicode is newer than
  // the server's, so its \p{Cn} never drops more than the server already did) ...
  const UNASSIGNED = /^\p{Cn}$/u;
  // ... and the letters and marks that render blank: Hangul fillers, the Khitan small script filler,
  // braille blank, combining grapheme joiner, Khmer inherent vowels, Mongolian selectors, variation
  // selectors but an emoji's FE0F (FE0E always), and the code points that render as nothing: U+2065,
  // U+FFF0-FFF8 and the whole tag block U+E0000-E0FFF (the server's BLANK and _BLANK_RANGES)
  const BLANK = /^[\u115f\u1160\u3164\uffa0\u{16fe4}\u2800\u034f\u17b4\u17b5\u180b-\u180d\u180f\ufe00-\ufe0e\u2065\ufff0-\ufff8\u{e0000}-\u{e0fff}]$/u;
  const JOINERS = new Set(['\u200c', '\u200d']);
  const ZWNJ = '\u200c';
  const VS16 = '\ufe0f'; // the emoji presentation selector
  const KEYCAP = '\u20e3'; // [0-9#*] + FE0F + U+20E3 is a keycap emoji
  const SPACEISH = /^[\t\p{Zs}]$/u;
  const EMOJI = /^\p{Extended_Pictographic}$/u;
  const SKIN = /^[\u{1f3fb}-\u{1f3ff}]$/u;
  const KEYCAP_BASE = /^[0-9#*]$/;
  // more than MAX_MARKS combining marks in a row: the server's draft.py refuses the text (FE-8);
  // a joiner between two marks does not break the run (as on the server)
  const MAX_MARKS = 4;
  const MARK = /^\p{M}$/u;
  const MARKISH = /[\p{M}\u200c\u200d]/gu; // what a grapheme count would fold into its base
  const WARN = 'This number didn\u2019t come from you or your contacts \u2014 check it before you send.';
  const ASSUMED = 'Assumed India (+91)';
  const HANDS_OVER = 'Opening the link hands this text to WhatsApp.';

  /** Every code point of a list of [first, last] ranges, as a Set. */
  function codes(ranges) {
    const set = new Set();
    ranges.forEach(([lo, hi]) => { for (let c = lo; c <= hi; c += 1) set.add(c); });
    return set;
  }
  // SEC-5 H1: jarvis.whatsapp.pictographic EMOJI_FE0F_BASES (Unicode 17.0): the code points whose
  // fully-qualified RGI emoji is cp + FE0F (Extended_Pictographic, Emoji_Presentation=No)
  const FE0F_BASES = codes([
    [0x00a9, 0x00a9], [0x00ae, 0x00ae], [0x203c, 0x203c], [0x2049, 0x2049], [0x2122, 0x2122],
    [0x2139, 0x2139], [0x2194, 0x2199], [0x21a9, 0x21aa], [0x2328, 0x2328], [0x23cf, 0x23cf],
    [0x23ed, 0x23ef], [0x23f1, 0x23f2], [0x23f8, 0x23fa], [0x24c2, 0x24c2], [0x25aa, 0x25ab],
    [0x25b6, 0x25b6], [0x25c0, 0x25c0], [0x25fb, 0x25fc], [0x2600, 0x2604], [0x260e, 0x260e],
    [0x2611, 0x2611], [0x2618, 0x2618], [0x261d, 0x261d], [0x2620, 0x2620], [0x2622, 0x2623],
    [0x2626, 0x2626], [0x262a, 0x262a], [0x262e, 0x262f], [0x2638, 0x263a], [0x2640, 0x2640],
    [0x2642, 0x2642], [0x265f, 0x2660], [0x2663, 0x2663], [0x2665, 0x2666], [0x2668, 0x2668],
    [0x267b, 0x267b], [0x267e, 0x267e], [0x2692, 0x2692], [0x2694, 0x2697], [0x2699, 0x2699],
    [0x269b, 0x269c], [0x26a0, 0x26a0], [0x26a7, 0x26a7], [0x26b0, 0x26b1], [0x26c8, 0x26c8],
    [0x26cf, 0x26cf], [0x26d1, 0x26d1], [0x26d3, 0x26d3], [0x26e9, 0x26e9], [0x26f0, 0x26f1],
    [0x26f4, 0x26f4], [0x26f7, 0x26f9], [0x2702, 0x2702], [0x2708, 0x2709], [0x270c, 0x270d],
    [0x270f, 0x270f], [0x2712, 0x2712], [0x2714, 0x2714], [0x2716, 0x2716], [0x271d, 0x271d],
    [0x2721, 0x2721], [0x2733, 0x2734], [0x2744, 0x2744], [0x2747, 0x2747], [0x2763, 0x2764],
    [0x27a1, 0x27a1], [0x2934, 0x2935], [0x2b05, 0x2b07], [0x3030, 0x3030], [0x303d, 0x303d],
    [0x3297, 0x3297], [0x3299, 0x3299], [0x1f170, 0x1f171], [0x1f17e, 0x1f17f], [0x1f202, 0x1f202],
    [0x1f237, 0x1f237], [0x1f321, 0x1f321], [0x1f324, 0x1f32c], [0x1f336, 0x1f336], [0x1f37d, 0x1f37d],
    [0x1f396, 0x1f397], [0x1f399, 0x1f39b], [0x1f39e, 0x1f39f], [0x1f3cb, 0x1f3ce], [0x1f3d4, 0x1f3df],
    [0x1f3f3, 0x1f3f3], [0x1f3f5, 0x1f3f5], [0x1f3f7, 0x1f3f7], [0x1f43f, 0x1f43f], [0x1f441, 0x1f441],
    [0x1f4fd, 0x1f4fd], [0x1f549, 0x1f54a], [0x1f56f, 0x1f570], [0x1f573, 0x1f579], [0x1f587, 0x1f587],
    [0x1f58a, 0x1f58d], [0x1f590, 0x1f590], [0x1f5a5, 0x1f5a5], [0x1f5a8, 0x1f5a8], [0x1f5b1, 0x1f5b2],
    [0x1f5bc, 0x1f5bc], [0x1f5c2, 0x1f5c4], [0x1f5d1, 0x1f5d3], [0x1f5dc, 0x1f5de], [0x1f5e1, 0x1f5e1],
    [0x1f5e3, 0x1f5e3], [0x1f5e8, 0x1f5e8], [0x1f5ef, 0x1f5ef], [0x1f5f3, 0x1f5f3], [0x1f5fa, 0x1f5fa],
    [0x1f6cb, 0x1f6cb], [0x1f6cd, 0x1f6cf], [0x1f6e0, 0x1f6e5], [0x1f6e9, 0x1f6e9], [0x1f6f0, 0x1f6f0],
    [0x1f6f3, 0x1f6f3]
  ]);
  // SEC-5 M1 (RFC 5892 CONTEXTJ): jarvis.whatsapp.joining VIRAMAS (canonical combining class 9) and
  // ARABIC_LETTERS (Python 3.12, Unicode 15.0) -- JavaScript has no combining-class property
  const VIRAMAS = codes([
    [0x094d, 0x094d], [0x09cd, 0x09cd], [0x0a4d, 0x0a4d], [0x0acd, 0x0acd], [0x0b4d, 0x0b4d],
    [0x0bcd, 0x0bcd], [0x0c4d, 0x0c4d], [0x0ccd, 0x0ccd], [0x0d3b, 0x0d3c], [0x0d4d, 0x0d4d],
    [0x0dca, 0x0dca], [0x0e3a, 0x0e3a], [0x0eba, 0x0eba], [0x0f84, 0x0f84], [0x1039, 0x103a],
    [0x1714, 0x1715], [0x1734, 0x1734], [0x17d2, 0x17d2], [0x1a60, 0x1a60], [0x1b44, 0x1b44],
    [0x1baa, 0x1bab], [0x1bf2, 0x1bf3], [0x2d7f, 0x2d7f], [0xa806, 0xa806], [0xa82c, 0xa82c],
    [0xa8c4, 0xa8c4], [0xa953, 0xa953], [0xa9c0, 0xa9c0], [0xaaf6, 0xaaf6], [0xabed, 0xabed],
    [0x10a3f, 0x10a3f], [0x11046, 0x11046], [0x11070, 0x11070], [0x1107f, 0x1107f], [0x110b9, 0x110b9],
    [0x11133, 0x11134], [0x111c0, 0x111c0], [0x11235, 0x11235], [0x112ea, 0x112ea], [0x1134d, 0x1134d],
    [0x11442, 0x11442], [0x114c2, 0x114c2], [0x115bf, 0x115bf], [0x1163f, 0x1163f], [0x116b6, 0x116b6],
    [0x1172b, 0x1172b], [0x11839, 0x11839], [0x1193d, 0x1193e], [0x119e0, 0x119e0], [0x11a34, 0x11a34],
    [0x11a47, 0x11a47], [0x11a99, 0x11a99], [0x11c3f, 0x11c3f], [0x11d44, 0x11d45], [0x11d97, 0x11d97],
    [0x11f41, 0x11f42]
  ]);
  const ARABIC_LETTERS = codes([
    [0x0620, 0x063f], [0x0641, 0x064a], [0x066e, 0x066f], [0x0671, 0x06d3], [0x06d5, 0x06d5],
    [0x06ee, 0x06ef], [0x06fa, 0x06fc], [0x06ff, 0x06ff], [0x0750, 0x077f], [0x0870, 0x0882],
    [0x0886, 0x0886], [0x0889, 0x088d], [0x08a0, 0x08c8], [0xfb50, 0xfbb1], [0xfbd3, 0xfbe9],
    [0xfbfc, 0xfbff], [0xfe80, 0xfef4]
  ]);

  const emoji = (ch) => !!ch && EMOJI.test(ch);
  const inTable = (table, ch) => !!ch && table.has(ch.codePointAt(0));

  /** Pass 1: each character kept (joiners and FE0F for pass 2), dropped, turned into a new line or
   *  one plain space. */
  function visible(text) {
    const out = [];
    for (const ch of text) {
      if (ch === '\n' || JOINERS.has(ch) || ch === VS16) out.push(ch);
      else if (SPACEISH.test(ch)) out.push(' ');
      else if (BLANK.test(ch)) continue;
      else if (ch === '\u2028' || ch === '\u2029') out.push('\n');
      else if (!DROPPED.test(ch) && !(UNASSIGNED.test(ch) && !emoji(ch))) out.push(ch);
    }
    return out;
  }

  /** SEC-5 M1: the joiner at chars[i] stays right after a virama, a ZWNJ also between two Arabic
   *  letters, a ZWJ also between an emoji (or its skin tone or FE0F) and the next emoji. */
  function keepJoiner(chars, i) {
    const prev = i > 0 ? chars[i - 1] : '';
    const next = i + 1 < chars.length ? chars[i + 1] : '';
    if (inTable(VIRAMAS, prev)) return true;
    if (chars[i] === ZWNJ) return inTable(ARABIC_LETTERS, prev) && inTable(ARABIC_LETTERS, next);
    const before = prev === VS16 ? (i > 1 && emoji(chars[i - 2])) : (emoji(prev) || SKIN.test(prev));
    return before && emoji(next);
  }

  /** SEC-5 H1: an FE0F stays only inside a keycap or right after a FE0F_BASES code point. */
  const keepSelector = (prev, next) => (KEYCAP_BASE.test(prev) && next === KEYCAP) || inTable(FE0F_BASES, prev);

  /** Pass 2: joiners and FE0F judged against their immediate neighbours in pass 1's text. */
  function joined(chars) {
    const out = [];
    chars.forEach((ch, i) => {
      if (JOINERS.has(ch)) {
        if (keepJoiner(chars, i)) out.push(ch);
      } else if (ch === VS16) {
        if (keepSelector(i > 0 ? chars[i - 1] : '', i + 1 < chars.length ? chars[i + 1] : '')) out.push(ch);
      } else out.push(ch);
    });
    return out.join('');
  }

  /** The text as the server's clean_text leaves it (so a card whose text differs is dropped). */
  function clean(text) {
    const once = joined(visible(text.replace(/\r\n?/g, '\n'))).replace(/ {2,}/g, ' ');
    const lines = once.split('\n').map((line) => line.replace(/^ +| +$/g, '')); // SEC-5 M2: both ends
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
      if (!text.trim() || Array.from(text).length > TEXT_MAX || hidden(text)) return null;
      if (clean(text) !== text) return null; // the server would never have sent it so
      if (stacked(text)) return null; // ... nor this (FE-8)
      const link = waLink(d.number, text);
      if (!link || d.link !== link) return null; // FE-7: exactly the server's link, or no card
      // SEC-5: NAME_MAX counts code points, as the server's (Python) string does
      const name = typeof d.name === 'string' && !hidden(d.name)
        ? Array.from(d.name.replace(/\s+/g, ' ').trim()).slice(0, NAME_MAX).join('').trim() : '';
      const flag = (v) => typeof v === 'string' && v.length > 0;
      return { name, number: d.number, text, link, warn: flag(d.warning), assumed: flag(d.assumed) };
    }).filter(Boolean);
  }

  /** A whatsapp_draft approval's summary (jarvis.whatsapp.tools._card_text) as its head (what, To,
   *  "Text (n lines, m characters), in full:") and its quote (every line "> "), so the approval card
   *  can give the quoted text dir="auto" (SEC-5); null when it is not that shape (shown whole). */
  function quoteParts(summary) {
    if (typeof summary !== 'string') return null;
    const lines = summary.split('\n');
    if (lines.length < 4 || !/^Text \(.+\), in full:$/.test(lines[2])) return null;
    const quote = lines.slice(3);
    if (!quote.every((line) => line === '>' || line.startsWith('> '))) return null;
    return { head: lines.slice(0, 3).join('\n'), quote: quote.join('\n') };
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
    const body = mk('p', 'watext', d.text);
    body.dir = 'auto'; // SEC-5: a right-to-left draft (Persian, Arabic) reads in its own direction
    box.append(head, to, body);
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

  window.JarvisWhatsApp = Object.freeze({ render, normal, waLink, clean, stacked, quoteParts });
})();
