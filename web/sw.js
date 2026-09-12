/* ZOUSEEKING PWA service worker - static app-shell caching only.
 *
 * Cache policy: network-first for same-origin navigation requests so deployed
 * HTML cannot be pinned to an old app shell; versioned static assets use
 * cache-first. API and cross-origin requests
 * (backend /api/*, Supabase /rest/v1|/auth/v1, /functions/*) always go
 * to the network - never cache member data, reports or auth responses.
 * Bump SW_VERSION to force an app-shell refresh after deploys.
 */
const SW_VERSION = "20260912-r6";
const APP_SHELL = [
  "./index.html",
  "./property-analysis.html",
  "./report.html",
  "./project.html",
  "./projects.html",
  "./mypage.html",
].map((path) => `${path}?v=${SW_VERSION}`);
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

self.addEventListener("message", (event) => {
  if (event.data?.type !== "GET_VERSION") return;
  const reply = { type: "VERSION", version: SW_VERSION };
  if (event.ports?.[0]) event.ports[0].postMessage(reply);
  else event.source?.postMessage(reply);
});

function isStaticAsset(url) {
  if (url.origin !== self.location.origin) return false;
  const path = url.pathname;
  if (["/api/", "/rest/v1/", "/auth/v1/", "/functions/"].some((prefix) => path.startsWith(prefix))) return false;
  if (path.endsWith(".html")) return APP_SHELL_PATHS.has(path);
  if (path.startsWith("/assets/")) return true;
  return /\.(css|js|json|webmanifest|svg|png|ico|woff2?)$/.test(path);
}

function isVersionedAsset(url) {
  return ["v", "version", "rev", "hash"].some((key) => url.searchParams.has(key));
}

function cacheAppShellFallback(pathname) {
  const versionedPath = `${pathname.replace(/\/$/, "") || "/index.html"}?v=${SW_VERSION}`;
  return caches.match(new URL(versionedPath, self.location)).then((cached) => {
    if (cached) return cached;
    return caches.match(new URL(`./index.html?v=${SW_VERSION}`, self.location));
  });
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            event.waitUntil(
              caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(request, response.clone()))
                .catch(() => {}),
            );
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || cacheAppShellFallback(url.pathname))),
    );
    return;
  }

  if (!isStaticAsset(url)) return;

  if (!isVersionedAsset(url)) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response && response.ok) {
          event.waitUntil(
            caches
              .open(CACHE_NAME)
              .then((cache) => cache.put(request, response.clone()))
              .catch(() => {}),
          );
        }
        return response;
      });
    }),
  );
});
