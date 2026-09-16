# Registration and Self-Contained HTML Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove false email-confirmation registration states and deliver unlocked paid reports as authenticated, owner-scoped, self-contained HTML downloads.

**Architecture:** Keep Supabase Auth as the registration/session authority. Add a small standard-library HTML renderer beside the existing report access helpers, and expose it through a `require_user`-protected owner/unlock route. The report page keeps its existing paywall and replaces unlocked detail rendering with one download action.

**Tech Stack:** FastAPI, asyncpg-compatible repository seams, Python standard library HTML escaping, vanilla browser JavaScript, Playwright, pytest.

**Spec:** `/tmp/zouseeking-html-download-task.md`

## Global Constraints

- No email confirmation is presented as required; successful registration must enter the logged-in state.
- Download access requires authentication, report ownership, and an unlocked entitlement.
- Locked responses never include report正文 fields.
- Download output is one HTML file with inline CSS and no external resource URLs.
- No new dependencies; no commit, push, deployment, SSH, or append-only `usage_events` writes.
- Run the requested full Python and web suites, `git diff --check`, and record real counts and request evidence in `/tmp/zouseeking-html-download-details.md`.

### Task 1: Backend download contract

**Files:**
- Modify: `backend/app/main.py`
- Test: `tests/api/test_report_access.py`

**Interfaces:**
- Produces `GET /api/reports/{query_key}/download` with structured errors, attachment headers, and rendered HTML.
- Keeps `row_to_report` and the locked allow-list as the source for business report values.

- [ ] Write tests for anonymous 401, locked 403 without deep fields, unlocked 200 self-contained HTML, and non-owner 404.
- [ ] Run the focused tests and observe failures caused by the missing route/renderer.
- [ ] Implement escaped HTML rendering using business labels, numeric JPY units, source periods, limitations, and print CSS.
- [ ] Implement owner/unlock checks without writing usage events.
- [ ] Run focused backend tests and the existing report-access tests.

### Task 2: Registration copy and failure mapping

**Files:**
- Modify: `web/app.js`
- Modify: `web/js/i18n.js`
- Modify: `tests/web/signup-flow.spec.js`

**Interfaces:**
- Registration with a valid Supabase session always saves the session and renders logged-in state.
- Missing session and known Auth errors produce honest, reason-specific messages; no confirmation-email pending branch remains.

- [ ] Update the web test that currently expects a pending email state to expect an honest failure.
- [ ] Run the signup spec to observe the old behavior fail the new contract.
- [ ] Remove the pending branch and map invalid password, duplicate email, network/service, and invalid session responses.
- [ ] Replace the four `account.registerPending` translations with non-confirmation copy or remove the key consistently.
- [ ] Run signup and i18n unit tests.

### Task 3: Single download action in the report page

**Files:**
- Modify: `web/report.html`
- Modify: `web/js/report-page.js`
- Modify: `web/js/report-page-core.js`
- Modify: `web/report-page.css`
- Modify: `tests/web/report-paywall.spec.js`

**Interfaces:**
- Unlocked reports expose exactly one primary action, `下载报告`, which sends the current access token and downloads the attachment.
- Locked reports expose only login or unlock; insufficient-data reports expose no payment/download action.

- [ ] Add/update Playwright assertions for one unlocked download action and Authorization on the request.
- [ ] Run the focused web spec and observe the old unlocked detail behavior fail.
- [ ] Implement token-bearing download and browser attachment handling, preserving the existing checkout flow.
- [ ] Keep four-language labels synchronized and add accessible button text.
- [ ] Run the focused web spec.

### Task 4: Verification and evidence report

**Files:**
- Create: `/tmp/zouseeking-html-download-details.md`

- [ ] Run all Python tests and capture exact passed/failed numbers.
- [ ] Run `npm run test:web -- --workers=1` and capture exact passed/failed numbers.
- [ ] Run request-level checks for locked, unlocked, and anonymous downloads, recording status, response summary, headers, and HTML excerpt.
- [ ] Run `git diff --check` and list any `NOT_EXECUTED` commands.
- [ ] Write the detailed evidence report without modifying generated content or committing changes.
