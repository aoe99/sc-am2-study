// Offline shell only. The question data lives in IndexedDB and is never
// cached here — it is copyrighted and must not leave the device.

const VERSION = 'sc-am2-v16';
const SHELL = [
  './', './index.html', './manifest.webmanifest',
  './css/app.css',
  './js/main.js', './js/db.js', './js/data.js', './js/settings.js',
  './js/ui.js', './js/engine.js', './js/leitner.js', './js/figures.js',
  './js/views/home.js', './js/views/setup.js', './js/views/quiz.js',
  './js/views/quizPm.js', './js/views/result.js', './js/views/resultPm.js',
  './js/views/stats.js', './js/views/settings.js', './js/views/import.js',
  './icons/icon-180.png', './icons/icon-192.png', './icons/icon-512.png',
  './icons/icon-512-maskable.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION)
    .then(c => c.addAll(SHELL))
    .then(() => self.skipWaiting())
    .catch(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Network-first for navigations so a redeploy is picked up, cache as fallback.
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req)
      .then(res => {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put('./index.html', copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match('./index.html')));
    return;
  }

  // Network-first for the rest of the shell too. Cache-first was stranding
  // devices on old modules: once a file was cached it was served forever, so a
  // fix could not reach a phone until its service worker happened to update.
  // The shell is ~180KB and the question data lives in IndexedDB, so paying a
  // round trip when online is cheap, and the cache still answers offline.
  e.respondWith(fetch(req)
    .then(res => {
      if (res.ok && res.type === 'basic') {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(req, copy)).catch(() => {});
      }
      return res;
    })
    .catch(() => caches.match(req)));
});
