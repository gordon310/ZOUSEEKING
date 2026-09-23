// PWA: keep old installed app shells from silently serving an incompatible UI.
// The secure-context check keeps local file previews and insecure origins unchanged.
const PWA_RELOAD_KEY = "zouseeking-pwa-auto-reload";
const STALE_SW_DISTANCE = 2;

function releaseNumber(version) {
  const match = String(version || "").match(/(?:^|-)r(\d+)$/);
  return match ? Number(match[1]) : null;
}

function versionDistance(current, latest) {
  const currentNumber = releaseNumber(current);
  const latestNumber = releaseNumber(latest);
  if (currentNumber === null || latestNumber === null) return null;
  return latestNumber - currentNumber;
}

function hasReloadedThisSession() {
  try {
    return window.sessionStorage.getItem(PWA_RELOAD_KEY) === "1";
  } catch {
    return false;
  }
}

function markReloadedThisSession() {
  try {
    window.sessionStorage.setItem(PWA_RELOAD_KEY, "1");
  } catch {
    // A missing session store must not prevent normal browsing.
  }
}

function isUserEditing() {
  const active = document.activeElement;
  return Boolean(active?.matches("input, textarea, select, button, [contenteditable='true']"));
}

function reloadOnce() {
  if (!navigator.onLine || hasReloadedThisSession()) return;
  if (isUserEditing()) {
    const retryAfterEditing = () => {
      document.removeEventListener("focusout", retryAfterEditing, true);
      window.setTimeout(() => reloadOnce(), 0);
    };
    document.addEventListener("focusout", retryAfterEditing, true);
    return;
  }
  markReloadedThisSession();
  window.location.reload();
}

function askServiceWorkerVersion(registration) {
  return new Promise((resolve) => {
    const worker = registration.active;
    if (!worker) return resolve(null);
    const channel = new MessageChannel();
    const timeout = window.setTimeout(() => resolve(null), 1200);
    channel.port1.onmessage = (event) => {
      window.clearTimeout(timeout);
      resolve(event.data?.version || null);
    };
    worker.postMessage({ type: "GET_VERSION" }, [channel.port2]);
  });
}

async function readLatestVersion() {
  try {
    const response = await fetch(`sw.js?version-probe=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return null;
    const source = await response.text();
    return source.match(/const SW_VERSION = "([^"]+)"/)?.[1] || null;
  } catch {
    return null;
  }
}

async function guardAgainstStaleWorker(registration) {
  const [activeVersion, latestVersion] = await Promise.all([
    askServiceWorkerVersion(registration),
    readLatestVersion(),
  ]);
  if (versionDistance(activeVersion, latestVersion) >= STALE_SW_DISTANCE) {
    const removed = await registration.unregister().catch(() => false);
    if (removed) reloadOnce();
  }
}

function watchForWorkerActivation(registration) {
  const hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (hadController) reloadOnce();
  }, { once: true });
  registration.addEventListener("updatefound", () => {
    const worker = registration.installing;
    if (!worker) return;
    worker.addEventListener("statechange", () => {
      if (worker.state === "activated" && hadController) reloadOnce();
    });
  });
}

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("sw.js", { scope: "./" });
      watchForWorkerActivation(registration);
      await registration.update();
      await guardAgainstStaleWorker(registration);
    } catch {
      // Network failures and private browsing restrictions leave the page usable.
    }
  });
}
