// PWA: register the static-shell service worker when supported by the browser.
// The secure-context check keeps local file previews and insecure origins unchanged.
if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => {});
  });
}
