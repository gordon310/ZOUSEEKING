/* ZOUSEEKING PWA service worker - static app-shell caching only.
 *
 * Cache policy: stale-while-revalidate for same-origin static assets
 * (html/css/js/svg/png/webmanifest). API and cross-origin requests
 * (backend /api/*, Supabase /rest/v1|/auth/v1, /functions/*) always go
 * to the network - never cache member data, reports or auth responses.
 * Bump SW_VERSION to force an app-shell refresh after deploys.
 */
const SW_VERSION = "2026-09-12-r2";
const APP_SHELL = [
  "./index.html",
  "./property-analysis.html",
  "./report.html",
  "./project.html",
  "./projects.html",
  "./mypage.html",
];
const CACHE_NAME = `zouseeking-shell-${SW_VERSION}`;
const APP_SHELL_PATHS = new Set(APP_SHELL.map((path) => new URL(path, self.location).pathname));

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()),
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
  if (["/api/", "/rest/v1/", "/auth/v1/", "/functions/"].some((prefix) => path.startsWith(prefix))) return false;
  if (path.endsWith(".html")) return APP_SHELL_PATHS.has(path);
  if (path.startsWith("/assets/")) return true;
  return /\.(css|js|json|webmanifest|svg|png|ico|woff2?)$/.test(path);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      caches
        .match(request)
        .then((cached) => cached || fetch(request))
        .catch(() => caches.match(new URL("./index.html", self.location).pathname)),
    );
    return;
  }

  if (!isStaticAsset(url)) return;

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
