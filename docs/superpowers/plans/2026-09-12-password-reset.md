# Password Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the C-end forgot-password email flow and recovery password update page without changing backend business logic.

**Architecture:** Keep the repository's existing Supabase Auth REST transport in `web/app.js`, but move password-reset-specific pure decisions and endpoint construction into a small browser-safe adapter. The five existing account pages use the adapter for the anti-enumeration request; `reset-password.html` uses the same adapter to establish the recovery session from Supabase's redirect response and update the password.

**Tech Stack:** Static HTML/CSS, browser JavaScript, Supabase Auth REST API, Node built-in test runner, Playwright contract tests.

**Spec:** `/tmp/zouseeking-password-reset-task.md`

## Global Constraints

- Use the existing Supabase Auth configuration and REST transport; do not add backend business logic, migrations, or disable email confirmation.
- Construct every recovery redirect from `window.location.origin` and `reset-password.html`; never hard-code a deployment domain.
- Return the same success copy for existing and non-existing email addresses; map transport failures to neutral copy.
- Reuse the existing 12–128 character password rule and control-character rejection.
- Keep four locale dictionaries key-identical; do not use test/demo wording in user-facing copy.
- Do not commit or push.

### Task 1: Pure password-recovery contract

**Files:**
- Create: `web/js/auth-recovery.js`
- Test: `tests/unit/auth-recovery.test.js`

- [ ] Write tests first for password validation, reset redirect construction, anti-enumeration copy selection, recovery-session classification, and neutral error mapping.
- [ ] Run `node --test tests/unit/auth-recovery.test.js` and confirm the missing-module failure.
- [ ] Implement the minimal browser/CommonJS-compatible pure functions and REST adapter contracts.
- [ ] Run the focused test and then the existing unit tests.

### Task 2: Wire request flow into account pages

**Files:**
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/mypage.html`
- Modify: `web/profile.html`
- Modify: `web/analysis.html`
- Modify: `web/data-query.html`
- Modify: `web/js/i18n.js`
- Test: `tests/web/password-reset.spec.js`

- [ ] Use the adapter for the current-origin `reset-password.html` redirect and the existing `/auth/v1/recover` transport.
- [ ] Keep the email-existence-independent success path and disable the submit button while sending.
- [ ] Add all reset/request/status keys to all four dictionaries and include the shared adapter before `app.js`.
- [ ] Add browser coverage for all five entry pages, form switching, redirect construction, disabled submission, and neutral failure copy.

### Task 3: Add recovery destination page

**Files:**
- Create: `web/reset-password.html`
- Create: `web/js/reset-password.js`
- Test: `tests/web/password-reset.spec.js`

- [ ] Add the report-style PWA head, locale switcher, labeled new/confirm password fields, status region, and login-entry link.
- [ ] Use the existing Auth REST session response as the recovery equivalent of an Auth state event; do not expose or store raw recovery tokens beyond the established session handoff.
- [ ] Render valid-session form, invalid/expired link state, neutral update failure, and explicit success with a login link.
- [ ] Test no-session, valid-session, mismatched/weak password, successful update, and failure paths with mocked Auth requests.

### Task 4: Verification and report evidence

- [ ] Run `node --check` on every changed JS file.
- [ ] Run focused Node and Playwright tests plus the repository offline checks that are available.
- [ ] Compare all four i18n key sets and record counts/results.
- [ ] Inspect `git status --short`, list changed files, and explicitly record that real SMTP delivery was not verified unless evidence exists.
