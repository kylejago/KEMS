"""Alpha9.180 historical rewards: counted only where independent evidence exists."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core.historical_reward_backfill import (
    estimate_historical_happy_hour_credits,
    historical_import_readings,
)
from kems_core.roi_reward_audit import build_reward_audit

START = datetime(2026, 10, 18, 11, tzinfo=UTC)
END = START + timedelta(hours=1)
NOW = datetime(2026, 11, 4, 14, tzinfo=UTC)
BOOKING = {
    "start": START.isoformat(),
    "end": END.isoformat(),
    "event_id": "oct-18-joined",
    "booking_source": "octopus_joined_events",
}


def reading(minute, *, power=4.0, rate=30.0, stale=(), tariff_stale=()):
    return SimpleNamespace(
        timestamp=START + timedelta(minutes=minute),
        grid_import_kw=power,
        current_import_rate=rate,
        stale_fields=stale,
        tariff_stale_fields=tariff_stale,
    )


def estimate(records, bookings=None):
    return estimate_historical_happy_hour_credits(
        confirmed_bookings=[BOOKING] if bookings is None else bookings,
        history=records,
        completed_receipts=[],
        now=NOW,
    )


def test_october_joined_hour_is_backfilled_from_only_50_witnessed_minutes():
    records = [reading(i) for i in range(0, 51, 5)]
    estimated = estimate(records)
    assert len(estimated) == 1
    credit = estimated[0]
    assert credit["import_kwh"] == pytest.approx(4 * 50 / 60)
    assert credit["credit_pence"] == pytest.approx(4 * 50 / 60 * 30, abs=0.001)
    assert credit["covered_minutes"] == 50.0
    assert credit["coverage_percent"] == 83.3
    assert credit["basis"] == "provisional_historical_five_minute_meter_credit"
    assert credit["rate_basis"] == "retained_five_minute_tariff_observations"
    assert credit["confidence"] == "low"
    assert credit["supplier_settled"] is False


def test_absent_history_or_unpriced_intervals_never_create_credit():
    assert estimate([]) == []
    assert estimate([reading(i, rate=None) for i in range(0, 51, 5)]) == []
    assert estimate([reading(0), reading(30), reading(60)]) == []


def test_covered_history_requires_joined_authority():
    unavailable = {**BOOKING, "event_id": None, "booking_source": "advertised"}
    assert estimate([reading(i) for i in range(0, 51, 5)], [unavailable]) == []


def test_stale_sources_are_excluded_before_any_historical_pricing():
    records = [reading(0), reading(5, stale=("grid_import_kw",))]
    assert len(historical_import_readings(records, [BOOKING])) == 1
    records = [reading(0), reading(5, tariff_stale=("current_import_rate",))]
    assert len(historical_import_readings(records, [BOOKING])) == 1


def test_historical_coverage_is_truthful_about_pending_power_down_rewards():
    key = f"{START.isoformat()}|{END.isoformat()}"
    audit = build_reward_audit(
        {
            key: {
                "day": "2026-10-18",
                "pence": 100,
                "basis": "provisional_historical_five_minute_meter_credit",
                "supplier_settled": False,
                "covered_minutes": 50,
                "coverage_percent": 83.3,
            }
        },
        {},
        [BOOKING],
        [
            SimpleNamespace(
                available=True,
                session_id="historic-pd",
                session_start=START,
                session_end=END,
                physical_export_verified=True,
                physical_grid_export_kwh=2.1,
                rewardable_reduction_kwh=None,
                fixed_export_income_pence=20,
            )
        ],
        now=NOW,
        commissioning_date=datetime(2026, 9, 12).date(),
    )
    assert audit["included_happy_hour_pence"] == 100
    assert audit["provisional_partial_pence"] == 100
    assert audit["entries"][0]["status"] != "supplier_settled"
    coverage = audit["historical_coverage"]
    assert coverage["known_happy_hour_hours"] == 1
    assert coverage["happy_hour_hours_in_roi"] == 1
    assert coverage["known_power_down_events"] == 1
    assert coverage["power_down_events_pending_evidence"] == 1
    assert coverage["all_historical_sessions_discovered"] is False
    assert audit["included_power_down_pence"] == 0
