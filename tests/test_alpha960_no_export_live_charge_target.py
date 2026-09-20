"""Alpha9.60 no-export live charge-authority regressions."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import kems_core
from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationState,
    Snapshot,
)
from kems_core.control_write_authority import assess_foxess_control_write_authority

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
COORDINATOR = KEMS / "coordinator.py"
PACKAGE = "kems_alpha960_control_authority_test"


def _load_alignment():
    package = ModuleType(PACKAGE)
    package.__path__ = [str(KEMS)]
    sys.modules[PACKAGE] = package
    sys.modules[f"{PACKAGE}.kems_core"] = kems_core

    name = f"{PACKAGE}.agile_control_alignment"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS / "agile_control_alignment.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


alignment = _load_alignment()


def _full_kems_cheap_charge() -> dict:
    return {
        "rolling_export_plan": {
            "available": True,
            "dispatch_mode": "cheap_charge",
            "dispatch_action": "Full KEMS cheap charge",
            "target_soc_percent": 100.0,
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 1.2,
            "solar_power_kw": 0.0,
            "grid_import_kw": 8.2,
            "grid_export_kw": 0.0,
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 7.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 0.0,
        },
    }


def _cheap_snapshot(*, soc: float) -> Snapshot:
    return Snapshot(
        timestamp=datetime(2026, 9, 19, 0, 0, tzinfo=UTC),
        off_peak=True,
        house_load_kw=1.2,
        solar_power_kw=0.0,
        grid_import_kw=1.2,
        grid_export_kw=0.0,
        battery_soc=soc,
    )


def _control_config() -> ControlConfig:
    return ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=15.0,
        island_reserve_percent=20.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=6.4,
        eps_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )


def _no_export_simulation(*, charge_kw: float, target_soc: float) -> SimulationState:
    return SimulationState(
        no_export_mode_active=True,
        export_tariff_active=False,
        overnight_charge_target_percent=target_soc,
        simulated_battery_soc=None,
        current_simulated_house_load_kw=1.2,
        current_simulated_solar_power_kw=0.0,
        current_simulated_grid_import_kw=1.2 + charge_kw,
        current_simulated_grid_export_kw=0.0,
        current_simulated_battery_charge_power_kw=charge_kw,
        current_simulated_battery_to_home_power_kw=0.0,
        current_simulated_battery_export_power_kw=0.0,
        current_simulated_grid_bypass_power_kw=1.2,
        current_simulated_total_site_import_kw=1.2 + charge_kw,
        site_import_limit_kw=14.5,
        site_import_headroom_kw=14.5 - 1.2 - charge_kw,
    )


def test_full_kems_alignment_remains_counterfactual_for_customer_views() -> None:
    live = _no_export_simulation(charge_kw=0.0, target_soc=53.9)

    control_view, shadow_view, metadata = alignment.aligned_agile_control_views(
        live,
        _full_kems_cheap_charge(),
    )

    assert control_view.current_simulated_battery_charge_power_kw == 7.0
    assert shadow_view.current_simulated_battery_charge_power_kw == 7.0
    assert metadata["active"] is True
    assert metadata["target"]["charge_kw"] == 7.0


def test_no_export_target_satisfied_holds_battery_and_keeps_house_on_cheap_grid() -> (
    None
):
    snapshot = _cheap_snapshot(soc=55.0)
    # The replay may still be behind live hardware and asking for charge.
    # Fresh physical SOC at/above the no-export target must win.
    simulation = _no_export_simulation(charge_kw=7.0, target_soc=53.9)

    control = ControlEngine().plan(
        snapshot,
        simulation,
        snapshot.timestamp,
        _control_config(),
    )

    assert control.desired_work_mode == "Self Use"
    assert control.desired_charge_power_kw == 0.0
    assert control.desired_min_soc_percent == 55.0
    assert control.desired_ev_charging_allowed is True
    assert control.desired_grid_export_allowed is False
    assert control.grid_bypass_power_kw == 1.2
    assert control.total_site_import_kw == 1.2
    assert "Hold the battery" in control.next_action

    decision = assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted is True
    assert decision.action == "self_use"
    assert decision.min_soc_on_grid_percent == 55.0


def test_no_export_below_target_force_charges_only_to_forecast_target() -> None:
    snapshot = _cheap_snapshot(soc=52.0)
    simulation = _no_export_simulation(charge_kw=7.0, target_soc=53.9)

    control = ControlEngine().plan(
        snapshot,
        simulation,
        snapshot.timestamp,
        _control_config(),
    )

    assert control.desired_work_mode == "Force Charge"
    assert control.desired_charge_power_kw == 7.0
    assert control.desired_min_soc_percent == 54.0
    assert control.total_site_import_kw == 8.2
    assert control.site_import_headroom_kw == 6.3

    decision = assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.action == "force_charge"
    assert decision.force_charge_power_kw == 7.0
    assert decision.min_soc_on_grid_percent == 54.0


def test_coordinator_keeps_live_no_export_control_separate_from_customer_twin() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")

    assert "if base_simulation.no_export_mode_active:" in source
    assert "control_simulation = base_simulation" in source
    assert "aligned_agile_control_views(simulation, agile_state)" in source
    assert "if not base_simulation.no_export_mode_active:" in source
    assert (
        "align_agile_control_state(\n"
        "                    control,\n"
        "                    control_simulation,"
    ) in source


def test_alpha960_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.66"
    assert "Alpha9.60 fixes no-paid-export cheap-period target authority" in reason
    assert "Full KEMS" in reason
    assert "solar-aware overnight target" in reason
    assert "Min SoC-on-grid" in reason
    assert "home/EV demand" in reason
    assert "write scope remains unchanged" in reason
