"""Alpha9.135: paid Agile price-slot intent and conservative reserve planning."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from custom_components.kems import agile_control_alignment as alignment
from custom_components.kems import agile_physical_planning as planning

NOW = "2026-10-24T15:51:30+01:00"


def _plan(*, current_slot=False, deadline_kwh=0.0):
    selected = [
        {
            "valid_from": "2026-10-24T16:00:00+01:00",
            "valid_to": "2026-10-24T16:30:00+01:00",
            "planned_battery_export_kwh": 2.5,
        }
    ]
    if current_slot:
        selected.append(
            {
                "valid_from": "2026-10-24T15:30:00+01:00",
                "valid_to": "2026-10-24T16:00:00+01:00",
                "planned_battery_export_kwh": 0.2,
            }
        )
    return {
        "available": True,
        "generated_at": NOW,
        "selected_slots": selected,
        "required_in_current_slot_kwh": deadline_kwh,
        "current_house_battery_kw": 0.66,
        "current_battery_discharge_target_kw": 1.301,
        "current_battery_export_target_kw": 0.641,
    }


def _target(plan):
    target, _ = alignment._rolling_target(
        SimpleNamespace(saving_session_active=False),
        {"rolling_export_plan": plan},
    )
    return target


def test_unselected_cheap_export_never_becomes_live_intent():
    target = _target(_plan())
    assert target["battery_to_home_kw"] == 0.66
    assert target["battery_export_kw"] == 0.0
    assert target["total_discharge_kw"] == 0.66


def test_current_selected_slot_can_export_up_to_allocation():
    assert _target(_plan(current_slot=True))["battery_export_kw"] == 0.641


def test_explicit_mandatory_deadline_keeps_independent_path():
    assert _target(_plan(deadline_kwh=0.3))["battery_export_kw"] == 0.641


def test_conservative_forecast_budget_matches_live_guard(monkeypatch):
    monkeypatch.setattr(
        planning,
        "physical_planning_soc",
        lambda manager, now, config: (
            60.662,
            {"available": True, "physical_energy_lower_bound_kwh": 34.225},
        ),
    )
    manager = SimpleNamespace(
        _kems_physical_planning_context={
            "forecast_plan": SimpleNamespace(
                ready=True,
                expected_house_remaining_today_kwh=10.841,
                expected_solar_remaining_today_kwh=1.18,
                confidence_percent=90.0,
            )
        }
    )
    config = SimpleNamespace(
        discharge_efficiency=0.95,
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
    )
    budget, proof = planning.conservative_physical_export_budget(
        manager, now=datetime.fromisoformat(NOW), config=config
    )
    assert budget is not None and 12.4 < budget < 12.7
    assert proof["solar_credit_kwh"] == 0.295
    assert proof["protected_house_stored_kwh"] > 13.0


def test_missing_physical_house_forecast_never_grants_budget(monkeypatch):
    monkeypatch.setattr(
        planning,
        "physical_planning_soc",
        lambda manager, now, config: (
            60.662,
            {"available": True, "physical_energy_lower_bound_kwh": 34.225},
        ),
    )
    manager = SimpleNamespace(_kems_physical_planning_context={})
    budget, proof = planning.conservative_physical_export_budget(
        manager, now=datetime.fromisoformat(NOW), config=SimpleNamespace()
    )
    assert budget is None
    assert proof["available"] is False
