"""Regression test for energy-until-off-peak forecasting."""

from datetime import UTC, datetime, timedelta

from kems_core import LearningEngine, Snapshot


def test_sparse_first_day_uses_load_fallback_for_all_remaining_slots() -> None:
    """A first-day forecast must not count only one known 15-minute slot."""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    next_offpeak = now + timedelta(hours=10)
    records = [
        Snapshot(
            timestamp=now - timedelta(minutes=5),
            house_load_kw=2.0,
            next_offpeak_start=next_offpeak,
        )
    ]

    learned = LearningEngine().analyse(records, now)

    assert learned.predicted_energy_until_offpeak_kwh == 20.0
