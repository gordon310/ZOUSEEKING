# Property Photo Location and Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add consent-driven house-photo geolocation, server-mediated address suggestions, and owner-scoped duplicate-aware investigation naming to the existing property intake flow.

**Architecture:** Keep the existing FastAPI intake path authoritative. The browser captures photos and device coordinates only after explicit user actions; FastAPI stores numeric location metadata and calls a small standard-library reverse-geocoder adapter. The server supplies the default project name from the confirmed address, performs owner-scoped duplicate checks inside the conversion transaction, and returns stable business errors for manual correction.

**Tech Stack:** Static HTML/CSS/ES modules, FastAPI, Pydantic v2, asyncpg/PostgreSQL, Supabase forward migrations, Python standard-library `urllib`, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-property-photo-location-design.md`

## Global Constraints

- Do not call geolocation or send coordinates before the user explicitly activates the location action and grants browser permission.
- Treat the reverse-geocoded value as a candidate address; require user confirmation/editing and never infer an exact building or room number.
- Keep the FastAPI intake route authoritative; do not extend the competing Edge Function or legacy regional-query path.
- Store latitude, longitude, accuracy, and timestamps as numeric/timestamp fields with provenance; do not calculate from presentation strings.
- Scope duplicate checks and saved projects by authenticated `user_id`; never accept `owner_user_id` from the browser.
- Add only forward migrations; do not apply live database, authentication, RLS, Storage, or deployment changes in this task.
- Preserve the existing ZOUBEACON visual system, accessible labels/focus states, mobile layout, and synthetic demo behavior.

---

### Task 1: Define and test the location/geocoder contracts

**Files:**
- Create: `backend/app/intake/geocoding.py`
- Modify: `backend/app/intake/models.py`
- Create: `tests/unit/test_intake_geocoding.py`
- Modify: `tests/unit/test_intake_models.py`

**Interfaces:**
- Produces `LocationRequest`, `LocationResponse`, `AddressCandidate`, `ReverseGeocoderError`, `parse_gsi_response()`, and `GsiReverseGeocoder.reverse_geocode()` for the route and repository.
- `LocationRequest` accepts only finite `latitude`, `longitude`, positive bounded `accuracy_m`, timezone-aware `captured_at`, `consent_version`, and `source="device_geolocation"`.
- `parse_gsi_response(payload)` returns an `AddressCandidate` with `address`, `source="gsi_reverse_geocoder"`, and `precision="town"`, or raises `ReverseGeocoderError` when the untrusted response has no usable town name.

- [ ] **Step 1: Write failing validation and parser tests**

```python
def test_location_request_rejects_out_of_range_or_naive_values():
    with pytest.raises(ValidationError):
        LocationRequest(
            latitude=91,
            longitude=135,
            accuracy_m=10,
            captured_at="2026-08-28T03:30:00Z",
            consent_version="location-2026-08",
        )
    with pytest.raises(ValidationError):
        LocationRequest(
            latitude=34.7,
            longitude=135.4,
            accuracy_m=0,
            captured_at="2026-08-28T03:30:00",
            consent_version="location-2026-08",
        )


def test_gsi_response_returns_town_candidate_only():
    candidate = parse_gsi_response({"results": {"muniCd": "27127", "lv01Nm": "大阪府大阪市北区梅田"}})
    assert candidate.address == "大阪府大阪市北区梅田"
    assert candidate.source == "gsi_reverse_geocoder"
    assert candidate.precision == "town"


def test_gsi_response_without_address_is_rejected():
    with pytest.raises(ReverseGeocoderError):
        parse_gsi_response({"results": {"muniCd": "27127", "lv01Nm": ""}})
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/unit/test_intake_geocoding.py tests/unit/test_intake_models.py`

Expected: FAIL because the location model and geocoder module do not exist.

- [ ] **Step 3: Implement strict models and the standard-library GSI adapter**

Implement the exact request/response fields from the spec. Build the URL with `urllib.parse.urlencode`, use `urllib.request.urlopen` with a short configurable timeout, parse only the expected `results` object, cap the returned address length, and convert all network/JSON/provider errors into `ReverseGeocoderError` without exposing raw response text. Use `REVERSE_GEOCODER_URL` and `REVERSE_GEOCODER_TIMEOUT_SECONDS` environment values with the official GSI endpoint and a bounded default timeout.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest -q tests/unit/test_intake_geocoding.py tests/unit/test_intake_models.py`

Expected: PASS, including existing intake model regression tests.

- [ ] **Step 5: Commit the contract unit**

```bash
git add backend/app/intake/geocoding.py backend/app/intake/models.py tests/unit/test_intake_geocoding.py tests/unit/test_intake_models.py
git commit -m "feat: define property location intake contracts"
```

### Task 2: Persist location metadata and enforce duplicate-aware conversion

**Files:**
- Create: `supabase/migrations/20260828000100_property_photo_location.sql`
- Modify: `backend/app/intake/repository.py`
- Modify: `backend/app/routes/intake.py`
- Modify: `backend/README.md`
- Modify: `tests/api/conftest.py`
- Modify: `tests/api/test_intake_routes.py`
- Modify: `tests/unit/test_intake_repository.py`
- Modify: `tests/sql/test_property_intake_schema.sql`

**Interfaces:**
- `IntakeRepository.save_location(session_id, request, candidate)` updates the editable session and returns the saved location row.
- `IntakeRepository.convert_to_user(session_id, token_hash, user_id, project_name=None)` remains idempotent for the same owner, rejects missing names, raises `DuplicateAddress` or `ProjectNameTaken`, and inserts the session location/provenance into `public.properties`.
- `PUT /api/intake/sessions/{session_id}/location` returns a `LocationResponse`, stores coordinates even when reverse geocoding is unavailable, and applies a session-scoped rate limit.
- `POST /api/intake/sessions/{session_id}/convert` accepts an optional strict `project_name` body and maps domain conflicts to stable JSON `{detail: {code, message}}` errors.

- [ ] **Step 1: Add failing route, repository, and SQL assertions**

```python
def test_location_endpoint_returns_candidate_and_saves_coordinates(client, session, fake_repository, monkeypatch):
    fake_repository.reverse_geocoder_result = AddressCandidate(
        address="大阪府大阪市北区梅田", source="gsi_reverse_geocoder", precision="town"
    )
    response = client.put(
        f"/api/intake/sessions/{session['session_id']}/location",
        headers={"X-Analysis-Session": session["session_token"]},
        json={
            "latitude": 34.7025,
            "longitude": 135.4959,
            "accuracy_m": 18.5,
            "captured_at": "2026-08-28T03:30:00Z",
            "consent_version": "location-2026-08",
            "source": "device_geolocation",
        },
    )
    assert response.status_code == 200
    assert response.json()["address_candidate"] == "大阪府大阪市北区梅田"
    assert fake_repository.sessions[session["session_id"]]["latitude"] == 34.7025


def test_duplicate_address_requires_manual_project_name(client, session, auth_header, fake_repository):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    fake_repository.duplicate_address = True
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_address"
```

Add SQL checks for `project_name`, numeric location columns, address provenance, the session location columns, and the partial owner/name uniqueness index. Keep the existing RLS/private-table assertions.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest -q tests/api/test_intake_routes.py tests/unit/test_intake_repository.py`

Expected: FAIL because the endpoint, repository methods, and domain errors are absent. The SQL assertion should fail against a database that has only the previous intake migration.

- [ ] **Step 3: Add the forward migration**

Add the fields and range checks to `analysis_sessions` and `properties`; add `idx_properties_owner_address` and a partial unique index on `(owner_user_id, project_name)` when `project_name <> ''`. Use idempotent `alter table ... add column if not exists` and guarded constraints, and keep `owner_user_id`/RLS unchanged. Do not edit `20260825000400_property_intake.sql`.

- [ ] **Step 4: Implement repository conversion and location persistence**

Lock the session before conversion. Normalize confirmed addresses with Unicode normalization and collapsed whitespace. If the same owner already has the normalized address and no genuinely different manual name was supplied, raise `DuplicateAddress`; if the final name is already used, raise `ProjectNameTaken`. Insert `project_name`, canonical numeric coordinates, accuracy, source, timestamp, and address source in the same transaction as the property and residential detail. Keep domain errors free of database exception strings.

- [ ] **Step 5: Implement the FastAPI location and conversion boundaries**

Call the reverse geocoder in `asyncio.to_thread`; on `ReverseGeocoderError`, save the coordinate row with `address_source="unavailable"` and return a manual-fallback response. Validate the session before both location and conversion. Preserve the existing anonymous-session rate limiting and map errors to 422/409 without leaking provider or database details. Update the fake repository and test fixtures to exercise owner scoping and idempotent conversion.

- [ ] **Step 6: Run the focused tests and verify they pass**

Run: `pytest -q tests/api/test_intake_routes.py tests/unit/test_intake_repository.py tests/unit/test_intake_geocoding.py tests/unit/test_intake_models.py`

Expected: PASS. Do not claim the SQL test passed unless a disposable PostgreSQL/Supabase database is configured; otherwise report it as not run.

- [ ] **Step 7: Commit the backend unit**

```bash
git add supabase/migrations/20260828000100_property_photo_location.sql backend/app/intake/repository.py backend/app/routes/intake.py backend/README.md tests/api/conftest.py tests/api/test_intake_routes.py tests/unit/test_intake_repository.py tests/sql/test_property_intake_schema.sql
git commit -m "feat: persist photo locations and guard project naming"
```

### Task 3: Add camera, consent, address confirmation, and duplicate-name UI

**Files:**
- Modify: `web/js/api-client.js`
- Modify: `web/js/property-intake.js`
- Modify: `web/property-analysis.html`
- Modify: `web/property-analysis.css`
- Modify: `tests/web/property-intake.spec.js`

**Interfaces:**
- `saveLocation(sessionId, sessionToken, payload)` calls the new location endpoint.
- `confirmField(..., options)` can pass the address evidence locator without changing existing callers.
- `convertSession(sessionId, sessionToken, accessToken, projectName)` sends only the optional project name; it exposes `error.status`, `error.code`, and `error.payload` for duplicate handling.

- [ ] **Step 1: Write failing browser tests for the agreed flow**

```javascript
test("photo capture requests location and fills a candidate address", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = (success) => success({
      coords: { latitude: 34.7025, longitude: 135.4959, accuracy: 18.5 },
      timestamp: Date.parse("2026-08-28T03:30:00Z"),
    });
  });
  await page.goto("/property-analysis.html");
  await page.setInputFiles("#propertyPhotos", {
    name: "house.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("photo"),
  });
  await page.getByRole("button", { name: "获取照片位置并生成地址" }).click();
  await expect(page.getByTestId("location-candidate")).toHaveText("大阪府大阪市北区梅田");
  await expect(page.getByLabel("完整地址")).toHaveValue("大阪府大阪市北区梅田");
});


test("duplicate address focuses manual investigation name", async ({ page }) => {
  // Mock the existing intake routes, including a 409 detail.code=duplicate_address.
  await page.goto("/property-analysis.html");
  // Complete the existing submit/confirm/preview flow, then click save.
  await expect(page.getByLabel("调查记录名称")).toBeFocused();
  await expect(page.getByText("同一地址已有调查记录，请手工修改记录名称")).toBeVisible();
});
```

Extend the existing route mock to respond to `/location` and to return the duplicate error once; keep the current mobile/desktop regression tests.

- [ ] **Step 2: Run the focused browser tests and verify they fail**

Run: `npm run test:web -- tests/web/property-intake.spec.js`

Expected: FAIL because the photo input, location action, project-name input, and API client support do not exist.

- [ ] **Step 3: Add semantic photo and location controls**

Add a camera-specific file input with `accept="image/jpeg,image/png"`, `capture="environment"`, visible label, and a count-only presentation. Keep the existing general file picker separate. Add a confirm-step location card explaining consent, purpose, server-mediated address lookup, and manual fallback; enable the location button only after a session exists and at least one photo is selected. Never show precise coordinates in the public UI.

- [ ] **Step 4: Implement the client API and location state**

Call `navigator.geolocation.getCurrentPosition` only from the explicit location action. Send only finite coordinate/accuracy/time/source fields. Store the candidate/status in the existing anonymous session state without persisting raw coordinates in browser storage. Render candidate text via `textContent`; do not overwrite a user-entered address.

- [ ] **Step 5: Implement conversion naming and error recovery**

Add a labeled `调查记录名称` input in the save area. Default it from the confirmed address until the user edits it. On `duplicate_address` or `project_name_taken`, leave the preview intact, show a focused accessible message, focus the name input, and let the user retry. On `project_name_required`, focus the same input. Keep demo mode synthetic and non-networked.

- [ ] **Step 6: Update responsive styles and progress summaries**

Use the existing orange/navy/white tokens and card spacing. Ensure camera/location cards fit within `390x844`, retain visible focus rings, and do not add a competing primary action. Update source/file summaries to count photos without changing the existing five-step flow.

- [ ] **Step 7: Run the focused browser tests and verify they pass**

Run: `npm run test:web -- tests/web/property-intake.spec.js`

Expected: PASS for camera/location success, permission denial/manual fallback, duplicate-name retry, existing mobile preview, desktop rail, upload error, and save regression cases.

- [ ] **Step 8: Commit the frontend unit**

```bash
git add web/js/api-client.js web/js/property-intake.js web/property-analysis.html web/property-analysis.css tests/web/property-intake.spec.js
git commit -m "feat: add photo location and duplicate naming flow"
```

### Task 4: Document the contract and verify the integrated result

**Files:**
- Modify: `docs/data-dictionary.md`
- Modify: `docs/supabase-setup.md`
- Modify: `progress.md`

- [ ] **Step 1: Document the new fields and external-service boundary**

Add `project_name`, location numeric fields, `address_candidate`, `address_source`, precision, timestamp, and the distinction between candidate and user-confirmed address to the data dictionary. Document the optional `REVERSE_GEOCODER_URL`/timeout configuration, official GSI default, rate limit, manual fallback, and the requirement to apply the forward migration only after backup/RLS verification.

- [ ] **Step 2: Run offline code checks**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
node --check web/js/api-client.js
node --check web/js/property-intake.js
git diff --check
```

Expected: all commands exit successfully.

- [ ] **Step 3: Run the complete available test suites**

Run:

```bash
pytest -q
npm run test:web
```

Expected: existing and new offline/API/browser tests pass. SQL integration remains explicitly unverified if no disposable database is configured.

- [ ] **Step 4: Perform rendered browser QA**

Use the local static server and Playwright fallback to check `/property-analysis.html` at `1440x900` and `390x844`: page identity, no overlay, console health, camera input/capture attribute, successful location candidate, denied-location manual fallback, duplicate-name focus/retry, keyboard/focus behavior, and screenshots. Record the exact browser command and remaining risk.

- [ ] **Step 5: Update progress with evidence and remaining migration risk**

Append a dated entry to `progress.md` listing changed files, passing commands, browser evidence, and the fact that the forward migration was not applied to any live database.

- [ ] **Step 6: Commit documentation and verification notes**

```bash
git add docs/data-dictionary.md docs/supabase-setup.md progress.md
git commit -m "docs: record property photo location contract"
```
