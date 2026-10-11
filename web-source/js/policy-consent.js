(() => {
  let checking = false;
  let dialog;
  let generation = 0;
  const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;
  const session = () => window.ZouAuthSession?.read?.();

  let activeUserId = session()?.userId;

  async function request(method, payload, userId) {
    if (!userId || session()?.userId !== userId) throw new Error("account changed");
    const token = await window.ZouAuthSession?.getValidAccessToken?.();
    if (!token || session()?.userId !== userId) throw new Error("session unavailable");
    const response = await fetch(`${String(window.ZOUSEEKING_API_BASE_URL || "").replace(/\/$/, "")}/api/account/consent`, {
      method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(payload ? { body: JSON.stringify(payload) } : {}), cache: "no-store",
    });
    if (!response.ok) throw new Error("confirmation unavailable");
    const receipt = await response.json();
    if (session()?.userId !== userId) throw new Error("account changed");
    return receipt;
  }

  function show(policy, unavailable = false, userId, version) {
    if (dialog?.open) return;
    dialog?.remove();
    const previousFocus = document.activeElement;
    dialog = document.createElement("dialog");
    dialog.id = "policyConsentDialog";
    dialog.setAttribute("aria-labelledby", "policyConsentTitle");
    const form = document.createElement("form");
    const title = document.createElement("h2");
    title.id = "policyConsentTitle";
    title.textContent = t("policy.confirmTitle", "プライバシーポリシーの更新");
    const copy = document.createElement("p");
    copy.textContent = t("policy.confirmCopy", "利用を続ける前に、更新内容を確認して同意してください。");
    const link = document.createElement("a");
    link.href = "privacy.html"; link.target = "_blank"; link.rel = "noopener";
    link.textContent = t("account.privacyPolicy", "プライバシーポリシー");
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox"; checkbox.required = true;
    label.append(checkbox, document.createTextNode(t("policy.accept", "更新されたポリシーと利用規約に同意します。")));
    const terms = document.createElement("a");
    terms.href = "terms.html"; terms.target = "_blank"; terms.rel = "noopener";
    terms.textContent = t("account.terms", "利用規約");
    const status = document.createElement("p"); status.setAttribute("role", "status");
    const submit = document.createElement("button"); submit.type = "submit"; submit.disabled = true;
    submit.textContent = t("policy.continue", "同意して続ける");
    checkbox.addEventListener("change", () => { submit.disabled = !checkbox.checked || unavailable; });
    const retry = document.createElement("button"); retry.type = "button";
    retry.textContent = t("policy.retry", "再試行"); retry.hidden = !unavailable;
    retry.addEventListener("click", () => { dialog.close(); ensure(); });
    const logout = document.createElement("button"); logout.type = "button";
    logout.textContent = t("nav.logout", "ログアウト");
    const decline = () => { window.ZouAuthSession?.write?.(null); dialog?.close(); window.location.assign("consumer-home.html"); };
    logout.addEventListener("click", decline);
    dialog.addEventListener("cancel", event => { event.preventDefault(); decline(); });
    dialog.addEventListener("close", () => previousFocus?.focus?.());
    if (unavailable) status.textContent = t("policy.unavailable", "確認サービスを利用できません。再試行してください。");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (!checkbox.checked || unavailable) return;
      submit.disabled = true;
      try {
        const receipt = await request("POST", { privacy_policy_version: policy.privacy_policy_version, terms_version: policy.terms_version }, userId);
        if (version !== generation) return;
        if (!receipt.accepted) throw new Error("confirmation not recorded");
        dialog.close();
      } catch {
        status.textContent = t("policy.unavailable", "確認サービスを利用できません。再試行してください。");
        submit.disabled = false;
      }
    });
    const support = document.createElement("a");
    support.href = "support.html";
    support.textContent = t("account.support", "サポート・個人情報の請求");
    form.append(title, copy, link, terms, label, status, submit, retry, logout, support);
    const deletion = document.querySelector("#openDeleteAccountButton");
    if (deletion) {
      const deleteButton = document.createElement("button"); deleteButton.type = "button";
      deleteButton.textContent = t("account.deleteSubmit", "削除を申請");
      deleteButton.addEventListener("click", () => { dialog.close(); deletion.click(); });
      form.append(deleteButton);
    }
    dialog.append(form); document.body.append(dialog); dialog.showModal();
  }

  async function ensure() {
    if (checking || dialog?.open || session()?.provider !== "supabase") return;
    const userId = session()?.userId;
    const version = generation;
    checking = true;
    try {
      const policy = await request("GET", undefined, userId);
      if (version === generation && !policy.accepted) show(policy, false, userId, version);
    } catch {
      if (version === generation && session()?.provider === "supabase") show(null, true, userId, version);
    } finally { if (version === generation) checking = false; }
  }
  window.addEventListener("zou-auth-session-changed", () => {
    const userId = session()?.userId;
    if (userId !== activeUserId) {
      activeUserId = userId;
      generation += 1;
      checking = false;
      dialog?.close(); dialog?.remove(); dialog = undefined;
    }
    ensure();
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ensure);
  else ensure();
})();
