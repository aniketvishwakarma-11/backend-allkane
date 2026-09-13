"""
Tests for the Health Score Engine (scoring.py).

Locks the score to guarantee regression resistance, verifies reference ranges,
and tests that missing biomarkers do not receive false unearned points.
"""

import pytest
from scoring import compute_score, _marker_score, PILLAR_WEIGHTS, REFERENCE_RANGES


class TestLockTheScore:
    """
    Regression lock: The score is the product. If someone refactors the engine
    next year, these tests guarantee that known patient profiles do not shift.
    """

    def test_full_report_r100_regression_lock(self):
        """
        Locks the score for Asha's full report (r_100).
        Verifies total score and exact points for each of the five pillars.
        """
        r100_readings = {
            "fasting_glucose": 92,
            "hba1c": 5.3,
            "triglycerides": 168,
            "resting_heart_rate": 64,
            "vo2_max": 41,
            "reaction_time_ms": 392,
            "sleep_hours": 6.4,
            "sleep_efficiency": 0.9,
            "steps_per_day": 6100,
        }

        result = compute_score(r100_readings)

        # Total score lock
        assert result["total"] == 946

        # Pillar breakdown lock
        pillars = result["pillars"]
        assert pillars["metabolic"] == 270.0
        assert pillars["fitness"] == 250.0
        assert pillars["cognitive"] == 133.9
        assert pillars["sleep"] == 153.1
        assert pillars["lifestyle"] == 139.4

    def test_partial_report_r101_regression_lock(self):
        """
        Locks the score for Ravi's partial report (r_101).
        Verifies that only metabolic readings are evaluated, and unmeasured
        pillars safely evaluate to 0.0.
        """
        r101_readings = {
            "fasting_glucose": 104,
            "hba1c": 5.9,
        }

        result = compute_score(r101_readings)

        assert result["total"] == 267
        assert result["pillars"]["metabolic"] == 267.5
        assert result["pillars"]["fitness"] == 0.0
        assert result["pillars"]["cognitive"] == 0.0
        assert result["pillars"]["sleep"] == 0.0
        assert result["pillars"]["lifestyle"] == 0.0


class TestMissingMarkersCorrectness:
    """
    Verifies that missing biomarkers do not corrupt scores or receive false 100% points.
    """

    def test_missing_triglycerides_does_not_score_100_percent(self):
        """
        In the old code, missing triglycerides defaulted to 0, which fell inside
        the (0, 150) range, awarding 1.0 (100% score).
        Here we test that missing triglycerides is omitted from the metabolic pillar.
        """
        readings_with_in_range_glucose_and_a1c = {
            "fasting_glucose": 85,  # in-range -> 1.0
            "hba1c": 5.0,           # in-range -> 1.0
            # triglycerides is missing
        }
        score = compute_score(readings_with_in_range_glucose_and_a1c)
        # Average of 2 present markers = (1.0 + 1.0)/2 = 1.0 -> 280.0
        assert score["pillars"]["metabolic"] == 280.0

    def test_present_elevated_triglycerides_reduces_score(self):
        """
        Verifies that providing elevated triglycerides appropriately lowers the score.
        """
        readings_with_elevated_trigs = {
            "fasting_glucose": 85,    # 1.0
            "hba1c": 5.0,             # 1.0
            "triglycerides": 300,     # 150/300 = 0.5
        }
        score = compute_score(readings_with_elevated_trigs)
        # Average = (1.0 + 1.0 + 0.5) / 3 = 2.5 / 3 = 0.8333 * 280 = 233.3
        assert score["pillars"]["metabolic"] == 233.3

    def test_empty_readings_returns_zero(self):
        """
        An empty readings dictionary must safely produce 0 total and 0.0 for all pillars
        without raising ZeroDivisionError.
        """
        result = compute_score({})
        assert result["total"] == 0
        assert all(v == 0.0 for v in result["pillars"].values())

    def test_unknown_markers_do_not_affect_score(self):
        """
        Unknown markers in readings must be ignored and not shift the score.
        """
        base = {"fasting_glucose": 85, "hba1c": 5.0}
        with_unknown = {"fasting_glucose": 85, "hba1c": 5.0, "cholesterol_total": 250, "crp": 3.0}

        assert compute_score(base) == compute_score(with_unknown)


class TestMarkerScoringFormulas:
    """
    Unit tests for the single marker scoring function (_marker_score).
    """

    def test_in_range_returns_one(self):
        assert _marker_score(85, 70, 100) == 1.0
        assert _marker_score(70, 70, 100) == 1.0
        assert _marker_score(100, 70, 100) == 1.0

    def test_below_range_proportional_score(self):
        # 35 is half of 70 -> score 0.5
        assert _marker_score(35, 70, 100) == pytest.approx(0.5)

    def test_above_range_proportional_score(self):
        # 200 is double 100 -> score 100/200 = 0.5
        assert _marker_score(200, 70, 100) == pytest.approx(0.5)

    def test_perfect_health_scores_1000(self):
        """
        When every marker sits inside its reference range, the total score must be 1000.
        """
        perfect_readings = {
            "fasting_glucose": 85,
            "hba1c": 5.0,
            "triglycerides": 100,
            "resting_heart_rate": 60,
            "vo2_max": 45,
            "reaction_time_ms": 250,
            "sleep_hours": 8.0,
            "sleep_efficiency": 0.95,
            "steps_per_day": 10000,
        }
        result = compute_score(perfect_readings)
        assert result["total"] == 1000
        for pillar, weight in PILLAR_WEIGHTS.items():
            assert result["pillars"][pillar] == float(weight)
