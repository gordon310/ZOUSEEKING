(() => {
  const scope = window.ZOUSEEKING_RELEASE_SCOPE || {};
  const role = document.body.dataset.role || "";
  const liveServiceTasks = role === "business" && document.body.dataset.businessPage === "service-tasks";
  const demoOnly =
    scope.phase === "consumer_intake_preview" &&
    ((role === "business" && scope.businessOperations === false && !liveServiceTasks) ||
      (role === "admin" && scope.adminOperations === false));
  if (!demoOnly) return;

  const publicStaticFetchPaths = new Set(["/content-library.json", "/field-options.json"]);
  const consumerServiceTaskPath = (pathname) => pathname === "/api/service/tasks" || pathname.startsWith("/api/service/tasks/");
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request?.url || String(input), window.location.href);
    const method = String(init.method || request?.method || "GET").toUpperCase();
    if (
      url.origin === window.location.origin &&
      method === "GET" &&
      publicStaticFetchPaths.has(url.pathname)
    ) {
      return nativeFetch(input, init);
    }
    if (consumerServiceTaskPath(url.pathname)) return nativeFetch(input, init);
    return Promise.reject(new Error("real operations are disabled on this demo-only surface"));
  };
  window.ZOUSEEKING_REAL_OPERATIONS_DISABLED = true;
})();
