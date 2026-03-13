// OpenClaw Admin Service Worker — offline caching
const CACHE_NAME = 'oc-admin-v1';
const PRECACHE = [
  '/admin',
  'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API requests: network-only (don't cache dynamic data)
  if (url.pathname.startsWith('/api/')) return;

  // SSE: skip
  if (event.request.headers.get('accept')?.includes('text/event-stream')) return;

  // Static assets: cache-first with network fallback
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    }).catch(() => caches.match('/admin'))
  );
});
