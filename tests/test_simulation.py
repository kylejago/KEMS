"""Tests for the KEMS read-only simulation engine."""

from datetime import UTC, datetime, timedelta

from kems_core import SimulationConfig, SimulationEngine, Snapshot


def test_battery_arbitrage_can_reduce_day_import() -> None:
    """Cheap charging followed by day discharge should reduce day-rate import."""
    start = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=3.49,
            off_peak=True,
            house_load_kw=1.0,
            grid_import_kw=1.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=15),
            current_import_rate=28.3,
            off_peak=False,
            house_load_kw=2.0,
            grid_import_kw=2.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.3,
            off_peak=False,
            house_load_kw=2.0,
            grid_import_kw=2.0,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=31),
        SimulationConfig(
            battery_capacity_kwh=10,
            battery_initial_percent=10,
            battery_reserve_percent=10,
            max_charge_kw=5,
            max_discharge_kw=5,
            export_rate_pence=0,
        ),
    )

    assert result.ready is False  # only two priced intervals are complete
    assert result.simulated_grid_import_kwh is not None
    assert result.actual_grid_import_kwh is not None
    assert result.saving_pence is not None and result.saving_pence > 0
    assert (
        result.avoided_day_rate_import_kwh is not None
        and result.avoided_day_rate_import_kwh > 0
    )
