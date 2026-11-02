// src/jarvis/api/static/console-whatsapp.js -- slice 12 D6 (docs/plans/phase2-slice12-integrations.md):
// the WhatsApp draft card under a reply. JARVIS writes the message; the owner opens it in WhatsApp and
// presses Send there. JARVIS sends nothing. No build step; CSP script-src 'self'; ASCII source with
// \u escapes only; every server string reaches the page through textContent, never markup.
//   window.JarvisWhatsApp  render(row, drafts) -> the row's first card (or null). console.js calls it
//     for a fresh reply (ChatResponse.whatsapp: [{name, number, text, link, warning}]).
//   The one link is built HERE from the checked number and the text (encodeURIComponent), never taken
//   from the server: https://wa.me/<digits>?text=<encoded>. It is an ordinary link -- it opens only when
//   the owner clicks it, in a new tab, with rel="noopener noreferrer" and no referrer.
//   A draft that is malformed (number not E.164, text longer than 2,000 characters, a hidden character,
//   a lone surrogate) is dropped, never shown half-right.
(() => {
  'use strict';
  const MAX_CARDS = 5;
  const TEXT_MAX = 2000;
  const NAME_MAX = 100;
  const DIGITS = /^[1-9][0-9]{6,14}$/;
  // what the server already removed (bidi controls and marks, zero-width space, BOM, controls but
  // new lines and tabs): a card still holding one is dropped
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/;
  const WARN = 'This number didn\u2019t come from you or your contacts \u2014 check it before you send.';
  const HINT = 'Opens WhatsApp with this text. Nothing is sent until you press Send there.';

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

  /** ChatResponse.whatsapp, checked field by field; anything odd is dropped. */
  function normal(list) {
    return (Array.isArray(list) ? list : []).slice(0, MAX_CARDS).map((d) => {
      if (!d || typeof d !== 'object' || typeof d.text !== 'string') return null;
      const text = d.text;
      if (!text.trim() || Array.from(text).length > TEXT_MAX || INVISIBLE.test(text)) return null;
      const link = waLink(d.number, text);
      if (!link) return null;
      const name = typeof d.name === 'string' && !INVISIBLE.test(d.name)
        ? d.name.replace(/\s+/g, ' ').trim().slice(0, NAME_MAX) : '';
      return { name, number: d.number, text, link, warn: typeof d.warning === 'string' && d.warning.length > 0 };
    }).filter(Boolean);
  }

  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  function card(d) {
    const who = d.name ? `${d.name}, ${shown(d.number)}` : shown(d.number);
    const box = mk('div', 'wadraft');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', `WhatsApp draft to ${who}`);
    const head = mk('div', 'wahead');
    head.append(mk('span', 'walabel', 'WhatsApp draft'), mk('span', 'wastate', 'Not sent'));
    const to = mk('div', 'wato');
    to.append(mk('span', 'wak', 'To'));
    if (d.name) to.append(mk('b', 'waname', d.name));
    to.append(mk('span', 'wanum', shown(d.number)));
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
    acts.append(a, mk('span', 'wahint', HINT));
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

  window.JarvisWhatsApp = Object.freeze({ render, normal, waLink });
})();
