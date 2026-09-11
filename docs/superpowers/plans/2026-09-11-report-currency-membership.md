# Report Currency and Membership Entitlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six-currency local pricing, report-scoped one-time purchases, and a minimal C Plus/B Data Pro subscription entitlement path.

**Architecture:** Keep Stripe provider objects unchanged. Resolve currency only from server-owned billing regions; persist a report identifier on one-time orders; make report access consult the matching paid order first, then an active subscription's UTC+8 monthly quota. Webhook processing remains the trusted writer for membership/profile and quota state.

**Tech Stack:** FastAPI, asyncpg/PostgreSQL, Stripe webhook adapter, vanilla JavaScript, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md` sections 4, 5, 9, and 10.

## Global Constraints

- Do not modify Stripe objects or print secrets.
- Do not edit `web/privacy.html` or `docs/legal/*`.
- Use a forward-only migration if a new column is required; do not execute migrations.
- Report ownership stays server-side and is keyed by `queries.query_key`.
- No automatic charging is introduced; cancellation is at period end.

### Task 1: Currency catalog and configuration

**Files:** `backend/app/billing/catalog.py`, `.env.example`, `deploy/.env.example`, `tests/billing/test_catalog.py`

- [ ] Add TWD/HKD/SGD price rows and TW/HK/SG/MO region mappings.
- [ ] Document 18 server price mappings without real IDs.
- [ ] Add failing and passing tests for values and regions.

### Task 2: Report-scoped one-time purchases

**Files:** `backend/app/main.py`, `backend/app/billing/service.py`, `backend/app/billing/routes.py`, `backend/app/billing/ports.py`, `backend/app/billing/store.py`, forward migration, backend/frontend tests.

- [ ] Add report identifier to the checkout request and payment metadata.
- [ ] Persist it on `payment_orders`; old null/user-scoped rows do not match.
- [ ] Change unlock queries to require the current report key.
- [ ] Update the locked/unlocked browser copy and request body in all locales.

### Task 3: Subscription entitlement and verification

**Files:** `backend/app/billing/store.py`, `backend/app/main.py`, tests, report.

- [ ] Add a UTC+8 monthly C Plus report quota path and membership/profile synchronization from webhook events.
- [ ] Make active subscription quota available before falling back to one-time purchase.
- [ ] Mark cancelled, past-due, failed, refunded, or expired subscriptions inactive for new access.
- [ ] Record the investigation table and exact verification commands in the task report.
