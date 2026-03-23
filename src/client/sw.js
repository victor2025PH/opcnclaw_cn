// OpenClaw Voice — Service Worker v9
const CACHE_NAME = 'oc-v9';
const API_CACHE = 'ssx-api-v3';

// 不缓存 HTML 页面（频繁更新，缓存导致旧版本问题）
const OFFLINE_URLS = [
  '/manifest.json',
];

const CACHEABLE_API = [
  '/api/models',
  '/api/mcp/servers',
  '/api/mcp/tools',
  '/api/mcp/skills',
  '/api/desktop-skills',
  '/api/system/gpu',
  '/api/system/disk',
  '/api/models/summary',
  '/api/emotion/state',
  '/api/history/sessions',
  '/api/router/status',
  '/api/setup/status',
];

// History sync — cache for offline viewing
const HISTORY_API = '/api/history/sync';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(OFFLINE_URLS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.protocol === 'wss:' || url.protocol === 'ws:') {
    return;
  }

  // Cacheable API + history sync: network-first with cache fallback
  const isCacheableApi = CACHEABLE_API.some(p => url.pathname === p);
  const isHistorySync = url.pathname === HISTORY_API;

  if (isCacheableApi || isHistorySync) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request).then((cached) => {
          if (cached) {
            const headers = new Headers(cached.headers);
            headers.set('X-OC-Cache', 'offline');
            return new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers });
          }
          return new Response(JSON.stringify({ error: 'offline', cached: false }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          });
        }))
    );
    return;
  }

  // Never intercept these paths (exact match for pages, prefix for /api/)
  const BYPASS_EXACT = ['/', '/qr', '/qr/', '/setup', '/setup/', '/cert', '/cert/', '/admin', '/admin/', '/demo', '/demo/'];
  const BYPASS_PREFIX = ['/api/', '/ws', '/docs', '/redoc'];
  if (BYPASS_EXACT.includes(url.pathname) || BYPASS_PREFIX.some(p => url.pathname.startsWith(p))) {
    return;
  }

  if (!OFFLINE_URLS.some((u) => url.pathname === u || url.pathname === u + '/')) {
    return;
  }

  // App shell: network-first with offline fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          return new Response(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>十三香小龙虾 - 离线</title></head>' +
            '<body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;background:#0a0a14;color:#e8e8f0">' +
            '<div style="font-size:64px;margin-bottom:16px">🦞</div>' +
            '<h1 style="font-size:22px;margin-bottom:8px">无网络连接</h1>' +
            '<p style="color:#666688;margin-bottom:24px">请连接到局域网后重试</p>' +
            '<button onclick="location.reload()" style="padding:14px 28px;background:#6366f1;color:#fff;border:none;border-radius:10px;font-size:16px;cursor:pointer;font-weight:600">重试连接</button>' +
            '</body></html>',
            { headers: { 'Content-Type': 'text/html;charset=utf-8' } }
          );
        });
      })
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CLEAR_API_CACHE') {
    caches.delete(API_CACHE);
  }
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
