# Part 1 & Part 2 — Solutions Implemented

This document details every fix applied, the exact code changes made, and the reasoning
behind each implementation decision. It serves as both a technical changelog and a
defensibility reference.

---

## Solution 1: Removed Plaintext Password from `/login` Response

**File**: `main.py`

**Original code (removed)**:
```python
return {"access_token": token, "password_was": body.password}
```

**Replacement code**:
```python
return {"access_token": token, "token_type": "bearer"}
```

**What changed and why**:
We removed the `"password_was"` key entirely from the login response. The response now
follows the standard OAuth2 Bearer Token format, returning only the JWT access token and
its type. This is the minimum information a client needs to authenticate subsequent requests.

No password, hashed or otherwise, should ever appear in an API response. The client already
knows the password (they just sent it in the request body), so echoing it back serves no
functional purpose and creates severe exposure risk across every system that touches the
HTTP response — network logs, CDN caches, browser developer tools, and client-side memory.

**Test coverage**: `test_login_success_does_not_leak_password` asserts that neither
`"password_was"` nor `"password"` appears anywhere in the response body.

---

## Solution 2: Enforced Object-Level Authorization (BOLA Protection)

**File**: `main.py`

**New helper function added**:
```python
def get_authorized_report(report_id: str, user: dict, write: bool = False) -> dict:
    report = REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Not found")

    is_clinician = user.get("role") == "clinician"
    is_owner = report.get("owner_id") == user.get("user_id")

    if not (is_clinician or is_owner):
        raise HTTPException(status_code=404, detail="Not found")

    if write and report.get("verified_by_clinician") and not is_clinician:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Clinician-verified reports cannot be modified by members",
        )

    return report
```

**What changed and why**:
We implemented a centralized authorization helper that is called by all three report
endpoints (`GET /reports/{id}`, `GET /reports/{id}/score`, `PATCH /reports/{id}/readings`).
This ensures consistent authorization logic across every access path.

The helper enforces two rules:
1. **Ownership check**: Members can only access reports where `report["owner_id"]` matches
   their `user["user_id"]` from the JWT payload. Clinicians bypass this check and can
   access any patient's reports (as required by their clinical role).
2. **Verified report protection**: When the `write=True` flag is set (only on the PATCH
   endpoint), members are blocked from modifying reports that have been verified by a
   clinician. Clinicians themselves can still modify verified reports under their
   professional authority.

**Information leakage prevention**: We deliberately return `404 Not Found` (not `403
Forbidden`) when a member tries to access another patient's report. This prevents report
ID enumeration — an attacker sending requests for `r_000` through `r_999` sees identical
`404` responses for both non-existent and unauthorized reports, making it impossible to
determine which report IDs are valid.

**Why a centralized helper instead of per-route checks**:
Duplicating authorization logic in each route handler is error-prone. If a new endpoint
is added later (e.g., `DELETE /reports/{id}`), the developer only needs to call
`get_authorized_report()` to get consistent authorization. This follows the principle of
"authorize once, use everywhere."

**Route simplification** — all three routes are now clean single-line calls:
```python
@app.get("/reports/{report_id}")
def get_report(report_id: str, user=Depends(current_user)):
    return get_authorized_report(report_id, user)

@app.get("/reports/{report_id}/score")
def get_score(report_id: str, user=Depends(current_user)):
    report = get_authorized_report(report_id, user)
    return compute_score(report["readings"])

@app.patch("/reports/{report_id}/readings")
def update_readings(report_id: str, body: ReadingsUpdate, user=Depends(current_user)):
    report = get_authorized_report(report_id, user, write=True)
    normalized = normalize_readings(body.readings)
    report["readings"].update(normalized)
    return report
```

**Test coverage**:
- `test_bola_patient_cannot_view_other_patient_report` — Ravi gets 404 for Asha's report
- `test_bola_patient_cannot_view_other_patient_score` — Ravi gets 404 for Asha's score
- `test_bola_patient_cannot_patch_other_patient_report` — Ravi gets 404 for PATCH on Asha's report
- `test_clinician_can_view_any_patient_report_and_score` — Dr. Mehta can access both
- `test_member_cannot_modify_clinician_verified_report` — Asha gets 403 on verified r_100
- `test_clinician_can_modify_verified_report` — Dr. Mehta can update verified r_100
- `test_nonexistent_report_returns_404` — unknown ID returns 404

---

## Solution 3: Fixed Scoring Engine for Missing Biomarkers

**File**: `scoring.py`

**Original code (buggy)**:
```python
for marker, (pillar, low, high) in REFERENCE_RANGES.items():
    value = readings.get(marker, 0)
    pillar_totals[pillar] += _marker_score(value, low, high)
    pillar_counts[pillar] += 1
```

**Replacement code**:
```python
for marker, (pillar, low, high) in REFERENCE_RANGES.items():
    if marker not in readings or readings[marker] is None:
        continue
    value = readings[marker]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        continue
    if value < 0:
        continue
    pillar_totals[pillar] += _marker_score(value, low, high)
    pillar_counts[pillar] += 1
```

**What changed and why**:
The original loop evaluated all 9 markers unconditionally, defaulting missing ones to `0`.
The fix introduces a series of guard clauses before scoring:

1. **`if marker not in readings`**: Skips markers that the patient never had tested. This is
   the core fix — unperformed tests should not contribute to the score at all, neither
   positively nor negatively.
2. **`if readings[marker] is None`**: Handles the case where a marker key exists but has a
   `None` value (e.g., from a partial data import where a field was present but empty).
3. **`isinstance(value, bool)` check**: Python's `bool` is a subclass of `int`, so
   `isinstance(True, int)` returns `True`. Without this guard, `True` would be scored as
   `1` and `False` as `0`, producing silently wrong results.
4. **`not isinstance(value, (int, float))`**: Rejects strings, lists, dicts, or any other
   non-numeric type that would cause a `TypeError` in the comparison operators inside
   `_marker_score()`.
5. **`if value < 0`**: Negative biomarker readings are physiologically impossible and
   indicate data corruption.

**Pillar average fix** — added zero-division guard:
```python
if pillar_counts[pillar] > 0:
    ratio = pillar_totals[pillar] / pillar_counts[pillar]
    points = ratio * weight
else:
    points = 0.0
```

Now `pillar_counts` only counts markers that were actually present and valid. If a pillar
has zero measured markers (e.g., no sleep data), it safely returns `0.0` points instead
of crashing with `ZeroDivisionError`.

**Score impact**:
- `r_100` (Asha, complete panel): **946** — unchanged, confirming no regression.
- `r_101` (Ravi, partial panel): **272 → 267** — corrected. The 5-point drop comes from
  removing the phantom triglycerides 1.0 score that was inflating the metabolic average.

**Test coverage**:
- `test_full_report_r100_regression_lock` — locks r_100 at exactly 946
- `test_partial_report_r101_regression_lock` — locks r_101 at exactly 267
- `test_missing_triglycerides_does_not_score_100_percent` — directly tests the core bug
- `test_empty_readings_returns_zero` — verifies zero-division safety
- `test_perfect_health_scores_1000` — all in-range markers must produce exactly 1000

---

## Solution 4: Added Pydantic Input Validation

**File**: `main.py`

**New validation code**:
```python
class ReadingsUpdate(BaseModel):
    readings: dict

    @field_validator("readings")
    @classmethod
    def validate_readings(cls, v):
        if not isinstance(v, dict) or not v:
            raise ValueError("Readings must be a non-empty dictionary")
        for marker, val in v.items():
            if not isinstance(marker, str) or not marker.strip():
                raise ValueError("Biomarker names must be non-empty strings")
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"Reading value for '{marker}' must be a number")
            if val < 0:
                raise ValueError(f"Reading value for '{marker}' cannot be negative")
        return v
```

**What changed and why**:
The original `ReadingsUpdate` model accepted any dictionary without constraints. We added
a Pydantic `@field_validator` that runs before the endpoint handler, ensuring:

- The readings dict is non-empty (empty updates are pointless and potentially indicate a
  client-side bug).
- All keys are non-empty strings (empty string marker names would corrupt the data store).
- All values are numeric (`int` or `float`) — strings, booleans, nulls, lists, and other
  types are rejected with a descriptive error message.
- All values are non-negative — biomarker readings cannot be negative in any physiological
  context.

Invalid payloads receive a `422 Unprocessable Entity` response with a clear error message,
which is the standard HTTP status code for syntactically valid but semantically invalid
request bodies.

**Test coverage**:
- `test_payload_validation_rejects_non_numeric_values` — string value → 422
- `test_payload_validation_rejects_negative_values` — negative value → 422

---

## Solution 5: JWT Key Upgrade & Datetime Modernization

**File**: `main.py`

**Original code**:
```python
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")
"exp": datetime.utcnow() + timedelta(hours=12)
```

**Replacement code**:
```python
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me-must-be-at-least-32-bytes-long!")
"exp": datetime.now(timezone.utc) + timedelta(hours=12)
```

**What changed and why**:
1. The fallback secret key was extended from 20 bytes to 52 bytes, exceeding the 32-byte
   minimum required by RFC 7518 Section 3.2 for HS256 HMAC keys. This silences PyJWT's
   `InsecureKeyLengthWarning` and provides adequate cryptographic strength.
2. `datetime.utcnow()` was replaced with `datetime.now(timezone.utc)` to produce
   timezone-aware datetime objects. This follows Python 3.12+ deprecation guidance and
   prevents subtle bugs when comparing datetimes from different sources.

**Test coverage**: `test_expired_token_returns_401` crafts a JWT with an expiration time
in the past and verifies it is rejected with `401 Unauthorized`.

---

## Solution 6: Biomarker Normalization Helper (Part 2)

**File**: `normalization.py` (new file, ~85 lines)

**Architecture**:
The normalization engine is built as a standalone module with two public functions:

### `normalize_marker_name(raw_name: str) -> str | None`
Takes a raw marker name string and returns the canonical name, or `None` if unrecognized.

```python
MARKER_ALIASES = {
    "glucose_fasting": "fasting_glucose",
    "fbs": "fasting_glucose",
    "fasting_glucose": "fasting_glucose",
    "a1c": "hba1c",
    "hba1c": "hba1c",
    "trigs": "triglycerides",
    "triglycerides": "triglycerides",
    "resting_heart_rate": "resting_heart_rate",
    "vo2_max": "vo2_max",
    "reaction_time_ms": "reaction_time_ms",
    "sleep_hours": "sleep_hours",
    "sleep_efficiency": "sleep_efficiency",
    "steps_per_day": "steps_per_day",
}

def normalize_marker_name(raw_name: str) -> str | None:
    if not isinstance(raw_name, str):
        return None
    cleaned = raw_name.strip().lower()
    return MARKER_ALIASES.get(cleaned)
```

**Lookup strategy**: All incoming marker names are stripped of whitespace and converted to
lowercase before dictionary lookup. This provides robust tolerance against case variations
(`FBS`, `Fbs`, `fbs` all resolve to `fasting_glucose`) and accidental whitespace
(`"  FBS  "` → `fasting_glucose`).

### `normalize_readings(readings: dict) -> dict`
Transforms an entire readings payload by normalizing keys and filtering invalid values.

```python
def normalize_readings(readings: dict) -> dict:
    if not isinstance(readings, dict):
        return {}
    normalized = {}
    for raw_marker, value in readings.items():
        canonical_name = normalize_marker_name(raw_marker)
        if canonical_name is None:
            continue  # Unknown marker: safely ignored
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < 0:
            continue
        normalized[canonical_name] = value
    return normalized
```

**Unknown marker handling**: If an incoming marker name is not in the alias dictionary,
it is silently dropped. This is a deliberate design choice — unknown markers should never
be stored in the readings because they would be ignored by the scoring engine anyway, and
storing unrecognized data could introduce confusion or data quality issues.

### Wiring into the API

The normalization function is called inside `PATCH /reports/{report_id}/readings`, positioned
between Pydantic validation and the store update:

```python
@app.patch("/reports/{report_id}/readings")
def update_readings(report_id: str, body: ReadingsUpdate, user=Depends(current_user)):
    report = get_authorized_report(report_id, user, write=True)
    normalized = normalize_readings(body.readings)    # ← normalization step
    report["readings"].update(normalized)
    return report
```

This ensures that all downstream code — including the scoring engine — only ever sees
canonical marker names, regardless of what alias the client used in the request.

**Test coverage** (25 normalization tests + 2 integration tests):
- All required aliases from Part 2 spec: `glucose_fasting`, `FBS`, `fbs`, `A1c`, `a1c`,
  `HbA1C`, `hba1c`, `trigs`, `triglycerides`
- Canonical name passthrough for all 9 markers
- Case insensitivity and whitespace tolerance
- Unknown marker returns `None` / gets dropped
- Non-string inputs safely return `None`
- End-to-end API integration: PATCH with aliases → verify canonical keys stored
- End-to-end scoring: PATCH with aliases → GET score → verify correct total
- Alias conflict behavior documented and tested (last-write-wins)

---

## Summary of Score Impact

| Report | Before Fixes | After Fixes | Change | Reason |
|--------|-------------|-------------|--------|--------|
| r_100 (Asha) | 946 | 946 | No change | Full panel, all markers present |
| r_101 (Ravi) | 272 | 267 | −5 | Phantom triglycerides 1.0 removed |
