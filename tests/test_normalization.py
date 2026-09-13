"""
Tests for the Biomarker Normalization Engine (normalization.py).

Verifies alias mapping, case and whitespace tolerance, canonical preservation,
and safe handling of unknown biomarker names.
"""

import pytest
from normalization import normalize_marker_name, normalize_readings, CANONICAL_MARKERS


class TestBiomarkerNormalization:
    """
    Tests for individual marker name normalization.
    """

    @pytest.mark.parametrize(
        "incoming,expected",
        [
            ("glucose_fasting", "fasting_glucose"),
            ("FBS", "fasting_glucose"),
            ("fbs", "fasting_glucose"),
            ("A1c", "hba1c"),
            ("a1c", "hba1c"),
            ("HbA1C", "hba1c"),
            ("hba1c", "hba1c"),
            ("trigs", "triglycerides"),
            ("triglycerides", "triglycerides"),
        ],
    )
    def test_required_aliases_from_spec(self, incoming, expected):
        """
        Verify all specific alias mappings requested in Part 2 of README.
        """
        assert normalize_marker_name(incoming) == expected

    def test_canonical_markers_pass_through(self):
        """
        All canonical markers defined in the system must map directly to themselves.
        """
        for canonical in CANONICAL_MARKERS:
            assert normalize_marker_name(canonical) == canonical

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("  FBS  ", "fasting_glucose"),
            ("  glucose_fasting\t", "fasting_glucose"),
            ("HBA1C", "hba1c"),
            ("TrIgS", "triglycerides"),
            ("  Vo2_MaX  ", "vo2_max"),
        ],
    )
    def test_whitespace_and_case_insensitivity(self, raw, expected):
        """
        Marker names must be trimmed and matched case-insensitively.
        """
        assert normalize_marker_name(raw) == expected

    @pytest.mark.parametrize(
        "unknown_name",
        [
            "cholesterol_total",
            "crp",
            "vitamin_d",
            "unknown_biomarker_xyz",
            "",
            "   ",
        ],
    )
    def test_unknown_marker_name_returns_none(self, unknown_name):
        """
        Unknown marker names must return None without raising errors.
        """
        assert normalize_marker_name(unknown_name) is None

    def test_non_string_marker_name_returns_none(self):
        """
        Non-string inputs must safely return None.
        """
        assert normalize_marker_name(None) is None
        assert normalize_marker_name(123) is None
        assert normalize_marker_name([]) is None


class TestNormalizeReadingsPayload:
    """
    Tests for the full dictionary transformation helper.
    """

    def test_normalize_readings_with_mixed_aliases(self):
        """
        Verifies that multiple incoming aliases are converted to canonical keys.
        """
        raw_payload = {
            "FBS": 95,
            "A1c": 5.4,
            "trigs": 140,
            "resting_heart_rate": 62,
        }
        normalized = normalize_readings(raw_payload)

        assert normalized == {
            "fasting_glucose": 95,
            "hba1c": 5.4,
            "triglycerides": 140,
            "resting_heart_rate": 62,
        }

    def test_unknown_markers_are_safely_ignored(self):
        """
        Unknown markers must not crash the helper and must not be present in output.
        """
        raw_payload = {
            "FBS": 92,
            "cholesterol_total": 210,
            "hdl": 55,
            "unknown_x": 999,
        }
        normalized = normalize_readings(raw_payload)

        # Only known markers are retained
        assert normalized == {"fasting_glucose": 92}
        assert "cholesterol_total" not in normalized
        assert "hdl" not in normalized
        assert "unknown_x" not in normalized

    def test_non_dict_input_returns_empty_dict(self):
        """
        Passing None or non-dict input safely returns an empty dict.
        """
        assert normalize_readings(None) == {}
        assert normalize_readings("invalid") == {}
        assert normalize_readings([]) == {}
