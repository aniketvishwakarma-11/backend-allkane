# Part 1 — Audit Findings: Security & Correctness Issues

This document provides a detailed audit of the vulnerabilities and correctness bugs
identified in the starter codebase before any fixes were applied. Each section walks
through the original problematic code, explains why it is dangerous or incorrect,
and describes the severity level and attack surface.

---

## Issue 1: Plaintext Password Exposure in `/login` Response

**Severity**: 🔴 Critical

**Original Code** (`main.py`, line 102):
```python
return {"access_token": token, "password_was": body.password}
```

**What was happening**:
The `/login` endpoint returned the user's plaintext password back in the HTTP response
body under the key `"password_was"`. This means that every time a user logged in, their
raw password was sent back over the network and stored in every system that touches the
response — browser developer tools, network proxy logs, CDN caches, client-side
JavaScript memory, and any logging middleware that captures response bodies.

**Why this is dangerous**:
- **Network interception**: Even over HTTPS, TLS-terminating proxies, load balancers, and
  WAFs may log response bodies. A plaintext password in the response body is captured by
  all of them.
- **Client-side exposure**: Frontend JavaScript receives the password in the JSON payload.
  If the app stores this in `localStorage`, Redux state, or a global variable, any XSS
  vulnerability instantly leaks credentials.
- **Log aggregation**: Most production systems route HTTP response bodies through logging
  pipelines (e.g., Datadog, Splunk, ELK stack). Passwords would be indexed and searchable
  in plaintext across the entire logging infrastructure.
- **Credential stuffing amplification**: Leaked passwords from one service are commonly
  reused across others. A single breach here cascades to every other service where the
  user reused the same password.

**What a proper `/login` response looks like**:
The industry-standard OAuth2 Bearer Token response only includes the token and its type.
No user credentials, secrets, or internal identifiers should ever be echoed back.

---

## Issue 2: Broken Object-Level Authorization (BOLA / IDOR)

**Severity**: 🔴 Critical

**Original Code** (`main.py`, lines 106–110):
```python
@app.get("/reports/{report_id}")
def get_report(report_id: str, user=Depends(current_user)):
    report = REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Not found")
    return report  # No ownership check whatsoever
```

**What was happening**:
All three report endpoints (`GET /reports/{id}`, `GET /reports/{id}/score`, and
`PATCH /reports/{id}/readings`) verified that the caller had a valid JWT token, but
never checked whether the authenticated user actually owned the requested report. The
JWT payload contained `user_id` and `role`, but these were completely ignored when
fetching reports.

**Concrete attack scenario**:
1. Ravi (`u_002`) logs in and receives a valid JWT.
2. Ravi sends `GET /reports/r_100` (Asha's medical report).
3. The server validates Ravi's JWT ✅, fetches `r_100` from the store ✅, and returns
   Asha's full diagnostic readings — fasting glucose, HbA1c, triglycerides, heart rate,
   VO2 max, sleep data — to an unauthorized user ❌.
4. Ravi can also `PATCH /reports/r_100/readings` to tamper with Asha's lab results.

**Why this is dangerous**:
- This is classified as **OWASP API Security Top 10 #1: Broken Object-Level Authorization
  (BOLA)**, the single most common and most exploited API vulnerability.
- In a health API context, this constitutes a **HIPAA violation** (in the US) or equivalent
  PHI breach in other jurisdictions. Patient diagnostic data is among the most sensitive
  categories of personal information.
- Report IDs (`r_100`, `r_101`) are sequential and predictable, making enumeration trivial.
  An attacker could iterate through `r_000` to `r_999` and download every patient's
  medical data in seconds.

**Additional hardening applied**:
Beyond adding ownership checks, we also changed the error response for unauthorized access
from `403 Forbidden` to `404 Not Found`. This prevents **information leakage through error
codes** — an attacker probing `GET /reports/r_100` through `r_999` would see `404` for both
non-existent and unauthorized reports, making it impossible to distinguish "this report
exists but I can't see it" from "this report doesn't exist at all."

---

## Issue 3: Unauthorized Tampering with Clinician-Verified Reports

**Severity**: 🟠 High

**Original Code** (`main.py`, line 126):
```python
report["readings"].update(body.readings)  # No check on verified_by_clinician flag
```

**What was happening**:
The `PATCH /reports/{report_id}/readings` endpoint allowed any authenticated user to
overwrite biomarker readings, even on reports where `"verified_by_clinician": True`. The
`verified_by_clinician` flag existed in the data model but was completely ignored by the
mutation endpoint.

**Why this is dangerous in a clinical context**:
- **Chain of custody**: In clinical diagnostics, once a licensed healthcare professional
  (Dr. Mehta in this case) reviews and verifies lab results, those results become part of
  the patient's official medical record. Allowing a patient to retroactively change verified
  readings breaks the chain of custody.
- **Treatment decisions**: Clinicians make treatment decisions (medication dosing, referrals,
  follow-up scheduling) based on verified lab values. If a patient modifies their glucose
  reading from 180 to 90 after verification, downstream clinical decisions become dangerously
  incorrect.
- **Audit trail integrity**: In regulated healthcare environments, verified records must be
  immutable (or at minimum, append-only with a full audit trail). Direct mutation of verified
  data violates this requirement.

**Design decision**:
We chose to block members from mutating verified reports entirely (`403 Forbidden`), while
still allowing clinicians to update verified reports (since they may need to correct
transcription errors or add late-arriving test results under their professional authority).

---

## Issue 4: Missing Triglycerides Awarding an Unearned 100% Score

**Severity**: 🔴 Critical (Correctness)

**Original Code** (`scoring.py`, line 50):
```python
value = readings.get(marker, 0)
# For triglycerides with range (0, 150):
# _marker_score(0, 0, 150) → 0 <= 0 <= 150 → True → 1.0 (100%!)
```

**What was happening**:
When a biomarker was missing from the readings dictionary, the code defaulted it to `0`
using `readings.get(marker, 0)`. For most markers, a value of `0` falls below the reference
range and receives a proportionally low score. But for triglycerides, whose reference range
starts at `0` (i.e., `(0, 150)`), the default value of `0` satisfies `0 <= 0 <= 150`,
which evaluates to `True`, awarding a perfect `1.0` score.

**Concrete impact on patient scores**:
- **Ravi's report (`r_101`)** only contains `fasting_glucose: 104` and `hba1c: 5.9` — both
  slightly elevated, indicating early metabolic concern.
- With the bug: Missing triglycerides scored `1.0`, making his metabolic pillar average
  `(0.96 + 0.91 + 1.0) / 3 = 0.957`, yielding a metabolic score of `271.7` out of `280`
  (97% — suggesting excellent metabolic health).
- After the fix: Only the two present markers are averaged: `(0.96 + 0.91) / 2 = 0.955`,
  yielding `267.5` out of `280`. The total score drops from `272` to `267`.
- The difference (5 points) might seem small numerically, but the clinical implication is
  significant: the old score falsely reported "near-perfect metabolic health" for a patient
  who never had their lipid panel tested at all.

**Why this specific bug is subtle and dangerous**:
This bug only manifests for triglycerides because it is the only marker whose reference range
lower bound is `0`. All other markers (glucose starts at 70, HbA1c at 4.0, heart rate at 50,
etc.) would default to `0` and correctly score below-range. This makes the bug
**marker-specific and hard to catch** without careful inspection of every reference range.

---

## Issue 5: Incomplete Panels Distorting Pillar Averages & Zero Division Risk

**Severity**: 🟠 High (Correctness)

**Original Code** (`scoring.py`, lines 49–57):
```python
pillar_totals = {p: 0.0 for p in PILLAR_WEIGHTS}
pillar_counts = {p: 0 for p in PILLAR_WEIGHTS}

for marker, (pillar, low, high) in REFERENCE_RANGES.items():
    value = readings.get(marker, 0)
    pillar_totals[pillar] += _marker_score(value, low, high)
    pillar_counts[pillar] += 1  # Always incremented, even if marker is missing!
```

**What was happening**:
The loop iterated over all 9 markers in `REFERENCE_RANGES` regardless of whether they existed
in the patient's readings. `pillar_counts` was always incremented, meaning the denominator
for each pillar's average was fixed at the number of defined markers (e.g., 3 for metabolic,
2 for fitness) rather than the number of actually measured markers.

**Two problems this causes**:
1. **Diluted scores for partial panels**: If Ravi only has 2 of 3 metabolic markers, the
   average is computed as `(score1 + score2 + 0) / 3` instead of `(score1 + score2) / 2`.
   The missing marker's `0` score drags down the average, penalizing the patient for tests
   that were never ordered or performed.
2. **Zero division risk**: If a patient's readings contain zero markers from a given pillar
   (e.g., no sleep data at all), then `pillar_counts["sleep"] = 0` and the division
   `pillar_totals["sleep"] / pillar_counts["sleep"]` would raise `ZeroDivisionError`,
   crashing the API with an unhandled 500 error.

**Design decision**:
Unmeasured pillars now safely evaluate to `0.0` points rather than crashing. This is the
correct behavior for a partial panel — the score reflects only what was actually tested,
and unmeasured categories contribute zero rather than an error.

---

## Issue 6: Missing Input Validation on `ReadingsUpdate`

**Severity**: 🟡 Medium

**Original Code** (`main.py`, lines 71–72):
```python
class ReadingsUpdate(BaseModel):
    readings: dict  # Accepts literally anything as values
```

**What was happening**:
The `ReadingsUpdate` Pydantic model declared `readings` as a bare `dict` with no type
constraints on keys or values. This means the API would accept payloads like:
- `{"readings": {"fasting_glucose": "elevated"}}` — string instead of number
- `{"readings": {"fasting_glucose": true}}` — boolean instead of number
- `{"readings": {"fasting_glucose": null}}` — null value
- `{"readings": {"fasting_glucose": -50}}` — negative biomarker reading
- `{"readings": {"": 100}}` — empty string as marker name

**What happens downstream without validation**:
These invalid values would be written directly into the in-memory report store. When the
scoring engine later processes them, `_marker_score("elevated", 70, 100)` would raise a
`TypeError` on the `<=` comparison, crashing the `/score` endpoint with an unhandled
`500 Internal Server Error`.

**Defense-in-depth strategy**:
We apply type/value validation at three layers as a conscious design decision:
1. **Pydantic boundary** (`ReadingsUpdate.validate_readings`): Rejects bad data at the API
   edge with a clean `422 Unprocessable Entity` before it enters the system.
2. **Normalization layer** (`normalize_readings()`): Filters out non-numeric and negative
   values as a second safety net.
3. **Scoring engine** (`compute_score()`): Skips invalid values with `continue` rather than
   crashing, ensuring resilience even if data enters through a non-API path.

This triple-layer approach ensures that if a future code path (e.g., a batch import script,
a migration tool, or a new API endpoint) bypasses the Pydantic boundary, the downstream
functions still reject bad data rather than crashing or producing silent corruption.

---

## Issue 7: Insecure JWT Key Length & Deprecated Datetime

**Severity**: 🟡 Medium

**Original Code** (`main.py`):
```python
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")  # Only 20 bytes
"exp": datetime.utcnow() + timedelta(hours=12)  # Deprecated in Python 3.12+
```

**What was happening**:
1. **JWT key length**: The default `SECRET_KEY` was `"dev-secret-change-me"` (20 bytes).
   RFC 7518 Section 3.2 requires HMAC keys for HS256 to be at least 256 bits (32 bytes).
   PyJWT raises `InsecureKeyLengthWarning` for keys shorter than this threshold, and
   shorter keys are more vulnerable to brute-force attacks.
2. **Deprecated datetime**: `datetime.utcnow()` returns a naive (timezone-unaware) datetime
   object. Python 3.12+ officially deprecates this function in favor of
   `datetime.now(timezone.utc)`, which returns a timezone-aware datetime. Naive datetimes
   can cause subtle bugs when compared with timezone-aware datetimes from other sources.

**Note**: The hardcoded fallback key is kept intentionally for this dev/task context. In a
production deployment, the application should fail loudly if `JWT_SECRET` is not set in
the environment rather than falling back to any default.
