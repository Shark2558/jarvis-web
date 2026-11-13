// src/jarvis/api/static/console-sw.js -- R3 D11: the Web Push service worker. Two handlers only
// (push, notificationclick) and NO fetch handler, so it can never serve a stale console. It is
// registered with scope /static/push/, so it controls no page; push needs only the registration.
// The payload is {kind, text, url} (template text, <= 1 KB, never a picture). Anything else is
// ignored.
// R7 D8-D10 (Part A): the click target is the panel the alert is about: `/`, `/?open=<panel>` or
// `/?do=<launch word>` and nothing else (the address rule below learned the `?`). Each alert offers
// "Talk", which opens JARVIS with the mic button ready (it never starts the microphone). The tag is
// the alert's kind (`tag: kind`, phone-contract.md section 6: the app sorts its channels by it).
// A tap with a JARVIS window already open focuses THAT window and hands it the target over the
// BroadcastChannel 'jarvis-launch' (console-r7-links.js opens the screen). Navigating fails on a
// window this worker does not control (every console window) and so opened a second window.
'use strict';

const TARGET = /^\/(?:\?(?:open=[a-z]{2,20}|do=(?:talk|look|sos|shared)))?$/;
const KIND = /^[a-z0-9_]{1,40}$/;
const TALK = '/?do=talk';

self.addEventListener('push', (event) => {
  let data = null;
  try { data = event.data ? event.data.json() : null; } catch (_) { data = null; }
  const ok = data && typeof data === 'object' && !Array.isArray(data);
  const text = ok && typeof data.text === 'string' ? data.text.slice(0, 300) : 'JARVIS has something for you.';
  const url = ok && typeof data.url === 'string' && TARGET.test(data.url) ? data.url : '/';
  const kind = ok && typeof data.kind === 'string' && KIND.test(data.kind) ? data.kind : 'alert';
  event.waitUntil(self.registration.showNotification('JARVIS', {
    body: text,
    tag: kind,
    data: { url },
    renotify: true,
    actions: [{ action: 'talk', title: 'Talk' }],
  }));
});

/** The JARVIS console window to reuse: this origin, the console's own address, focused first. */
function consoleWindow(wins) {
  const ours = wins.filter((w) => {
    try { const u = new URL(w.url); return u.origin === self.location.origin && u.pathname === '/'; } catch (_) { return false; }
  });
  return ours.find((w) => w.focused) || ours[0] || null;
}

function handOver(target) {
  const q = new URL(target, self.location.origin).searchParams;
  const ch = new BroadcastChannel('jarvis-launch');
  ch.postMessage({ type: 'launch', open: q.get('open') || '', do: q.get('do') || '' });
  ch.close();
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const d = event.notification.data;
  const url = d && typeof d.url === 'string' && TARGET.test(d.url) ? d.url : '/';
  const target = event.action === 'talk' ? TALK : url;
  event.waitUntil((async () => {
    const win = consoleWindow(await self.clients.matchAll({ type: 'window', includeUncontrolled: true }));
    if (win && 'focus' in win) {
      try { await win.focus(); handOver(target); return; } catch (_) { /* gone: open one */ }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});
