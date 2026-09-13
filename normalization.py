"""
Biomarker Normalization Engine.

Maps lab-specific biomarker aliases to canonical marker names expected by the
health score engine. Unknown markers are safely ignored to avoid corrupting
the score or crashing requests.
"""

from typing import Any

# Canonical names expected by the scoring engine
CANONICAL_MARKERS = {
    "fasting_glucose",
    "hba1c",
    "triglycerides",
    "resting_heart_rate",
    "vo2_max",
    "reaction_time_ms",
    "sleep_hours",
    "sleep_efficiency",
    "steps_per_day",
}

# Alias dictionary (normalized to lowercase for case-insensitive lookup)
MARKER_ALIASES = {
    # Fasting glucose aliases
    "glucose_fasting": "fasting_glucose",
    "fbs": "fasting_glucose",
    "fasting_glucose": "fasting_glucose",
    # HbA1c aliases
    "a1c": "hba1c",
    "hba1c": "hba1c",
    # Triglycerides aliases
    "trigs": "triglycerides",
    "triglycerides": "triglycerides",
    # Pass-through for other canonical markers
    "resting_heart_rate": "resting_heart_rate",
    "vo2_max": "vo2_max",
    "reaction_time_ms": "reaction_time_ms",
    "sleep_hours": "sleep_hours",
    "sleep_efficiency": "sleep_efficiency",
    "steps_per_day": "steps_per_day",
}


def normalize_marker_name(raw_name: str) -> str | None:
    """
    Return the canonical marker name for an incoming alias, or None if unknown.
    Matching is case-insensitive and ignores leading/trailing whitespace.
    """
    if not isinstance(raw_name, str):
        return None
    cleaned = raw_name.strip().lower()
    return MARKER_ALIASES.get(cleaned)


def normalize_readings(readings: dict[str, Any]) -> dict[str, Any]:
    """
    Transform a dictionary of incoming readings by mapping alias keys to their
    canonical marker names.

    - Recognised aliases (e.g. 'FBS', 'A1c', 'trigs') are mapped to canonical names.
    - Canonical names already formatted are preserved.
    - Unknown markers are safely ignored (neither crashed nor added).
    - If a reading value is not a valid positive number, it is skipped.
    """
    if not isinstance(readings, dict):
        return {}

    normalized = {}
    for raw_marker, value in readings.items():
        canonical_name = normalize_marker_name(raw_marker)
        if canonical_name is None:
            # Unknown marker: ignore safely as specified in the requirements
            continue

        # Keep valid numeric values
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < 0:
            continue

        normalized[canonical_name] = value

    return normalized
