// QR Console Service Worker — offline status + PWA shell
const CACHE_NAME = 'oc-qr-v2';
const API_CACHE  = 'oc-qr-api-v2';

const SHELL_URLS = ['/qr', '/qr-manifest.json', '/i18n/zh.json', '/i18n/en.json'];

const CACHEABLE_API = [
  '/api/system/health',
  '/api/system/info',
  '/api/wechat/status',
  '/api/config/auto-open-qr',
  '/api/setup/status',
  '/api/cowork/status',
  '/api/events',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_URLS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME && k !== API_CACHE).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // SSE — never intercept
  if (event.request.headers.get('accept')?.includes('text/event-stream')) return;

  // Cacheable API: network-first, stale fallback
  if (CACHEABLE_API.some(p => url.pathname === p)) {
    event.respondWith(
      fetch(event.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(API_CACHE).then(c => c.put(event.request, clone));
        }
        return resp;
      }).catch(() =>
        caches.match(event.request).then(cached => {
          if (cached) {
            const h = new Headers(cached.headers);
            h.set('X-OC-Cache', 'offline');
            return new Response(cached.body, { status: cached.status, headers: h });
          }
          return new Response(JSON.stringify({ error: 'offline' }), {
            status: 503, headers: { 'Content-Type': 'application/json' },
          });
        })
      )
    );
    return;
  }

  // App shell: network-first
  if (url.pathname === '/qr' || url.pathname === '/qr/') {
    event.respondWith(
      fetch(event.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
        }
        return resp;
      }).catch(() =>
        caches.match(event.request).then(cached => {
          if (cached) return cached;
          return new Response(offlineHTML(), { headers: { 'Content-Type': 'text/html;charset=utf-8' } });
        })
      )
    );
    return;
  }
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data?.type === 'CLEAR_CACHE') {
    caches.delete(API_CACHE);
    caches.delete(CACHE_NAME);
  }
});

function offlineHTML() {
  return '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>控制台 — 离线</title></head>' +
    '<body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;background:#0f1117;color:#e8e8f0">' +
    '<div style="font-size:64px;margin-bottom:16px">🦞</div>' +
    '<h1 style="font-size:20px;margin-bottom:8px">设备离线</h1>' +
    '<p style="color:#8888aa;margin-bottom:24px;font-size:14px">请连接到局域网后重试</p>' +
    '<button onclick="location.reload()" style="padding:12px 24px;background:#6366f1;color:#fff;border:none;border-radius:10px;font-size:15px;cursor:pointer;font-weight:600">重试连接</button>' +
    '</body></html>';
}
