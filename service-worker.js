const CACHE_NAME = 'pos-wai-offline-v8';
const ASSETS = ['/', '/index.html', '/line_pos_prototype.html', '/manifest.json'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then(res => res || caches.match('/index.html')))
  );
});
