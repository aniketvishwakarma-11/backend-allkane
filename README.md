# Take-home task — Backend and Platform

A secure, verified, and tested API for a digital health platform. Members upload lab reports, the service securely stores and normalizes readings, and computes an accurate health score out of 1000 across five pillars.

---

## Resolved Issues & Implemented Solutions

### Part 1: Security & Correctness Fixes

1. **Plaintext Password Leak in `/login`**:
   - **Error**: Endpoint returned `"password_was": body.password` in the response payload alongside the JWT token.
   - **Solution**: Removed password reflection entirely, returning standard OAuth2 Bearer tokens (`{"access_token": token, "token_type": "bearer"}`).

2. **Broken Object-Level Authorization (BOLA / IDOR)**:
   - **Error**: Any authenticated patient (e.g. Ravi) could view or edit any other patient's (e.g. Asha's) lab reports and scores.
   - **Solution**: Implemented `get_authorized_report()` in `main.py` restricting members strictly to their own reports (`report["owner_id"] == user["user_id"]`), while clinicians (`dr_mehta`) retain elevated access to review all patient records (`403 Forbidden` on unauthorized access).

3. **Tampering with Clinician-Verified Reports**:
   - **Error**: Patients could mutate readings on reports certified by a doctor (`"verified_by_clinician": True`).
   - **Solution**: Prohibited patient modifications on verified reports with `403 Forbidden: Clinician-verified reports cannot be modified by members`, safeguarding clinical data integrity.

4. **Scoring Correctness — Missing Triglycerides 100% Score Bug**:
   - **Error**: Missing biomarkers defaulted to `0`. For triglycerides with range `(0, 150)`, `0 <= 0 <= 150` evaluated to `True`, awarding unperformed lipid tests a perfect 1.0 (100%) score and artificially inflating metabolic scores.
   - **Solution**: Updated `compute_score()` in `scoring.py` to evaluate only biomarkers that are actually present in the readings dictionary.

5. **Incomplete Panel Average Skew & Zero Division**:
   - **Error**: Missing biomarkers in incomplete panels were treated as zero failures, and unmeasured pillars risked division-by-zero crashes.
   - **Solution**: Calculated pillar averages based strictly on measured biomarkers, added safe division guards returning `0.0` points for unmeasured pillars, and locked baseline scores on complete reports (`r_100` total: 946).

6. **Input Validation on Readings Payload**:
   - **Error**: Non-numeric types (e.g., strings, None) or negative numbers caused 500 server crashes.
   - **Solution**: Added Pydantic field validation on `ReadingsUpdate` rejecting invalid inputs with `422 Unprocessable Entity`.

7. **Insecure JWT Key Length & Deprecated Datetime**:
   - **Error**: 20-byte secret key triggered RFC 7518 security warnings for HS256, and `datetime.utcnow()` is deprecated in Python 3.12+.
   - **Solution**: Upgraded default secret to $\ge 32$ bytes and switched to timezone-aware `datetime.now(timezone.utc)`.

---

### Part 2: Biomarker Normalization Engine (`normalization.py`)

- **Alias Mapping**: Created a dedicated module mapping lab-specific biomarker names to canonical names:
  - `glucose_fasting`, `FBS`, `fbs` $\rightarrow$ `fasting_glucose`
  - `A1c`, `a1c`, `HbA1C`, `hba1c` $\rightarrow$ `hba1c`
  - `trigs` $\rightarrow$ `triglycerides`
  - Canonical names map directly to themselves.
- **Tolerance**: Case-insensitive and whitespace-tolerant matching (`raw_name.strip().lower()`).
- **Safe Unknown Marker Handling**: Unknown biomarkers (e.g., `cholesterol_total`, `crp`) are safely ignored without crashing requests or corrupting scores.
- **Pipeline Wiring**: Integrated into `PATCH /reports/{report_id}/readings` before saving into the stored report.

---

## Setup & Running

### Installation
```bash
pip install fastapi uvicorn pyjwt pytest
```

### Run the API Server
```bash
python -m uvicorn main:app --reload
```
- Interactive Swagger Docs: http://127.0.0.1:8000/docs
- Alternative ReDoc Docs: http://127.0.0.1:8000/redoc

### Test Credentials
- **Asha (Member)**: `asha` / `asha123`
- **Ravi (Member)**: `ravi` / `ravi123`
- **Dr. Mehta (Clinician)**: `dr_mehta` / `mehta123`

---

## Running the Automated Test Suite

A comprehensive 47-test suite locks the score, verifies normalization, and checks security:

```bash
python -m pytest -v
```

All 47 tests pass:
- `tests/test_scoring.py`: Regression lock for `r_100`, missing marker checks, boundary math.
- `tests/test_normalization.py`: Required aliases, whitespace/casing, unknown-name safety.
- `tests/test_api.py`: Login credential hygiene, BOLA 403 checks, clinician access, verified report protection, input validation.

---

## Detailed Audit Findings

For an in-depth write-up of every issue, clinical domain observations, and transparent AI tool disclosure, see [FINDINGS.md](FINDINGS.md).
