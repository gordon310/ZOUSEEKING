const test = require("node:test");
const assert = require("node:assert/strict");
const recovery = require("../../web/js/auth-recovery.js");

test("uses the same password rule as registration", () => {
  assert.equal(recovery.isPasswordValid("a".repeat(7)), false);
  assert.equal(recovery.isPasswordValid("a".repeat(8)), true);
  assert.equal(recovery.isPasswordValid("a".repeat(128)), true);
  assert.equal(recovery.isPasswordValid("a".repeat(129)), false);
  assert.equal(recovery.isPasswordValid(`valid\u0007password`), false);
});

test("builds the recovery redirect from the current origin", () => {
  assert.equal(
    recovery.buildResetRedirectUrl("https://zoubeacon.app/"),
    "https://zoubeacon.app/reset-password.html",
  );
  assert.equal(
    recovery.buildResetRedirectUrl("https://platform.zoubeacon.com"),
    "https://platform.zoubeacon.com/reset-password.html",
  );
});

test("selects one success message for both known and unknown emails", () => {
  assert.equal(recovery.resetRequestResultMessage(), recovery.resetRequestResultMessage());
  assert.match(recovery.resetRequestResultMessage(), /注册|registered|enregistr|登録/);
});

test("maps transport failures to a neutral message", () => {
  assert.equal(recovery.resetRequestErrorMessage(new Error("user not found")), recovery.resetRequestErrorMessage(new Error("rate limit")));
});

test("classifies recovery session without requiring an email address", () => {
  assert.equal(recovery.classifyRecoverySession({ accessToken: "token", user: { id: "user-1" } }), "valid");
  assert.equal(recovery.classifyRecoverySession({ accessToken: "", user: null }), "invalid");
});
