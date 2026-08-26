"""Regression coverage for Alpha8.26 control/shadow target alignment."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import kems_core
from kems_core import ControlConfig, ControlState, SimulationState
from kems_core.shadow_validation import shadow_plan_vs_outcome

ROOT = Path(__file__).parents[1]


def _alignment_module():
    """Load the package-relative helper without importing Home Assistant."""
    package_name = "kems_alpha826_testpkg"
    module_name = f"{package_name}.agile_control_alignment"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    package = ModuleType(package_name)
    package.__path__ = [str(ROOT / "custom_components/kems")]
    sys.modules[package_name] = package
    sys.modules[f"{package_name}.kems_core"] = kems_core

    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "custom_components/kems/agile_control_alignment.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _state(
    *,
    house_target: float = 0.0,
    export_target: float = 0.0,
    discharge_target: float = 0.0,
    routed_house: float = 0.0,
    routed_export: float = 0.0,
) -> dict:
    return {
        "current_action": "solar to home first, store solar for higher Agile slot",
        "rolling_export_plan": {
            "available": True,
            "dispatch_mode": "price_optimised",
            "dispatch_action": "price-optimised rolling export; house first",
            "target_soc_percent": 10.0,
            "current_house_battery_kw": house_target,
            "current_battery_export_target_kw": export_target,
            "current_battery_discharge_target_kw": discharge_target,
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.892,
            "solar_power_kw": 1.805,
            "grid_import_kw": 0.0,
            "grid_export_kw": round(0.913 + routed_export, 3),
            "solar_to_home_kw": 0.892,
            "solar_to_battery_kw": 0.0,
            "solar_export_kw": 0.913,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": routed_house,
            "battery_export_kw": routed_export,
            "total_discharge_kw": routed_house + routed_export,
            "normalised_kh7_ac_output_kw": round(
                1.805 + routed_house + routed_export,
                3,
            ),
        },
    }


def _base_simulation() -> SimulationState:
    """Reproduce the stale Alpha8.25 base digital-twin current flows."""
    return SimulationState(
        ready=True,
        current_simulated_house_load_kw=0.892,
        current_simulated_solar_power_kw=1.805,
        current_simulated_grid_import_kw=0.0,
        current_simulated_grid_export_kw=2.697,
        current_simulated_battery_power_kw=1.784,
        current_simulated_battery_charge_power_kw=0.0,
        current_simulated_solar_to_battery_power_kw=0.0,
        current_simulated_battery_to_home_power_kw=0.892,
        current_simulated_battery_export_power_kw=0.892,
        current_simulated_total_kh7_output_kw=3.589,
        current_simulated_grid_bypass_power_kw=0.0,
        current_simulated_total_site_import_kw=0.0,
        target_battery_export_power_kw=0.892,
        simulated_battery_soc=81.0,
    )


def test_live_alpha825_zero_target_gets_exact_control_and_shadow_views() -> None:
    module = _alignment_module()
    original = _base_simulation()

    control_view, shadow_view, context = module.aligned_agile_control_views(
        original,
        _state(),
    )

    assert context["active"] is True
    assert control_view.current_simulated_battery_to_home_power_kw == 0.0
    assert control_view.current_simulated_battery_export_power_kw == 0.0
    assert control_view.target_battery_export_power_kw == 0.0
    assert shadow_view.current_simulated_battery_to_home_power_kw == 0.0
    assert shadow_view.current_simulated_battery_export_power_kw == 0.0
    assert shadow_view.current_simulated_grid_import_kw == 0.0
    assert original.current_simulated_battery_to_home_power_kw == 0.892
    assert original.current_simulated_battery_export_power_kw == 0.892


def test_published_control_state_is_reconciled_to_exact_zero_target() -> None:
    module = _alignment_module()
    original = _base_simulation()
    stale_control = ControlState(
        operating_mode="simulate",
        operating_reason="paced_export",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=0.892,
        desired_battery_export_power_kw=0.892,
        desired_total_discharge_power_kw=1.784,
        virtual_scenario_solar_power_kw=1.805,
        total_kh7_ac_output_kw=3.589,
        kh7_output_headroom_kw=3.411,
        control_enabled=False,
        commissioned=False,
        real_backend_available=False,
        commands_permitted=False,
        plan_safe=True,
    )

    aligned = module.align_agile_control_state(
        stale_control,
        original,
        _state(),
        ControlConfig(),
    )

    assert aligned.operating_reason == "agile_rolling_price_optimised"
    assert aligned.desired_work_mode == "Self Use"
    assert aligned.desired_battery_to_home_power_kw == 0.0
    assert aligned.desired_battery_export_power_kw == 0.0
    assert aligned.desired_total_discharge_power_kw == 0.0
    assert aligned.total_kh7_ac_output_kw == 1.805
    assert aligned.real_backend_available is False
    assert aligned.commands_permitted is False


def test_exact_selected_export_target_survives_into_control_state() -> None:
    module = _alignment_module()
    original = _base_simulation()
    state = _state(export_target=3.5, discharge_target=3.5, routed_export=3.5)

    _, shadow_view, _ = module.aligned_agile_control_views(original, state)
    aligned = module.align_agile_control_state(
        ControlState(
            operating_mode="simulate",
            virtual_scenario_solar_power_kw=1.805,
            plan_safe=True,
        ),
        original,
        state,
        ControlConfig(),
    )

    assert aligned.desired_battery_to_home_power_kw == 0.0
    assert aligned.desired_battery_export_power_kw == 3.5
    assert aligned.desired_total_discharge_power_kw == 3.5
    assert aligned.desired_work_mode == "Feed-in First"
    tracking = shadow_plan_vs_outcome(aligned, shadow_view)
    assert tracking["tracking_score_percent"] == 100.0
    assert all(tracking["within_tolerance"].values())


def test_zero_target_shadow_tracking_is_no_longer_alpha825_mismatch() -> None:
    module = _alignment_module()
    original = _base_simulation()
    state = _state()
    _, shadow_view, _ = module.aligned_agile_control_views(original, state)
    aligned = module.align_agile_control_state(
        ControlState(
            operating_mode="simulate",
            virtual_scenario_solar_power_kw=1.805,
            plan_safe=True,
        ),
        original,
        state,
        ControlConfig(),
    )

    tracking = shadow_plan_vs_outcome(aligned, shadow_view)
    assert tracking["target"] == {
        "charge_kw": 0.0,
        "battery_to_home_kw": 0.0,
        "battery_export_kw": 0.0,
        "total_discharge_kw": 0.0,
    }
    assert tracking["outcome"] == tracking["target"]
    assert tracking["tracking_score_percent"] == 100.0


def test_active_power_down_keeps_existing_event_priority_path() -> None:
    module = _alignment_module()
    original = replace(_base_simulation(), saving_session_active=True)
    control_view, shadow_view, context = module.aligned_agile_control_views(
        original,
        _state(),
    )

    assert context["active"] is False
    assert control_view is original
    assert shadow_view is original


def test_coordinator_aligns_after_agile_update_before_shadow_validation() -> None:
    source = (ROOT / "custom_components/kems/coordinator.py").read_text()

    agile_update = source.index("await self._agile_smart_export.async_update")
    views = source.index("aligned_agile_control_views(", agile_update)
    plan = source.index("control = self._control.plan", views)
    reconcile = source.index("control = align_agile_control_state", plan)
    shadow = source.index("await self._shadow_validation.async_update", reconcile)

    assert agile_update < views < plan < reconcile < shadow
    assert "simulation=shadow_simulation" in source[shadow : shadow + 500]
    assert "simulation=simulation" in source[source.index("return KEMSData") :]
    assert "commands_permitted=False" in (
        ROOT / "custom_components/kems/agile_control_alignment.py"
    ).read_text()
