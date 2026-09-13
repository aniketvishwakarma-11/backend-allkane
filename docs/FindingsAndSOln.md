# Findings & Technical Decisions

This document summarizes all security and correctness issues identified and resolved in **Part 1**, details the architecture of the normalization helper in **Part 2**, highlights clinical domain observations, and provides transparent disclosure of AI tool usage as requested in the task guidelines.

---

## 1. Issues Found & Fixed (Part 1)

### Issue 1: Plaintext Password Exposure in `/login` Response
* **What it was**: The `/login` endpoint returned `"password_was": body.password` in the response payload alongside the JWT token.
* **Why it matters**: Echoing plaintext passwords in HTTP responses creates severe credential exposure across network logs, client memory, browser caches, and proxy monitoring tools.
* **What was changed**: Removed `"password_was"` completely from `main.py` and aligned the response with standard OAuth2 Bearer format (`{"access_token": token, "token_type": "bearer"}`).

---

### Issue 2: Broken Object-Level Authorization (BOLA / IDOR)
* **What it was**: The endpoints `GET /reports/{id}`, `GET /reports/{id}/score`, and `PATCH /reports/{id}/readings` validated JWT tokens but never verified whether the authenticated user owned the requested report.
* **Why it matters**: Any authenticated patient (e.g., Ravi) could read or tamper with another patient's (e.g., Asha's) sensitive diagnostic reports, constituting a critical Protected Health Information (PHI) breach.
* **What was changed**: Implemented `get_authorized_report()` in `main.py`. Members are strictly restricted to reports where `report["owner_id"] == user["user_id"]` (returning `403 Forbidden` on mismatch), while clinicians (`dr_mehta`) retain elevated access to review any patient record.

---

### Issue 3: Unauthorized Tampering with Clinician-Verified Reports
* **What it was**: Any user could mutate biomarker readings on reports where `"verified_by_clinician": True`.
* **Why it matters**: In clinical workflows, once diagnostic data has been reviewed and certified by a healthcare professional, patient modifications without clinician oversight compromise medical integrity and patient safety.
* **What was changed**: Enforced a write check in `get_authorized_report()` that prohibits members from mutating verified reports with `403 Forbidden: Clinician-verified reports cannot be modified by members`.

---

### Issue 4: Missing Triglycerides Awarding an Unearned 100% Score
* **What it was**: In `scoring.py`, missing biomarkers defaulted to `0` via `readings.get(marker, 0)`. Because the reference range for triglycerides is `(0, 150)`, `_marker_score(0, 0, 150)` evaluated `0 <= 0 <= 150` as `True`, awarding missing triglycerides an automatic 1.0 (100%) score.
* **Why it matters**: Patients who never had a lipid panel performed were awarded full health points for triglycerides, artificially inflating their metabolic score (e.g., in `r_101`, Ravi's tested markers were both elevated, but missing triglycerides falsely pulled his metabolic score up to 97%).
* **What was changed**: Updated `compute_score()` to only evaluate biomarkers that are actually present in the readings dictionary, ensuring unperformed tests never receive unearned points.

---

### Issue 5: Incomplete Panels Distorting Pillar Averages & Zero Division
* **What it was**: `compute_score()` unconditionally incremented `pillar_counts` for all 9 markers in `REFERENCE_RANGES`, penalizing unmeasured markers as zero scores and risking `ZeroDivisionError` if a pillar had zero markers.
* **Why it matters**: Lab reports frequently contain partial panels (e.g., only blood chemistry without wearable sleep or fitness metrics); penalizing unmeasured markers as total failures distorts the health score.
* **What was changed**: Calculated pillar ratios based strictly on present markers (`sum / present_count`), guarded against zero division by safely returning `0.0` points for completely unmeasured pillars, and verified that complete reports (`r_100`) retain their exact scores (total: 946).

---

### Issue 6: Missing Input Validation on `ReadingsUpdate`
* **What it was**: `ReadingsUpdate` accepted arbitrary dictionaries without validating key or value types.
* **Why it matters**: Submitting non-numeric types (`{"fasting_glucose": "elevated"}` or `None`) or negative numbers caused unhandled 500 server crashes inside the scoring engine.
* **What was changed**: Added Pydantic field validation ensuring all reading values are non-negative numeric types (`int` or `float`), cleanly rejecting invalid payloads with `422 Unprocessable Entity`.

---

### Issue 7: Insecure JWT Key Length & Deprecated Datetime
* **What it was**: The default `SECRET_KEY` was only 20 bytes (triggering `InsecureKeyLengthWarning` under RFC 7518 for `HS256`), and `datetime.utcnow()` is deprecated in Python 3.12+.
* **What was changed**: Upgraded the default secret key to $\ge 32$ bytes and switched to timezone-aware `datetime.now(timezone.utc)`.

---

## 2. Normalization Helper Architecture (Part 2)

### Structure & Rationale
We designed the normalization engine in a standalone module (`normalization.py`):
1. **Separation of Concerns**: Kept the normalization logic decoupled from FastAPI route handling and the scoring math. This ensures the helper is easily testable in isolation and reusable across future ingestion paths (e.g., CSV imports, HL7/FHIR feeds).
2. **Lookup Strategy**: Built an alias map (`MARKER_ALIASES`) where all incoming keys are stripped of whitespace and converted to lowercase (`raw_name.strip().lower()`). This provides robust tolerance against case and formatting variations:
   - `glucose_fasting`, `FBS`, `fbs` $\rightarrow$ `fasting_glucose`
   - `A1c`, `a1c`, `HbA1C`, `hba1c` $\rightarrow$ `hba1c`
   - `trigs` $\rightarrow$ `triglycerides`
   - Canonical names map directly to themselves.
3. **Safe Unknown Marker Handling**: If an incoming marker is not in `MARKER_ALIASES`, `normalize_marker_name()` returns `None`, and `normalize_readings()` safely omits it from the sanitized dictionary. Unknown markers neither crash the request nor corrupt stored readings or scores.
4. **Wiring**: Placed `normalize_readings()` directly inside `PATCH /reports/{report_id}/readings` before updating `report["readings"]`, ensuring downstream scoring automatically receives canonical keys.

---

## 3. Clinical Domain Observations (Left Undone / Future Scope)

While inspecting `scoring.py`, we identified an asymmetry in how reference ranges are evaluated:
* **Two-Sided Penalties on One-Sided Biomarkers**: `_marker_score` computes `high / value` for any reading exceeding `high`.
  - For biomarkers where higher is clinically better (e.g., `vo2_max` [35, 60] or `steps_per_day` [7000, 15000]), an athlete with a VO2 max of 70 or someone walking 20,000 steps is penalized with a lower score.
  - For `reaction_time_ms` [200, 350], faster reflexes (< 200 ms) are penalized with a lower score via `value / low`.
* **Recommendation**: In production, directional biomarkers should use open-ended or plateau ranges (e.g., VO2 max $\ge 35 \implies 1.0$) rather than treating all markers as two-sided bell curves. We left the existing range boundaries intact to preserve product specification and avoid out-of-scope engine refactoring.

---

## 4. Transparent AI Usage Disclosure

As encouraged in the assignment instructions, AI assistance was used during this task:
1. **Where AI was used**:
   - Architecture and phased implementation planning to ensure atomic commits.
   - Comprehensive edge-case auditing (e.g., identifying why missing triglycerides produced `1.0` due to `0 <= 0 <= 150`).
   - Generating the 47-case `pytest` test suite covering regression locks, BOLA authorization, and alias normalization.
   - Structuring and drafting documentation.
2. **Defensibility Guarantee**: Every line of code, math formula, Pydantic validator, authorization rule, and test assertion has been reviewed, tested, and can be fully explained and defended in detail during the interview.
