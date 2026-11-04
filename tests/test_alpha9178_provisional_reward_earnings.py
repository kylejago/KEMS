"""Alpha9.178 provisional reward earnings must remain evidence-bounded."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kems_core.roi_provisional_happy_hour import estimate_partial_reward_hours
from kems_core.roi_reward_audit import build_reward_audit
from kems_core.roi_rewards import apply_reward_roi
from kems_core import ROIState


START = datetime(2026, 11, 1, 13, tzinfo=UTC)
END = START + timedelta(hours=1)
NOW = datetime(2026, 11, 4, 9, tzinfo=UTC)
BOOKING = {
    "start": START.isoformat(),
    "end": END.isoformat(),
    "event_id": "8068",
    "booking_source": "octopus_joined_events",
}
ADJACENT_VERIFIED_HOUR = {
    "start": (START - timedelta(hours=1)).isoformat(),
    "end": START.isoformat(),
    "credit_pence": 261.729143,
    "rate_pence": 35.8828,
    "completed": True,
    "import_kwh": 7.294,
}


def sample(minute, kw=4.0, rate=None):
    return SimpleNamespace(
        timestamp=START + timedelta(minutes=minute),
        grid_import_kw=kw,
        import_rate_pence=rate,
    )


def estimate(readings, *, bookings=None, receipts=None):
    return estimate_partial_reward_hours(
        windows=[BOOKING] if bookings is None else bookings,
        readings=readings,
        completed_receipts=[ADJACENT_VERIFIED_HOUR] if receipts is None else receipts,
        now=NOW,
    )


def test_legacy_partial_hour_counts_only_covered_time_using_adjacent_rate():
    data = estimate([sample(i) for i in range(0, 49, 2)])
    assert len(data) == 1
    value = data[0]
    assert value["import_kwh"] == pytest.approx(3.2)
    assert value["covered_minutes"] == 48.0
    assert value["coverage_percent"] == 80.0
    assert value["credit_pence"] == pytest.approx(3.2 * 35.8828)
    assert value["confidence"] == "low"
    assert value["rate_basis"] == "adjacent_verified_hour_indicative_rate_proxy"
    # Does not fabricate the missing 12 minutes, or a full 16 kWh allowance.
    assert value["credit_pence"] < 4 * 35.8828


def test_captured_tariff_is_preferred_to_legacy_adjacent_rate():
    data = estimate([sample(i, kw=4, rate=20) for i in range(0, 21, 2)])
    assert data[0]["credit_pence"] == pytest.approx(4 * 20 / 3)
    assert data[0]["rate_basis"] == "witnessed_historical_tariff_samples"
    assert data[0]["confidence"] == "medium"


def test_confirmed_complete_receipt_replaces_incomplete_estimate():
    completed = {
        "start": START.isoformat(),
        "end": END.isoformat(),
        "completed": True,
        "rate_pence": 35.8828,
        "import_kwh": 4.0,
        "credit_pence": 143.5312,
    }
    assert estimate([sample(i, rate=20) for i in range(0, 21, 2)], receipts=[
        ADJACENT_VERIFIED_HOUR, completed
    ]) == []


@pytest.mark.parametrize("windows,readings", [
    ([{**BOOKING, "booking_source": "public_available_events", "event_id": None}], [sample(i, rate=20) for i in range(0, 41, 2)]),
    ([BOOKING], [sample(0, rate=20), sample(40, rate=20)]),
    ([BOOKING], [sample(i, rate=None) for i in range(0, 41, 2)]),
    ([BOOKING], []),
])
def test_no_unverified_booking_or_meter_or_tariff_is_invented(windows, readings):
    assert estimate(readings, bookings=windows, receipts=[]) == []


def test_provisional_reward_included_and_audit_preserves_source():
    provisional = estimate([sample(i) for i in range(0, 49, 2)])[0]
    key = f"{START.isoformat()}|{END.isoformat()}"
    payload = {
        key: {
            "day": provisional["day"],
            "pence": provisional["credit_pence"],
            "basis": provisional["basis"],
            "confidence": provisional["confidence"],
            "covered_minutes": provisional["covered_minutes"],
            "coverage_percent": provisional["coverage_percent"],
            "rate_basis": provisional["rate_basis"],
            "observed_import_kwh": provisional["import_kwh"],
            "supplier_settled": False,
        },
    }
    audit = build_reward_audit(
        payload, {}, [BOOKING], [], now=NOW,
        commissioning_date=datetime(2026, 9, 12, tzinfo=UTC).date(),
    )
    assert audit["included_count"] == 1
    assert audit["pending_count"] == 0
    assert audit["provisional_partial_pence"] == pytest.approx(provisional["credit_pence"])
    assert audit["unsettled_total_pence"] == pytest.approx(provisional["credit_pence"])
    assert audit["entries"][0]["status"] == "included_provisional_partial_estimate"
    assert audit["entries"][0]["coverage_percent"] == 80
    assert audit["entries"][0]["event_id"] == "8068"


def test_power_down_modelled_agile_export_is_displayed_but_not_added_to_roi():
    event = SimpleNamespace(
        available=True, session_id="8135", session_start=NOW - timedelta(hours=15),
        session_end=NOW - timedelta(hours=14),
        fixed_export_income_pence=51.12, rewardable_reduction_kwh=None,
        physical_export_verified=True, physical_grid_export_kwh=3.268,
    )
    audit = build_reward_audit(
        {}, {}, [], [event], now=NOW,
        commissioning_date=datetime(2026, 9, 12, tzinfo=UTC).date(),
    )
    assert audit["included_total_pence"] == 0
    assert audit["entries"][0]["modelled_agile_export_income_pence"] == 51.12
    assert audit["entries"][0]["agile_export_income_already_counted"]
    assert audit["entries"][0]["estimated_reward_pence"] is None


def test_roi_reports_provisional_separately_from_meter_supported_reward():
    roi = ROIState(
        system_installed=True, net_investment_gbp=20995.0,
        actual_value_created_total_gbp=385.68,
        actual_value_created_today_gbp=0.0,
    )
    total = 261.729143 + 114.82496
    out = apply_reward_roi(roi, {
        "total": total, "today": 0.0,
        "happy": total, "power_down": 0.0,
        "unsettled": total,
        "provisional": 114.82496,
        "meter_supported": 261.729143,
    })
    assert out.actual_value_created_total_gbp == round(385.68 + total / 100, 2)
    assert out.roi_rewards_provisional_gbp == 1.15
    assert out.roi_rewards_meter_supported_gbp == 2.62
    assert out.roi_rewards_unsettled_gbp == 3.77
