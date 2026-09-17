"""Alpha9.52 physical export-permission projection regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import kems_core
from kems_core.foxess_command_shadow import build_foxess_command_shadow
from kems_core.models import ControlConfig, ControlState, SimulationState
from kems_core.shadow_validation import validate_shadow_command

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_alpha952_physical_export_projection_test"


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


def _config() -> ControlConfig:
    return ControlConfig(
        normal_reserve_percent=15.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        export_limit_kw=6.4,
        inverter_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )


def _control(*, export_allowed: bool) -> ControlState:
    return ControlState(
        operating_mode="simulate",
        desired_work_mode="Self Use",
        desired_min_soc_percent=15.0,
        desired_grid_export_allowed=export_allowed,
        data_fresh=True,
        plan_safe=True,
        blocked_reason="Virtual backend only",
        preflight_passed=15,
        preflight_total=15,
        preflight_status="PASS",
    )


def _agile_state() -> dict:
    return {
        "current_action": "planned battery export; house first",
        "rolling_export_plan": {
            "available": True,
            "dispatch_mode": "price_optimised",
            "dispatch_action": "price-optimised discharge; house first",
            "current_house_battery_kw": 0.862,
            "current_battery_discharge_target_kw": 6.4,
            "current_battery_export_target_kw": 5.538,
            "target_soc_percent": 15.0,
        },
    }


def test_no_export_permission_projects_counterfactual_export_to_house_only() -> None:
    """The physical command candidate must not inherit forbidden grid export."""
    projected = alignment.align_agile_control_state(
        _control(export_allowed=False),
        SimulationState(),
        _agile_state(),
        _config(),
    )

    assert projected.desired_grid_export_allowed is False
    assert projected.desired_battery_to_home_power_kw == 0.862
    assert projected.desired_battery_export_power_kw == 0.0
    assert projected.desired_total_discharge_power_kw == 0.862
    assert projected.desired_work_mode == "Self Use"
    assert projected.total_kh7_ac_output_kw == 0.862
    assert projected.plan_safe is True
    assert projected.commands_permitted is False
    assert projected.real_backend_available is False
    assert "physical export blocked; house load only" in projected.next_action

    safety = validate_shadow_command(projected, _config())
    assert safety["passed"] is True
    assert "export_permission" not in safety["failed_checks"]

    shadow = build_foxess_command_shadow(projected, export_limit_kw=6.4)
    proposed = shadow["proposed_foxess_command"]
    assert shadow["translation_status"] == "PASS"
    assert proposed["work_mode"] == "Self Use"
    assert proposed["force_discharge_power_kw"] is None
    assert proposed["export_power_limit_w"] == 0
    assert proposed["grid_export_allowed"] is False
    assert proposed["discharge_enabled"] is False


def test_export_permission_preserves_existing_agile_export_target() -> None:
    """Paid/authorised export keeps the existing physical projection unchanged."""
    projected = alignment.align_agile_control_state(
        _control(export_allowed=True),
        SimulationState(),
        _agile_state(),
        _config(),
    )

    assert projected.desired_grid_export_allowed is True
    assert projected.desired_battery_to_home_power_kw == 0.862
    assert projected.desired_battery_export_power_kw == 5.538
    assert projected.desired_total_discharge_power_kw == 6.4
    assert projected.desired_work_mode == "Feed-in First"
    assert projected.total_kh7_ac_output_kw == 6.4
    assert projected.plan_safe is True
    assert "physical export blocked" not in projected.next_action


def test_full_kems_control_view_keeps_counterfactual_export_target() -> None:
    """Physical no-export policy must not downscope the Full-KEMS digital twin."""
    simulation = SimulationState()
    control_view, _shadow_view, metadata = alignment.aligned_agile_control_views(
        simulation,
        _agile_state(),
    )

    assert simulation.current_simulated_battery_export_power_kw is None
    assert control_view.current_simulated_battery_to_home_power_kw == 0.862
    assert control_view.current_simulated_battery_export_power_kw == 5.538
    assert control_view.target_battery_export_power_kw == 5.538
    assert metadata["target"]["battery_export_kw"] == 5.538
    assert metadata["target"]["total_discharge_kw"] == 6.4


def test_island_state_also_fails_closed_for_rolling_export() -> None:
    """An islanded physical command must never inherit a rolling export target."""
    projected = alignment.align_agile_control_state(
        ControlState(
            operating_mode="simulate",
            desired_work_mode="Self Use / EPS",
            desired_min_soc_percent=15.0,
            desired_grid_export_allowed=True,
            island_mode_active=True,
            data_fresh=True,
            plan_safe=True,
            blocked_reason="Virtual backend only",
            preflight_status="PASS",
        ),
        SimulationState(),
        _agile_state(),
        _config(),
    )

    assert projected.desired_battery_export_power_kw == 0.0
    assert projected.desired_total_discharge_power_kw == 0.862
    assert projected.desired_work_mode == "Self Use"
    safety = validate_shadow_command(projected, _config())
    assert safety["passed"] is True
    assert "island_export_block" not in safety["failed_checks"]
