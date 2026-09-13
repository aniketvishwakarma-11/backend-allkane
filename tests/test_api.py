"""
Integration tests for the API routes (main.py).

Verifies authentication hygiene, BOLA/IDOR protection, clinician role elevation,
clinician-verified report protection, input validation, and normalization integration.
"""

import pytest
from fastapi.testclient import TestClient
from main import app, REPORTS


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def asha_headers(client):
    res = client.post("/login", json={"username": "asha", "password": "asha123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ravi_headers(client):
    res = client.post("/login", json={"username": "ravi", "password": "ravi123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def dr_mehta_headers(client):
    res = client.post("/login", json={"username": "dr_mehta", "password": "mehta123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuthenticationSecurity:
    """
    Tests for authentication endpoint and token hygiene.
    """

    def test_login_success_does_not_leak_password(self, client):
        """
        Verify that /login returns an access token and NEVER echoes the plaintext password.
        """
        response = client.post("/login", json={"username": "asha", "password": "asha123"})
        assert response.status_code == 200
        body = response.json()

        assert "access_token" in body
        assert body.get("token_type") == "bearer"
        assert "password_was" not in body
        assert "password" not in body

    def test_login_bad_credentials_returns_401(self, client):
        """
        Bad passwords must be rejected with 401 Unauthorized.
        """
        response = client.post("/login", json={"username": "asha", "password": "wrongpassword"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Bad credentials"

    def test_missing_token_returns_403_or_401(self, client):
        """
        Protected endpoints without Authorization header must be rejected.
        """
        response = client.get("/reports/r_100")
        assert response.status_code in (401, 403)


class TestObjectLevelAuthorization:
    """
    BOLA / IDOR tests: Patients must only access their own reports;
    clinicians can access all reports.
    """

    def test_patient_can_view_own_report_and_score(self, client, asha_headers):
        """
        Asha can access her own report (r_100) and score.
        """
        rep_res = client.get("/reports/r_100", headers=asha_headers)
        assert rep_res.status_code == 200
        assert rep_res.json()["report_id"] == "r_100"

        score_res = client.get("/reports/r_100/score", headers=asha_headers)
        assert score_res.status_code == 200
        assert score_res.json()["total"] == 946

    def test_bola_patient_cannot_view_other_patient_report(self, client, ravi_headers):
        """
        Ravi attempting to access Asha's report (r_100) must receive 403 Forbidden.
        """
        response = client.get("/reports/r_100", headers=ravi_headers)
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]

    def test_bola_patient_cannot_view_other_patient_score(self, client, ravi_headers):
        """
        Ravi attempting to compute Asha's score (r_100/score) must receive 403 Forbidden.
        """
        response = client.get("/reports/r_100/score", headers=ravi_headers)
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]

    def test_clinician_can_view_any_patient_report_and_score(self, client, dr_mehta_headers):
        """
        Clinicians (Dr. Mehta) have elevated access to view any patient's report and score.
        """
        r100_res = client.get("/reports/r_100", headers=dr_mehta_headers)
        assert r100_res.status_code == 200

        r101_res = client.get("/reports/r_101", headers=dr_mehta_headers)
        assert r101_res.status_code == 200

    def test_nonexistent_report_returns_404(self, client, asha_headers):
        """
        Requesting a non-existent report returns 404 Not Found.
        """
        response = client.get("/reports/r_999", headers=asha_headers)
        assert response.status_code == 404


class TestClinicalIntegrityAndNormalization:
    """
    Tests for verified report protection and biomarker alias normalization.
    """

    def test_member_cannot_modify_clinician_verified_report(self, client, asha_headers):
        """
        A member cannot mutate readings on a report that has already been verified by a clinician.
        """
        payload = {"readings": {"fasting_glucose": 90}}
        response = client.patch("/reports/r_100/readings", json=payload, headers=asha_headers)

        assert response.status_code == 403
        assert "Clinician-verified reports cannot be modified" in response.json()["detail"]

    def test_member_can_update_unverified_report_with_aliases(self, client, ravi_headers):
        """
        Ravi updating unverified report (r_101) with biomarker aliases:
        aliases must be normalized to canonical keys, and unknown markers dropped safely.
        """
        payload = {
            "readings": {
                "FBS": 90,
                "A1c": 5.2,
                "trigs": 135,
                "unknown_lipid_panel_marker": 55,
            }
        }
        response = client.patch("/reports/r_101/readings", json=payload, headers=ravi_headers)
        assert response.status_code == 200
        readings = response.json()["readings"]

        # Canonical names stored
        assert readings["fasting_glucose"] == 90
        assert readings["hba1c"] == 5.2
        assert readings["triglycerides"] == 135

        # Unknown marker safely filtered out
        assert "unknown_lipid_panel_marker" not in readings

    def test_payload_validation_rejects_non_numeric_values(self, client, ravi_headers):
        """
        Passing non-numeric values must be rejected with 422 Unprocessable Entity.
        """
        invalid_payload = {"readings": {"fasting_glucose": "elevated"}}
        response = client.patch("/reports/r_101/readings", json=invalid_payload, headers=ravi_headers)
        assert response.status_code == 422

    def test_payload_validation_rejects_negative_values(self, client, ravi_headers):
        """
        Passing negative biomarker values must be rejected with 422 Unprocessable Entity.
        """
        negative_payload = {"readings": {"fasting_glucose": -50}}
        response = client.patch("/reports/r_101/readings", json=negative_payload, headers=ravi_headers)
        assert response.status_code == 422
