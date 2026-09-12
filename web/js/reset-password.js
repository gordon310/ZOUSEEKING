(() => {
  const config = {
    supabaseUrl: (window.ZOUSEEKING_SUPABASE_URL || "").replace(/\/$/, ""),
    anonKey: window.ZOUSEEKING_SUPABASE_ANON_KEY || "",
  };
  const api = window.ZouAuthRecovery?.createAuthApi?.(config);
  let recoverySession = null;

  const $ = (selector) => document.querySelector(selector);
  const t = (key, fallback) => window.ZouI18n?.t(key, fallback) || fallback;

  function status(message, tone = "") {
    const element = $("#resetStatus");
    element.textContent = message;
    element.className = `form-message ${tone}`;
  }

  function showInvalid() {
    $("#resetPasswordForm").classList.add("hidden");
    $("#resetInvalidState").hidden = false;
    $("#resetSuccessState").hidden = true;
    status(t("account.resetInvalidLink", "链接已失效，请重新申请。"), "error");
  }

  function showForm() {
    $("#resetPasswordForm").classList.remove("hidden");
    $("#resetInvalidState").hidden = true;
    $("#resetSuccessState").hidden = true;
    status("");
  }

  async function loadRecoverySession() {
    if (!api) return showInvalid();
    try {
      recoverySession = await api.establishRecoverySession(window.location);
      if (!recoverySession || window.ZouAuthRecovery.classifyRecoverySession(recoverySession) !== "valid") return showInvalid();
      history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      showForm();
    } catch {
      showInvalid();
    }
  }

  async function updatePassword(event) {
    event.preventDefault();
    const password = $("#resetNewPassword").value;
    const confirmation = $("#resetConfirmPassword").value;
    const button = $("#resetPasswordForm button[type='submit']");
    if (!window.ZouAuthRecovery.isPasswordValid(password)) {
      status(t("account.resetPasswordInvalid", "密码需为 12–128 位，且不能包含控制字符。"), "error");
      return;
    }
    if (password !== confirmation) {
      status(t("account.resetPasswordMismatch", "两次输入的密码不一致。"), "error");
      return;
    }
    button.disabled = true;
    status(t("account.resetUpdating", "正在更新密码……"));
    try {
      await api.updateUser({ password }, recoverySession.accessToken);
      $("#resetPasswordForm").reset();
      $("#resetPasswordForm").classList.add("hidden");
      $("#resetSuccessState").hidden = false;
      status(t("account.resetSuccess", "密码已更新"), "success");
    } catch {
      status(t("account.resetUpdateFailed", "密码更新未完成，请重新打开有效链接后再试。"), "error");
    } finally {
      button.disabled = false;
    }
  }

  document.body.classList.remove("auth-pending");
  $("#resetPasswordForm").addEventListener("submit", updatePassword);
  loadRecoverySession();
})();
