"""
Lab report API — a cut-down service for the take-home task.

Runs with:  uvicorn main:app --reload
Docs at:    http://127.0.0.1:8000/docs
"""

import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator

from scoring import compute_score
from normalization import normalize_readings

app = FastAPI(title="Lab Report API")
security = HTTPBearer()

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me-must-be-at-least-32-bytes-long!")
ALGORITHM = "HS256"


# ---------------------------------------------------------------- fake store

USERS = {
    "asha": {"user_id": "u_001", "password": "asha123", "role": "member"},
    "ravi": {"user_id": "u_002", "password": "ravi123", "role": "member"},
    "dr_mehta": {"user_id": "u_003", "password": "mehta123", "role": "clinician"},
}

REPORTS = {
    "r_100": {
        "report_id": "r_100",
        "owner_id": "u_001",
        "collected_on": "2026-08-14",
        "verified_by_clinician": True,
        "readings": {
            "fasting_glucose": 92,
            "hba1c": 5.3,
            "triglycerides": 168,
            "resting_heart_rate": 64,
            "vo2_max": 41,
            "reaction_time_ms": 392,
            "sleep_hours": 6.4,
            "sleep_efficiency": 0.9,
            "steps_per_day": 6100,
        },
    },
    "r_101": {
        "report_id": "r_101",
        "owner_id": "u_002",
        "collected_on": "2026-08-20",
        "verified_by_clinician": False,
        "readings": {
            "fasting_glucose": 104,
            "hba1c": 5.9,
        },
    },
}


# ---------------------------------------------------------------- models

class LoginRequest(BaseModel):
    username: str
    password: str


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


# ---------------------------------------------------------------- auth

def current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


def get_authorized_report(report_id: str, user: dict, write: bool = False) -> dict:
    report = REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Not found")

    is_clinician = user.get("role") == "clinician"
    is_owner = report.get("owner_id") == user.get("user_id")

    if not (is_clinician or is_owner):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: You do not have permission to access this report",
        )

    if write and report.get("verified_by_clinician") and not is_clinician:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Clinician-verified reports cannot be modified by members",
        )

    return report


# ---------------------------------------------------------------- routes

@app.post("/login")
def login(body: LoginRequest):
    user = USERS.get(body.username)
    if not user or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="Bad credentials")

    token = jwt.encode(
        {
            "user_id": user["user_id"],
            "role": user["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"access_token": token, "token_type": "bearer"}


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
