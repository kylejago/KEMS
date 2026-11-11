"""Dual-SOC regression: 15% paid export, 10% household until cheap charging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kems_core.agile_live_reserve import (
    physically_exportable_paid_agile_energy_kwh,
    protected_precheap_house_stored_kwh,
    total_discharge_deadline_goal_soc_percent,
)
from kems_core.discharge_slot_ledger import (
    allocate_total_discharge_slots,
    required_total_discharge_kwh,
)

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def test_nov11_2026_measured_25_percent_case_retains_separate_reserves() -> None:
    """Do not double-reserve 15% and future household energy above the 10% floor."""
    capacity = 56.42
    stored = 13.681  # Verified physical lower bound in user's 20:24 diagnostic.
    house_forecast_ac = 3.906
    efficiency = 0.95
    guarded = protected_precheap_house_stored_kwh(
        capacity_kwh=capacity,
        export_target_soc_percent=15.0,
        protected_house_stored_kwh=house_forecast_ac / efficiency,
        separate_house_floor_proven=True,
    )
    original = protected_precheap_house_stored_kwh(
        capacity_kwh=capacity,
        export_target_soc_percent=15.0,
        protected_house_stored_kwh=house_forecast_ac / efficiency,
        separate_house_floor_proven=False,
    )
    assert guarded == pytest.approx(9.754, abs=0.001)
    assert original == pytest.approx(12.575, abs=0.001)
    assert guarded < original

    # The *final*, more conservative physical budget includes the additional
    # 2kWh / 20% home buffer; it still caps exports even if the economic
    # scheduler discovers more opportunity with the 10% HOUSE floor.
    physically_allowed_stored = physically_exportable_paid_agile_energy_kwh(
        stored_kwh=stored,
        capacity_kwh=capacity,
        export_reserve_percent=15.0,
        protected_house_kwh=6.112,
    )
    assert physically_allowed_stored == pytest.approx(1.927, abs=0.001)
    assert physically_allowed_stored * efficiency == pytest.approx(1.831, abs=0.001)
    assert physically_allowed_stored <= stored - capacity * 0.15
    assert physically_allowed_stored <= stored - capacity * 0.10 - 6.112


@pytest.mark.parametrize(
    ("forecast", "proof", "expected"),
    [
        (15.0, True, 10.0),
        (None, True, 10.0),
        (15.0, False, 15.0),
        (18.0, True, 18.0),  # Preserve a genuinely higher overnight requirement.
        (18.0, False, 18.0),
    ],
)
def test_house_deadline_goal_does_not_lower_export_floor(
    forecast: float | None, proof: bool, expected: float
) -> None:
    assert (
        total_discharge_deadline_goal_soc_percent(
            export_target_soc_percent=15.0,
            forecast_minimum_precheap_soc_percent=forecast,
            separate_house_floor_proven=proof,
        )
        == expected
    )


def test_missing_house_evidence_cannot_release_extra_export() -> None:
    # Even a proven physical battery SOC is insufficient without a reliable
    # remaining-house forecast and its independent safety buffer.
    assert protected_precheap_house_stored_kwh(
        capacity_kwh=56.42,
        export_target_soc_percent=15.0,
        protected_house_stored_kwh=float("nan"),
        separate_house_floor_proven=True,
    ) == pytest.approx(56.42)
    assert (
        total_discharge_deadline_goal_soc_percent(
            export_target_soc_percent=15.0,
            forecast_minimum_precheap_soc_percent=None,
            separate_house_floor_proven=False,
        )
        == 15.0
    )


def _slot(start: datetime, price: float) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": price,
        "label": start.strftime("%H:%M"),
    }


def test_house_to_ten_plan_has_more_total_capacity_without_export_entitlement() -> None:
    now = datetime(2026, 11, 11, 20, 30, tzinfo=UTC)
    deadline = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)
    slots = [_slot(now + timedelta(minutes=30 * n), 22.0 - n) for n in range(6)]
    segments = [
        {
            "start": (now + timedelta(minutes=5 * n)).isoformat(),
            "end": (now + timedelta(minutes=5 * (n + 1))).isoformat(),
            "solar_kw": 0.0,
            "battery_kw": 7.0,
        }
        for n in range(36)
    ]

    target15 = required_total_discharge_kwh(
        battery_capacity_kwh=56.42,
        soc_percent=24.249,
        target_soc_percent=15.0,
        discharge_efficiency=0.95,
    )
    target10 = required_total_discharge_kwh(
        battery_capacity_kwh=56.42,
        soc_percent=24.249,
        target_soc_percent=10.0,
        discharge_efficiency=0.95,
    )
    assert target15 == pytest.approx(4.957, abs=0.001)
    assert target10 == pytest.approx(7.637, abs=0.001)
    assert target10 > target15 + 2.6

    plan = allocate_total_discharge_slots(
        slots=slots,
        capacity_segments=segments,
        now=now,
        deadline=deadline,
        required_discharge_kwh=target10,
        house_kw=1.68,
        export_limit_kw=7.0,
        safety_headroom_kwh=3.5,
    )
    assert plan.unallocated_total_discharge_kwh == pytest.approx(0.0, abs=0.001)
    assert plan.allocated_total_discharge_kwh == pytest.approx(target10, abs=0.001)
    assert plan.planned_house_battery_kwh > 0.0
    # This is an uncapped economic candidate, not permission to export it.
    # The live physical budget and FoxESS command guard impose the smaller
    # 1.831 kWh AC allowance in the actual diagnostic scenario.
    assert plan.planned_battery_export_kwh > 0.0
    assert all(allocation.valid_from < deadline for allocation in plan.allocations)


def test_runtime_keeps_two_distinct_targets_and_final_guard() -> None:
    rolling = (ROOT / "agile_rolling_replan_runtime.py").read_text()
    ledger = (ROOT / "agile_total_discharge_ledger.py").read_text()
    path = (ROOT / "agile_forecast_path_scheduler.py").read_text()
    dominance = (ROOT / "agile_deadline_dominance.py").read_text()
    floor = (ROOT / "agile_safety_floor.py").read_text()
    physical = (ROOT / "kems_core" / "agile_live_reserve.py").read_text()

    assert "protected_precheap_house_stored_kwh(" in rolling
    assert '"household_cheap_start_minimum_soc_percent": 10.0' in rolling
    assert "total_discharge_deadline_goal_soc_percent(" in ledger
    assert '"deliberate_export_floor_soc_percent": round(target, 3)' in ledger
    assert "total_discharge_deadline_goal_soc_percent(" in path
    assert '"physical_export_cap_still_required": True' in path
    assert "return cap_physical_ac_export(state, resolved, now=now)" in dominance
    assert "HARD_SAFETY_FLOOR_SOC_PERCENT = 10.0" in floor
    assert "HARD_SAFETY_RECOVERY_SOC_PERCENT = 12.0" in floor
    assert "allow_paid_agile_house_discharge_to_ten_percent(" in physical
    for protected in ('"cheap_charge"', '"happy_hour_charge"', '"power_down_session"'):
        assert protected in ledger
    assert "_enforce_cheap_boundary(state, deadline)" in ledger


def test_both_agile_dashboard_views_name_export_and_house_floors_separately() -> None:
    legacy = (ROOT / "dashboard_alpha740_agile_primary.py").read_text()
    focused = (ROOT / "agile_operator_dashboard_runtime.py").read_text()
    for dashboard in (legacy, focused):
        assert "**Deliberate-export minimum SOC:**" in dashboard
        assert "household_cheap_start_minimum_soc_percent" in dashboard
        assert "sensor.kems_projected_soc_at_cheap_period" in dashboard
        assert "estimate" in dashboard
        assert "Export earnings evidence:" in dashboard
        assert "supplier settlement" in dashboard
        assert "Power Down" in dashboard
        assert "**Target SOC at cheap start:**" not in dashboard
