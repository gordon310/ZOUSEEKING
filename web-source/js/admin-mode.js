(() => {
  // Mode resolution for the back-office admin page (mirrors web/app.js's
  // convention: the page talks to the real /api/admin/* backend only when a
  // base URL is configured AND the surface is not demo-only).
  //
  // Sources, in priority order:
  //   1. window.ZOUSEEKING_API_BASE_URL   (set by web/config.js or deployment)
  //   2. localStorage "zou_house_api_base" (per-browser override, app.js habit)
  //   3. release boundary: release-boundary.js sets
  //      window.ZOUSEEKING_REAL_OPERATIONS_DISABLED = true on demo-only
  //      surfaces (role=admin + adminOperations=false in the release scope).
  //   4. "?demo=1" query flag (same convention as projects/property pages).
  //
  // Demo stays the default: git-tree config.js points the release scope at the
  // consumer_intake_preview phase with adminOperations=false, so the release
  // boundary marks the surface demo-only before this file runs.
  function readLocal(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function queryDemoForced() {
    try {
      return new URLSearchParams(window.location.search).get("demo") === "1";
    } catch {
      return false;
    }
  }

  const apiBaseUrl = String(
    window.ZOUSEEKING_API_BASE_URL || readLocal("zou_house_api_base") || "",
  ).replace(/\/+$/, "");
  const demoForced = queryDemoForced();
  const realOperationsDisabled = window.ZOUSEEKING_REAL_OPERATIONS_DISABLED === true;
  const live = Boolean(apiBaseUrl) && !demoForced && !realOperationsDisabled;

  window.ZouAdminMode = Object.freeze({
    apiBaseUrl,
    live,
    demoForced,
    realOperationsDisabled,
  });
})();
