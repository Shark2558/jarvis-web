// src/jarvis/api/static/console-book-tour.js -- R6.3 D9, D14 (docs/plans/r6-3-book-content.md): the short tour's own
// parts of the show page, through the three hooks console-book-show.js calls only while it plays a tour (kind "tour"):
//   label(script, n, title) -> the chapters menu's words for scene n: its title; for the owner also "You only" on his
//                              own scenes (T16) and the scene's full-book chapter by name ("Full book: Costs")
//   seen(script, beat)       -> remembers the owner's place once the tour plays: localStorage jarvis_book_place_v1
//                              {release, scene} (ids only; the reader's {page} of the same release is kept beside it,
//                              and the reader's place of ANOTHER release is left as it is: C's rule, I1);
//                              Questions or the closing reached: the tour is done and its scene is forgotten
//   start(script, beats)     -> the beat index to begin at: the FIRST line of the remembered scene of this release
//                              ("continue where I left off" restarts the scene, never the middle of a line), else 0
// A guest's tour is never remembered and always starts at the beginning. The pictures are today's (console-book-
// script.js picture(): each tour scene's `visual` drawn with its own facts); every word shown comes from the server's
// script except the full book's chapter titles below (facts_model.CHAPTERS and gen/modules.MODULES, kept equal by
// tests/test_r63_d_static.py). No build step; CSP script-src 'self'; textContent only (nothing here writes the DOM).
(() => {
  'use strict';
  const PLACE_KEY = 'jarvis_book_place_v1';
  const RID = /^[0-9a-f]{7}$/, PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/;
  const FIRST = 1, LAST = 17; // the tour's content scenes; Questions (18) and Closing (19) follow
  const CHAPTER_NAMES = Object.freeze({
    pg_chapter_what: 'What JARVIS is',
    pg_chapter_example: 'The running example',
    pg_chapter_data: 'Data, hosting, security and recovery',
    pg_chapter_answers: 'How answers are made',
    pg_chapter_setup: 'A local setup',
    pg_chapter_technology: 'The technology inventory',
    pg_chapter_costs: 'Costs',
    pg_chapter_planned: 'What\'s planned',
    pg_module_console: 'Console and API',
    pg_module_brain: 'Chat and the brain router',
    pg_module_voice: 'Voice',
    pg_module_memory: 'Memory and knowledge',
    pg_module_vault: 'Vault and documents',
    pg_module_people: 'People and faces',
    pg_module_home: 'Home bridge and cameras',
    pg_module_alerts: 'Alerts and notifications',
    pg_module_integrations: 'Google, Telegram and other integrations',
    pg_module_vitals: 'Vitals, costs and the systems check',
    pg_module_privacy: 'The privacy panel',
    pg_module_activity: 'Activity log and undo',
    pg_module_approvals: 'Approvals and passkeys',
    pg_module_android: 'The Android app',
    pg_module_helpers: 'Daily helpers (brief, helpers, family, groceries, parcels)',
    pg_module_delivery: 'Delivery, CI and backups',
    pg_module_book: 'The Build Book',
    pg_module_wardrobe: 'Wardrobe & Try-on',
  });
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const store = {
    get() {
      try {
        const v = JSON.parse(localStorage.getItem(PLACE_KEY) || 'null');
        return v && typeof v === 'object' && !Array.isArray(v) ? v : null;
      } catch (_) { return null; }
    },
    put(v) {
      try { if (v) localStorage.setItem(PLACE_KEY, JSON.stringify(v)); else localStorage.removeItem(PLACE_KEY); } catch (_) {}
    },
  };
  const releaseOf = (sc) => (sc && sc.release && RID.test(sc.release.id || '') ? sc.release.id : '');
  /** Only the owner's tour is remembered (D14: owner only), and only with a release to bind it to. */
  const owners = (sc) => !!sc && sc.kind === 'tour' && sc.audience === 'owner' && !!releaseOf(sc);
  const sceneOf = (sc, n) => (sc && Array.isArray(sc.scenes) && sc.scenes.find((s) => s && s.n === n)) || null;

  function label(sc, n, title) {
    const s = sceneOf(sc, n);
    if (!s || sc.audience !== 'owner') return title; // a guest: the scene's title, nothing of the owner's
    const words = [title];
    if (s.audience === 'owner') words.push('You only');
    if (typeof s.chapter === 'string' && own(CHAPTER_NAMES, s.chapter)) words.push('Full book: ' + CHAPTER_NAMES[s.chapter]);
    return words.join(' \u00b7 ');
  }

  /** What this browser keeps for this release, checked field by field: a tour scene, the reader's page. */
  function place(release) {
    const v = store.get(), out = { release };
    if (!v || v.release !== release) return out; // another release's place is not this one's
    if (Number.isInteger(v.scene) && v.scene >= FIRST && v.scene <= LAST) out.scene = v.scene;
    if (typeof v.page === 'string' && PAGE.test(v.page)) out.page = v.page;
    return out;
  }
  let begun = false, last = 0; // nothing is remembered before Begin; one write a scene, not one a line
  function seen(sc, beat) {
    if (!begun || !owners(sc) || !beat || !Number.isInteger(beat.scene)) return;
    const done = beat.scene > LAST;
    if (beat.scene === last && !done) return;
    last = beat.scene;
    const rid = releaseOf(sc), old = store.get();
    const readers = old ? Object.keys(old).filter((k) => k !== 'scene' && k !== 'release') : [];
    if (readers.length && old.release !== rid) return; // the reader's place of another release stays as it is
    const p = place(rid);
    if (done) delete p.scene; else p.scene = beat.scene;
    store.put(p.scene || p.page ? p : null);
  }
  function start(sc, beats) {
    begun = true; last = 0;
    if (!owners(sc) || !Array.isArray(beats)) return 0;
    const p = place(releaseOf(sc));
    if (!p.scene || p.scene === FIRST) return 0;
    const i = beats.findIndex((b) => b && b.scene === p.scene && b.i === 0);
    return i > 0 ? i : 0;
  }
  window.JarvisBookTour = Object.freeze({ label, seen, start, PLACE_KEY });
})();
