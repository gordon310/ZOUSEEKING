# Consumer launch page-to-API dependency graph

**Scope date:** 2026-09-26.  This is the evidence source for
`CONSUMER_LAUNCH_API_CONTRACT`, not a replacement for server authorization.

## Collection method and source-layout note

`web-source/**/*.html` has **zero files** in this checkout.  The readable
source tree contains JavaScript and CSS only; `scripts/build_web_static_assets.py:4-18`
copies/minifies those assets into `web/`.  The page/script inventory below
therefore reads the generated, read-only `web/*.html` files for script tags
(including their `?v=20260925-r64` cache key), while every call-site and
conditional judgement is taken from readable `web-source/` JavaScript.  This
is a source-layout discrepancy with the requested `web-source/**/*.html`
enumeration, recorded rather than silently papered over.

## Table 1 — page, scripts, and role

| Page(s) | Script `src` (version query omitted only in this column) | Role |
| --- | --- | --- |
| `admin.html` | `config.js`, `release-boundary.js`, `i18n.js`, `admin-mode.js`, `auth-session.js`, `admin-api-client.js`, `admin-views.js`, `admin.js` | back office |
| `analysis.html` | `config.js`, `auth-session.js`, `release-boundary.js`, `i18n.js`, `auth-recovery.js`, `app.js` | B |
| `billing.html` | `config.js`, `release-boundary.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |
| `consumer-home.html` | none | C |
| `data-query.html` | `config.js`, `auth-session.js`, `release-boundary.js`, `i18n.js`, `auth-recovery.js`, `record-location.js`, `app.js`, `business.js` | B |
| `exports.html` | `config.js`, `release-boundary.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |
| `index.html` | `config.js`, `auth-session.js`, `release-boundary.js`, `i18n.js`, `auth-recovery.js`, `business-api.js`, `record-location.js`, `app.js`, `business.js`, `pwa.js` | B |
| `invite.html` | `config.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |
| `mypage.html` | `config.js`, `auth-session.js`, `pwa.js`, `release-boundary.js`, `i18n.js`, `auth-recovery.js`, `business-api.js`, `record-location.js`, `app.js`, `service-tasks-consumer.js` | B |
| `organization.html` | `config.js`, `release-boundary.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |
| `privacy.html` | `i18n.js` | shared static |
| `profile.html` | `config.js`, `auth-session.js`, `release-boundary.js`, `i18n.js`, `auth-recovery.js`, `business-api.js`, `record-location.js`, `app.js`, `profile-role.js` | shared; C only with `?role=consumer` (`profile-role.js:2-6`), otherwise B |
| `project.html` | `pwa.js`, `project-workspace.js` | C |
| `projects.html` | `pwa.js`, `projects.js` | C |
| `property-analysis.html` | `config.js`, `auth-session.js`, `pwa.js`, `i18n.js`, `property-intake.js` (module), `recognition.js` (module) | C |
| `report.html` | `config.js`, `auth-session.js`, `pwa.js`, `i18n.js`, `report-page.js` (module) | C |
| `reset-password.html` | `config.js`, `pwa.js`, `i18n.js`, `auth-recovery.js`, `reset-password.js` | shared account recovery |
| `service-tasks.html` | `config.js`, `release-boundary.js`, `auth-session.js`, `business-api.js`, `i18n.js`, `business-pages.js` | B |
| `subscriptions.html` | `config.js`, `release-boundary.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |
| `support.html` | none | shared static |
| `terms.html` | none | shared static |
| `ui-review.html` | none | shared review |
| `usage.html` | `config.js`, `release-boundary.js`, `i18n.js`, `auth-session.js`, `business-api.js`, `business-pages.js` | B |

Every listed generated page uses the `?v=20260925-r64` query string shown in
its HTML; the inventory intentionally normalizes it away from the table.

## Table 2 — normalized API calls and reachability

| API | Trigger page / condition and evidence | Attribution |
| --- | --- | --- |
| `POST /api/intake/sessions` | C `property-analysis.html`; submit event → `createSession`, `property-intake.js:808-857`, client `api-client.js:47-50` | C reachable |
| `POST /api/intake/sessions/{session_id}/inputs` | C intake submit when source text/URL is nonempty, `property-intake.js:852-854`; `api-client.js:56-60` | C reachable |
| `POST /api/intake/sessions/{session_id}/files` | C intake submit when files/photos exist, `property-intake.js:856-857`; `api-client.js:69-82` | C reachable |
| `PUT /api/intake/sessions/{session_id}/location` | C intake client export, `api-client.js:99-103`; current UI uses it only through the intake flow | C reachable |
| `PUT /api/intake/sessions/{session_id}/fields/{field_name}` | C preview event loops confirmed fields, `property-intake.js:900-928`; `api-client.js:88-96` | C reachable |
| `POST /api/intake/sessions/{session_id}/preview` | C preview submit after authenticated token, `property-intake.js:878-942`; `api-client.js:107-111` | C reachable |
| `POST /api/intake/sessions/{session_id}/convert` | C save-project button after login, `property-intake.js:945-1037`; `api-client.js:115-125` | C reachable |
| `POST /api/recognition` | C photo input change only, `recognition.js:48-75` | C reachable |
| `GET /api/reports/{query_key}` | C `report.html` initialization/polling, `report-page.js:170-188,213-233` | C reachable |
| `GET /api/reports/{query_key}/download` | C unlocked-report download-button event, `report-page.js:67-98` | C reachable |
| `GET /api/billing/prices` | C report paywall only after authenticated report is locked, `report-page.js:121-150` | C reachable |
| `POST /api/billing/checkout` | C report unlock click, `report-page.js:153-168` | C reachable |
| `POST /api/auth/invite-register` | C account registration submit; `profile.html?role=consumer` swaps the visible surface at `profile-role.js:2-48`; request is `app.js:1999-2035` | C reachable |
| `GET /api/me` | C account entitlement view after authenticated profile render, `app.js:942-960`; same shared script is loaded by `profile.html?role=consumer` | C reachable |
| `GET /api/my/queries` | shared account loader is called by `app.js:2254-2292`; C consumer profile loads it and its authenticated backend branch is `app.js:847-867` | C reachable |
| `POST /api/account/deletion-request` | C profile confirmation button, `app.js:1031-1062,2330-2335` | C reachable |
| `POST /api/query` | task-mandated C key path; shared query handler calls it only after authenticated-backend check, `app.js:1735-1777,1780-1793`. The currently generated form is `data-query.html` (B), so this inclusion is an explicit launch requirement rather than independent C-page DOM evidence. | C reachable (required exception) |
| `GET /api/jobs/{job_id}` | paired polling path for task-mandated query route, `app.js:1763-1775` | C reachable (required exception) |
| `POST /api/billing/webhook` | mandatory contract item; browser graph has no caller, as expected for provider webhook | C reachable (mandatory) |
| `POST /api/analysis` | B `analysis.html` form → `loadAnalysis`, `app.js:1280-1307,2336-2339` | B only |
| `POST /api/jobs/{query_id}/run` | B my-page action, `app.js:1310-1342` | B only |
| `GET /api/org/region-stats` | B `data-query.html` `#regionStatsForm`; endpoint branch `app.js:1926-1947` | B only |
| `GET /api/org/region-stats/trend` | same B form, selected trend mode at `app.js:1929-1939` | B only |
| `GET /api/org/me` | B billing/organization/usage/export initial loads, `business-pages.js:81-149,172,229,353` via `business-api.js:33` | B only |
| `GET /api/org/usage` | B usage/export organization mode, `business-pages.js:229,367`; `business-api.js:34` | B only |
| `GET /api/org/billing` | B billing page, `business-pages.js:172-218`; `business-api.js:35` | B only |
| `GET /api/org/members` | B organization page, `business-pages.js:81-149`; `business-api.js:36` | B only |
| `POST /api/org/invitations` | B organization invite form, `business-pages.js:131-141`; `business-api.js:37` | B only |
| `GET /api/org/invitations` | B manager organization view, `business-pages.js:118-129`; `business-api.js:38` | B only |
| `POST /api/org/invitations/{invitation_id}/revoke` | B organization pending-invite button, `business-pages.js:123-126`; `business-api.js:39` | B only |
| `POST /api/org/invitations/accept` | B invite-page button, `business-pages.js:151-157`; `business-api.js:40` | B only |
| `GET /api/org/service-tasks` | B service task page, `business-api.js:41` | B only |
| `POST /api/org/service-tasks/{task_id}/apply` | B service task action, `business-api.js:45` | B only |
| `POST /api/org/service-tasks/{task_id}/withdraw` | B service task action, `business-api.js:46` | B only |
| `POST /api/org/service-tasks/{task_id}/consent` | B service task action, `business-api.js:47` | B only |
| `POST /api/org/service-tasks/{task_id}/complete` | B service task action, `business-api.js:48` | B only |
| `GET /api/service/tasks` | B `mypage.html` creator task loader, `service-tasks-consumer.js:30-47`; `business-api.js:42` | B only |
| `POST /api/service/tasks/{task_id}/consent` | B creator task button, `service-tasks-consumer.js:36-44`; `business-api.js:43` | B only |
| `POST /api/service/tasks/{task_id}/confirm-completion` | B creator task button, `service-tasks-consumer.js:36-44`; `business-api.js:44` | B only |
| `GET /api/exports`, `POST /api/exports`, `GET /api/exports/{export_id}` | B export page list/create/download, `business-pages.js:285-388`; client `business-api.js:49-57` | B only |
| `GET /api/org/exports`, `POST /api/org/exports`, `GET /api/org/exports/{export_id}` | B export page only after organization-mode check, `business-pages.js:353-376`; client `business-api.js:59-67` | B only |
| `GET /api/admin/pricing` | `admin.html`; `admin-api-client.js:87-89` | back office |
| `POST /api/admin/pricing/prices` | `admin.html`; `admin-api-client.js:93-95` | back office |
| `POST /api/admin/pricing/prices/{price_id}/status` | `admin.html`; `admin-api-client.js:96-98` | back office |
| `POST /api/admin/pricing/regions` | `admin.html`; `admin-api-client.js:99-101` | back office |
| `POST /api/admin/pricing/plans` | `admin.html`; `admin-api-client.js:102-104` | back office |
| `POST /api/admin/pricing/entitlements` | `admin.html`; `admin-api-client.js:105-107` | back office |
| `GET /api/admin/invite-codes` | `admin.html`; `admin-api-client.js:90` | back office |
| `POST /api/admin/invite-codes` | `admin.html`; `admin-api-client.js:91` | back office |
| `POST /api/admin/invite-codes/{invite_code_id}/status` | `admin.html`; `admin-api-client.js:92` | back office |
| `GET /api/admin/members` | `admin.html`; `admin-api-client.js:108-111` | back office |
| `GET /api/admin/members/{user_id}` | `admin.html`; `admin-api-client.js:112-115` | back office |
| `POST /api/admin/members/{user_id}/status` | `admin.html`; `admin-api-client.js:116-123` | back office |
| `POST /api/admin/members/{user_id}/audience` | `admin.html`; `admin-api-client.js:124-129` | back office |
| `GET /api/admin/audit` | `admin.html`; `admin-api-client.js:130-133` | back office |
| `GET /api/admin/finance/orders` | `admin.html`; `admin-api-client.js:134-137` | back office |
| `GET /api/admin/finance/refunds` | `admin.html`; `admin-api-client.js:138-141` | back office |
| `GET /api/admin/collection/runs` | `admin.html`; `admin-api-client.js:142-148` | back office |
| `POST /api/admin/collection/runs` | `admin.html`; `admin-api-client.js:159-165` | back office |
| `GET /api/admin/overview` | `admin.html`; `admin-api-client.js:149-152` | back office |
| `GET /api/admin/service/tasks` | `admin.html`; `admin-api-client.js:153-158` | back office |
| `GET /api/admin/internal/me` | `admin.html`; `admin-api-client.js:166-169` | back office |
| `GET /api/admin/internal/roles` | `admin.html`; `admin-api-client.js:170-173` | back office |
| `POST /api/admin/internal/roles` | `admin.html`; `admin-api-client.js:174-180` | back office |
| `DELETE /api/admin/internal/roles/{user_id}/{role}` | `admin.html`; `admin-api-client.js:181-186` | back office |
| `POST /api/admin/organizations` | legacy 42-entry baseline admin member; retained for `admin.html` back-office scope though no current client call | back office |
| `POST /api/admin/service/tasks` | legacy 42-entry baseline admin member; retained for `admin.html` back-office scope though no current client call | back office |
| `POST /api/admin/service/tasks/{task_id}/status` | legacy 42-entry baseline admin member; retained for `admin.html` back-office scope though no current client call | back office |

The three `admin.html` API scripts (`admin-api-client.js`, `admin.js`, and
`admin-views.js`) yield only the 24 `/api/admin/*` source calls listed above;
there are no non-`/api/admin/*` calls to add to the back-office required set.

`GET/POST /api/exports*`, `POST /api/analysis`, `GET /api/usage/summary`,
the organization invitation/service-task group, and the B-only analysis/job
run paths were removed from the old 42-entry baseline.  `GET /api/usage/summary`
is invoked by B `business-pages.js:229,353`; it has no C trigger.

## Shared-script condition analysis

* `app.js` is shared.  Its B region-statistics request is not an initializer:
  it runs only from `loadRegionStats()` (`app.js:1926-1947`) after the
  document submit listener recognizes `#regionStatsForm` (`app.js:2261-2263`).
  That form exists on `data-query.html`, not C pages.
* The B analysis call is conditioned twice: `loadAnalysis()` requires an
  authenticated backend (`app.js:1280-1285`) and is bound only to
  `#analysisForm` (`app.js:2336-2339`), whose panel belongs to
  `analysis.html`.
* The C profile route is runtime-selected: `profile-role.js:2-6` exits unless
  `?role=consumer`, then rewrites the body role and navigation (`:17-48`).
  The shared `app.js` entitlement request is additionally protected by both
  the target DOM and `ZouBusinessApi.hasToken()` (`app.js:942-951`), so it is
  reachable from that C profile route but not anonymously or on pages without
  the profile target.

## UNCERTAIN

None.  The one mixed-evidence item is explicitly labelled in table 2:
`POST /api/query` and its job polling are included because the task requires
them to be launch-critical, while the current page inventory only exposes the
query form on B `data-query.html`.  This is a recorded contract exception,
not an unclassified endpoint.
