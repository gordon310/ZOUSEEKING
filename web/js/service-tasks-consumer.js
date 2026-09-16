(() => {
  const list = document.querySelector("#creatorServiceTaskList");
  if (!list || !window.ZouBusinessApi) return;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
  const statusLabels = {
    completion_pending: "business.creatorTaskCompletionPending",
    matched_pending_consent: "business.creatorTaskAwaitingConsent",
    in_progress: "business.taskInProgress",
    completed: "business.taskCompleted",
    open: "business.taskOpen",
    cancelled: "business.taskCancelled",
    expired: "business.taskExpired",
    closed_unconfirmed: "business.taskClosedUnconfirmed",
    suspended: "business.taskSuspended",
  };
  const render = (items) => {
    if (!items.length) { list.innerHTML = `<p class="empty">${escapeHtml(t("business.creatorTaskEmpty"))}</p>`; return; }
    list.innerHTML = items.map((task) => {
      const creatorConsentGranted = task.status === "matched_pending_consent" && task.creator_consent_status === "granted";
      const statusKey = creatorConsentGranted ? "business.creatorTaskAwaitingOtherConsent" : (statusLabels[task.status] || "business.creatorTaskStatusUnknown");
      const action = task.status === "completion_pending"
        ? `<button class="ghost-button" type="button" data-confirm-task="${escapeHtml(task.id)}">${escapeHtml(t("business.creatorTaskConfirmCompletion"))}</button>`
        : task.status === "matched_pending_consent" && !creatorConsentGranted
          ? `<button class="ghost-button" type="button" data-consent-task="${escapeHtml(task.id)}">${escapeHtml(t("business.creatorTaskGrantConsent"))}</button>`
          : "";
      return `<article class="task-card"><div><strong>${escapeHtml(task.purpose)}</strong><p>${escapeHtml(task.public_description)}</p></div><div class="task-meta"><span>${escapeHtml(t(statusKey))}</span>${action}</div></article>`;
    }).join("");
  };
  const load = async () => {
    if (!window.ZouAuthSession?.read?.()?.accessToken) { list.innerHTML = `<p class="empty">${escapeHtml(t("business.creatorTaskLogin"))}</p>`; return; }
    list.innerHTML = `<p class="empty">${escapeHtml(t("business.creatorTaskLoading"))}</p>`;
    try { const payload = await window.ZouBusinessApi.listCreatorServiceTasks(); render(payload?.items || []); }
    catch { list.innerHTML = `<p class="empty">${escapeHtml(t("business.creatorTaskUnavailable"))}</p>`; }
  };
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    button.disabled = true;
    try {
      if (button.dataset.confirmTask) await window.ZouBusinessApi.confirmCreatorServiceTask(button.dataset.confirmTask);
      if (button.dataset.consentTask) await window.ZouBusinessApi.grantCreatorServiceTaskConsent(button.dataset.consentTask);
      await load();
    } catch { button.disabled = false; }
  });
  load();
  window.addEventListener("zou-auth-session-changed", load);
})();
