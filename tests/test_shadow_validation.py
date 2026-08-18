"""Independent safety and tracking tests for alpha7.19 shadow validation."""

from __future__ import annotations

from kems_core.models import ControlConfig, ControlState, SimulationState
from kems_core.shadow_validation import (
    shadow_plan_vs_outcome,
    validate_shadow_command,
)


def _control(**changes) -> ControlState:
    values = {
        "desired_charge_power_kw": 0.0,
        "desired_battery_to_home_power_kw": 1.5,
        "desired_battery_export_power_kw": 4.5,
        "desired_total_discharge_power_kw": 6.0,
        "desired_min_soc_percent": 10.0,
        "desired_grid_export_allowed": True,
        "total_kh7_ac_output_kw": 6.0,
        "total_site_import_kw": 0.0,
        "data_fresh": True,
        "plan_safe": True,
    }
    values.update(changes)
    return ControlState(**values)


def _simulation(**changes) -> SimulationState:
    values = {
        "ready": True,
        "current_simulated_battery_charge_power_kw": 0.0,
        "current_simulated_battery_to_home_power_kw": 1.5,
        "current_simulated_battery_export_power_kw": 4.5,
    }
    values.update(changes)
    return SimulationState(**values)


def test_safe_shadow_command_passes_independent_envelope() -> None:
    result = validate_shadow_command(_control(), ControlConfig())
    assert result["passed"] is True
    assert result["passed_checks"] == result["total_checks"]
    assert result["failed_checks"] == []


def test_shadow_validation_rejects_simultaneous_charge_and_discharge() -> None:
    result = validate_shadow_command(
        _control(desired_charge_power_kw=2.0),
        ControlConfig(),
    )
    assert result["passed"] is False
    assert "no_charge_discharge_conflict" in result["failed_checks"]


def test_shadow_validation_rejects_export_when_export_is_blocked() -> None:
    result = validate_shadow_command(
        _control(desired_grid_export_allowed=False),
        ControlConfig(),
    )
    assert result["passed"] is False
    assert "export_permission" in result["failed_checks"]


def test_shadow_validation_rejects_command_above_inverter_limit() -> None:
    result = validate_shadow_command(
        _control(
            desired_battery_export_power_kw=7.5,
            desired_total_discharge_power_kw=8.0,
            total_kh7_ac_output_kw=8.0,
        ),
        ControlConfig(),
    )
    assert result["passed"] is False
    assert "discharge_limit" in result["failed_checks"]
    assert "export_limit" in result["failed_checks"]
    assert "inverter_limit" in result["failed_checks"]


def test_shadow_plan_tracking_reports_target_outcome_and_difference() -> None:
    result = shadow_plan_vs_outcome(
        _control(),
        _simulation(current_simulated_battery_export_power_kw=4.3),
    )
    assert result["basis"] == "digital_twin"
    assert result["available"] is True
    assert result["target"]["battery_export_kw"] == 4.5
    assert result["outcome"]["battery_export_kw"] == 4.3
    assert result["difference"]["battery_export_kw"] == -0.2
    assert result["within_tolerance"]["battery_export_kw"] is True


def test_shadow_tracking_marks_large_miss_outside_tolerance() -> None:
    result = shadow_plan_vs_outcome(
        _control(),
        _simulation(current_simulated_battery_export_power_kw=2.5),
    )
    assert result["within_tolerance"]["battery_export_kw"] is False
    assert result["tracking_score_percent"] < 100.0
