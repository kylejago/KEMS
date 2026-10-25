"""Alpha9.138: a verified upcoming Happy Hour may create guarded physical headroom."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.kems.happy_hour_physical_preparation import (
    apply_verified_happy_hour_preparation,
)
from custom_components.kems.kems_core.models import ControlState, Snapshot


START = datetime(2026, 10, 25, 11, tzinfo=UTC)
END = START + timedelta(hours=2)
NOW = datetime(2026, 10, 25, 9, 24, tzinfo=UTC)


def _joined(two: bool = True):
    bookings = [
        {
            "start": START.isoformat(),
            "end": (START + timedelta(hours=1)).isoformat(),
            "event_id": "7723",
            "booking_source": "octopus_joined_events",
        },
    ]
    if two:
        bookings.append(
            {
                "start": (START + timedelta(hours=1)).isoformat(),
                "end": END.isoformat(),
                "event_id": "7724",
                "booking_source": "octopus_joined_events",
            }
        )
    return {"status": "booked", "bookings": bookings}


def _case():
    control = ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_economic_floor_hold",
        desired_work_mode="Self Use",
        desired_grid_export_allowed=True,
        desired_battery_export_power_kw=0.0,
        control_enabled=True,
        commissioned=True,
        data_fresh=True,
        plan_safe=True,
        grid_available=True,
        preflight_passed=27,
        preflight_total=27,
    )
    snapshot = Snapshot(
        timestamp=NOW,
        battery_soc=97,
        solar_power_kw=2.885,
        house_load_kw=2.188,
        grid_export_kw=0.015,
        grid_import_kw=0.022,
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0,
        ev_power_age_seconds=0.9,
    )
    context = {
        "start": START.isoformat(),
        "end": END.isoformat(),
        "source": "octopus_energy",
        "mode": "preparation",
        "preparation_in_current_horizon": True,
        "physical_soc_verified": True,
        "physical_charge_headroom_verified": True,
        "current_physical_soc_percent": 97.0,
        "physical_required_headroom_export_kwh": 9.856,
        "required_headroom_export_kwh": 6.482,  # digital twin, not live authority
    }
    agile = {
        "generated_at": NOW.isoformat(),
        "rolling_export_plan": {
            "available": True,
            "generated_at": NOW.isoformat(),
            "dispatch_mode": "economic_floor_hold",
            "current_battery_export_target_kw": 0.0,
            "physical_planning_evidence": {"available": True},
            "physical_house_budget_evidence": {
                "available": True,
                "exportable_ac_kwh": 22.410,
            },
        },
        "today_slots": [
            {
                "valid_from": datetime(2026, 10, 25, h, m, tzinfo=UTC).isoformat(),
                "valid_to": (
                    datetime(2026, 10, 25, h, m, tzinfo=UTC)
                    + timedelta(minutes=30)
                ).isoformat(),
                "rate_pence": rate,
            }
            for h, m, rate in [
                (9, 0, 0.73),
                (9, 30, 0.86),
                (10, 0, 0.56),
                (10, 30, 0.17),
            ]
        ],
    }
    config = SimpleNamespace(
        max_discharge_kw=10.0,
        export_limit_kw=7.0,
        inverter_limit_kw=10.0,
        emergency_stop=False,
    )
    simulation = SimpleNamespace(max_discharge_kw=10.0)
    return {
        "control": control,
        "snapshot": snapshot,
        "booking": _joined(),
        "context": context,
        "agile_state": agile,
        "now": NOW,
        "config": config,
        "simulation_config": simulation,
        "power_down_active": False,
        "agile_selected": True,
    }


def test_real_morning_regression_exports_only_verified_physical_headroom():
    args = _case()
    new, evidence = apply_verified_happy_hour_preparation(**args)
    assert evidence["status"] == "submitted_to_independent_physical_guard"
    assert evidence["physical_required_headroom_export_kwh"] == 9.856
    assert evidence["physically_budgeted_preparation_kwh"] == 9.856
    assert sum(
        item["planned_battery_export_kwh"] for item in evidence["selected_slots"]
    ) == pytest.approx(9.856, abs=0.005)
    assert 0 < new.desired_battery_export_power_kw <= 7.0
    assert new.operating_reason == "happy_hour_verified_physical_preparation"
    assert new.desired_work_mode == "Feed-in First"
    assert new.commands_permitted is False  # existing final FoxESS gate owns writes
    assert new.desired_total_discharge_power_kw == new.desired_battery_export_power_kw
    assert args["agile_state"]["rolling_export_plan"]["dispatch_mode"] == (
        "economic_floor_hold"
    )
    assert args["context"]["required_headroom_export_kwh"] == 6.482


@pytest.mark.parametrize(
    "change,blocked",
    [
        ({"booking": _joined(False)}, "joined_window_not_independently_confirmed"),
        ({"agile_selected": False}, "no_upcoming_confirmed_eligible_event"),
        ({"power_down_active": True}, "higher_priority_event_or_cheap_period"),
        ({"context": {"source": "manual"}}, "no_upcoming_confirmed_eligible_event"),
        (
            {"context": {"physical_soc_verified": False}},
            "no_verified_same_scan_physical_soc",
        ),
        (
            {"context": {"physical_required_headroom_export_kwh": None}},
            "invalid_physical_headroom_or_house_budget",
        ),
        (
            {"context": {"current_physical_soc_percent": 91}},
            "no_verified_same_scan_physical_soc",
        ),
        (
            {"rolling": {"physical_house_budget_evidence": {"available": False}}},
            "same_scan_physical_house_budget_unverified",
        ),
        (
            {"rolling": {"generated_at": "2026-10-25T08:00:00+00:00"}},
            "same_scan_physical_house_budget_unverified",
        ),
    ],
)
def test_missing_join_or_physical_proof_cannot_authorise_export(change, blocked):
    args = _case()
    if "context" in change:
        args["context"].update(change["context"])
    elif "rolling" in change:
        args["agile_state"]["rolling_export_plan"].update(change["rolling"])
    else:
        args.update(change)
    original = args["control"]
    new, evidence = apply_verified_happy_hour_preparation(**args)
    assert new is original
    assert new.desired_battery_export_power_kw == 0
    assert evidence["requested_export_kw"] == 0
    assert evidence["status"] == blocked


def test_household_budget_remains_hard_cap_on_preparation_schedule():
    args = _case()
    args["agile_state"]["rolling_export_plan"]["physical_house_budget_evidence"][
        "exportable_ac_kwh"
    ] = 1.0
    control, report = apply_verified_happy_hour_preparation(**args)
    assert report["physically_budgeted_preparation_kwh"] == 1.0
    assert sum(
        item["planned_battery_export_kwh"] for item in report["selected_slots"]
    ) <= 1.001
    assert control.desired_battery_export_power_kw >= 0.0


def test_original_agile_and_happy_hour_safety_gates_remain_authoritative():
    from pathlib import Path

    root = Path(__file__).parents[1]
    coordinator = (
        root / "custom_components" / "kems" / "coordinator.py"
    ).read_text(encoding="utf-8")
    a = coordinator.index("control = align_agile_control_state(")
    b = coordinator.index("apply_verified_happy_hour_preparation(")
    c = coordinator.index("guard_paid_agile_physical_export(")
    d = coordinator.index("self._foxess_control.async_update(")
    assert a < b < c < d
    diagnostics = (
        root / "custom_components" / "kems" / "diagnostics.py"
    ).read_text(encoding="utf-8")
    assert '"happy_hour_preparation_dispatch"' in diagnostics
    assert '"no_upcoming_confirmed_eligible_event"' not in coordinator


def test_no_live_preparation_after_reward_starts_or_when_grid_islanded():
    args = _case()
    args["now"] = START
    _state, report = apply_verified_happy_hour_preparation(**args)
    assert report["status"] == "no_upcoming_confirmed_eligible_event"
    args = _case()
    args["control"] = replace(args["control"], island_mode_active=True)
    result, report = apply_verified_happy_hour_preparation(**args)
    assert report["status"] == "physical_control_gate_closed"
    assert result.desired_battery_export_power_kw == 0


def test_price_requirements_never_invent_a_slot_or_use_negative_prices():
    args = _case()
    args["agile_state"]["today_slots"] = []
    new, report = apply_verified_happy_hour_preparation(**args)
    assert new.desired_battery_export_power_kw == 0
    assert report["status"] == "awaiting_selected_physical_preparation_slot"
    args["agile_state"]["today_slots"] = [
        {
            "valid_from": NOW.isoformat(),
            "valid_to": (NOW + timedelta(minutes=30)).isoformat(),
            "rate_pence": -2.0,
        }
    ]
    new, report = apply_verified_happy_hour_preparation(**args)
    assert new.desired_battery_export_power_kw == 0
    assert report["status"] == "awaiting_selected_physical_preparation_slot"
