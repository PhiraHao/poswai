const CACHE_NAME = 'pos-wai-offline-v18';
const ASSETS = [
  "/",
  "/index.html",
  "/line_pos_prototype.html",
  "/ui.css",
  "/workspace.css?v=18",
  "/sales-redesign.css?v=18",
  "/ops-redesign.css?v=18",
  "/people-redesign.css?v=18",
  "/reports-restore.css?v=18",
  "/service-call.css?v=18",
  "/workspace.js?v=18",
  "/sales-redesign.js?v=18",
  "/ops-redesign.js?v=18",
  "/people-redesign.js?v=18",
  "/reports-restore.js?v=18",
  "/service-call.js?v=18",
  "/icons.svg",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
  "/assets/fonts.css",
  "/assets/food-icon.svg",
  "/assets/drink-icon.svg",
  "/assets/dessert-icon.svg",
  "/assets/menu-placeholder.svg",
  "/assets/noto-thai-0.ttf",
  "/assets/noto-thai-1.ttf",
  "/assets/noto-thai-2.ttf",
  "/assets/noto-thai-3.ttf"
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))),
    self.clients.claim()
  ]));
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).pathname.startsWith('/api/')) return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request, { ignoreSearch: true }).then(res => res || (event.request.mode === 'navigate' ? caches.match('/index.html') : Response.error())))
  );
});
