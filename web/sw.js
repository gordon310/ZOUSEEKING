/* ZOUSEEKING PWA service worker - static app-shell caching only.
 *
 * Cache policy: stale-while-revalidate for same-origin static assets
 * (html/css/js/svg/png/webmanifest). API and cross-origin requests
 * (backend /api/*, Supabase /rest/v1|/auth/v1, /functions/*) always go
 * to the network - never cache member data, reports or auth responses.
 * Bump SW_VERSION to force an app-shell refresh after deploys.
 */
const SW_VERSION = "2026-09-09-r1";
const APP_SHELL = "./index.html";
const CACHE_NAME = `zouseeking-shell-${SW_VERSION}`;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll([APP_SHELL])).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

function isStaticAsset(url) {
  if (url.origin !== self.location.origin) return false;
  const path = url.pathname;
  if (path.includes("/api/")) return false;
  if (path.endsWith(".html")) return path === "/index.html";
  if (path.startsWith("/assets/")) return true;
  return /\.(css|js|json|webmanifest|svg|png|ico|woff2?)$/.test(path);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || !isStaticAsset(new URL(request.url))) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});
