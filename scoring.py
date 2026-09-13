"""
Health score engine.

Takes a set of biomarker readings and produces a score out of 1000
across five pillars. The score is the product, so it has to be right.
"""

PILLAR_WEIGHTS = {
    "metabolic": 280,
    "fitness": 250,
    "cognitive": 150,
    "sleep": 160,
    "lifestyle": 160,
}

# Reference ranges: (low, high). A reading inside the range scores 1.0,
# outside scores proportionally less.
REFERENCE_RANGES = {
    "fasting_glucose": ("metabolic", 70, 100),
    "hba1c": ("metabolic", 4.0, 5.6),
    "triglycerides": ("metabolic", 0, 150),
    "resting_heart_rate": ("fitness", 50, 70),
    "vo2_max": ("fitness", 35, 60),
    "reaction_time_ms": ("cognitive", 200, 350),
    "sleep_hours": ("sleep", 7, 9),
    "sleep_efficiency": ("sleep", 0.85, 1.0),
    "steps_per_day": ("lifestyle", 7000, 15000),
}


def _marker_score(value, low, high):
    """Return 0.0 to 1.0 for how well a single reading sits in range."""
    if low <= value <= high:
        return 1.0
    if value < low:
        return max(0.0, value / low) if low else 0.0
    return max(0.0, high / value)


def compute_score(readings):
    """
    readings: dict of marker name -> value, e.g. {"hba1c": 5.2}

    Returns dict with the total score and the per-pillar breakdown.
    Biomarkers are only scored if present and valid in readings,
    preventing missing tests from receiving unearned points or zero penalties.
    """
    pillar_totals = {p: 0.0 for p in PILLAR_WEIGHTS}
    pillar_counts = {p: 0 for p in PILLAR_WEIGHTS}

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

    pillars = {}
    total = 0.0
    for pillar, weight in PILLAR_WEIGHTS.items():
        if pillar_counts[pillar] > 0:
            ratio = pillar_totals[pillar] / pillar_counts[pillar]
            points = ratio * weight
        else:
            points = 0.0
        pillars[pillar] = round(points, 1)
        total += points

    return {
        "total": round(total),
        "pillars": pillars,
    }
