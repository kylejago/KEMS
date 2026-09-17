"""Alpha9.52 physical-export authority and FoxESS shadow regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import kems_core
from kems_core import ControlConfig, ControlState, SimulationState
from kems_core.foxess_command_shadow import WAIT, build_foxess_command_shadow

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha952_shadow_export_authority_test"


def _load_alignment():
    package = ModuleType(PACKAGE)
    package.__path__ = [str(KEMS_ROOT)]
    sys.modules[PACKAGE] = package
    sys.modules[f"{PACKAGE}.kems_core"] = kems_core

    name = f"{PACKAGE}.agile_control_alignment"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS_ROOT / "agile_control_alignment.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


alignment = _load_alignment()


def _rolling_export_state() -> dict:
    return {
        "rolling_export_plan": {
            "available": True,
            "dispatch_mode": "export",
            "dispatch_action": "Counterfactual Full-KEMS export target",
            "current_house_battery_kw": 0.862,
            "current_battery_discharge_target_kw": 6.4,
            "current_battery_export_target_kw": 5.538,
            "target_soc_percent": 49.4,
        }
    }


def _no_export_control() -> ControlState:
    return ControlState(
        operating_reason="normal",
        desired_work_mode="Self Use",
        desired_battery_to_home_power_kw=0.862,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.862,
        desired_grid_export_allowed=False,
        desired_min_soc_percent=10.0,
        data_fresh=True,
        plan_safe=True,
        control_enabled=False,
        commissioned=False,
        real_backend_available=False,
        commands_permitted=False,
        blocked_reason="Virtual backend only",
    )


def test_counterfactual_export_cannot_leak_into_physical_control_state() -> None:
    """No-export live policy must remain authoritative at the control boundary."""
    simulation = SimulationState(
        ready=True,
        no_export_mode_active=True,
        actual_export_income_pence=0.0,
        simulated_export_income_pence=121.23,
        simulated_battery_export_kwh=5.054,
    )
    agile_state = _rolling_export_state()
    config = ControlConfig(
        export_limit_kw=6.4,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
    )

    control_view, _, alignment_status = alignment.aligned_agile_control_views(
        simulation,
        agile_state,
    )
    assert alignment_status["target"]["battery_export_kw"] == 5.538
    assert control_view.current_simulated_battery_export_power_kw == 5.538
    assert control_view.simulated_battery_export_kwh == 5.054
    assert control_view.simulated_export_income_pence == 121.23
    assert control_view.actual_export_income_pence == 0.0

    physical = alignment.align_agile_control_state(
        _no_export_control(),
        simulation,
        agile_state,
        config,
    )

    assert physical.desired_grid_export_allowed is False
    assert physical.desired_battery_export_power_kw == 0.0
    assert physical.desired_battery_to_home_power_kw == 0.862
    assert physical.desired_total_discharge_power_kw == 0.862
    assert physical.desired_work_mode == "Self Use"
    assert physical.total_kh7_ac_output_kw == 0.862
    assert physical.real_backend_available is False
    assert physical.commands_permitted is False
    assert physical.control_enabled is False
    assert physical.commissioned is False

    shadow = build_foxess_command_shadow(physical, export_limit_kw=6.4)
    proposed = shadow["proposed_foxess_command"]
    assert shadow["configured_export_limit_kw"] == 6.4
    assert proposed["export_power_limit_w"] == 0
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["discharge_enabled"] is False
    assert proposed["grid_export_allowed"] is False
    assert shadow["commands_permitted"] is False
    assert shadow["real_hardware_writes"] == "blocked"
    assert shadow["maximum_allowed_stage"] == "shadow"

    # The Full-KEMS rolling plan remains untouched and can still model export.
    assert agile_state["rolling_export_plan"]["current_battery_export_target_kw"] == 5.538
    assert (
        agile_state["rolling_export_plan"]["current_battery_discharge_target_kw"]
        == 6.4
    )


def test_contradictory_no_export_state_fails_closed_before_force_discharge() -> None:
    """Defense in depth must reject export intent when export permission is off."""
    contradictory = ControlState(
        operating_reason="agile_rolling_export",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=0.862,
        desired_battery_export_power_kw=5.538,
        desired_total_discharge_power_kw=6.4,
        desired_grid_export_allowed=False,
        data_fresh=True,
        plan_safe=True,
    )

    result = build_foxess_command_shadow(
        contradictory,
        export_limit_kw=6.4,
    )
    proposed = result["proposed_foxess_command"]

    assert result["translation_status"] == WAIT
    assert "grid export is disabled" in result["translation_reason"]
    assert result["configured_export_limit_kw"] == 6.4
    assert proposed["export_power_limit_w"] == 0
    assert proposed["work_mode"] is None
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["discharge_enabled"] is False
    assert proposed["remote_control_required"] is False
    assert result["commands_permitted"] is False
    assert result["real_hardware_writes"] == "blocked"
