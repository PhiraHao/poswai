const CACHE_NAME = 'pos-wai-offline-v34';
const ASSETS = [
  "/",
  "/index.html",
  "/line_pos_prototype.html",
  "/ui.css",
  "/workspace.css?v=19",
  "/sales-redesign.css?v=19",
  "/ops-redesign.css?v=19",
  "/people-redesign.css?v=19",
  "/staff-admin.css?v=32",
  "/reports-restore.css?v=19",
  "/reports-live.css?v=20",
  "/service-call.css?v=19",
  "/auth-ui.css?v=20",
  "/payment-ui.css?v=21",
  "/workspace.js?v=19",
  "/sales-redesign.js?v=19",
  "/ops-redesign.js?v=19",
  "/people-redesign.js?v=30",
  "/staff-admin.js?v=29",
  "/reports-restore.js?v=19",
  "/reports-live.js?v=31",
  "/service-call.js?v=19",
  "/auth-ui.js?v=34",
  "/payment-ui.js?v=21",
  "/live-data.js?v=24",
  "/inventory-live.js?v=23",
  "/commerce-ui.css?v=28",
  "/commerce-ui.js?v=27",
  "/icons.svg",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
  "/assets/brand-logo.webp",
  "/assets/brand-mark.webp",
  "/assets/mascot-pos.webp",
  "/assets/mascot-wave.webp",
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
