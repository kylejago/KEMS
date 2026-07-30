"""Tests for KEMS source-data quality scoring."""

from kems_core import Snapshot, assess_quality


def test_quality_reports_missing_configured_fields() -> None:
    """Configured but unavailable observations should reduce quality."""
    quality = assess_quality(
        Snapshot(current_import_rate=28.3),
        {"current_import_rate", "house_load_kw", "solar_power_kw"},
    )

    assert quality.available == 1
    assert quality.configured == 3
    assert "house_load_kw" in quality.missing_fields
    assert quality.score < 50
