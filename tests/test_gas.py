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


def test_octopus_gas_midnight_carryover_does_not_inflate_today_or_month() -> None:
    """A stale prior-day maximum must not beat a later corrected daily sensor."""
    now = datetime(2026, 11, 15, 19, 38, tzinfo=UTC)
    previous = datetime(2026, 11, 14, 23, 55, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=previous,
            gas_usage_today_kwh=19.546,
            gas_cost_today_pence=193.0,
            gas_current_rate=8.4362,
            gas_standing_charge=28.54,
        ),
        Snapshot(
            timestamp=datetime(2026, 11, 15, 0, 4, tzinfo=UTC),
            gas_usage_today_kwh=19.546,
            gas_cost_today_pence=193.0,
        ),
        Snapshot(
            timestamp=datetime(2026, 11, 15, 6, 40, tzinfo=UTC),
            gas_usage_today_kwh=5.0,
            gas_cost_today_pence=75.0,
        ),
        Snapshot(
            timestamp=now,
            gas_usage_today_kwh=10.83913,
            gas_cost_today_pence=120.0,
        ),
    ]
    summary = GasEngine().summarise(records, now)
    assert summary.usage_today_kwh == 10.839
    assert summary.cost_today_pence == 120.0
    assert summary.usage_month_kwh == 30.385
    assert summary.cost_month_pence == 313.0


def test_out_of_order_gas_snapshot_cannot_overwrite_newer_reset_value() -> None:
    now = datetime(2026, 11, 15, 19, 38, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=now,
            gas_usage_today_kwh=10.839,
            gas_cost_today_pence=120.0,
        ),
        Snapshot(
            timestamp=now - timedelta(hours=19),
            gas_usage_today_kwh=19.546,
            gas_cost_today_pence=193.0,
        ),
    ]
    summary = GasEngine().summarise(records, now)
    assert summary.usage_today_kwh == 10.839
    assert summary.cost_today_pence == 120.0
