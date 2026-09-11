# [Superseded] Photo Recognition Privacy Disclosure Implementation Plan

> Superseded on 2026-09-11: the product decision changed to EXIF-only location prefill; listing-photo AI recognition is not launched.

> **For agentic workers:** This plan is executed inline in the current session; no commit or push is performed.

**Goal:** Disclose third-party OpenAI processing and require explicit consent before the listing-photo recognition request can be sent.

**Architecture:** Keep the existing `/api/recognition` request and prefill flow unchanged. Add localized disclosure and consent UI in the analysis page, enforce the consent gate in the recognition module before any network call, and document the verified persistence facts in both privacy-policy surfaces and the task report.

**Tech Stack:** Static HTML, vanilla ES modules, existing `web/js/i18n.js`, Playwright, Markdown.

**Spec:** `/tmp/zouseeking-privacy-disclosure-task.md`

## Global Constraints

- Do not modify backend business logic or `supabase/`.
- Do not claim OpenAI retention duration unless verified; mark unknown retention as unconfirmed.
- Preserve existing recognition and prefill behavior after consent.
- Do not execute `git commit` or `git push`.

### Task 1: Verify data retention and flow

**Files:** Read-only inspection of `backend/app/recognition/service.py`, `backend/app/recognition/routes.py`, and `/Users/gordonmac/GordonDev/JPPGSKILL/server/{api.mjs,openaiAnalysis.mjs,database.mjs}`.

- [x] Trace the request body from FastAPI to JPPGSKILL and OpenAI.
- [x] Check for logging, file writes, SQLite writes, and retention/deletion code.
- [ ] Record exact line evidence in the final report.

### Task 2: Update privacy disclosures

**Files:** Modify `web/privacy.html` and `docs/legal/privacy-policy.md`.

- [ ] Add a Chinese-only photo-recognition disclosure after the existing processing section, because `web/privacy.html` has no language switcher.
- [ ] State OpenAI third-party processing, US cross-border transfer, purpose/scope, verified non-persistence on the recognition path, unconfirmed provider retention, opt-out, and existing rights/contact path.
- [ ] Mark all new legal text as “待法务/负责人确认” and copy the same facts into both surfaces.

### Task 3: Add localized upload notice and consent gate

**Files:** Modify `web/property-analysis.html`, `web/js/recognition.js`, and `web/js/i18n.js`.

- [ ] Add localized notice, sensitive-image warning, and required consent checkbox.
- [ ] Disable the recognition button until consent is checked.
- [ ] Re-check consent inside `recognize()` before any fetch so a programmatic click cannot bypass the UI.
- [ ] Keep compression, POST body, result rendering, and prefill behavior unchanged.

### Task 4: Verify with browser tests and static checks

**Files:** Modify `tests/web/recognition.spec.js`; create the final task report under `docs/superpowers/reports/`.

- [ ] Add a failing Playwright assertion for no POST before consent and a passing assertion after consent.
- [ ] Run the focused browser test, existing related tests, static syntax checks, the required OpenAI grep, and `git status --short`.
- [ ] Report exact commands, results, evidence lines, privacy text, and any unverified retention facts.
