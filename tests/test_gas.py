"""Tests for KEMS gas aggregation."""

from datetime import UTC, datetime, timedelta

from kems_core import GasEngine, Snapshot


def test_direct_octopus_daily_gas_values_are_used() -> None:
    """Current accumulated gas sensors should produce daily and monthly totals."""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=now - timedelta(days=1),
            gas_current_rate=6.2,
            gas_standing_charge=31.0,
            gas_usage_today_kwh=8.0,
            gas_cost_today_pence=80.6,
        ),
        Snapshot(
            timestamp=now,
            gas_current_rate=6.2,
            gas_standing_charge=31.0,
            gas_usage_today_kwh=3.0,
            gas_cost_today_pence=49.6,
        ),
    ]

    summary = GasEngine().summarise(records, now)

    assert summary.available is True
    assert summary.usage_today_kwh == 3.0
    assert summary.cost_today_pence == 49.6
    assert summary.usage_month_kwh == 11.0
    assert summary.typical_daily_usage_kwh == 8.0


def test_cumulative_gas_meter_fallback_uses_positive_deltas() -> None:
    """KEMS should calculate gas use from cumulative kWh when needed."""
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(timestamp=now - timedelta(hours=2), gas_meter_total_kwh=100.0),
        Snapshot(
            timestamp=now - timedelta(hours=1),
            gas_meter_total_kwh=101.5,
            gas_current_rate=6.0,
            gas_standing_charge=30.0,
        ),
        Snapshot(timestamp=now, gas_meter_total_kwh=102.0),
    ]

    summary = GasEngine().summarise(records, now)

    assert summary.usage_today_kwh == 2.0
    assert summary.cost_today_pence == 42.0
