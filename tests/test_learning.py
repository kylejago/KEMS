"""Tests for the KEMS learning engine."""

from datetime import UTC, datetime, timedelta

from kems_core import LearningEngine, Snapshot


def test_learning_builds_profile_and_confidence() -> None:
    """Repeated observations should create a usable rolling profile."""
    start = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    records: list[Snapshot] = []
    for day in range(8):
        for slot in range(12):
            records.append(
                Snapshot(
                    timestamp=start + timedelta(days=day, minutes=15 * slot),
                    house_load_kw=2.0,
                    solar_power_kw=1.0,
                    grid_import_kw=1.0,
                    current_import_rate=28.3,
                )
            )

    learned = LearningEngine().analyse(records, start + timedelta(days=8))

    assert learned.days_observed == 8
    assert learned.samples == 96
    assert learned.ready is True
    assert learned.confidence > 0
    assert learned.average_import_rate_pence == 28.3
    assert learned.predicted_house_energy_tomorrow_kwh is not None
    assert len(learned.predicted_house_tomorrow_hourly_kwh) == 24
