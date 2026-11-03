// src/jarvis/api/static/console-text.js -- the console's ONE rule for characters that can't be seen
// (slice 12 final review; docs/plans/phase2-slice12-integrations.md). Used by console-media.js (Maps /
// YouTube cards, Home and Work), console-drive.js (folder names) and console-whatsapp.js (a draft
// whose name or text still holds one is dropped). No build step; CSP script-src 'self'; ASCII
// source with backslash-u escapes only. Loads before every module that uses it.
//   window.JarvisText  INVISIBLE_CLASS (the character class, as text), hasInvisible(s) -> bool,
//     strip(s) -> s without them ('' for anything but a string).
// Removed: C0 / C1 controls but new line, tab and carriage return; the soft hyphen; the combining
// grapheme joiner; the Arabic letter mark; the Mongolian vowel separator; zero-width space;
// left-to-right / right-to-left marks; line and paragraph separators; the bidi embeddings,
// overrides and isolates; word joiner and the invisible operators; BOM; and the tag characters
// U+E0000-E007F (invisible "ASCII smuggling"). The RegExp has the u flag, so it reads code points:
// without it a tag character (a surrogate pair) could never match. KEPT: the zero-width
// non-joiner and joiner (U+200C / U+200D), which Malayalam and other Indic scripts need to spell
// words (and emoji sequences need to join) -- the server keeps them too
// (jarvis.tools.external.model_text, jarvis.whatsapp.draft.clean_text).
(() => {
  'use strict';
  const INVISIBLE_CLASS = '[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f-\\u009f\\u00ad\\u034f\\u061c\\u180e\\u200b\\u200e\\u200f\\u2028-\\u202e\\u2060-\\u2064\\u2066-\\u2069\\ufeff\\u{e0000}-\\u{e007f}]';
  const ONE = new RegExp(INVISIBLE_CLASS, 'u');
  const ALL = new RegExp(INVISIBLE_CLASS, 'gu');
  const hasInvisible = (s) => typeof s === 'string' && ONE.test(s);
  const strip = (s) => (typeof s === 'string' ? s.replace(ALL, '') : '');
  window.JarvisText = Object.freeze({ INVISIBLE_CLASS, hasInvisible, strip });
})();
