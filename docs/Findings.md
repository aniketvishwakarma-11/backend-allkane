# Part 1 Audit Findings: Security Vulnerabilities & Scoring Correctness

This document provides a comprehensive technical audit of the issues identified in **Part 1** of the codebase, covering security, authorization, data integrity, and scoring engine calculations.

---

## 1. Security & Authorization Vulnerabilities (`main.py`)

### Issue 1: Plaintext Password Exposure in `/login` Response
- **Location**: `main.py` (Line 102)
- **What it is**: The `/login` route returns `"password_was": body.password` alongside the JWT `access_token`.
- **Why it matters**: Exposing plaintext credentials in HTTP response payloads violates basic security principles. It leaks sensitive user passwords into client application memory, browser history, network interception logs, and proxy caches.
- **Proposed Fix**: Remove `"password_was"` entirely from the response dictionary. Return standard OAuth2 token fields:
  ```python
  return {"access_token": token, "token_type": "bearer"}
  ```

---

### Issue 2: Broken Object-Level Authorization (BOLA / IDOR)
- **Location**: `main.py` (Lines 106, 114, 122)
  - `GET /reports/{report_id}`
  - `GET /reports/{report_id}/score`
  - `PATCH /reports/{report_id}/readings`
- **What it is**: The endpoints verify that a valid JWT token is provided via `current_user`, but they **never verify report ownership or role permissions**. Any authenticated user (e.g., `ravi`, user ID `u_002`) can request or mutate any other user's report (e.g., `asha`'s report `r_100`).
- **Why it matters**: In a digital health application, this constitutes a critical privacy violation, exposing Protected Health Information (PHI) across patient boundaries.
- **Proposed Fix**: Implement an authorization check before returning or mutating reports:
  - If `user["role"] == "clinician"`: allow access to any report.
  - If `user["role"] == "member"`: verify `report["owner_id"] == user["user_id"]`. If mismatched, raise `HTTPException(status_code=403, detail="Forbidden")`.

---

### Issue 3: Unauthorized Tampering with Clinician-Verified Reports
- **Location**: `main.py` (Lines 121–127)
- **What it is**: In `PATCH /reports/{report_id}/readings`, any user can overwrite readings even when `report["verified_by_clinician"]` is `True`.
- **Why it matters**: In clinical workflows, once a medical professional certifies and signs off on a diagnostic report, patients must not be allowed to tamper with the underlying biomarker values without clinician oversight.
- **Proposed Fix**:
  - Check `report.get("verified_by_clinician")`.
  - Disallow modifications by non-clinicians on verified reports (`HTTP 403 Forbidden`).
  - Alternatively, if modifications are allowed, reset `report["verified_by_clinician"] = False` so that the modified data mandates clinician re-verification.

---

### Issue 4: Insecure JWT Secret Key & Deprecated Datetime Usage
- **Location**: `main.py` (Lines 21, 97)
- **What it is**: 
  - `SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")` uses a 20-byte string. For HMAC-SHA256 (`HS256`), RFC 7518 Section 3.2 specifies a minimum key length of 32 bytes (256 bits), triggering `InsecureKeyLengthWarning`.
  - `datetime.utcnow()` is deprecated in modern Python (3.12+).
- **Why it matters**: Short or predictable HMAC keys are susceptible to brute-force token forgery. Deprecated UTC methods introduce timezone discrepancies across different execution environments.
- **Proposed Fix**: 
  - Update default secret to a minimum 32-byte string: e.g. `"dev-secret-change-me-must-be-at-least-32-bytes-long!"`.
  - Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`.

---

### Issue 5: Missing Input Validation on `ReadingsUpdate`
- **Location**: `main.py` (Line 71)
- **What it is**: `ReadingsUpdate` defines `readings: dict` without validating key types, value types, or numeric boundaries.
- **Why it matters**: Submitting non-numeric types (`{"fasting_glucose": "elevated"}` or `{"fasting_glucose": None}`) triggers unhandled `TypeError` exceptions inside the scoring engine (`_marker_score`), resulting in `500 Internal Server Error`.
- **Proposed Fix**: Add schema-level validation ensuring that all submitted reading values are valid, positive numeric types (`int` or `float`).

---

## 2. Scoring Engine Correctness Issues (`scoring.py`)

### Issue 6: Missing Triglycerides Awards an Automatic 100% Score
- **Location**: `scoring.py` (Lines 21, 50)
- **What it is**: 
  - Reference range definition: `"triglycerides": ("metabolic", 0, 150)`.
  - In `compute_score`: `value = readings.get(marker, 0)`.
  - When `triglycerides` is missing from `readings` (e.g., in report `r_101`), `readings.get("triglycerides", 0)` returns `0`.
  - In `_marker_score(0, 0, 150)`, the condition `low <= value <= high` (`0 <= 0 <= 150`) evaluates to `True`, awarding a **1.0 (100%) score**.
- **Why it matters**: A patient who never had a lipid panel performed receives an automatic perfect score for triglycerides. In `r_101`, Ravi's tested biomarkers (glucose: 104, HbA1c: 5.9) are both out-of-range (averaging 95.5%), but missing triglycerides pulls his metabolic score up to 97.0% (271.7 / 280).
- **Proposed Fix**: Missing biomarkers must not default to `0`. Missing readings must be distinguished from measured values so unperformed tests do not receive free points.

---

### Issue 7: Unmeasured Markers Distorting Pillar Averages
- **Location**: `scoring.py` (Lines 46–60)
- **What it is**: `pillar_counts` unconditionally increments by 1 for all 9 markers in `REFERENCE_RANGES`, regardless of how many tests were actually performed.
  - For markers where `low > 0`, missing markers default to 0 and score `0.0`.
  - If a patient only took a blood panel (metabolic), their fitness, cognitive, sleep, and lifestyle pillars are calculated as `0.0 / count * weight = 0.0`.
  - If a pillar has 3 reference markers and only 2 were tested, dividing the sum by 3 severely penalizes the patient for markers that were never tested.
- **Why it matters**: Lab reports frequently contain partial panels (e.g., only blood chemistry, without wearable sleep/fitness metrics). Penalizing unmeasured markers as zeros distorts the health score.
- **Proposed Fix**: Compute each pillar's score ratio based only on markers that were **actually present in the report**:
  $$\text{pillar\_ratio} = \frac{\sum \text{marker\_scores for present markers}}{\text{count of present markers in pillar}}$$
  If a pillar has 0 markers present in the report, its points safely evaluate to `0.0` (with a safe division guard preventing `ZeroDivisionError`).

---

### Issue 8: Biological Asymmetry in Reference Ranges (Clinical Observation)
- **Location**: `scoring.py` (Lines 23, 27, 31–37)
- **What it is**: 
  - `_marker_score` computes `high / value` for any reading exceeding `high`.
  - For biomarkers where higher values indicate superior health (e.g., `vo2_max` [35, 60] or `steps_per_day` [7000, 15000]), an athlete with a VO2 max of 70 or someone walking 20,000 steps gets penalized with a lower score.
  - For `reaction_time_ms` [200, 350], faster reflexes (< 200 ms) are penalized with a lower score via `value / low`.
- **Why it matters**: While the current mathematical model treats all reference ranges as two-sided bell curves, clinical biomarkers often have single-sided health thresholds. Documenting this distinction demonstrates domain rigor.
